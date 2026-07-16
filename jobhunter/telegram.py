"""Telegram notifications — plain HTTPS against api.telegram.org, no deps.

Config: telegram.json (gitignored)
    {"bot_token": "123456:ABC...", "chat_id": 123456789}

chat_id may be absent initially; the bot (telegram_bot.py) fills it in on
the first /start from the owner.
"""

import json
import logging
import urllib.parse
import urllib.request

from .config import BASE_DIR

TELEGRAM_FILE = BASE_DIR / "telegram.json"

log = logging.getLogger("jobhunter")


def load_telegram() -> dict:
    if not TELEGRAM_FILE.exists():
        return {}
    try:
        return json.loads(TELEGRAM_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_telegram(cfg: dict) -> None:
    TELEGRAM_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def api_call(token: str, method: str, params: dict, timeout: float = 35.0):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def send_message(text: str, chat_id=None, token: str | None = None) -> bool:
    """Best-effort send to the configured chat. Returns True on success."""
    cfg = load_telegram()
    token = token or cfg.get("bot_token")
    chat_id = chat_id or cfg.get("chat_id")
    if not token or not chat_id:
        return False
    try:
        # Telegram caps messages at 4096 chars
        for chunk_start in range(0, len(text), 4000):
            api_call(token, "sendMessage", {
                "chat_id": chat_id,
                "text": text[chunk_start:chunk_start + 4000],
                "disable_web_page_preview": "true",
            }, timeout=15)
        return True
    except Exception as e:
        log.warning("telegram send failed: %s", e)
        return False


def format_job(e: dict) -> str:
    tags = f" [{e['tags']}]" if e.get("tags") else ""
    return (
        f"{e['title']} — {e['company']}\n"
        f"fit {e['score']}/10 | {e['location']}{tags}\n"
        f"{e.get('summary', '')}\n"
        f"{e['url']}"
    )


def notify_run(entries: list[dict], error: str | None = None) -> None:
    """Digest after a run: one message per accepted job, or a status line."""
    if error:
        send_message(f"JobHunter run FAILED:\n{error[:500]}")
        return
    if not entries:
        return  # quiet on empty runs — the daily heartbeat lives in the sheet
    send_message(f"JobHunter: {len(entries)} new job(s) found")
    for e in entries:
        send_message(format_job(e))
