"""Job feedback storage (job_feedback.json) — persistent user feedback on job cards.

Keyed by job URL:
{
    "url": {
        "category": "location_restricted" | "irrelevant_role" | "language_restricted" | "expired" | "good_fit",
        "label": "Location Restricted",
        "updated_at": "2026-08-23T12:34:40"
    }
}
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from .config import BASE_DIR

FEEDBACK_FILE = BASE_DIR / "job_feedback.json"
log = logging.getLogger("jobhunter")

CATEGORIES = {
    "location_restricted": {"label": "📍 Location Restricted", "chip_cls": "geo-warn"},
    "irrelevant_role": {"label": "❌ Irrelevant Role", "chip_cls": "badge-red"},
    "language_restricted": {"label": "🌐 Language Requirement", "chip_cls": "badge-purple"},
    "expired": {"label": "⏰ Expired / Dead Link", "chip_cls": "badge-grey"},
    "good_fit": {"label": "👍 Good Fit / Applied", "chip_cls": "geo-ok"},
}


def load_feedback() -> dict[str, dict]:
    if not FEEDBACK_FILE.exists():
        return {}
    try:
        return json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("failed to read %s: %s", FEEDBACK_FILE.name, e)
        return {}


def save_feedback(url: str, category: str) -> None:
    data = load_feedback()
    if category == "clear":
        data.pop(url, None)
    elif category in CATEGORIES:
        data[url] = {
            "category": category,
            "label": CATEGORIES[category]["label"],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    FEEDBACK_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
