"""Full-posting fetcher: HTTP + BeautifulSoup, Playwright fallback.

Fetching IS the liveness check — 404s, homepage redirects, and
"no longer accepting applications" pages come back status="dead".
"""

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .models import FetchResult, Job

log = logging.getLogger("jobhunter")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_DEAD_PATTERNS = re.compile(
    r"(job.no.longer|position.closed|no.longer.available|this.job.has.expired"
    r"|page.not.found|listing.has.expired|role.has.been.filled"
    r"|application.closed|vacancy.closed|no longer accepting applications"
    r"|job.(?:was.)?not.found|job.you.requested.was.not.found|posting.has.been.removed)",
    re.IGNORECASE,
)

_JS_SHELL_RE = re.compile(
    r"enable javascript|javascript is required|loading\.{3}|please wait",
    re.IGNORECASE,
)

MIN_TEXT_CHARS = 400


def _is_homepage_redirect(orig_url: str, final_url: str) -> bool:
    orig_path = urllib.parse.urlparse(orig_url.lower()).path.rstrip("/")
    final_path = urllib.parse.urlparse(final_url.lower()).path.rstrip("/")
    return bool(orig_path) and len(orig_path) > 10 and len(final_path) < len(orig_path) * 0.35


def _extract_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = root.get_text(separator="\n")
    # Collapse blank-line runs
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _http_fetch(url: str, timeout: float = 15.0) -> FetchResult:
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.url
            if resp.status in (404, 410):
                return FetchResult("dead", final_url=final_url)
            if _is_homepage_redirect(url, final_url):
                return FetchResult("dead", final_url=final_url)
            html = resp.read(1_000_000).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return FetchResult("dead", final_url=url)
        return FetchResult("error", final_url=url)
    except Exception:
        return FetchResult("error", final_url=url)

    text = _extract_text(html)
    if _DEAD_PATTERNS.search(text):
        return FetchResult("dead", text=text, final_url=final_url)
    return FetchResult("ok", text=text, final_url=final_url)


def _playwright_fetch(url: str, timeout_ms: int = 20000) -> FetchResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return FetchResult("error", final_url=url)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=_UA)
                # networkidle never fires on some ATS pages (Ashby keeps
                # connections open) — wait for DOM, then poll for rendered text
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                text = ""
                for _ in range(16):  # up to ~8s
                    text = page.inner_text("body")
                    if len(text) >= MIN_TEXT_CHARS:
                        break
                    page.wait_for_timeout(500)
                final_url = page.url
            finally:
                browser.close()
    except Exception as e:
        log.warning("playwright fetch failed %s: %s", url[:60], str(e)[:100])
        return FetchResult("error", final_url=url)

    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    if _is_homepage_redirect(url, final_url):
        return FetchResult("dead", final_url=final_url, used_playwright=True)
    if _DEAD_PATTERNS.search(text):
        return FetchResult("dead", text=text, final_url=final_url, used_playwright=True)
    if len(text) < MIN_TEXT_CHARS:
        return FetchResult("error", text=text, final_url=final_url, used_playwright=True)
    return FetchResult("ok", text=text, final_url=final_url, used_playwright=True)


def fetch_posting(url: str) -> FetchResult:
    result = _http_fetch(url)
    if result.status == "dead":
        return result
    needs_js = result.status == "error" or len(result.text) < MIN_TEXT_CHARS or _JS_SHELL_RE.search(
        result.text[:2000]
    )
    if needs_js:
        return _playwright_fetch(url)
    return result


def fetch_batch(jobs: list[Job], http_workers: int = 6) -> dict[str, FetchResult]:
    """Fetch full text for every job that needs it. Returns {url: FetchResult}."""
    results: dict[str, FetchResult] = {}
    to_fetch = [j for j in jobs if j.needs_fetch]
    if not to_fetch:
        return results

    print(f"  Fetching {len(to_fetch)} posting page(s)...")
    needs_pw: list[Job] = []
    with ThreadPoolExecutor(max_workers=http_workers) as ex:
        future_map = {ex.submit(_http_fetch, j.url): j for j in to_fetch}
        for future, j in future_map.items():
            try:
                r = future.result()
            except Exception:
                r = FetchResult("error", final_url=j.url)
            if r.status == "ok" and (
                len(r.text) < MIN_TEXT_CHARS or _JS_SHELL_RE.search(r.text[:2000])
            ):
                needs_pw.append(j)
            elif r.status == "error":
                needs_pw.append(j)
            else:
                results[j.url] = r

    # Playwright fallbacks run sequentially — they're few, and it avoids
    # multi-browser flakiness
    for j in needs_pw:
        print(f"  [playwright] {j.title[:60]}")
        results[j.url] = _playwright_fetch(j.url)

    dead = sum(1 for r in results.values() if r.status == "dead")
    errs = sum(1 for r in results.values() if r.status == "error")
    print(f"  fetched: {len(results) - dead - errs} ok | {dead} dead | {errs} error")
    return results
