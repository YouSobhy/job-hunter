"""Cheap first-pass filter: URL sanity, title blocklist, keyword ranking.

This exists only to limit LLM calls — the bar is deliberately LOW.
Acceptance decisions belong to the judge.
"""

import logging
import re

from .config import Config
from .models import Job

log = logging.getLogger("jobhunter")

# Aggregator / noise domains - block regardless of path
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

# Obviously-wrong roles by title — saves an LLM call, nothing more
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
    r"|unpaid|volunteer|intern(?:ship)?|php developer|rails engineer"
    r"|ruby developer|blockchain|web3|crypto)\b",
    re.IGNORECASE,
)

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

_SIDE_ROLE_RE = re.compile(
    r"\bpart[\s\-]time\b|\bcontractor\b|\bcontract\s+role\b|\bfractional\b",
    re.IGNORECASE,
)


def is_valid_job_url(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    if AGGREGATOR_DOMAINS.search(url):
        return False
    if JUNK_URL_RE.search(url):
        return False
    if "aclick" in url or "msclkid" in url or len(url) > 500:
        return False
    return True


def keyword_score(title: str, description: str) -> int:
    text = f"{title} {description}".lower()
    score = sum(1 for kw in SKILL_KEYWORDS if kw in text)
    score += sum(3 for kw in HIGH_VALUE_KEYWORDS if kw in text)
    if _SIDE_ROLE_RE.search(text):
        score += 2
    return score


def prefilter(jobs: list[Job], cfg: Config) -> list[Job]:
    """Drop junk, rank by keyword score, cap at cfg.max_llm_calls."""
    kept: list[Job] = []
    for j in jobs:
        if not is_valid_job_url(j.url):
            continue
        if TITLE_BLOCKED_RE.search(j.title):
            continue
        j.prescore = keyword_score(j.title, j.description)
        if j.prescore < 1:
            continue
        if _SIDE_ROLE_RE.search(f"{j.title} {j.description}"):
            j.tags.append("SIDE_ROLE")
        kept.append(j)

    kept.sort(key=lambda j: j.prescore, reverse=True)
    if len(kept) > cfg.max_llm_calls:
        log.info("prefilter: capping %d candidates to %d", len(kept), cfg.max_llm_calls)
        kept = kept[: cfg.max_llm_calls]
    return kept
