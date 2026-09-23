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

from .config import (Config, load_anthropic_key, load_gemini_key,
                     load_grok_key, load_groq_key)
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

2. geo: "eligible" ONLY if an international candidate residing in Egypt (UTC+2) can actually be hired —
   i.e. the posting explicitly states Worldwide, Global, Remote Anywhere, EMEA, Middle East, Africa, or Egypt.
   "ineligible" if:
   - The posting is located in or restricted to ANY single specific country/city outside Egypt (e.g. India/New Delhi, US, EU, UK, Canada, Philippines, Germany, LatAm, Australia, etc.) UNLESS it explicitly states that candidates from outside that country (Worldwide/EMEA/Egypt) are eligible.
   - The posting requires local work authorization, visa, citizenship, or residency in a country outside Egypt (e.g. W-2, Green Card, India PF, UK Right to Work).
   - The posting offers benefits tied exclusively to a foreign country (e.g. US 401k, UK NHS, India PF/Gratuity).
   "unclear" if location eligibility is not specified.
   Be extremely strict: a job located in "New Delhi, India" or "Austin, TX" or "London, UK" without explicit global/EMEA remote eligibility MUST be marked "ineligible".

3. language_ok: false if fluency in any language other than English or Arabic is
   required (e.g. German postings marked "(m/w/d)" that require German, "French +
   English", etc.).

4. role_type_ok: false if the role is actually engineering/development, design,
   quota-carrying sales, marketing, or otherwise outside the profile's target roles.

Also extract:
- company: the real company name as stated on the page (not the job board name).
- location_stated: the location text exactly as the posting states it (e.g.
  "Remote - EMEA", "Austin, TX", "New Delhi, India"). Use "Not stated" if absent.
- reason: one sentence explaining the verdict.
- summary: one sentence describing the job itself. Reply in valid JSON format matching the schema."""


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
    def __init__(self, cfg: Config, custom_terms: list[str] | None = None):
        self.cfg = cfg
        self._system = build_system_prompt(cfg)
        if custom_terms:
            self._system += (
                "\n\nIMPORTANT — custom search override: for this search the "
                "candidate is specifically hunting for these roles: "
                + ", ".join(custom_terms)
                + ". Treat postings matching these titles as core target roles "
                "(fit 8-10 if they match well), even if they fall outside the "
                "usual profile. Geo and language rules still apply unchanged."
            )
        gemini_key = load_gemini_key()
        grok_key = load_grok_key()
        groq_key = load_groq_key()
        anthropic_key = load_anthropic_key()
        if gemini_key:
            from google import genai

            self.provider = "gemini"
            self.model = cfg.gemini_model
            self._client = genai.Client(api_key=gemini_key)
        elif grok_key:
            from openai import OpenAI

            self.provider = "grok"
            self.model = cfg.grok_model
            self._client = OpenAI(api_key=grok_key, base_url="https://api.x.ai/v1")
        elif groq_key:
            from openai import OpenAI

            self.provider = "groq"
            self.model = cfg.groq_model
            self._client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
        elif anthropic_key:
            import anthropic

            self.provider = "anthropic"
            self.model = cfg.model
            self._client = anthropic.Anthropic(api_key=anthropic_key)
        else:
            raise JudgeUnavailable(
                "No LLM API key found. Create gemini_key.json, grok_key.json, groq_key.json, or anthropic_key.json "
                'with {"api_key": "..."}, or set GEMINI_API_KEY / GROK_API_KEY / GROQ_API_KEY / ANTHROPIC_API_KEY.'
            )

    def _switch_fallback_provider(self) -> bool:
        grok_key = load_grok_key()
        groq_key = load_groq_key()
        anthropic_key = load_anthropic_key()
        if grok_key and self.provider != "grok":
            from openai import OpenAI

            log.warning("Switching LLM provider to Grok (%s)", self.cfg.grok_model)
            print(f"  [judge] switching provider to Grok ({self.cfg.grok_model})")
            self.provider = "grok"
            self.model = self.cfg.grok_model
            self._client = OpenAI(api_key=grok_key, base_url="https://api.x.ai/v1")
            return True
        elif groq_key and self.provider != "groq":
            from openai import OpenAI

            log.warning("Switching LLM provider to Groq (%s)", self.cfg.groq_model)
            print(f"  [judge] switching provider to Groq ({self.cfg.groq_model})")
            self.provider = "groq"
            self.model = self.cfg.groq_model
            self._client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            return True
        elif anthropic_key and self.provider != "anthropic":
            import anthropic

            log.warning("Switching LLM provider to Anthropic Claude (%s)", self.cfg.model)
            print(f"  [judge] switching provider to Anthropic Claude ({self.cfg.model})")
            self.provider = "anthropic"
            self.model = self.cfg.model
            self._client = anthropic.Anthropic(api_key=anthropic_key)
            return True
        return False


    # -- per-provider calls ------------------------------------------------

    def _judge_gemini(self, job: Job, page_text: str) -> Verdict:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=self._system,
            response_mime_type="application/json",
            response_schema=Verdict,
        )
        attempts = 0
        while True:
            attempts += 1
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
                if attempts >= 3:
                    if self._switch_fallback_provider():
                        return self.judge_job(job, page_text)
                    raise
                if e.code == 429 and "quota" in str(e).lower():
                    if self.model != self.cfg.gemini_fallback_model:
                        log.warning("Gemini daily quota hit on %s; switching to %s",
                                    self.model, self.cfg.gemini_fallback_model)
                        print(f"  [judge] quota hit; switching to {self.cfg.gemini_fallback_model}")
                        self.model = self.cfg.gemini_fallback_model
                        continue
                    elif self._switch_fallback_provider():
                        return self.judge_job(job, page_text)
                if e.code in (429, 503):
                    log.info("Gemini %s (rate limit/overload); sleeping 30s", e.code)
                    time.sleep(30)
                    continue
                raise
        verdict = resp.parsed
        if verdict is None:
            verdict = Verdict.model_validate_json(resp.text)
        return verdict

    def _judge_grok(self, job: Job, page_text: str) -> Verdict:
        attempts = 0
        while True:
            attempts += 1
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self._system},
                        {"role": "user", "content": _user_msg(job, page_text, self.cfg)},
                    ],
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content
                return Verdict.model_validate_json(content)
            except Exception as e:
                if self._is_fatal(e):
                    raise JudgeUnavailable(f"Grok auth/permission error: {e}") from e
                if attempts >= 3:
                    if self._switch_fallback_provider():
                        return self.judge_job(job, page_text)
                    raise
                log.info("Grok API error (%s); sleeping 10s before retry", e)
                time.sleep(10)

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
            v = self._judge_gemini(job, page_text)
        elif self.provider in ("grok", "groq"):
            v = self._judge_grok(job, page_text)
        else:
            v = self._judge_anthropic(job, page_text)

        # Programmatic safety check: override single foreign locations (India, US, UK, etc.) to ineligible
        loc_check = (str(job.location or "") + " " + str(v.location_stated or "")).lower()
        body_check = (str(job.title or "") + " " + str(page_text[:2000])).lower()
        is_global = any(g in body_check or g in loc_check for g in ("worldwide", "global", "emea", "middle east", "egypt", "remote anywhere"))

        single_country_keywords = ("india", "new delhi", "delhi", "philippines", "manila", "united states", "us only", "usa", "uk only", "london", "canada", "australia", "germany", "france")
        if any(ck in loc_check for ck in single_country_keywords) and not is_global:
            v.geo = "ineligible"
            v.reason = f"Posting location ({v.location_stated or job.location}) is restricted to a single foreign country outside Egypt."

        return v

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
        if self.provider in ("grok", "groq"):
            import openai

            return isinstance(
                e,
                (openai.AuthenticationError, openai.PermissionDeniedError),
            )
        if self.provider == "anthropic":
            import anthropic

            return isinstance(
                e,
                (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
                 anthropic.APIConnectionError),
            )
        from google.genai import errors

        return isinstance(e, errors.APIError) and e.code in (401, 403)


