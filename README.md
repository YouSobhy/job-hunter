# Remote Job Hunter

Automated daily remote-job search for implementation, customer success, and SaaS
onboarding roles — judged for relevance and Egypt-eligibility by **Claude Haiku**
instead of regex rules.

---

## What it does

Each run, `run.py`:

1. **Gathers candidates** from:
   - **Remotive API** — 18 targeted role terms (full descriptions included)
   - **SerpAPI / Google CSE / DuckDuckGo** — career/ATS pages (Greenhouse, Lever,
     Ashby, Workable, Deel, Personio, etc.)
2. **Deduplicates** against `seen_jobs.json` — URLs seen in previous runs are skipped
3. **Prefilters** cheaply (junk URLs, obviously-wrong titles, keyword ranking) and
   caps the list at `max_llm_calls` (default 20) to bound API cost
4. **Fetches the full posting page** (HTTP + BeautifulSoup, Playwright fallback for
   JS-heavy ATS pages). Dead/expired/redirected postings are dropped here
5. **Judges each posting with Claude Haiku** (`claude-haiku-4-5-20251001`): role fit
   (0–10) against the profile in `config.json`, geo eligibility for an Egypt-based
   candidate, language requirement (English/Arabic only), real company name, stated
   location, and a one-line summary. A job is accepted only if
   `fit ≥ 6 AND geo eligible AND language ok AND role type ok`
   (geo "unclear" is accepted but tagged `GEO?`)
6. **Outputs**:
   - Google Sheet `Remote Job Leads – Youssef` (col J = summary + reason;
     a `Meta` tab cell shows the last-run heartbeat)
   - `job_results_log.txt` (human-readable, capped at 2 MB)
   - `status.json` (last run / last success / counts / error)

Typical cost: ~$0.003 per judged job — a normal 1–3-job day costs well under a cent.

```
Usage:  python run.py [--dry-run] [--max-llm N]
```

---

## Setup

```
pip install -r requirements.txt
playwright install chromium   # once, for the JS-page fallback
```

**Anthropic API key** (required): set `ANTHROPIC_API_KEY`, or create
`anthropic_key.json`:

```json
{ "api_key": "sk-ant-..." }
```

**Google Sheets** (optional): see `SHEETS_SETUP.md` → `google_credentials.json`.

**Search engine** (optional, first available wins):

| Priority | Engine | Config file |
|----------|--------|-------------|
| 1 | SerpAPI | `serpapi.json` — `{ "api_key": "..." }` |
| 2 | Google CSE | `google_cse.json` — `{ "api_key": "...", "cx": "..." }` |
| 3 | DuckDuckGo | *(none needed — free fallback)* |

**Profile & search terms** live in `config.json` — edit the `profile` string to
change what the judge considers a fit.

---

## Scheduling

One Windows scheduled task, `JobHunter`, runs daily at 18:00 via
`run_job_search.bat` (no shell redirection — Python owns its own logging).

```powershell
# First-time setup (as Administrator):
& "D:\Joe\JobHunter\setup_scheduler.ps1"

# Run immediately:
Start-ScheduledTask -TaskName "JobHunter"

# Health check — last run/success timestamps:
Get-Content D:\Joe\JobHunter\status.json
```

If no successful run happens for 3+ days, the next run writes an ALERT into the
sheet's `Meta` tab and attempts a Windows toast.

---

## Tools

```
python tools/replay.py --fetch-only          # zero-cost fetch/dead-link test
python tools/replay.py --sample 12           # re-judge recent log entries (~$0.05)
python tools/cleanup_sheet.py                # re-judge sheet rows, mark Status col
python tools/cleanup_sheet.py --delete       # delete DEAD/REJECT rows
```

---

## File structure

```
JobHunter/
├── run.py                   # Entry point / pipeline orchestrator
├── config.json              # Profile, search terms, thresholds, caps
├── requirements.txt
├── run_job_search.bat       # Scheduled-task entry point
├── setup_scheduler.ps1      # Registers the JobHunter task (removes legacy tasks)
├── jobhunter/
│   ├── config.py            # Paths + config/credential loading
│   ├── models.py            # Job / FetchResult dataclasses
│   ├── sources.py           # Remotive + SerpAPI→CSE→DDG search chain
│   ├── prefilter.py         # Cheap first pass: URL sanity, title blocklist, ranking
│   ├── fetch.py             # Full-page fetcher + dead-link detection
│   ├── judge.py             # Claude Haiku structured relevance judge
│   ├── store.py             # seen_jobs.json dedup
│   ├── sheet.py             # Google Sheets output + heartbeat
│   ├── runlog.py            # Rotating logs
│   └── notify.py            # status.json + stale-run alert
├── tools/
│   ├── replay.py            # Re-judge past results from the log
│   └── cleanup_sheet.py     # Re-judge existing sheet rows
│
│   # Not tracked in git:
├── anthropic_key.json
├── google_credentials.json
├── serpapi.json
├── seen_jobs.json
├── status.json
└── job_results_log.txt
```
