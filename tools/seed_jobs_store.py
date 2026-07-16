"""One-time backfill: parse job_results_log.txt into jobs.jsonl.

Safe to re-run — it skips URLs already in the store.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunter.config import RESULTS_LOG
from jobhunter.results import append_jobs, load_jobs

RUN_RE = re.compile(r"^Run:\s+(\d{4}-\d{2}-\d{2})")
JOB_RE = re.compile(r"^\[(\d+)\]\s+(.+)$")
FIELD_RE = re.compile(r"^\s+(Company|Location|Source|Tags|Summary|URL)\s+:\s+(.*)$")
SRC_RE = re.compile(r"^(.*?)\s*\|\s*Posted:\s*(\S+)\s*\|\s*Score:\s*(\S+)")


def parse() -> list[dict]:
    entries, current, run_date = [], None, ""
    for line in RESULTS_LOG.read_text(encoding="utf-8").splitlines():
        m = RUN_RE.match(line)
        if m:
            run_date = m.group(1)
            continue
        m = JOB_RE.match(line)
        if m:
            if current:
                entries.append(current)
            current = {"found": run_date, "title": m.group(2).strip(), "company": "",
                       "location": "", "source": "", "posted": "", "score": 0,
                       "tags": "", "url": "", "summary": ""}
            continue
        m = FIELD_RE.match(line)
        if m and current:
            key, val = m.group(1).lower(), m.group(2).strip()
            if key == "source":
                sm = SRC_RE.match(val)
                if sm:
                    current["source"] = sm.group(1).strip()
                    current["posted"] = sm.group(2)
                    try:
                        current["score"] = int(sm.group(3))
                    except ValueError:
                        pass
                else:
                    current["source"] = val
            else:
                current[key] = val
    if current:
        entries.append(current)
    return entries


def main() -> None:
    existing = {e["url"] for e in load_jobs()}
    parsed = parse()
    fresh, seen = [], set()
    for e in parsed:
        u = e.get("url", "")
        if u.startswith("http") and u not in existing and u not in seen:
            seen.add(u)
            fresh.append(e)
    append_jobs(fresh)
    print(f"parsed {len(parsed)} log entries; added {len(fresh)} new to jobs.jsonl "
          f"({len(existing)} were already there)")


if __name__ == "__main__":
    main()
