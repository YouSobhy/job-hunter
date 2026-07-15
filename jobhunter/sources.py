"""Job sources: Remotive API + search-engine chain (SerpAPI -> Google CSE -> DDG).

Sources return raw candidates. All relevance/geo judgment happens later
(prefilter caps the list; the LLM judge decides).
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from .config import Config, load_cse_creds, load_serpapi_key
from .models import Job

log = logging.getLogger("jobhunter")

# DuckDuckGo/SerpAPI: prepend site: targets so we hit company/ATS pages
_DDG_SITES = (
    "site:boards.greenhouse.io OR site:jobs.lever.co "
    "OR site:jobs.ashbyhq.com OR site:apply.workable.com "
    "OR site:careers.smartrecruiters.com OR site:jobs.jobvite.com "
    "OR site:deel.com OR site:remote.com OR site:rippling.com "
    "OR site:hibob.com OR site:personio.com OR site:freshworks.com "
    "OR site:zendesk.com OR site:bamboohr.com OR site:chargebee.com"
)


def fetch_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "JobSearch/3.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode(errors="replace")[:400]
            msg = json.loads(body).get("error", {}).get("message", body[:200])
        except Exception:
            msg = str(e)
        log.warning("fetch failed %s: HTTP %s - %s", url[:60], e.code, msg)
        return None
    except Exception as e:
        log.warning("fetch failed %s: %s", url[:60], e)
        return None


def _normalize_date(raw: str) -> str:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19], fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return raw[:10] if raw else datetime.now().strftime("%Y-%m-%d")


# -- Remotive ------------------------------------------------------------------

def fetch_remotive(term: str) -> list[Job]:
    url = f"https://remotive.com/api/remote-jobs?search={urllib.parse.quote(term)}&limit=20"
    data = fetch_json(url)
    if not data or "jobs" not in data:
        return []
    out = []
    for j in data["jobs"]:
        out.append(Job(
            source="Remotive",
            title=j.get("title", ""),
            url=j.get("url", ""),
            company=j.get("company_name", ""),
            location=j.get("candidate_required_location", ""),
            posted=_normalize_date(j.get("publication_date", "")),
            description=j.get("description", ""),
            needs_fetch=False,   # Remotive gives the full description
        ))
    return out


# -- Search engines ------------------------------------------------------------

def _serpapi_search(query: str, api_key: str, num: int = 10) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": query, "api_key": api_key, "engine": "google", "num": num, "hl": "en",
    })
    data = fetch_json(f"https://serpapi.com/search.json?{params}")
    if not data:
        return []
    if "error" in data:
        log.warning("SerpAPI: %s", data["error"])
        return []
    return [
        {"href": r.get("link", ""), "title": r.get("title", ""), "body": r.get("snippet", "")}
        for r in data.get("organic_results", [])
    ]


def _google_cse_search(query: str, api_key: str, cx: str, num: int = 10) -> list[dict]:
    results = []
    for start in (1, 11):
        params = urllib.parse.urlencode({
            "key": api_key, "cx": cx, "q": query, "num": min(num, 10), "start": start,
        })
        data = fetch_json(f"https://www.googleapis.com/customsearch/v1?{params}")
        if not data:
            break
        if "error" in data:
            err = data["error"]
            log.warning("Google CSE error %s: %s", err.get("code", "?"), err.get("message", ""))
            break
        for item in data.get("items", []):
            results.append({
                "href": item.get("link", ""),
                "title": item.get("title", ""),
                "body": item.get("snippet", ""),
            })
        if len(data.get("items", [])) < 10:
            break
    return results


def _ddgs_search(query: str, max_results: int = 10, retries: int = 1) -> list[dict]:
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
                log.warning("DDG fallback: %s", msg)
    return []


def pick_engine() -> tuple[str, str | None, str | None, str | None]:
    """Returns (engine_name, serpapi_key, cse_key, cse_cx)."""
    serpapi_key = load_serpapi_key()
    cse_key, cx = load_cse_creds()
    if serpapi_key:
        return "SerpAPI (Google)", serpapi_key, None, None
    if cse_key and cx:
        return "Google CSE", None, cse_key, cx
    return "DuckDuckGo (fallback)", None, None, None


def search_query(query: str, serpapi_key, cse_key, cx) -> list[Job]:
    """Run one query through the engine chain; return raw candidates."""
    if serpapi_key:
        raw = _serpapi_search(f"({_DDG_SITES}) {query}", serpapi_key)
    elif cse_key and cx:
        raw = _google_cse_search(query, cse_key, cx)  # engine already domain-restricted
    else:
        raw = _ddgs_search(f"({_DDG_SITES}) {query}")

    out = []
    today = datetime.now().strftime("%Y-%m-%d")
    for r in raw:
        url, title = r.get("href", ""), r.get("title", "")
        if not url or not title:
            continue
        out.append(Job(
            source="Company",
            title=title,
            url=url,
            description=r.get("body", ""),  # snippet only
            posted=today,
            needs_fetch=True,
        ))
    return out


def gather_all(cfg: Config) -> list[Job]:
    """All sources, raw. Throttles between search queries."""
    engine, serpapi_key, cse_key, cx = pick_engine()
    log.info("search engine: %s", engine)
    print(f"  Search: {engine}")

    jobs: list[Job] = []
    print("\n--- Remotive ---")
    for term in cfg.remotive_terms:
        print(f"[>] {term}")
        jobs.extend(fetch_remotive(term))

    print(f"\n--- {engine} ---")
    for q in cfg.search_queries:
        label = q.split('"')[1] if '"' in q else q[:60]
        print(f"[>] {label}")
        jobs.extend(search_query(q, serpapi_key, cse_key, cx))
        if serpapi_key:
            time.sleep(1)
        elif not cse_key:
            time.sleep(4)  # heavier throttle for DDG
    return jobs
