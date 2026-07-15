"""Claude Haiku relevance judge.

Reads each job's fetched posting text and returns a structured Verdict:
role fit for Youssef's profile, geo eligibility for an Egypt-based
candidate, language check, real company name, and a one-line summary.
"""

import logging
from typing import Literal

from pydantic import BaseModel

from .config import Config, load_anthropic_key
from .models import Job

log = logging.getLogger("jobhunter")


class Verdict(BaseModel):
    fit_score: int  # 0-10 vs the candidate profile
    geo: Literal["eligible", "ineligible", "unclear"]
    language_ok: bool
    role_type_ok: bool
    company: str          # real company name as stated on the page
    location_stated: str  # what the posting actually says, e.g. "Remote - EMEA"
    reason: str           # one line: why accepted/rejected
    summary: str          # one-line job summary for the sheet


class JudgeUnavailable(Exception):
    """Total API failure (auth/network) — abort judging, retry next run."""


def make_client():
    import anthropic

    key = load_anthropic_key()
    if not key:
        raise JudgeUnavailable(
            "No Anthropic API key. Set ANTHROPIC_API_KEY or create anthropic_key.json "
            'with {"api_key": "sk-ant-..."}'
        )
    return anthropic.Anthropic(api_key=key)


def build_system_prompt(cfg: Config) -> str:
    return f"""You screen job postings for a candidate with this profile:

{cfg.profile}

Judge each posting on:

1. fit_score (0-10): 8-10 = core target role for this profile; 5-7 = adjacent role
   (e.g. account manager with heavy onboarding duties); 0-4 = wrong role
   (engineering, design, quota-carrying sales, marketing, recruiting, etc. —
   also set role_type_ok=false for those).

2. geo: "eligible" only if a candidate based in Egypt can actually be hired —
   worldwide/global/anywhere, EMEA, Middle East, Africa, or explicit Egypt.
   "ineligible" if US-only, EU-only, UK-only, single-foreign-country, on-site
   anywhere outside Egypt, US work authorization required, or US-business-hours-only.
   "unclear" only if the page truly does not say.
   Be strict: "Remote" alone from a US company listing US benefits (401k, US health
   insurance, W-2) usually means US-only — call that "ineligible" and say why.

3. language_ok: false if fluency in any language other than English or Arabic is
   required (e.g. German postings marked "(m/w/d)" that require German, "French +
   English", etc.).

4. role_type_ok: false if the role is actually engineering/development, design,
   quota-carrying sales, marketing, or otherwise outside the profile's target roles.

Also extract:
- company: the real company name as stated on the page (not the job board name).
- location_stated: the location text exactly as the posting states it (e.g.
  "Remote - EMEA", "Austin, TX", "Remote (US only)"). Use "Not stated" if absent.
- reason: one sentence explaining the verdict.
- summary: one sentence describing the job itself."""


def _truncate(text: str, cfg: Config) -> str:
    head, tail = cfg.truncate_head_chars, cfg.truncate_tail_chars
    if len(text) <= head + tail:
        return text
    # Head-biased: eligibility info is usually near the top, but "must be
    # located in..." often sits at the bottom
    return text[:head] + "\n[...truncated...]\n" + text[-tail:]


def judge_job(client, job: Job, page_text: str, cfg: Config) -> Verdict:
    user_msg = (
        f"Title: {job.title}\n"
        f"Source: {job.source}\n"
        f"URL: {job.url}\n"
        f"Source-reported location: {job.location or 'Not provided'}\n\n"
        f"Posting text:\n{_truncate(page_text, cfg)}"
    )
    response = client.messages.parse(
        model=cfg.model,
        max_tokens=1024,
        system=build_system_prompt(cfg),
        messages=[{"role": "user", "content": user_msg}],
        output_format=Verdict,
    )
    return response.parsed_output


def judge_batch(client, items: list[tuple[Job, str]], cfg: Config) -> dict[str, Verdict]:
    """Judge each (job, page_text). Returns {url: Verdict}; jobs whose call
    failed are simply absent (skipped, retried next run)."""
    import anthropic

    verdicts: dict[str, Verdict] = {}
    for i, (job, text) in enumerate(items, 1):
        print(f"  [judge {i}/{len(items)}] {job.title[:60]}")
        try:
            verdicts[job.url] = judge_job(client, job, text, cfg)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise JudgeUnavailable(f"Anthropic auth failed: {e}") from e
        except anthropic.APIConnectionError as e:
            raise JudgeUnavailable(f"Cannot reach Anthropic API: {e}") from e
        except Exception as e:
            # Per-job failure: skip, don't mark seen — retried next run
            log.warning("judge failed for %s: %s", job.url[:60], str(e)[:200])
    return verdicts
