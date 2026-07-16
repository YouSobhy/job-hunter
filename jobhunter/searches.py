"""Custom searches: saved-search list + the one-shot request file.

The dashboard/bot never run the pipeline directly — they write
search_request.json and fire the JobHunter scheduled task; run.py
consumes the request at startup (delete-on-read, so a crashed custom
run can't leak custom terms into the next scheduled run).
"""

import json
import logging
from datetime import datetime

from .config import BASE_DIR

SAVED_FILE = BASE_DIR / "saved_searches.json"
REQUEST_FILE = BASE_DIR / "search_request.json"

log = logging.getLogger("jobhunter")


# -- Saved searches ------------------------------------------------------------

def load_saved() -> list[dict]:
    if SAVED_FILE.exists():
        try:
            return json.loads(SAVED_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("saved_searches.json unreadable; starting fresh")
    return []


def save_all(searches: list[dict]) -> None:
    SAVED_FILE.write_text(
        json.dumps(searches, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def add_search(name: str, terms: list[str]) -> None:
    searches = load_saved()
    searches.append({
        "name": name.strip(),
        "terms": terms,
        "created": datetime.now().isoformat(timespec="seconds"),
        "last_run": None,
    })
    save_all(searches)


def update_search(index: int, *, name: str | None = None,
                  terms: list[str] | None = None,
                  last_run: str | None = None) -> None:
    searches = load_saved()
    if not 0 <= index < len(searches):
        return
    if name is not None:
        searches[index]["name"] = name.strip()
    if terms is not None:
        searches[index]["terms"] = terms
    if last_run is not None:
        searches[index]["last_run"] = last_run
    save_all(searches)


def delete_search(index: int) -> None:
    searches = load_saved()
    if 0 <= index < len(searches):
        searches.pop(index)
        save_all(searches)


def parse_terms(raw: str) -> list[str]:
    """Split user input on commas/semicolons/newlines into clean terms."""
    parts = [p.strip() for chunk in raw.splitlines() for p in
             chunk.replace(";", ",").split(",")]
    return [p for p in parts if p]


# -- One-shot request file ------------------------------------------------------

def write_request(terms: list[str], source: str = "dashboard") -> None:
    REQUEST_FILE.write_text(
        json.dumps({
            "terms": terms,
            "requested_at": datetime.now().isoformat(timespec="seconds"),
            "source": source,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def consume_request() -> dict | None:
    """Read and delete the pending request. Returns None if there is none."""
    if not REQUEST_FILE.exists():
        return None
    try:
        req = json.loads(REQUEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        req = None
        log.warning("search_request.json unreadable; discarding")
    try:
        REQUEST_FILE.unlink()
    except OSError:
        pass
    if req and isinstance(req.get("terms"), list) and req["terms"]:
        return req
    return None
