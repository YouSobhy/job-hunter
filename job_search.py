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
    "customer support agent",
    "support specialist",
    "technical support specialist",
    "technical support agent",
    "customer onboarding",
    # Part-time / contractor variants — surface side-role opportunities
    "customer support part time",
    "customer support contractor",
    "technical support part time",
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
    '"technical support specialist" saas remote',
    '"support specialist" saas remote',
    # Part-time / contractor queries — surface side-role opportunities
    '"customer support" part-time remote',
    '"customer support" contract remote',
]
# 11 queries/day × 30 days = 330/month — slightly over SerpAPI free tier (250/month);
# consider dropping 2 lower-value queries if quota becomes an issue

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
    "technical support specialist",
    "support specialist",
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
    r"\((brazil|india|philippines|pakistan|nigeria|kenya|egypt|manila)\b",
    r"\b(brazil|india|philippines|pakistan|nigeria|kenya)\s*,\s*global\b",
    r"\bmanila\b",   # Manila = Philippines, on-site required
]]

# Locations that are genuinely open to worldwide applicants (including Egypt)
LOCATION_OPEN_RE = re.compile(
    r"^\s*$"
    r"|^\s*(remote|worldwide|anywhere|global|work from anywhere|international"
    r"|remote\s*\(verify\s*posting\)|n/?a)\s*$"
    r"|\bemea\b"            # EMEA includes Egypt
    r"|\begypt\b"
    r"|\bmiddle\s+east\b"
    r"|\bafrica\b"
    r"|\bremote\s*[-,]?\s*(?:worldwide|global|anywhere|international|emea|africa|middle\s+east)\b",
    re.IGNORECASE,
)

# Specific foreign countries that are NOT Egypt — block when found in the location field
_FOREIGN_COUNTRIES = (
    r"united states?|u\.?s\.?a?|usa|canada|united kingdom|australia|new zealand|north america"
    r"|india|singapore|japan|south korea|korea|china|hong kong|taiwan"
    r"|brazil|mexico|colombia|argentina|chile|peru"
    r"|germany|france|spain|italy|netherlands|sweden|norway|denmark|finland"
    r"|ireland|poland|ukraine|czech|romania|hungary|portugal|belgium|austria"
    r"|switzerland|israel|turkey|saudi arabia|uae|nigeria|kenya|south africa|ghana"
    r"|philippines|indonesia|malaysia|thailand|vietnam|pakistan|bangladesh"
    r"|costa rica|nicosia|cyprus"
)
_FOREIGN_CITIES = (
    r"london|berlin|paris|amsterdam|sydney|melbourne|dublin|toronto|vancouver"
    r"|singapore|tokyo|seoul|jakarta|mumbai|delhi|bangalore|bengaluru|hyderabad"
    r"|s[aã]o paulo|mexico city|tel aviv|istanbul|warsaw|prague|budapest|bucharest"
    r"|kyiv|athens|lisbon|madrid|barcelona|milan|rome|z[üu]rich|geneva|brussels"
    r"|copenhagen|stockholm|oslo|helsinki|nairobi|lagos|cape town|johannesburg"
    r"|bogot[aá]|santiago|lima|bangkok|kuala lumpur|manila|ho chi minh|taipei"
    r"|beijing|shanghai|nicosia|san francisco|new york|chicago|austin|seattle"
    r"|boston|denver|atlanta|miami|dallas|houston|phoenix|portland|minneapolis"
    r"|washington\s*dc|salt lake city|los angeles"
)

SPECIFIC_LOCATION_RE = re.compile(
    rf"\b({_FOREIGN_COUNTRIES})\b"
    rf"|\b({_FOREIGN_CITIES})\b",
    re.IGNORECASE,
)

# US city + state abbreviation (kept for legacy matching)
_US_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN"
    "|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT"
    "|VA|WA|WV|WI|WY|DC"
)
US_CITY_STATE_RE = re.compile(
    rf"^[\w\s\-\.]+,\s*({_US_STATES})(\s*,?\s*(?:US|USA|United States?))?\s*$",
    re.IGNORECASE,
)
SINGLE_COUNTRY_RE = US_CITY_STATE_RE  # alias kept so existing call sites don't break

# On-site / in-office / hybrid-with-location jobs
ONSITE_RE = re.compile(
    r"\bon[\s\-]?site\b|\bin[\s\-]?office\b|\bin\s+person\b"
    r"|\boffice[\s\-]based\b|\bnot\s+remote\b|\bno\s+remote\b"
    r"|\bhybrid\s+\(.*\b(us|usa|uk|canada|australia|new york|san francisco"
    r"|london|toronto|sydney|chicago|austin|seattle|boston|denver)\b",
    re.IGNORECASE,
)

# Matches geo-restriction phrases embedded in body text / page snippets
BODY_GEO_BLOCKED_RE = re.compile(
    r"remote\s*[\(\[]\s*(united states?|u\.?s\.?a?|usa|canada|uk|united kingdom|australia|north america)\s*[\)\]]"
    r"|\b(united states?|usa|u\.?s\.?a?|canada|uk|united kingdom|australia|north america)\s*only\b"
    r"|\bonly\s+(us|usa|uk|canada|australia)\s+residents?\b"
    r"|\bmust\s+(be\s+)?(based|located|residing)\s+in\s+the\s+(us|usa|united states?|uk|canada|australia)\b"
    r"|\bopen\s+to\s+(us|usa|united states?|canada|uk|australia)\s+residents?\s+only\b"
    # "open to US-based only" / "US-based candidates only" / "US based only"
    r"|\bopen\s+to\s+(us|usa|united states?|canada|uk|australia)[\s\-]+based\b"
    r"|\b(us|usa|united states?|canada|uk|australia)[\s\-]+based\s+(only|candidates|applicants|employees|residents)\b"
    r"|\bremote\s+position[s]?\s+(are\s+)?open\s+to\s+(the\s+)?(us|usa|united states?)\b"
    # "Remote Canada", "Remote UK", "Remote USA" as standalone location phrases
    r"|\bremote\s+(canada|uk|united kingdom|australia|north america)\b"
    r"|\bremote\s+(us|usa|united states?)\b"
    r"|\bremote\s+within\s+(?:the\s+)?(?:us|usa|united states?|canada|uk)\b"
    # "REMOTE - US; ..." or "-REMOTE, USA-" location strings
    r"|\bremote\s*[-,]\s*(?:us|usa|united states?)\b",
    re.IGNORECASE,
)

# Soft geo flag: job mentions a preference (not a hard requirement) for US/NA.
# Does NOT hard-block — instead score is penalised -2 and "GEO_SOFT_BLOCK" tag
# is appended so Youssef can see and decide for himself.
SOFT_GEO_PREFERRED_RE = re.compile(
    r"\bca\s+or\s+nyc\s+preferred\b"
    r"|\bus\s+preferred\b"
    r"|\bunited\s+states\s+preferred\b"
    r"|\bbased\s+in\s+the\s+us\s+preferred\b"
    r"|\bnorth\s+america\s+preferred\b",
    re.IGNORECASE,
)
# Broader location checks for compound restricted strings like "USA, Canada"
_LOC_WORLDWIDE_RE = re.compile(
    r"\b(worldwide|global|anywhere|international)\b", re.IGNORECASE
)
_LOC_RESTRICTED_RE = re.compile(
    r"\b(usa|united states?|canada|uk|united kingdom|australia"
    r"|north america|americas?|latin america|latam)\b"
    r"|\bu\.?s\.?a?\b",
    re.IGNORECASE,
)

TITLE_RELEVANT_RE = re.compile(
    r"implementation|configuration|onboarding|integration specialist"
    r"|customer success|customer support|technical support|support specialist"
    r"|support agent"
    r"|product specialist|enablement|deployment specialist"
    r"|business analyst|revenue operations|payroll specialist|crm specialist"
    r"|account manager|client success|client onboarding|saas specialist"
    r"|hrms|hris|erp specialist|support specialist|customer operations",
    re.IGNORECASE,
)

TITLE_BLOCKED_RE = re.compile(
    r"\b(engineer"
    r"|software engineer|frontend|backend|full.?stack|devops|data engineer"
    r"|data scientist|ml engineer|machine learning|site reliability|sre"
    r"|android|ios developer|mobile developer|ui.?ux|designer|product designer"
    r"|product manager|engineering manager|staff engineer|principal engineer"
    r"|security engineer|cloud engineer|platform engineer|infrastructure engineer"
    r"|copywriter|content writer|content marketing|marketing manager|growth manager"
    r"|recruiter|talent acquisition|hr director|finance director|controller"
    r"|inside sales|sales representative|sales development|account executive"
    r"|territory account manager|senior account manager|account manager"
    r"|technical account manager"
    r"|revenue operations|rev ops|revops"
    r"|business analyst"
    r"|support enablement|enablement manager|enablement lead"
    r"|wfm|rtm|workforce management|workforce manager"
    r"|product content|content marketing|marketing manager|growth manager"
    r"|ai engineer|founding.*lead|founding.*engineer"
    r"|engineering lead|product lead|product owner"
    r"|unpaid|volunteer|intern(?:ship)?|php developer|rails engineer"
    r"|ruby developer|devops engineer|blockchain|web3|crypto engineer"
    r"|m&a integration|merger.*integration|acquisition.*integration"
    # Explicitly block engineering-flavoured support titles that slip past the
    # blanket \bengineer\b — "developer support" / "support developer" are not
    # caught by that rule; the engineer variants are redundant but kept for clarity
    r"|support engineer|technical support engineer|support software engineer"
    r"|developer support|support developer)\b",
    re.IGNORECASE,
)

# Body-text filter: blocks postings whose description signals an engineering-heavy
# role despite a support-sounding title.  Applied inside is_blocked() alongside
# BLOCKED_PATTERNS.  MDM combination uses lookaheads so both terms must co-occur.
ROLE_TYPE_BLOCKED_RE = re.compile(
    # Dev languages / frameworks that indicate a coding role
    r"\bphp\b|\blaravel\b"
    r"|\bpython\s+scripting\b|\bjava\s+scripting\b"
    # Mobile-dev IDEs
    r"|\bandroid\s+studio\b|\bxcode\b"
    # SIEM / security-tooling heavy roles
    r"|\bsplunk\b|\barcsight\b"
    # MDM stack: only block when BOTH "mdm" AND a specific MDM tool appear
    # (lookaheads match zero-width so re.search succeeds at position 0 when
    #  both terms exist anywhere in the text)
    r"|(?=.*\bmdm\b)(?=.*\b(?:intune|airwatch)\b)",
    re.IGNORECASE | re.DOTALL,
)

TITLE_GEO_BLOCKED_RE = re.compile(
    r"\(\s*remote[\s,\-]+(us|usa|united states?|canada|north america|uk|united kingdom|australia)\s*\)"
    r"|\bremote[\s,\-]+(us|usa|united states?)\b"
    r"|\b(us|usa|united states?)[\s,\-]+remote\b"        # "US Remote" order
    r"|\bus[\s\-]+remote\b"                               # "US Remote" reversed order
    r"|\bremote\s+from\s+(us|usa|united states?|canada)\b"
    r"|\b(us|usa|united states?|canada|north america)\s*only\b"
    r"|\(us\)|\(usa\)|\(north america\)"
    r"|\(\s*(united states?|canada|uk|united kingdom|australia|north america)\s*\)"
    r"|\bamericas?\b"                                     # "Americas" / "America" region
    r"|\blatam\b"
    r"|\bnorth\s+america\s*\(remote\)"                    # "North America (Remote)"
    r"|\bcanada[\s,\-]+remote\b|\bremote[\s,\-]+canada\b"
    r"|\btoronto[\s\-]+based\b"
    r"|\b(st\.?\s*louis|toronto|vancouver|montreal)\b"
    r"|\(\s*\w[\w\s]+,\s*philippines\s*\)"
    # specific city+province/country in parens or after comma
    r"|\(\s*(?:toronto|calgary|vancouver|sydney|london|manila|philippines)\b"
    r"|,\s*(?:toronto|calgary|vancouver|ab|bc|on)\s*[\),]"
    # on-site indicators in titles
    r"|\bon[\s\-]?site\b|\bin[\s\-]?office\b"
    # city+state in title like "Manager, Austin TX" or "Specialist - New York"
    r"|,\s*(?:new york|san francisco|los angeles|chicago|austin|seattle|boston|denver"
    r"|atlanta|miami|dallas|houston|phoenix|washington\s*dc|portland|minneapolis)\b"
    # title ending with "- United States" or "(United States)"
    r"|[\-\s]+united states?\s*$"
    r"|\(\s*united states?\s*\)"
    # Country names appearing in parentheses in title — "(Remote, South Africa)", "(UK)", etc.
    r"|\(\s*(?:remote\s*,\s*)?(?:south africa|india|philippines|pakistan|nigeria|kenya"
    r"|brazil|mexico|indonesia|bangladesh|uk|united kingdom|australia|new zealand"
    r"|germany|france|spain|netherlands|poland|ukraine|israel|turkey|singapore)\b"
    # Explicit city/location after dash in title — "Engineer - Dallas, TX"
    r"|[-–]\s*(?:dallas|houston|austin|chicago|new york|san francisco|los angeles"
    r"|seattle|boston|denver|atlanta|miami|phoenix|portland|minneapolis)\b"
    # City in parentheses in title — "(Dallas TX)", "(Chicago, IL)"
    r"|\(\s*(?:dallas|houston|austin|chicago|new york|san francisco|los angeles"
    r"|seattle|boston|denver|atlanta|miami|phoenix|portland|minneapolis)\b",
    re.IGNORECASE,
)

# Aggregator / noise domains – block regardless of path
AGGREGATOR_DOMAINS = re.compile(
    r"\b(leverdemo|remoterocketship|dailyremote|kickstartremote|remotely\.jobs|flexjobs"
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


# ATS domains whose pages reliably embed location in <meta> tags
_ATS_DOMAINS = (
    "jobs.lever.co", "boards.greenhouse.io", "job-boards.greenhouse.io",
    "jobs.ashbyhq.com", "apply.workable.com", "jobs.jobvite.com", "ats.rippling.com",
)

_META_LOCATION_RE = re.compile(
    r'<meta\s[^>]*name=["\']twitter:data1["\']\s[^>]*value=["\']([^"\']+)["\']'
    r'|<meta\s[^>]*value=["\']([^"\']+)["\']\s[^>]*name=["\']twitter:data1["\']',
    re.IGNORECASE,
)

# Lever: JSON blob embedded in page  e.g. "location":"Remote (US)"
_LEVER_LOCATION_RE = re.compile(
    r'"location"\s*:\s*"([^"]{1,80})"',
    re.IGNORECASE,
)
# Ashby: <span> or <div> labelled "location" class
_ASHBY_LOCATION_RE = re.compile(
    r'<(?:span|div|p)[^>]*class=["\'][^"\']*location[^"\']*["\'][^>]*>\s*([^<]{1,80})\s*</',
    re.IGNORECASE,
)
# Workable: og:description often contains "Location: Remote (US)"
_WORKABLE_LOCATION_RE = re.compile(
    r'[Ll]ocation[:\s]+([^\n<"]{1,60})',
)

def _playwright_geo_blocked(url: str, timeout_ms: int = 12000) -> bool:
    """
    Render a job page with a headless browser and check visible text for
    geo-restriction phrases.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return False   # Playwright not installed — skip silently
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page    = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            text = page.inner_text("body")

            # Restricted countries/regions — any of these appearing as a standalone
            # location (in a structured field or as a short phrase) means blocked.
            _GEO_LOCATION_RE = re.compile(
                r"\b(united states?|u\.?s\.?a?|usa|canada|uk|united kingdom"
                r"|australia|north america|pakistan|india|philippines|nigeria"
                r"|kenya|bangladesh|nepal|sri lanka)\b",
                re.IGNORECASE,
            )

            # Check structured location elements across common ATS layouts.
            _LOCATION_SELECTORS = [
                ".jv-job-detail-meta",              # Jobvite
                "[data-qa='location']",             # Ashby
                "h3[class*='location']",
                "[class*='location']",
                "[class*='Location']",
                "[data-automation='job-location']",
                "[data-testid*='location']",
            ]
            for sel in _LOCATION_SELECTORS:
                try:
                    for el in page.query_selector_all(sel):
                        loc_text = el.inner_text().strip()
                        if not loc_text:
                            continue
                        # Split on semicolons/pipes — ATS sometimes lists multiple
                        # locations like "Remote Canada; Remote USA"
                        parts = re.split(r"[;|]", loc_text)
                        for part in parts:
                            part = part.strip()
                            if SINGLE_COUNTRY_RE.match(part) or US_CITY_STATE_RE.match(part):
                                browser.close()
                                return True
                            # Short location field (≤40 chars) that contains a
                            # blocked country/region name → blocked
                            if len(part) <= 40 and _GEO_LOCATION_RE.search(part):
                                browser.close()
                                return True
                except Exception:
                    pass

            # Scan short lines (≤60 chars) in body text as a fallback location check.
            # ATS pages often render location as a bare line like
            # "Toronto, Ontario; Remote Canada; Remote USA" outside any labelled element.
            for line in text.splitlines():
                line = line.strip()
                if not line or len(line) > 60:
                    continue
                parts = re.split(r"[;|,]", line)
                for part in parts:
                    part = part.strip()
                    if SINGLE_COUNTRY_RE.match(part) or US_CITY_STATE_RE.match(part):
                        browser.close()
                        return True
                    if len(part) <= 40 and _GEO_LOCATION_RE.search(part):
                        browser.close()
                        return True

            # US business hours = practical US-only restriction
            if re.search(r"\bu\.?s\.?\s+(\w+\s+)?business\s+hours\b", text, re.IGNORECASE):
                browser.close()
                return True

            browser.close()
        return bool(BODY_GEO_BLOCKED_RE.search(text))
    except Exception:
        return False   # Any error — don't block the job


def _playwright_geo_check_batch(jobs: list[dict], workers: int = 3) -> list[dict]:
    """
    Filter out geo-blocked jobs from JS-rendered ATS pages.
    Only processes jobs whose URL matches _JS_ATS_DOMAINS; others pass through.
    Uses a small thread pool so multiple pages render in parallel.
    """
    js_jobs = [j for j in jobs if j.get("needs_pw_check")]
    if not js_jobs:
        return jobs

    print(f"  Playwright geo-check: {len(js_jobs)} JS-rendered page(s)…")
    blocked_urls: set[str] = set()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_map = {ex.submit(_playwright_geo_blocked, j["url"]): j for j in js_jobs}
        for future in future_map:
            j = future_map[future]
            try:
                if future.result():
                    blocked_urls.add(j["url"])
                    print(f"  [geo-blocked] {j['title'][:70]}")
            except Exception:
                pass

    clean = [j for j in jobs if j["url"] not in blocked_urls]
    for j in clean:
        j.pop("needs_pw_check", None)
    return clean


def _ats_location(url: str) -> str:
    """
    Fetch an ATS job page and return the location value.
    Tries multiple extraction strategies across different ATS platforms.
    Also embeds any geo-restriction phrase found in the body so callers can
    pass the return value straight into BODY_GEO_BLOCKED_RE.
    """
    from urllib.parse import urlparse
    parsed_host = urlparse(url).netloc
    if not any(parsed_host.endswith(d) for d in _ATS_DOMAINS):
        return ""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            # 64 KB covers <head> meta tags + enough of the job description body
            page_html = r.read(65536).decode("utf-8", errors="ignore")

        loc = ""

        # Strategy 1: twitter:data1 meta tag (Greenhouse, Jobvite, some Lever)
        m = _META_LOCATION_RE.search(page_html)
        if m:
            loc = (m.group(1) or m.group(2) or "").strip()

        # Strategy 2: Lever JSON blob — "location":"Remote (US)"
        if not loc and "lever.co" in parsed_host:
            for m in _LEVER_LOCATION_RE.finditer(page_html):
                candidate = m.group(1).strip()
                # Skip obvious non-location JSON values
                if candidate and not candidate.startswith("http") and len(candidate) < 60:
                    loc = candidate
                    break

        # Strategy 3: Ashby location class element
        if not loc and "ashbyhq.com" in parsed_host:
            m = _ASHBY_LOCATION_RE.search(page_html)
            if m:
                loc = m.group(1).strip()

        # Strategy 4: Workable og:description or plain "Location:" text
        if not loc and "workable.com" in parsed_host:
            m = _WORKABLE_LOCATION_RE.search(page_html)
            if m:
                loc = m.group(1).strip().rstrip(",;. ")

        # Strategy 5: Look for common ATS location patterns in page title
        if not loc:
            title_m = re.search(r'<title[^>]*>([^<]{1,200})</title>', page_html, re.IGNORECASE)
            if title_m:
                title_text = title_m.group(1)
                # e.g. "Job Title - Remote (US)" or "Job Title | Remote, United States"
                loc_in_title = re.search(
                    r'[-|]\s*(remote[^<"]{0,40})',
                    title_text, re.IGNORECASE,
                )
                if loc_in_title:
                    loc = loc_in_title.group(1).strip()

        # Strip HTML tags for a plain-text excerpt to check geo patterns
        plain = re.sub(r"<[^>]+>", " ", page_html)

        # Return location + first geo-restriction sentence found, so the caller
        # can run both SINGLE_COUNTRY_RE and BODY_GEO_BLOCKED_RE on the result.
        if BODY_GEO_BLOCKED_RE.search(plain):
            geo_match = BODY_GEO_BLOCKED_RE.search(plain)
            return f"{loc} {geo_match.group()}".strip()
        return loc
    except Exception:
        pass
    return ""


# ── Scoring helpers ───────────────────────────────────────────────────────────
# Detects part-time / contractor / fractional signals for the SIDE_ROLE boost
_SIDE_ROLE_RE = re.compile(
    r"\bpart[\s\-]time\b|\bcontractor\b|\bcontract\s+role\b|\bfractional\b",
    re.IGNORECASE,
)

# Detects EMEA timezone alignment — natural fit for Egypt (UTC+2/+3)
_EMEA_RE = re.compile(
    r"\bemea\b|\butc\+[23]\b",
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
    url = url.strip().rstrip("/").lower().split("?")[0]
    # Rippling serves the same job with locale prefixes (e.g. /pt-BR/, /fr-CA/)
    url = re.sub(r"(ats\.rippling\.com)/[a-z]{2}-[a-z]{2}/", r"\1/", url)
    # Lever job URLs sometimes appear with a trailing /apply
    url = re.sub(r"(jobs\.lever\.co/[^/]+/[^/]+)/apply$", r"\1", url)
    return url


def score_job(title: str, description: str) -> int:
    text = f"{title} {description}".lower()
    score = sum(1 for kw in SKILL_KEYWORDS if kw in text)
    score += sum(3 for kw in HIGH_VALUE_KEYWORDS if kw in text)
    # +2 for part-time / contractor / fractional — side-role opportunities
    if _SIDE_ROLE_RE.search(text):
        score += 2
    # +1 for EMEA / UTC+2/+3 mentions — strong timezone alignment for Egypt
    if _EMEA_RE.search(text):
        score += 1
    return score


def is_blocked(location: str, description: str, title: str = "") -> bool:
    loc = location.strip()

    # If the location is clearly open/worldwide, only check title/body signals
    if LOCATION_OPEN_RE.match(loc):
        if title and TITLE_GEO_BLOCKED_RE.search(title):
            return True
        combined = f"{location} {title} {description}".lower()
        if ONSITE_RE.search(combined):
            return True
        if any(rx.search(combined) for rx in BLOCKED_PATTERNS):
            return True
        if BODY_GEO_BLOCKED_RE.search(f"{location} {description}"):
            return True
        if ROLE_TYPE_BLOCKED_RE.search(combined):
            return True
        return False

    # Location names a specific country or city — block unless it's Egypt/EMEA
    if SPECIFIC_LOCATION_RE.search(loc):
        return True
    # US city+state abbreviation
    if US_CITY_STATE_RE.match(loc):
        return True

    # Fallback: check title and body signals for any remaining cases
    if title and TITLE_GEO_BLOCKED_RE.search(title):
        return True
    combined = f"{location} {title} {description}".lower()
    if ONSITE_RE.search(combined):
        return True
    if any(rx.search(combined) for rx in BLOCKED_PATTERNS):
        return True
    if BODY_GEO_BLOCKED_RE.search(f"{location} {description}"):
        return True
    if ROLE_TYPE_BLOCKED_RE.search(combined):
        return True
    return False


def is_title_relevant(title: str) -> bool:
    if TITLE_BLOCKED_RE.search(title):
        return False
    return bool(TITLE_RELEVANT_RE.search(title))


def is_valid_job_url(url: str, require_job_path: bool = False) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
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
        if TITLE_GEO_BLOCKED_RE.search(title) or is_blocked(loc, desc, title):
            continue
        sc        = score_job(title, desc)
        base_tags = ", ".join(j.get("tags", [])[:6])
        # Append SIDE_ROLE tag when part-time / contractor signals are present
        extra = ["SIDE_ROLE"] if _SIDE_ROLE_RE.search(f"{title} {desc}") else []
        tags  = ", ".join(filter(None, [base_tags] + extra))
        job   = make_job(
            "Remotive", title, j.get("company_name", ""), loc,
            j.get("url", ""),
            normalize_date(j.get("publication_date", "")),
            sc, tags,
        )
        # Soft geo preference: penalise -2 and tag rather than hard-block
        if SOFT_GEO_PREFERRED_RE.search(f"{loc} {desc}"):
            job["score"] = max(0, job["score"] - 2)
            job["tags"]  = ", ".join(filter(None, [job["tags"], "GEO_SOFT_BLOCK"]))
        out.append(job)
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
        if BODY_GEO_BLOCKED_RE.search(body):
            continue
        ats_loc = _ats_location(url)
        if ats_loc and (SINGLE_COUNTRY_RE.match(ats_loc) or BODY_GEO_BLOCKED_RE.search(ats_loc)):
            continue
        sc = score_job(title, body)
        if sc < 1:
            continue
        company = _company_from_url(url)
        # Append SIDE_ROLE tag when part-time / contractor signals are present
        tags = ["SIDE_ROLE"] if _SIDE_ROLE_RE.search(f"{title} {body}") else []
        job  = make_job(source_tag, title, company, "Remote (verify posting)",
                        url, datetime.now().strftime("%Y-%m-%d"), sc,
                        ", ".join(tags))
        # Soft geo preference: penalise -2 and tag rather than hard-block
        if SOFT_GEO_PREFERRED_RE.search(f"{title} {body}"):
            job["score"] = max(0, job["score"] - 2)
            job["tags"]  = ", ".join(filter(None, [job["tags"], "GEO_SOFT_BLOCK"]))
        # Flag for Playwright check — we only have a short search snippet for
        # these URLs, so geo restrictions in the full page body haven't been read.
        job["needs_pw_check"] = True
        out.append(job)
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
        client = gspread.service_account(filename=str(GSHEET_CREDS))
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

    # ── Playwright geo-check (JS-rendered ATS pages) ───────────────────────
    live_jobs = _playwright_geo_check_batch(live_jobs)

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
