"""Run status tracking + stale-run alarm."""

import json
import logging
import subprocess
from datetime import datetime, timedelta

from .config import STATUS_FILE

log = logging.getLogger("jobhunter")

STALE_AFTER_DAYS = 3


def read_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def write_status(*, success: bool, new_jobs: int = 0, judged: int = 0,
                 error: str | None = None, mode: str = "scheduled",
                 terms: list[str] | None = None) -> None:
    status = read_status()
    now = datetime.now().isoformat(timespec="seconds")
    status["last_run"] = now
    if success:
        status["last_success"] = now
    status["new_jobs"] = new_jobs
    status["judged"] = judged
    status["error"] = error
    status["mode"] = mode
    status["terms"] = terms or []
    STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")


def check_stale() -> str | None:
    """Returns an alert string if the last success is suspiciously old."""
    status = read_status()
    last = status.get("last_success")
    if not last:
        return None
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return None
    if datetime.now() - last_dt > timedelta(days=STALE_AFTER_DAYS):
        days = (datetime.now() - last_dt).days
        return f"ALERT: no successful run in {days} days (last: {last[:16]})"
    return None


def toast(message: str) -> None:
    """Best-effort Windows toast; failure ignored."""
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] > $null; "
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText01); "
        f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{message}')) > $null; "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'JobHunter').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass
