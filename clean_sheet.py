"""
Remove filtered-out jobs from the Google Sheet.
Runs each row through is_blocked + is_title_relevant and deletes rows that fail.
Processes in reverse order so row indices stay valid during deletion.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from job_search import (
    GSHEET_CREDS, GSHEET_NAME,
    is_blocked, is_title_relevant,
    TITLE_GEO_BLOCKED_RE,
)


def get_sheet():
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = Credentials.from_service_account_file(str(GSHEET_CREDS), scopes=scopes)
    client = gspread.authorize(creds)
    return client.open(GSHEET_NAME).sheet1


def should_remove(row: list) -> tuple[bool, str]:
    """Return (True, reason) if the row should be deleted."""
    # Header indices: Date(0) Title(1) Company(2) Location(3) Source(4) Score(5) Tags(6) URL(7) Status(8)
    if len(row) < 2:
        return False, ""
    title    = row[1] if len(row) > 1 else ""
    location = row[3] if len(row) > 3 else ""
    # Skip header row
    if title.lower() == "title":
        return False, ""

    if TITLE_GEO_BLOCKED_RE.search(title):
        m = TITLE_GEO_BLOCKED_RE.search(title)
        return True, f"title-geo ({m.group()!r})"

    if not is_title_relevant(title):
        from job_search import TITLE_BLOCKED_RE, TITLE_RELEVANT_RE
        if TITLE_BLOCKED_RE.search(title):
            m = TITLE_BLOCKED_RE.search(title)
            return True, f"title-blocked ({m.group()!r})"
        return True, "title-not-relevant"

    if is_blocked(location, "", title):
        return True, f"geo-blocked (loc={location!r})"

    return False, ""


def main():
    if not GSHEET_CREDS.exists():
        print("google_credentials.json not found — cannot connect to Sheets.")
        sys.exit(1)

    print("Connecting to Google Sheet…")
    ws = get_sheet()

    all_rows = ws.get_all_values()
    total    = len(all_rows)
    print(f"Loaded {total} rows (including header)\n")

    # Identify rows to delete (1-indexed for Sheets API)
    to_delete = []   # list of (sheet_row_number, title, reason)
    for i, row in enumerate(all_rows):
        sheet_row = i + 1   # Sheets rows are 1-indexed
        remove, reason = should_remove(row)
        if remove:
            title = row[1] if len(row) > 1 else "(empty)"
            to_delete.append((sheet_row, title, reason))

    print(f"Rows to remove: {len(to_delete)}\n")
    for row_num, title, reason in to_delete:
        print(f"  row {row_num:>4}  {reason:<40}  {title[:70]}")

    if not to_delete:
        print("\nNothing to remove.")
        return

    print(f"\nDeleting {len(to_delete)} rows in a single batch request…")
    # Build a batchUpdate body that deletes all rows in one API call.
    # Requests must be sorted descending so indices don't shift during the operation.
    row_nums = sorted([r for r, _, _ in to_delete], reverse=True)
    requests = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId":    ws.id,
                    "dimension":  "ROWS",
                    "startIndex": row_num - 1,   # 0-indexed
                    "endIndex":   row_num,
                }
            }
        }
        for row_num in row_nums
    ]
    ws.spreadsheet.batch_update({"requests": requests})

    remaining = total - len(to_delete)
    print(f"\nDone. {len(to_delete)} rows removed. {remaining} rows remain.")


if __name__ == "__main__":
    main()
