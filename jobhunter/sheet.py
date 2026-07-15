"""Google Sheets output — the single auth helper for the whole project."""

import logging
from datetime import datetime

from .config import GSHEET_CREDS, Config

log = logging.getLogger("jobhunter")

SHEET_HEADERS = ["Date Found", "Title", "Company", "Location",
                 "Source", "Score", "Tags", "URL", "Status", "Summary"]


def get_spreadsheet(cfg: Config):
    """Open (or create) the spreadsheet. Returns gspread Spreadsheet or None."""
    if not GSHEET_CREDS.exists():
        return None
    try:
        import gspread
        client = gspread.service_account(filename=str(GSHEET_CREDS))
        try:
            return client.open(cfg.sheet_name)
        except gspread.SpreadsheetNotFound:
            sh = client.create(cfg.sheet_name)
            sh.share(None, perm_type="anyone", role="reader")
            return sh
    except Exception as e:
        log.warning("Google Sheets: %s", e)
        return None


def get_worksheet(sh):
    if sh is None:
        return None
    ws = sh.sheet1
    values = ws.get_all_values()
    if not values:
        ws.append_row(SHEET_HEADERS)
    elif len(values[0]) < len(SHEET_HEADERS) or values[0][9:10] != ["Summary"]:
        # Add the new Summary header to col J on existing sheets
        try:
            ws.update_cell(1, 10, "Summary")
        except Exception:
            pass
    return ws


def append_rows(ws, rows: list[list]) -> None:
    if not ws or not rows:
        return
    try:
        ws.append_rows(rows, value_input_option="USER_ENTERED", table_range="A1")
        print(f"  [sheets] {len(rows)} job(s) appended.")
    except Exception as e:
        log.warning("Sheet append: %s", e)


def write_heartbeat(sh, text: str) -> None:
    """Write run status to Meta!A1 — the most visible failure alarm."""
    if sh is None:
        return
    try:
        import gspread
        try:
            meta = sh.worksheet("Meta")
        except gspread.WorksheetNotFound:
            meta = sh.add_worksheet(title="Meta", rows=4, cols=2)
        meta.update_acell("A1", text)
    except Exception as e:
        log.warning("heartbeat write failed: %s", e)


def make_row(job, verdict) -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    tags = list(job.tags)
    if verdict.geo == "unclear":
        tags.append("GEO?")
    return [
        today,
        job.title,
        verdict.company or job.company,
        verdict.location_stated,
        job.source,
        verdict.fit_score,
        ", ".join(tags),
        job.url,
        "",
        f"{verdict.summary} | {verdict.reason}",
    ]
