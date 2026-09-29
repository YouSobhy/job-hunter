import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
from .models import Job
import time
import re
import logging

log = logging.getLogger("jobhunter")

def gather_linkedin(query: str, location: str = "Remote") -> list[Job]:
    """Scrape LinkedIn jobs-guest API for recent job postings."""
    params = urllib.parse.urlencode({
        "keywords": query,
        "location": location,
        "f_TPR": "r604800", # Past week (7 days)
        "f_WT": "2" # Remote
    })
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{params}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
    }
    
    req = urllib.request.Request(url, headers=headers)
    try:
        log.info(f"Fetching LinkedIn jobs for: {query}")
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode("utf-8")
    except Exception as e:
        log.error(f"LinkedIn search failed for {query}: {e}")
        return []
        
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    
    for card in soup.find_all("div", class_="base-card"):
        title_elem = card.find("h3", class_="base-search-card__title")
        company_elem = card.find("h4", class_="base-search-card__subtitle")
        loc_elem = card.find("span", class_="job-search-card__location")
        link_elem = card.find("a", class_="base-card__full-link")
        
        if not title_elem or not link_elem:
            continue
            
        title = title_elem.get_text(strip=True)
        company = company_elem.get_text(strip=True) if company_elem else ""
        location_text = loc_elem.get_text(strip=True) if loc_elem else ""
        
        raw_url = link_elem.get("href", "")
        # Clean the tracking parameters
        url_clean = raw_url.split("?")[0] if raw_url else ""
        
        # We extract the Job ID to use the raw text API for the detail fetcher
        # so we don't get blocked by LinkedIn's login walls.
        job_id_match = re.search(r'-(\d+)$', url_clean)
        if job_id_match:
            job_id = job_id_match.group(1)
            detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
        else:
            detail_url = url_clean
        
        jobs.append(Job(
            source="LinkedIn",
            title=title,
            company=company,
            location=location_text,
            url=detail_url,
            needs_fetch=True,
            tags=["LinkedIn"]
        ))
        
    return jobs
