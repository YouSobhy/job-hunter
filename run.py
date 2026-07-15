"""JobHunter — daily remote-job search with an LLM relevance judge.

Usage:
    python run.py [--dry-run] [--max-llm N]

Pipeline: sources -> dedup -> prefilter (cap) -> fetch full text
          -> Claude judge -> sheet + log + status
"""

import argparse
import sys
import traceback
from datetime import datetime

from jobhunter import notify, runlog, sheet
from jobhunter.config import load_config
from jobhunter.fetch import fetch_batch
from jobhunter.judge import JudgeUnavailable, judge_batch, make_client
from jobhunter.models import FetchResult
from jobhunter.prefilter import prefilter
from jobhunter.sources import gather_all
from jobhunter.store import load_seen, normalize_url, save_seen

log = runlog.setup_logging()


def main(dry_run: bool = False, max_llm: int | None = None) -> None:
    cfg = load_config()
    if max_llm is not None:
        cfg.max_llm_calls = max_llm

    print("=" * 70)
    print("  JobHunter - Remote Job Search (LLM-judged)")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}{'  [DRY RUN]' if dry_run else ''}")
    print("=" * 70)

    alert = notify.check_stale()
    seen = load_seen()
    sh = sheet.get_spreadsheet(cfg)
    ws = sheet.get_worksheet(sh)
    print(f"  Sheets: {'connected' if ws else 'offline'}")
    if alert and not dry_run:
        sheet.write_heartbeat(sh, alert)
        notify.toast(alert)

    # Fail fast on a missing API key before spending time on sources
    client = make_client()

    # -- Gather + dedup --------------------------------------------------
    raw = gather_all(cfg)
    by_url = {}
    for j in raw:
        key = normalize_url(j.url)
        if key and key.startswith("http") and key not in by_url:
            j.url = j.url.strip()
            by_url[key] = j
    new = {k: j for k, j in by_url.items() if k not in seen}
    print(f"\n  {len(raw)} raw hits | {len(by_url)} unique | {len(new)} unseen")

    if not new:
        print(f"  No new jobs. ({len(seen)} already seen)")
        if not dry_run:
            notify.write_status(success=True, new_jobs=0, judged=0)
            sheet.write_heartbeat(
                sh, f"Last run: {datetime.now().strftime('%Y-%m-%d %H:%M')} - 0 new"
            )
        return

    # -- Prefilter (rank + cap LLM calls) ---------------------------------
    candidates = prefilter(list(new.values()), cfg)
    print(f"  {len(candidates)} candidate(s) after prefilter (cap {cfg.max_llm_calls})")
    if not candidates:
        if not dry_run:
            seen.update(new.keys())
            save_seen(seen)
            notify.write_status(success=True, new_jobs=0, judged=0)
            sheet.write_heartbeat(
                sh, f"Last run: {datetime.now().strftime('%Y-%m-%d %H:%M')} - 0 new"
            )
        return

    # -- Fetch full postings (fetch IS the liveness check) ----------------
    print("\n--- Fetch ---")
    fetched = fetch_batch(candidates)
    to_judge: list = []
    dead_urls: set[str] = set()
    retry_urls: set[str] = set()   # network errors — don't mark seen
    for j in candidates:
        if not j.needs_fetch:
            to_judge.append((j, j.description))
            continue
        r: FetchResult = fetched.get(j.url, FetchResult("error", final_url=j.url))
        if r.status == "ok":
            to_judge.append((j, r.text))
        elif r.status == "dead":
            dead_urls.add(normalize_url(j.url))
        else:
            retry_urls.add(normalize_url(j.url))
    if dead_urls:
        print(f"  {len(dead_urls)} dead link(s) dropped")

    # -- Judge -------------------------------------------------------------
    print(f"\n--- Claude judge ({cfg.model}) ---")
    verdicts = judge_batch(client, to_judge, cfg)

    accepted = []
    for j, _text in to_judge:
        v = verdicts.get(j.url)
        if v is None:
            retry_urls.add(normalize_url(j.url))  # per-job failure, retry next run
            continue
        ok = (
            v.fit_score >= cfg.fit_threshold
            and v.geo in ("eligible", "unclear")
            and v.language_ok
            and v.role_type_ok
        )
        mark = "ACCEPT" if ok else "reject"
        print(f"  [{mark}] {v.fit_score}/10 geo={v.geo:<10} {j.title[:55]}")
        print(f"           {v.reason[:100]}")
        if ok:
            accepted.append((j, v))

    accepted.sort(key=lambda p: p[1].fit_score, reverse=True)

    print(f"\n{'=' * 70}")
    print(f"  {len(accepted)} accepted | {len(to_judge) - len(accepted)} rejected "
          f"| {len(dead_urls)} dead | {len(retry_urls)} retry-next-run")
    print(f"{'=' * 70}\n")

    rows = [sheet.make_row(j, v) for j, v in accepted]
    for row in rows:
        print(f"  {row[1]}  |  {row[2]}  |  {row[3]}  |  fit {row[5]}")
        print(f"    {row[9]}")
        print(f"    {row[7]}\n")

    if dry_run:
        print("[dry-run] No writes: sheet, log, seen_jobs, status all untouched.")
        return

    # -- Persist -----------------------------------------------------------
    # Mark everything processed this run as seen, EXCEPT retry-next-run URLs.
    # Candidates over the prefilter cap were never processed - leave unseen too.
    processed = {normalize_url(j.url) for j in candidates} - retry_urls
    seen.update(processed)
    save_seen(seen)

    sheet.append_rows(ws, rows)
    runlog.append_results([
        {
            "title": j.title, "company": v.company or j.company,
            "location": v.location_stated, "source": j.source,
            "posted": j.posted, "score": v.fit_score,
            "tags": ", ".join(j.tags + (["GEO?"] if v.geo == "unclear" else [])),
            "url": j.url, "summary": f"{v.summary} | {v.reason}",
        }
        for j, v in accepted
    ])
    notify.write_status(success=True, new_jobs=len(accepted), judged=len(verdicts))
    sheet.write_heartbeat(
        sh, f"Last run: {datetime.now().strftime('%Y-%m-%d %H:%M')} - {len(accepted)} new"
    )
    print("[ok] Run complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JobHunter LLM-judged job search")
    parser.add_argument("--dry-run", action="store_true",
                        help="print would-be results; no writes")
    parser.add_argument("--max-llm", type=int, default=None,
                        help="override max LLM calls this run")
    args = parser.parse_args()
    try:
        main(dry_run=args.dry_run, max_llm=args.max_llm)
    except JudgeUnavailable as e:
        print(f"[error] {e}")
        log.error("judge unavailable: %s", e)
        notify.write_status(success=False, error=str(e))
        sys.exit(1)
    except Exception as e:
        traceback.print_exc()
        log.error("run failed: %s", e)
        notify.write_status(success=False, error=f"{type(e).__name__}: {e}")
        sys.exit(1)
