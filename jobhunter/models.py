"""Shared data structures for the JobHunter pipeline."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Job:
    source: str            # "Remotive" | "Company" (search engine)
    title: str
    url: str
    company: str = ""
    location: str = ""     # location as reported by the source, if any
    posted: str = ""       # YYYY-MM-DD
    description: str = ""  # full text when the source provides it (Remotive)
    needs_fetch: bool = True   # search hits only have a snippet; fetch full page
    prescore: int = 0      # cheap keyword score, used only to rank/cap LLM calls
    tags: list[str] = field(default_factory=list)


@dataclass
class FetchResult:
    status: Literal["ok", "dead", "error"]  # error = network issue, retry next run
    text: str = ""
    final_url: str = ""
    used_playwright: bool = False
