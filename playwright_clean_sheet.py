"""
Playwright geo-check every URL in the Google Sheet and delete blocked rows.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from job_search import GSHEET_CREDS, GSHEET_NAME, _playwright_geo_blocked

import gspread
from google.oauth2.service_account import Credentials

WORKERS = 5   # parallel headless browsers

def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = Credentials.from_service_account_file(str(GSHEET_CREDS), scopes=scopes)
    return gspread.authorize(creds).open(GSHEET_NAME).sheet1


def main():
    print("Connecting to sheet…")
    ws   = get_sheet()
    rows = ws.get_all_values()
    print(f"{len(rows)} rows loaded (including header)\n")

    # Skip header row; URL is col index 7 (column H), title is col index 1
    data_rows = [
        (i + 1, row)           # sheet row number (1-indexed)
        for i, row in enumerate(rows)
        if i > 0 and len(row) > 7 and row[7].startswith("http")
    ]
    print(f"Checking {len(data_rows)} URLs with {WORKERS} parallel browsers…\n")

    blocked: list[tuple[int, str, str]] = []   # (sheet_row, title, url)
    done = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        future_map = {
            ex.submit(_playwright_geo_blocked, row[7]): (sheet_row, row)
            for sheet_row, row in data_rows
        }
        for future in as_completed(future_map):
            sheet_row, row = future_map[future]
            title = row[1] if len(row) > 1 else ""
            url   = row[7]
            done += 1
            try:
                is_blocked = future.result()
            except Exception as e:
                is_blocked = False
                print(f"  [error] row {sheet_row}: {e}")

            status = "BLOCKED" if is_blocked else "ok"
            print(f"  [{done:>3}/{len(data_rows)}] {status:<8} {title[:60]}")
            if is_blocked:
                blocked.append((sheet_row, title, url))

    print(f"\n{'='*60}")
    print(f"  Geo-blocked: {len(blocked)}  |  Clean: {len(data_rows) - len(blocked)}")
    print(f"{'='*60}\n")

    if not blocked:
        print("Nothing to remove.")
        return

    print("Rows to delete:")
    for row_num, title, url in blocked:
        print(f"  row {row_num:>4}  {title[:65]}")

    print(f"\nDeleting {len(blocked)} rows in one batch request…")
    row_nums = sorted([r for r, _, _ in blocked], reverse=True)
    requests = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId":    ws.id,
                    "dimension":  "ROWS",
                    "startIndex": rn - 1,
                    "endIndex":   rn,
                }
            }
        }
        for rn in row_nums
    ]
    ws.spreadsheet.batch_update({"requests": requests})
    print(f"Done. {len(blocked)} rows removed.")


if __name__ == "__main__":
    main()
