"""
Remote Job Search – Youssef Sobhy
Sources : Remotive API · DuckDuckGo broad search (job-boards excluded) · company career pages
Dedup   : seen_jobs.json  (persistent across every run)
Validate: HEAD-checks every new URL before saving (drops expired postings)
Output  : Google Sheets (if credentials present) + cumulative local log
"""

import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = Path("D:/Joe/JobHunter")
SEEN_FILE    = BASE_DIR / "seen_jobs.json"
LOG_FILE     = BASE_DIR / "job_results_log.txt"
GSHEET_CREDS  = BASE_DIR / "google_credentials.json"
GSHEET_NAME   = "Remote Job Leads – Youssef"
GOOGLE_CSE_FILE = BASE_DIR / "google_cse.json"   # {"api_key": "...", "cx": "..."}
SERPAPI_FILE    = BASE_DIR / "serpapi.json"       # {"api_key": "..."}

# ── Remotive search terms ─────────────────────────────────────────────────────
REMOTIVE_TERMS = [
    "implementation specialist",
    "configuration specialist",
    "implementation consultant",
    "saas implementation",
    "hrms implementation",
    "integration specialist",
    "onboarding specialist",
    "customer success manager",
    "customer success specialist",
    "customer support specialist",
    "technical support specialist",
    "technical account manager",
    "solutions engineer",
    "customer onboarding",
]

# ── Search queries ─────────────────────────────────────────────────────────────
# When Google CSE is active, these run against the 42 domains you configured.
# When falling back to DuckDuckGo, _DDG_SITES is prepended automatically.
_NO_LANG = "-french -german -spanish -portuguese -dutch -mandarin -czech -polish -ukrainian"

CSE_QUERIES = [
    '"implementation specialist" remote',
    '"configuration specialist" saas remote',
    '"onboarding specialist" saas remote',
    '"integration specialist" saas remote',
    '"customer success manager" saas remote',
    '"customer success specialist" saas remote',
    '"customer support specialist" saas remote',
    '"technical account manager" saas remote',
]
# 8 queries/day × 30 days = 240/month — within SerpAPI free tier (250/month)

# DuckDuckGo fallback: prepend site: targets so we still hit company/ATS pages
_DDG_SITES = (
    "site:boards.greenhouse.io OR site:jobs.lever.co "
    "OR site:jobs.ashbyhq.com OR site:apply.workable.com "
    "OR site:careers.smartrecruiters.com OR site:jobs.jobvite.com "
    "OR site:deel.com OR site:remote.com OR site:rippling.com "
    "OR site:hibob.com OR site:personio.com OR site:freshworks.com "
    "OR site:zendesk.com OR site:bamboohr.com OR site:chargebee.com"
)

# ── Scoring ───────────────────────────────────────────────────────────────────
SKILL_KEYWORDS = [
    "saas", "hrms", "hris", "implementation", "configuration",
    "onboarding", "integration", "api", "rest api", "webhook",
    "data migration", "n8n", "power automate", "automation",
    "uat", "customer success", "payroll", "erp", "customer support",
    "technical support", "crm", "data mapping",
]
HIGH_VALUE_KEYWORDS = [
    "implementation specialist", "configuration specialist",
    "implementation consultant", "integration specialist",
    "saas implementation", "hrms", "hris", "data migration",
    "onboarding specialist", "implementation manager",
    "technical onboarding", "customer onboarding",
    "customer success manager", "customer success specialist",
    "technical support specialist", "technical account manager",
]

# ── Filters ───────────────────────────────────────────────────────────────────
BLOCKED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    # Region restrictions
    r"\bus[\s\-]?only\b", r"\bunited states only\b", r"\busa only\b",
    r"\bcanada only\b", r"\buk only\b", r"\bunited kingdom only\b",
    r"\beu only\b", r"\beurope only\b", r"\baustralia only\b",
    r"\bnorth america only\b",
    r"must (be|reside|live) in (the )?(us|usa|uk|canada|australia|europe|eu)\b",
    r"(us|usa|uk|canada|eu|europe|australia)[- ]based (only|required|candidates)",
    r"authorized to work in the (us|usa|united states)",
    r"eligible to work in the (us|usa|united states)",
    r"right to work in (the )?(uk|united kingdom)",
    r"no.*egypt", r"egypt.*not",
    # Language requirements (Arabic + English only)
    r"(fluent|proficient|native|speaking|speaker)\s+in\s+(french|german|spanish"
    r"|portuguese|italian|dutch|mandarin|chinese|japanese|korean|turkish|hindi"
    r"|czech|polish|ukrainian|russian|hebrew|persian|greek|romanian|hungarian)",
    r"(french|german|spanish|portuguese|italian|dutch|mandarin|czech|polish"
    r"|ukrainian|russian|hebrew|turkish|hindi)\s+(speaking|speaker|required|fluency|fluent|\+)",
    r"must (speak|be fluent in|have proficiency in) (french|german|spanish|portuguese|italian|dutch|czech|polish)",
    r"bilingual.*(french|german|spanish|portuguese|italian|dutch)",
    r"\((fluent\s+)?(french|german|spanish|portuguese|italian|dutch|czech|polish"
    r"|ukrainian|russian|hebrew|turkish|hindi|mandarin)\b",
    r"\b(french|german|spanish|portuguese|dutch|czech|polish|ukrainian)\s*[\+&]\s*english\b",
]]

SINGLE_COUNTRY_RE = re.compile(
    r"^(usa|united states?|u\.?s\.?a?|canada|uk|united kingdom|australia"
    r"|remote[\s,\-]+u\.?s\.?a?|remote[\s,\-]+us|us[\s,\-]+remote"
    r"|remote[\s,\-]+united states?|remote[\s,\-]+canada"
    r"|remote[\s,\-]+uk|remote[\s,\-]+australia)[,\.\s\-]*(only|based)?\s*$",
    re.IGNORECASE,
)

TITLE_RELEVANT_RE = re.compile(
    r"implementation|configuration|onboarding|integration specialist"
    r"|customer success|customer support|technical support|technical account"
    r"|solutions engineer|product specialist|enablement|deployment specialist"
    r"|business analyst|revenue operations|payroll specialist|crm specialist"
    r"|account manager|client success|client onboarding|saas specialist"
    r"|hrms|hris|erp specialist|support specialist|customer operations",
    re.IGNORECASE,
)

TITLE_BLOCKED_RE = re.compile(
    r"\b(software engineer|frontend|backend|full.?stack|devops|data engineer"
    r"|data scientist|ml engineer|machine learning|site reliability|sre"
    r"|android|ios developer|mobile developer|ui.?ux|designer|product designer"
    r"|product manager|engineering manager|staff engineer|principal engineer"
    r"|security engineer|cloud engineer|platform engineer|infrastructure engineer"
    r"|copywriter|content writer|content marketing|marketing manager|growth manager"
    r"|recruiter|talent acquisition|hr director|finance director|controller"
    r"|inside sales|sales representative|sales development|account executive"
    r"|engineering lead|product lead|product owner"
    r"|unpaid|volunteer|intern(?:ship)?|php developer|rails engineer"
    r"|ruby developer|devops engineer|blockchain|web3|crypto engineer"
    r"|wfm|rtm|workforce management)\b",
    re.IGNORECASE,
)

TITLE_GEO_BLOCKED_RE = re.compile(
    r"\(\s*remote[\s,\-]+(us|usa|united states?|canada|north america|uk|united kingdom|australia)\s*\)"
    r"|\bremote[\s\-]+(us|usa|united states?)\b"
    r"|\b(us|usa|united states?|canada)\s*only\b"
    r"|\(us\)|\(usa\)|\(north america\)"
    r"|\blatam\b",
    re.IGNORECASE,
)

# Aggregator / noise domains – block regardless of path
AGGREGATOR_DOMAINS = re.compile(
    r"\b(remoterocketship|dailyremote|kickstartremote|remotely\.jobs|flexjobs"
    r"|virtualvocations|swooped\.co|workingnomads|talantix|nofluffjobs"
    r"|wearedistributed|euremotejobs|nodesk\.co|jobspresso|remotehub"
    r"|pangian|4dayweek|justremote|workstep|zippia|builtin\.com"
    r"|himalayas\.app|wellfound|angel\.co|otta\.com|jobgether"
    r"|snagajob|simplyhired|careerbuilder|monster\.com|glassdoor"
    r"|ziprecruiter|linkedin\.com|indeed\.com|reddit\.com|quora\.com"
    r"|medium\.com|gartner\.com|g2\.com|capterra\.com|bing\.com)\b",
    re.IGNORECASE,
)

# URL path patterns that are content pages, not job postings
JUNK_URL_RE = re.compile(
    r"/(blog|post|article|resources?|glossary|guide|review|essential.guide"
    r"|aclick|msclkid)\b",
    re.IGNORECASE,
)

# URL patterns that look like real job postings
JOB_URL_RE = re.compile(
    r"/(jobs?|j|careers?|openings?|positions?|apply|applications?|vacancies|roles?)/",
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def fetch_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "JobSearch/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode(errors="replace")[:400]
            parsed = json.loads(body)
            msg = parsed.get("error", {}).get("message", body[:200])
        except Exception:
            msg = body[:200] or str(e)
        print(f"  [warn] fetch failed {url[:60]}: HTTP {e.code} – {msg}")
        return None
    except Exception as e:
        print(f"  [warn] fetch failed {url[:60]}: {e}")
        return None


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/").lower().split("?")[0]


def score_job(title: str, description: str) -> int:
    text = f"{title} {description}".lower()
    score = sum(1 for kw in SKILL_KEYWORDS if kw in text)
    score += sum(3 for kw in HIGH_VALUE_KEYWORDS if kw in text)
    return score


def is_blocked(location: str, description: str, title: str = "") -> bool:
    if SINGLE_COUNTRY_RE.match(location.strip()):
        return True
    combined = f"{location} {title} {description}".lower()
    return any(rx.search(combined) for rx in BLOCKED_PATTERNS)


def is_title_relevant(title: str) -> bool:
    if TITLE_BLOCKED_RE.search(title):
        return False
    return bool(TITLE_RELEVANT_RE.search(title))


def is_valid_job_url(url: str, require_job_path: bool = False) -> bool:
    if AGGREGATOR_DOMAINS.search(url):
        return False
    if JUNK_URL_RE.search(url):
        return False
    if "aclick" in url or "msclkid" in url or len(url) > 500:
        return False
    if require_job_path:
        return bool(JOB_URL_RE.search(url))
    return True


def normalize_date(raw: str) -> str:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(raw[:25], fmt[:len(raw[:25])]).strftime("%Y-%m-%d")
        except Exception:
            pass
    return raw[:10] if raw else datetime.now().strftime("%Y-%m-%d")


def make_job(source, title, company, location, url, posted, score, tags="") -> dict:
    return {
        "source": source, "title": title, "company": company,
        "location": location or "Worldwide", "url": url,
        "posted": posted, "score": score, "tags": tags,
    }


# ── URL liveness check ────────────────────────────────────────────────────────
_DEAD_PATTERNS = re.compile(
    r"(job.no.longer|position.closed|no.longer.available|this.job.has.expired"
    r"|not.found|404|page.not.found|listing.has.expired|role.has.been.filled"
    r"|application.closed|vacancy.closed)",
    re.IGNORECASE,
)


def _url_is_alive(url: str, timeout: int = 8) -> bool:
    """HEAD-request a URL. Returns False if expired/gone, True otherwise."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        req.get_method = lambda: "HEAD"
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 404:
                return False
            final = resp.url.lower()
            # Redirected to homepage? (path shrinks dramatically)
            orig_path  = urllib.parse.urlparse(url.lower()).path.rstrip("/")
            final_path = urllib.parse.urlparse(final).path.rstrip("/")
            if orig_path and len(orig_path) > 10 and len(final_path) < len(orig_path) * 0.35:
                return False
            if _DEAD_PATTERNS.search(final):
                return False
            return resp.status < 400
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        if e.code == 405:   # HEAD not allowed — assume alive
            return True
        return e.code < 400
    except Exception:
        return True     # Network error — assume alive (avoid false negatives)


def validate_links(jobs: list[dict], workers: int = 12) -> list[dict]:
    if not jobs:
        return []
    print(f"  Validating {len(jobs)} URLs (parallel)...")
    alive: list[dict] = []
    dead = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_map = {ex.submit(_url_is_alive, j["url"]): j for j in jobs}
        for future in future_map:
            j = future_map[future]
            try:
                if future.result():
                    alive.append(j)
                else:
                    dead += 1
            except Exception:
                alive.append(j)     # error → keep
    print(f"  {len(alive)} live  |  {dead} expired/removed")
    return alive


# ── Deduplication ─────────────────────────────────────────────────────────────
def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")).get("urls", []))
        except Exception:
            pass
    return set()


def save_seen(seen: set):
    SEEN_FILE.write_text(
        json.dumps({"urls": sorted(seen), "last_updated": datetime.now().isoformat()}, indent=2),
        encoding="utf-8",
    )


# ── Source: Remotive ──────────────────────────────────────────────────────────
def fetch_remotive(term: str) -> list[dict]:
    url  = f"https://remotive.com/api/remote-jobs?search={urllib.parse.quote(term)}&limit=20"
    data = fetch_json(url)
    if not data or "jobs" not in data:
        return []
    out = []
    for j in data["jobs"]:
        loc   = j.get("candidate_required_location", "")
        desc  = j.get("description", "")
        title = j.get("title", "")
        if is_blocked(loc, desc, title):
            continue
        out.append(make_job(
            "Remotive", title, j.get("company_name", ""), loc,
            j.get("url", ""),
            normalize_date(j.get("publication_date", "")),
            score_job(title, desc),
            ", ".join(j.get("tags", [])[:6]),
        ))
    return out


# ── Source: DuckDuckGo ────────────────────────────────────────────────────────
def _load_cse_creds() -> tuple[str, str] | tuple[None, None]:
    """Return (api_key, cx) from google_cse.json, or (None, None) if not configured."""
    if not GOOGLE_CSE_FILE.exists():
        return None, None
    try:
        data = json.loads(GOOGLE_CSE_FILE.read_text(encoding="utf-8"))
        return data.get("api_key"), data.get("cx")
    except Exception:
        return None, None


def _google_cse_search(query: str, api_key: str, cx: str, num: int = 10) -> list[dict]:
    """Google Custom Search API – returns [{title, href, body}]."""
    results = []
    # CSE returns max 10 per request; fetch up to 20 with two pages
    for start in (1, 11):
        params = urllib.parse.urlencode({
            "key": api_key, "cx": cx,
            "q": query, "num": min(num, 10), "start": start,
        })
        url = f"https://www.googleapis.com/customsearch/v1?{params}"
        data = fetch_json(url)
        if not data:
            break
        if "error" in data:
            err = data["error"]
            print(f"  [warn] Google CSE error {err.get('code','?')}: {err.get('message','')}")
            for detail in err.get("errors", []):
                print(f"         reason={detail.get('reason','')}  domain={detail.get('domain','')}")
            break
        for item in data.get("items", []):
            results.append({
                "href":  item.get("link", ""),
                "title": item.get("title", ""),
                "body":  item.get("snippet", ""),
            })
        if len(data.get("items", [])) < 10:
            break
    return results


def _ddgs_search(query: str, max_results: int = 10, retries: int = 1) -> list:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []
    for attempt in range(retries + 1):
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            msg = str(e)[:80]
            if "No results" in msg:
                return []
            if attempt < retries:
                time.sleep(5)
            else:
                print(f"  [warn] DDG fallback: {msg}")
    return []


def _load_serpapi_key() -> str | None:
    """Return api_key from serpapi.json, or None if not configured."""
    if not SERPAPI_FILE.exists():
        return None
    try:
        return json.loads(SERPAPI_FILE.read_text(encoding="utf-8")).get("api_key")
    except Exception:
        return None


def _serpapi_search(query: str, api_key: str, num: int = 10) -> list[dict]:
    """SerpAPI Google search – returns [{title, href, body}]."""
    params = urllib.parse.urlencode({
        "q": query, "api_key": api_key,
        "engine": "google", "num": num, "hl": "en",
    })
    data = fetch_json(f"https://serpapi.com/search.json?{params}")
    if not data:
        return []
    if "error" in data:
        print(f"  [warn] SerpAPI: {data['error']}")
        return []
    return [
        {"href": r.get("link", ""), "title": r.get("title", ""), "body": r.get("snippet", "")}
        for r in data.get("organic_results", [])
    ]


def _search(query: str, api_key: str | None, cx: str | None,
            serpapi_key: str | None = None, max_results: int = 10) -> list[dict]:
    """Priority: SerpAPI → Google CSE → DuckDuckGo."""
    if serpapi_key:
        return _serpapi_search(query, serpapi_key, num=max_results)
    if api_key and cx:
        return _google_cse_search(query, api_key, cx, num=max_results)
    return _ddgs_search(query, max_results=max_results)


def fetch_cse_query(query: str, api_key=None, cx=None, serpapi_key=None) -> list[dict]:
    """
    Run one query against the search engine.
    - SerpAPI / DDG: prepend site: operators to target career pages.
    - Google CSE: engine already restricted to configured domains, query runs as-is.
    """
    if api_key and cx:
        effective_query = query
    else:
        effective_query = f"({_DDG_SITES}) {query}"
    source_tag = "Company"

    out = []
    for r in _search(effective_query, api_key, cx, serpapi_key, max_results=10):
        url   = r.get("href", "")
        title = r.get("title", "")
        body  = r.get("body", "")
        if not url or not title:
            continue
        if not is_valid_job_url(url, require_job_path=False):
            continue
        if TITLE_GEO_BLOCKED_RE.search(title):
            continue
        if is_blocked("", body, title):
            continue
        sc = score_job(title, body)
        if sc < 1:
            continue
        company = _company_from_url(url)
        out.append(make_job(source_tag, title, company, "Remote (verify posting)",
                            url, datetime.now().strftime("%Y-%m-%d"), sc))
    return out


def _company_from_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        host   = parsed.hostname or ""
        path   = parsed.path
        # boards.greenhouse.io/company/…  jobs.lever.co/company/…  jobs.ashbyhq.com/company/…
        if any(x in host for x in ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
                                    "smartrecruiters.com", "jobvite.com", "personio.com")):
            parts = [p for p in path.split("/") if p]
            return parts[0].replace("-", " ").title() if parts else host
        # company.com → company
        return host.replace("www.", "").split(".")[0].replace("-", " ").title()
    except Exception:
        return ""


# ── Google Sheets ─────────────────────────────────────────────────────────────
SHEET_HEADERS = ["Date Found", "Title", "Company", "Location",
                 "Source", "Score", "Tags", "URL", "Status"]


def get_sheet():
    if not GSHEET_CREDS.exists():
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds  = Credentials.from_service_account_file(str(GSHEET_CREDS), scopes=scopes)
        client = gspread.authorize(creds)
        try:
            sh = client.open(GSHEET_NAME)
        except gspread.SpreadsheetNotFound:
            sh = client.create(GSHEET_NAME)
            sh.share(None, perm_type="anyone", role="reader")
        ws = sh.sheet1
        if not ws.get_all_values():
            ws.append_row(SHEET_HEADERS)
        return ws
    except Exception as e:
        print(f"  [warn] Google Sheets: {e}")
        return None


def append_to_sheet(ws, jobs: list[dict]):
    if not ws or not jobs:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    rows  = [[today, j["title"], j["company"], j["location"],
              j["source"], j["score"], j["tags"], j["url"], ""]
             for j in jobs]
    try:
        ws.append_rows(rows, value_input_option="USER_ENTERED", table_range="A1")
        print(f"  [sheets] {len(rows)} job(s) appended.")
    except Exception as e:
        print(f"  [warn] Sheet append: {e}")


# ── Local log ─────────────────────────────────────────────────────────────────
def append_to_log(jobs: list[dict]):
    if not jobs:
        return
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 70}\n")
        f.write(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  {len(jobs)} new job(s)\n")
        f.write(f"{'=' * 70}\n\n")
        for i, j in enumerate(jobs, 1):
            f.write(f"[{i}] {j['title']}\n")
            f.write(f"    Company  : {j['company']}\n")
            f.write(f"    Location : {j['location']}\n")
            f.write(f"    Source   : {j['source']} | Posted: {j['posted']} | Score: {j['score']}\n")
            if j["tags"]:
                f.write(f"    Tags     : {j['tags']}\n")
            f.write(f"    URL      : {j['url']}\n\n")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("  Remote Job Search – Youssef Sobhy")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    seen = load_seen()
    ws   = get_sheet()
    api_key, cx  = _load_cse_creds()
    serpapi_key  = _load_serpapi_key()
    if serpapi_key:
        engine = "SerpAPI (Google)"
    elif api_key:
        engine = "Google CSE"
    else:
        engine = "DuckDuckGo (fallback)"
    print(f"  Sheets: {'connected' if ws else 'offline (see SHEETS_SETUP.md)'}")
    print(f"  Search: {engine}")

    all_jobs: list[dict] = []

    # ── Remotive ───────────────────────────────────────────────────────────
    print("\n--- Remotive ---")
    for term in REMOTIVE_TERMS:
        print(f"[>] {term}")
        all_jobs.extend(fetch_remotive(term))

    # ── Career site search ─────────────────────────────────────────────────
    if serpapi_key:
        engine_label = "SerpAPI – company/ATS career pages"
    elif api_key:
        engine_label = "Google CSE – 42 company/ATS domains"
    else:
        engine_label = "DuckDuckGo – ATS sites"
    print(f"\n--- {engine_label} ---")
    for q in CSE_QUERIES:
        label = q.split('"')[1] if '"' in q else q[:60]
        print(f"[>] {label}")
        all_jobs.extend(fetch_cse_query(q, api_key, cx, serpapi_key))
        if serpapi_key:
            time.sleep(1)       # light throttle for SerpAPI
        elif not api_key:
            time.sleep(4)       # heavier throttle for DDG

    # ── Deduplicate within run ─────────────────────────────────────────────
    seen_this_run: dict[str, dict] = {}
    for j in all_jobs:
        key = normalize_url(j["url"])
        if key and key not in seen_this_run:
            seen_this_run[key] = j

    # ── Relevance filter ───────────────────────────────────────────────────
    candidates = {
        k: v for k, v in seen_this_run.items()
        if v["score"] >= 3 and is_title_relevant(v["title"])
    }

    # ── Remove already-seen ────────────────────────────────────────────────
    new_jobs = {k: v for k, v in candidates.items() if k not in seen}

    if not new_jobs:
        print(f"\n  No new jobs found. ({len(seen)} already seen)")
        return

    # ── Validate URLs (drop expired postings) ─────────────────────────────
    print(f"\n--- Link Validation ---")
    live_jobs = validate_links(list(new_jobs.values()))

    # Update seen set to include both live and dead (so dead links don't resurface)
    seen.update(new_jobs.keys())
    save_seen(seen)

    # ── Sort and output ────────────────────────────────────────────────────
    ranked = sorted(live_jobs, key=lambda j: j["score"], reverse=True)

    print(f"\n{'=' * 70}")
    print(f"  {len(ranked)} NEW live jobs  |  {len(seen)} total seen")
    print(f"{'=' * 70}\n")

    for i, j in enumerate(ranked, 1):
        print(f"[{i:>3}] {j['title']}")
        print(f"       {j['company']}  |  {j['location']}  |  {j['source']}  |  Score {j['score']}")
        print(f"       {j['url']}")
        print()

    append_to_sheet(ws, ranked)
    append_to_log(ranked)
    print(f"[ok] Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
