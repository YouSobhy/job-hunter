"""Configuration and credential loading."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_FILE = BASE_DIR / "config.json"
SEEN_FILE = BASE_DIR / "seen_jobs.json"
RESULTS_LOG = BASE_DIR / "job_results_log.txt"
DIAG_LOG = BASE_DIR / "jobhunter.log"
STATUS_FILE = BASE_DIR / "status.json"
GSHEET_CREDS = BASE_DIR / "google_credentials.json"
GOOGLE_CSE_FILE = BASE_DIR / "google_cse.json"
SERPAPI_FILE = BASE_DIR / "serpapi.json"
ANTHROPIC_KEY_FILE = BASE_DIR / "anthropic_key.json"
GEMINI_KEY_FILE = BASE_DIR / "gemini_key.json"
GROK_KEY_FILE = BASE_DIR / "grok_key.json"
GROQ_KEY_FILE = BASE_DIR / "groq_key.json"
XAI_KEY_FILE = BASE_DIR / "xai_key.json"


@dataclass
class Config:
    sheet_name: str
    model: str
    profile: str
    gemini_model: str = "gemini-3.6-flash"
    gemini_fallback_model: str = "gemini-flash-lite-latest"
    grok_model: str = "grok-2-latest"
    groq_model: str = "openai/gpt-oss-120b"
    max_llm_calls: int = 20
    fit_threshold: int = 6
    truncate_head_chars: int = 7000
    truncate_tail_chars: int = 1000
    remotive_terms: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    freelance_terms: list[str] = field(default_factory=list)


def load_config() -> Config:
    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return Config(**data)


def _json_key(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(key)
    except Exception:
        return None


def load_serpapi_key() -> str | None:
    return _json_key(SERPAPI_FILE, "api_key")


def load_cse_creds() -> tuple[str | None, str | None]:
    return _json_key(GOOGLE_CSE_FILE, "api_key"), _json_key(GOOGLE_CSE_FILE, "cx")


def load_anthropic_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or _json_key(ANTHROPIC_KEY_FILE, "api_key")


def load_gemini_key() -> str | None:
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or _json_key(GEMINI_KEY_FILE, "api_key")
    )


def load_grok_key() -> str | None:
    return (
        os.environ.get("GROK_API_KEY")
        or os.environ.get("XAI_API_KEY")
        or _json_key(GROK_KEY_FILE, "api_key")
        or _json_key(XAI_KEY_FILE, "api_key")
    )


def load_groq_key() -> str | None:
    return (
        os.environ.get("GROQ_API_KEY")
        or _json_key(GROQ_KEY_FILE, "api_key")
    )


