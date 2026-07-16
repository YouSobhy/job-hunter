"""Structured results store (jobs.jsonl) — the data source for the
dashboard and the Telegram bot.

One JSON object per line:
{found, title, company, location, source, posted, score, tags, url, summary}
"""

import json
import logging

from .config import BASE_DIR

JOBS_FILE = BASE_DIR / "jobs.jsonl"

log = logging.getLogger("jobhunter")


def append_jobs(entries: list[dict]) -> None:
    if not entries:
        return
    with JOBS_FILE.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def load_jobs() -> list[dict]:
    if not JOBS_FILE.exists():
        return []
    out = []
    for line in JOBS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("bad line in %s ignored", JOBS_FILE.name)
    return out
