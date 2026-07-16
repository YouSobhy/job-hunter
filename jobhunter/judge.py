"""LLM relevance judge — Gemini or Claude backend, auto-detected by key.

Reads each job's fetched posting text and returns a structured Verdict:
role fit for Youssef's profile, geo eligibility for an Egypt-based
candidate, language check, real company name, and a one-line summary.

Provider selection: Gemini key (GEMINI_API_KEY / GOOGLE_API_KEY /
gemini_key.json) wins if present — its free tier covers this workload.
Otherwise the Anthropic key (ANTHROPIC_API_KEY / anthropic_key.json).
"""

import logging
import time
from typing import Literal

from pydantic import BaseModel

from .config import Config, load_anthropic_key, load_gemini_key
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
    """Total API failure (no key / auth / network) — abort judging, retry next run."""


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


def _user_msg(job: Job, page_text: str, cfg: Config) -> str:
    return (
        f"Title: {job.title}\n"
        f"Source: {job.source}\n"
        f"URL: {job.url}\n"
        f"Source-reported location: {job.location or 'Not provided'}\n\n"
        f"Posting text:\n{_truncate(page_text, cfg)}"
    )


class Judge:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._system = build_system_prompt(cfg)
        gemini_key = load_gemini_key()
        anthropic_key = load_anthropic_key()
        if gemini_key:
            from google import genai

            self.provider = "gemini"
            self.model = cfg.gemini_model
            self._client = genai.Client(api_key=gemini_key)
        elif anthropic_key:
            import anthropic

            self.provider = "anthropic"
            self.model = cfg.model
            self._client = anthropic.Anthropic(api_key=anthropic_key)
        else:
            raise JudgeUnavailable(
                "No LLM API key found. Create gemini_key.json or anthropic_key.json "
                'with {"api_key": "..."}, or set GEMINI_API_KEY / ANTHROPIC_API_KEY.'
            )

    # -- per-provider calls ------------------------------------------------

    def _judge_gemini(self, job: Job, page_text: str) -> Verdict:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=self._system,
            response_mime_type="application/json",
            response_schema=Verdict,
        )
        for attempt in (1, 2):
            try:
                resp = self._client.models.generate_content(
                    model=self.model,
                    contents=_user_msg(job, page_text, self.cfg),
                    config=config,
                )
                break
            except errors.APIError as e:
                if e.code in (401, 403):
                    raise JudgeUnavailable(f"Gemini auth failed: {e}") from e
                if e.code == 429 and attempt == 1:
                    log.info("Gemini rate limit hit; sleeping 30s")
                    time.sleep(30)
                    continue
                raise
        verdict = resp.parsed
        if verdict is None:
            verdict = Verdict.model_validate_json(resp.text)
        return verdict

    def _judge_anthropic(self, job: Job, page_text: str) -> Verdict:
        response = self._client.messages.parse(
            model=self.model,
            max_tokens=1024,
            system=self._system,
            messages=[{"role": "user", "content": _user_msg(job, page_text, self.cfg)}],
            output_format=Verdict,
        )
        return response.parsed_output

    # -- public API ----------------------------------------------------------

    def judge_job(self, job: Job, page_text: str) -> Verdict:
        if self.provider == "gemini":
            return self._judge_gemini(job, page_text)
        return self._judge_anthropic(job, page_text)

    def judge_batch(self, items: list[tuple[Job, str]]) -> dict[str, Verdict]:
        """Judge each (job, page_text). Returns {url: Verdict}; jobs whose call
        failed are simply absent (skipped, retried next run)."""
        verdicts: dict[str, Verdict] = {}
        for i, (job, text) in enumerate(items, 1):
            print(f"  [judge {i}/{len(items)}] {job.title[:60]}")
            try:
                verdicts[job.url] = self.judge_job(job, text)
            except JudgeUnavailable:
                raise
            except Exception as e:
                if self._is_fatal(e):
                    raise JudgeUnavailable(f"{self.provider} API unavailable: {e}") from e
                # Per-job failure: skip, don't mark seen — retried next run
                log.warning("judge failed for %s: %s", job.url[:60], str(e)[:200])
            if self.provider == "gemini" and i < len(items):
                time.sleep(4)  # stay under the free tier's requests-per-minute cap
        return verdicts

    def _is_fatal(self, e: Exception) -> bool:
        if self.provider == "anthropic":
            import anthropic

            return isinstance(
                e,
                (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
                 anthropic.APIConnectionError),
            )
        from google.genai import errors

        return isinstance(e, errors.APIError) and e.code in (401, 403)
