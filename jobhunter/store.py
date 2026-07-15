"""Persistent dedup store (seen_jobs.json)."""

import json
import re
from datetime import datetime

from .config import SEEN_FILE


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/").lower().split("?")[0]
    # Rippling serves the same job with locale prefixes (e.g. /pt-BR/, /fr-CA/)
    url = re.sub(r"(ats\.rippling\.com)/[a-z]{2}-[a-z]{2}/", r"\1/", url)
    # Lever job URLs sometimes appear with a trailing /apply
    url = re.sub(r"(jobs\.lever\.co/[^/]+/[^/]+)/apply$", r"\1", url)
    return url


def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        try:
            urls = json.loads(SEEN_FILE.read_text(encoding="utf-8")).get("urls", [])
            # Scrub junk entries (malformed relative URLs like "/goto?...")
            return {u for u in urls if u.startswith("http")}
        except Exception:
            pass
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(
        json.dumps(
            {"urls": sorted(seen), "last_updated": datetime.now().isoformat()},
            indent=2,
        ),
        encoding="utf-8",
    )
