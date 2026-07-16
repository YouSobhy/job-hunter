"""Re-judge every row in the Google Sheet and mark (default) or delete failures.

Usage:
    python tools/cleanup_sheet.py             # write verdicts into the Status column
    python tools/cleanup_sheet.py --delete    # delete rows that fail (dead/reject)
    python tools/cleanup_sheet.py --limit 20  # only process the first N data rows

Replaces the old clean_sheet.py and playwright_clean_sheet.py.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunter.config import load_config
from jobhunter.fetch import fetch_posting
from jobhunter.judge import Judge
from jobhunter.models import Job
from jobhunter.sheet import get_spreadsheet, get_worksheet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true",
                        help="delete failing rows instead of marking Status")
    parser.add_argument("--limit", type=int, default=None,
                        help="max data rows to process")
    args = parser.parse_args()

    cfg = load_config()
    sh = get_spreadsheet(cfg)
    ws = get_worksheet(sh)
    if not ws:
        print("Sheet unavailable — check google_credentials.json")
        sys.exit(1)

    rows = ws.get_all_values()
    if len(rows) < 2:
        print("No data rows.")
        return
    data = rows[1:]
    if args.limit:
        data = data[: args.limit]

    judge = Judge(cfg)
    verdicts: dict[int, str] = {}   # row index (1-based sheet row) -> status text
    to_delete: list[int] = []

    for i, row in enumerate(data, start=2):
        title = row[1] if len(row) > 1 else ""
        url = row[7] if len(row) > 7 else ""
        if not url.startswith("http"):
            verdicts[i] = "DEAD: invalid URL"
            to_delete.append(i)
            print(f"[row {i}] invalid URL — {title[:60]}")
            continue
        print(f"[row {i}] {title[:65]}")
        r = fetch_posting(url)
        if r.status == "dead":
            verdicts[i] = "DEAD"
            to_delete.append(i)
            print("         -> DEAD")
            continue
        if r.status == "error":
            verdicts[i] = "CHECK: fetch failed"
            print("         -> fetch error (kept)")
            continue
        try:
            v = judge.judge_job(Job(source="Cleanup", title=title, url=url), r.text)
        except Exception as e:
            verdicts[i] = "CHECK: judge failed"
            print(f"         -> judge error: {str(e)[:80]}")
            continue
        ok = (v.fit_score >= cfg.fit_threshold and v.geo in ("eligible", "unclear")
              and v.language_ok and v.role_type_ok)
        if ok:
            verdicts[i] = f"OK {v.fit_score}/10"
            print(f"         -> OK {v.fit_score}/10 ({v.geo})")
        else:
            verdicts[i] = f"REJECT: {v.reason[:80]}"
            to_delete.append(i)
            print(f"         -> REJECT ({v.geo}, fit {v.fit_score}): {v.reason[:70]}")

    if args.delete and to_delete:
        print(f"\nDeleting {len(to_delete)} row(s)...")
        requests = [
            {"deleteDimension": {"range": {
                "sheetId": ws.id, "dimension": "ROWS",
                "startIndex": idx - 1, "endIndex": idx,
            }}}
            for idx in sorted(to_delete, reverse=True)
        ]
        ws.spreadsheet.batch_update({"requests": requests})
        print("Done.")
    else:
        print(f"\nWriting {len(verdicts)} Status value(s)...")
        cells = [{"range": f"I{idx}", "values": [[text]]} for idx, text in verdicts.items()]
        ws.batch_update(cells, value_input_option="RAW")
        if to_delete:
            print(f"{len(to_delete)} row(s) marked DEAD/REJECT — rerun with --delete to remove them.")
        print("Done.")


if __name__ == "__main__":
    main()
