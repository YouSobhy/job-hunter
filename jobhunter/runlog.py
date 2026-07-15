"""Logging: rotating diagnostic log + capped human-readable results log."""

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

from .config import DIAG_LOG, RESULTS_LOG

RESULTS_LOG_CAP = 2 * 1024 * 1024  # 2 MB


def setup_logging() -> logging.Logger:
    log = logging.getLogger("jobhunter")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        DIAG_LOG, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    log.addHandler(handler)
    return log


def _rotate_results_log() -> None:
    if RESULTS_LOG.exists() and RESULTS_LOG.stat().st_size > RESULTS_LOG_CAP:
        backup = RESULTS_LOG.with_suffix(".txt.1")
        if backup.exists():
            backup.unlink()
        RESULTS_LOG.rename(backup)


def append_results(entries: list[dict]) -> None:
    """Human-readable run record. Each entry: {title, company, location,
    source, posted, score, tags, url, summary}."""
    if not entries:
        return
    _rotate_results_log()
    with RESULTS_LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 70}\n")
        f.write(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  {len(entries)} new job(s)\n")
        f.write(f"{'=' * 70}\n\n")
        for i, e in enumerate(entries, 1):
            f.write(f"[{i}] {e['title']}\n")
            f.write(f"    Company  : {e['company']}\n")
            f.write(f"    Location : {e['location']}\n")
            f.write(f"    Source   : {e['source']} | Posted: {e['posted']} | Score: {e['score']}\n")
            if e.get("tags"):
                f.write(f"    Tags     : {e['tags']}\n")
            if e.get("summary"):
                f.write(f"    Summary  : {e['summary']}\n")
            f.write(f"    URL      : {e['url']}\n\n")
