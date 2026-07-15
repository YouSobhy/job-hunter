"""Re-judge past results from job_results_log.txt through the new pipeline.

Usage:
    python tools/replay.py --fetch-only            # zero-cost: test fetch/dead-link only
    python tools/replay.py --sample 12             # fetch + judge a sample (~$0.05)
    python tools/replay.py --urls URL [URL ...]    # judge specific URLs
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunter.config import RESULTS_LOG, load_config
from jobhunter.fetch import fetch_posting
from jobhunter.judge import judge_batch, make_client
from jobhunter.models import Job

JOB_RE = re.compile(r"^\[(\d+)\]\s+(.+)$")
COMP_RE = re.compile(r"^\s+Company\s+:\s+(.+)$")
LOC_RE = re.compile(r"^\s+Location\s+:\s+(.+)$")
URL_RE = re.compile(r"^\s+URL\s+:\s+(.+)$")


def parse_log() -> list[dict]:
    jobs, current = [], {}
    for line in RESULTS_LOG.read_text(encoding="utf-8").splitlines():
        m = JOB_RE.match(line)
        if m:
            if current.get("title"):
                jobs.append(current)
            current = {"title": m.group(2).strip()}
            continue
        for rx, key in ((COMP_RE, "company"), (LOC_RE, "location"), (URL_RE, "url")):
            m = rx.match(line)
            if m and current:
                current[key] = m.group(1).strip()
    if current.get("title"):
        jobs.append(current)
    # Dedupe by URL, keep valid http URLs only
    out, seen = [], set()
    for j in jobs:
        u = j.get("url", "")
        if u.startswith("http") and u not in seen:
            seen.add(u)
            out.append(j)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=10, help="how many log entries to replay")
    parser.add_argument("--fetch-only", action="store_true", help="no LLM calls, just fetch")
    parser.add_argument("--urls", nargs="*", help="judge these URLs instead of log entries")
    args = parser.parse_args()

    cfg = load_config()

    if args.urls:
        entries = [{"title": "(manual)", "url": u} for u in args.urls]
    else:
        entries = parse_log()
        print(f"Parsed {len(entries)} unique jobs from log; taking last {args.sample}")
        entries = entries[-args.sample:]

    items = []
    for e in entries:
        print(f"\n[fetch] {e['title'][:70]}")
        print(f"        {e['url']}")
        r = fetch_posting(e["url"])
        pw = " (playwright)" if r.used_playwright else ""
        print(f"        -> {r.status}{pw}, {len(r.text)} chars")
        if r.status == "ok":
            job = Job(source="Replay", title=e["title"], url=e["url"],
                      company=e.get("company", ""), location=e.get("location", ""))
            items.append((job, r.text))

    if args.fetch_only:
        print(f"\n[fetch-only] {len(items)} fetched ok; skipping judge.")
        return

    if not items:
        print("\nNothing fetched ok — nothing to judge.")
        return

    print(f"\n--- Judging {len(items)} posting(s) with {cfg.model} ---")
    client = make_client()
    verdicts = judge_batch(client, items, cfg)

    print(f"\n{'fit':>3} | {'geo':<10} | {'lang':<5} | {'role':<5} | company / location / reason")
    print("-" * 100)
    for job, _ in items:
        v = verdicts.get(job.url)
        if not v:
            print(f"  ? | {'FAILED':<10} |       |       | {job.title[:50]}")
            continue
        print(f"{v.fit_score:>3} | {v.geo:<10} | {str(v.language_ok):<5} | {str(v.role_type_ok):<5} "
              f"| {v.company} / {v.location_stated}")
        print(f"    | {job.title[:80]}")
        print(f"    | {v.reason}")
        print()


if __name__ == "__main__":
    main()
