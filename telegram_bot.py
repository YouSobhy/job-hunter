"""JobHunter Telegram bot — long-polls api.telegram.org, no extra deps.

Commands (owner only):
    /start     claim the bot (first /start binds your chat as owner)
    /run       fire the JobHunter scheduled task; reports when it finishes
    /search    custom search: "/search hr analyst; payroll lead" or "/search 2"
               to run saved search #2
    /searches  list saved searches
    /status    last run / last success / counts
    /last      show the N most recent accepted jobs (default 3)

Setup: create a bot with @BotFather, put the token in telegram.json:
    {"bot_token": "123456:ABC..."}
then send /start to the bot. Runs as the JobHunterBot scheduled task (at logon).
"""

import subprocess
import sys
import time
import urllib.error

from datetime import datetime

from jobhunter import runlog
from jobhunter.notify import read_status
from jobhunter.results import load_jobs
from jobhunter.searches import load_saved, parse_terms, update_search, write_request
from jobhunter.telegram import api_call, format_job, load_telegram, save_telegram

log = runlog.setup_logging()

TASK_NAME = "JobHunter"
RUN_TIMEOUT_S = 25 * 60
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ps(cmd: str) -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW,
    )
    return out.stdout.strip()


def task_state() -> str:
    try:
        return _ps(f"(Get-ScheduledTask -TaskName {TASK_NAME}).State") or "Unknown"
    except Exception:
        return "Unknown"


def start_task() -> bool:
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Start-ScheduledTask -TaskName {TASK_NAME}"],
            capture_output=True, timeout=20, creationflags=_NO_WINDOW,
        )
        return True
    except Exception:
        return False


def status_text() -> str:
    s = read_status()
    lines = [
        f"Last run    : {(s.get('last_run') or 'never')[:16].replace('T', ' ')}",
        f"Last success: {(s.get('last_success') or 'never')[:16].replace('T', ' ')}",
        f"New jobs    : {s.get('new_jobs', '-')} | judged: {s.get('judged', '-')}",
        f"Task state  : {task_state()}",
    ]
    if s.get("error"):
        lines.append(f"Error: {s['error'][:200]}")
    return "\n".join(lines)


def handle_run(send, terms: list[str] | None = None) -> None:
    if task_state() == "Running":
        send("A run is already in progress.")
        return
    if terms:
        write_request(terms, source="telegram")
    if not start_task():
        send("Could not start the scheduled task.")
        return
    what = f"Custom search for: {', '.join(terms)}" if terms else "Run"
    send(f"{what} started - I'll report when it finishes.")
    deadline = time.time() + RUN_TIMEOUT_S
    time.sleep(20)
    while time.time() < deadline:
        if task_state() != "Running":
            s = read_status()
            if s.get("error"):
                send(f"Run FAILED: {s['error'][:300]}")
            else:
                n = s.get("new_jobs", 0)
                send(f"Run finished: {n} new job(s)."
                     + (" Details above." if n else ""))
            return
        time.sleep(15)
    send("Run still going after 25 min - check the PC.")


def handle_last(send, arg: str) -> None:
    try:
        n = max(1, min(10, int(arg)))
    except (ValueError, TypeError):
        n = 3
    jobs = load_jobs()
    if not jobs:
        send("No jobs in the store yet.")
        return
    for e in jobs[-n:]:
        send(format_job(e))


def handle_search(send, arg: str) -> None:
    arg = arg.strip()
    if not arg:
        send("Usage:\n/search hr analyst; payroll lead\n/search 2  (run saved search #2, see /searches)")
        return
    saved = load_saved()
    if arg.isdigit():
        idx = int(arg) - 1
        if not 0 <= idx < len(saved):
            send(f"No saved search #{arg}. Send /searches to list them.")
            return
        update_search(idx, last_run=datetime.now().isoformat(timespec="seconds"))
        handle_run(send, terms=saved[idx]["terms"])
        return
    terms = parse_terms(arg)
    if not terms:
        send("Couldn't parse any titles from that.")
        return
    handle_run(send, terms=terms)


def handle_searches(send) -> None:
    saved = load_saved()
    if not saved:
        send("No saved searches yet - create them in the dashboard, "
             "or run a one-off with /search <titles>.")
        return
    lines = []
    for i, s in enumerate(saved, 1):
        lr = (s.get("last_run") or "never")[:16].replace("T", " ")
        lines.append(f"{i}. {s['name']} - {', '.join(s['terms'])} (last run: {lr})")
    lines.append("\nRun one with /search <number>")
    send("\n".join(lines))


HELP = (
    "/run - fire a job search now\n"
    "/search t1; t2 - custom search for specific titles\n"
    "/search N - run saved search number N\n"
    "/searches - list saved searches\n"
    "/status - last run info\n"
    "/last N - show N most recent jobs (default 3)"
)


def main() -> None:
    cfg = load_telegram()
    token = cfg.get("bot_token")
    if not token:
        print("telegram.json missing or has no bot_token - exiting.")
        sys.exit(0)

    offset = cfg.get("_offset", 0)
    print("JobHunter bot polling...")
    log.info("telegram bot started")

    while True:
        try:
            resp = api_call(token, "getUpdates",
                            {"timeout": 30, "offset": offset}, timeout=45)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log.warning("telegram poll error: %s", str(e)[:100])
            time.sleep(30)
            continue
        except Exception as e:
            log.warning("telegram poll unexpected: %s", str(e)[:150])
            time.sleep(60)
            continue

        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            chat_id = (msg.get("chat") or {}).get("id")
            text = (msg.get("text") or "").strip()
            if not chat_id or not text:
                continue

            cfg = load_telegram()
            owner = cfg.get("chat_id")
            if owner is None and text.startswith("/start"):
                cfg["chat_id"] = chat_id
                save_telegram(cfg)
                owner = chat_id
                api_call(token, "sendMessage", {
                    "chat_id": chat_id,
                    "text": "Bound to this chat. You'll get new jobs here.\n" + HELP,
                })
                continue
            if chat_id != owner:
                continue  # ignore strangers

            def send(t, _cid=chat_id):
                try:
                    api_call(token, "sendMessage", {
                        "chat_id": _cid, "text": t,
                        "disable_web_page_preview": "true",
                    }, timeout=15)
                except Exception as e:
                    log.warning("telegram send failed: %s", str(e)[:100])

            cmd, _, arg = text.partition(" ")
            cmd = cmd.split("@")[0].lower()
            if cmd == "/run":
                handle_run(send)
            elif cmd == "/search":
                handle_search(send, arg)
            elif cmd == "/searches":
                handle_searches(send)
            elif cmd == "/status":
                send(status_text())
            elif cmd == "/last":
                handle_last(send, arg.strip())
            else:
                send(HELP)


if __name__ == "__main__":
    main()
