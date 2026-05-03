# Remote Job Hunter

Automated daily remote job search tailored for implementation, customer success, and SaaS onboarding roles — filtered for worldwide/Egypt-eligible positions and ranked by relevance score.

---

## What it does

Each run, `job_search.py`:

1. **Searches three sources** for new remote job postings:
   - **Remotive API** — queried with 14 targeted role terms
   - **SerpAPI / Google CSE / DuckDuckGo** — searches career pages and ATS platforms (Greenhouse, Lever, Ashby, Workable, etc.) using 8 structured queries
2. **Filters** out geo-restricted postings (US/UK/Canada/EU only), language requirements (non-Arabic/English), and irrelevant titles (engineering, design, sales, etc.)
3. **Scores** each posting based on matching skill keywords and high-value role terms (max score wins)
4. **Deduplicates** against `seen_jobs.json` — URLs already seen on previous runs are skipped permanently
5. **Validates** all new URLs with a HEAD request — expired or removed postings are dropped before output
6. **Outputs** results to:
   - A Google Sheet (`Remote Job Leads – Youssef`) if credentials are configured
   - A local cumulative log (`job_results_log.txt`)

---

## Scheduling

The script runs **daily at 18:00** via Windows Task Scheduler.

### First-time setup

Run `setup_scheduler.ps1` **once as Administrator** in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& "D:\Joe\JobHunter\setup_scheduler.ps1"
```

This registers the `YousefJobSearch` task. To verify it was created:

```powershell
Get-ScheduledTask -TaskName "YousefJobSearch"
```

To trigger an immediate run without waiting for 18:00:

```powershell
Start-ScheduledTask -TaskName "YousefJobSearch"
```

To remove the task:

```powershell
Unregister-ScheduledTask -TaskName "YousefJobSearch" -Confirm:$false
```

Logs from each scheduled run are written to `scheduler_run.log`.

---

## Search engine priority

The script picks the first available engine in this order:

| Priority | Engine | Config file | Notes |
|----------|--------|-------------|-------|
| 1 | SerpAPI | `serpapi.json` | 250 free searches/month |
| 2 | Google CSE | `google_cse.json` | Custom 42-domain engine |
| 3 | DuckDuckGo | *(none needed)* | Free fallback, slower |

---

## Setup

### Requirements

```
pip install gspread google-auth duckduckgo-search
```

### Google Sheets (optional)

Follow `SHEETS_SETUP.md` to create a service account and place `google_credentials.json` in the project folder.

### SerpAPI (optional)

Follow `GOOGLE_CSE_SETUP.md` or create `serpapi.json`:

```json
{ "api_key": "your_serpapi_key" }
```

### Google CSE (optional)

Create `google_cse.json`:

```json
{ "api_key": "your_google_api_key", "cx": "your_cse_cx_id" }
```

---

## File structure

```
JobHunter/
├── job_search.py          # Main script
├── setup_scheduler.ps1    # Registers the Windows scheduled task
├── SHEETS_SETUP.md        # Guide: Google Sheets service account setup
├── GOOGLE_CSE_SETUP.md    # Guide: SerpAPI / Google CSE setup
├── README.md
│
│   # Not tracked in git:
├── google_credentials.json
├── serpapi.json
├── google_cse.json
├── seen_jobs.json
└── job_results_log.txt
```
