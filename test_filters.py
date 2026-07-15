"""
Run existing log entries through the current filter logic and report results.
Only title + location are available in the log (no description), so description
is left blank — some false-negatives are expected for description-only filters.
"""

import re
import sys
from pathlib import Path

# ── Import filters from job_search ────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from job_search import (
    is_blocked, is_title_relevant,
    TITLE_GEO_BLOCKED_RE, ONSITE_RE,
    US_CITY_STATE_RE, SINGLE_COUNTRY_RE,
    BLOCKED_PATTERNS,
)

LOG_FILE = Path("D:/Joe/JobHunter/job_results_log.txt")

# ── Parse log ──────────────────────────────────────────────────────────────────
JOB_RE   = re.compile(r"^\[(\d+)\]\s+(.+)$")
COMP_RE  = re.compile(r"^\s+Company\s+:\s+(.+)$")
LOC_RE   = re.compile(r"^\s+Location\s+:\s+(.+)$")
URL_RE   = re.compile(r"^\s+URL\s+:\s+(.+)$")

jobs = []
current = {}
for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
    m = JOB_RE.match(line)
    if m:
        if current.get("title"):
            jobs.append(current)
        current = {"idx": m.group(1), "title": m.group(2).strip()}
        continue
    m = COMP_RE.match(line)
    if m and current:
        current["company"] = m.group(1).strip()
    m = LOC_RE.match(line)
    if m and current:
        current["location"] = m.group(1).strip()
    m = URL_RE.match(line)
    if m and current:
        current["url"] = m.group(1).strip()

if current.get("title"):
    jobs.append(current)

print(f"Loaded {len(jobs)} jobs from log\n")

# ── Run filters ────────────────────────────────────────────────────────────────
passed = []
blocked = []

for j in jobs:
    title = j.get("title", "")
    loc   = j.get("location", "")
    url   = j.get("url", "")
    reasons = []

    # Title relevance (combined blocked + relevant check)
    if not is_title_relevant(title):
        # Figure out which sub-rule caught it
        from job_search import TITLE_BLOCKED_RE, TITLE_RELEVANT_RE
        if TITLE_BLOCKED_RE.search(title):
            reasons.append(f"title-blocked ({TITLE_BLOCKED_RE.search(title).group()!r})")
        elif not TITLE_RELEVANT_RE.search(title):
            reasons.append("title-not-relevant")

    # Geo block on title
    if TITLE_GEO_BLOCKED_RE.search(title):
        reasons.append(f"title-geo ({TITLE_GEO_BLOCKED_RE.search(title).group()!r})")

    # Location block
    loc_strip = loc.strip()
    if SINGLE_COUNTRY_RE.match(loc_strip):
        reasons.append(f"location-country ({loc_strip!r})")
    elif US_CITY_STATE_RE.match(loc_strip):
        reasons.append(f"location-us-city ({loc_strip!r})")

    # Body/combined block (no description, so just location+title)
    combined = f"{loc} {title}".lower()
    for rx in BLOCKED_PATTERNS:
        m = rx.search(combined)
        if m:
            reasons.append(f"body-pattern ({m.group()!r})")
            break

    if reasons:
        blocked.append((j, reasons))
    else:
        passed.append(j)

# ── Report ─────────────────────────────────────────────────────────────────────
print(f"{'='*70}")
print(f"  WOULD BE BLOCKED: {len(blocked)}  |  WOULD PASS: {len(passed)}")
print(f"{'='*70}\n")

print("--- BLOCKED ---")
for j, reasons in blocked:
    print(f"  [{j['idx']:>3}] {j['title']}")
    print(f"         {j.get('company','')}  |  {j.get('location','')}")
    print(f"         Reason: {'; '.join(reasons)}")
    print()

print("--- PASSING ---")
for j in passed:
    print(f"  [{j['idx']:>3}] {j['title']}")
    print(f"         {j.get('company','')}  |  {j.get('location','')}")
    print()
