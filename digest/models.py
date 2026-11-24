from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Item:
    """One candidate story from any source."""

    source: str            # "arxiv" | "hackernews" | "github" | "rss"
    title: str
    url: str
    published: datetime
    text: str = ""         # abstract / description / snippet used for ranking and summaries
    origin: str = ""       # e.g. feed host, repo name, arXiv category
    signals: dict = field(default_factory=dict)  # e.g. {"points": 120, "comments": 40}
    also_seen_at: list[str] = field(default_factory=list)  # duplicate URLs merged into this one

    # filled by the pipeline
    score: float | None = None
    tag: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat()
        return d


@dataclass
class Story:
    """A final digest entry written by the LLM."""

    headline: str
    summary: str
    why_it_matters: str
    tag: str
    url: str
    source: str
    published: str
    score: float
    also_seen_at: list[str] = field(default_factory=list)
    model: str = ""
