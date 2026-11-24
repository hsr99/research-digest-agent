"""Fetchers for each news source. Every fetcher returns list[Item] and never raises:
a broken source is logged and skipped so one dead feed can't kill the daily run."""
from __future__ import annotations

import html
import logging
import os
import re
from calendar import timegm
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import feedparser
import httpx

from .models import Item

log = logging.getLogger(__name__)

USER_AGENT = "research-digest-agent/0.1 (+https://github.com)"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(raw: str, limit: int = 1500) -> str:
    text = html.unescape(TAG_RE.sub(" ", raw or ""))
    return WS_RE.sub(" ", text).strip()[:limit]


def _struct_to_dt(st) -> datetime | None:
    return datetime.fromtimestamp(timegm(st), tz=timezone.utc) if st else None


def make_client() -> httpx.Client:
    return httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})


# ---------------------------------------------------------------- arXiv
def fetch_arxiv(client: httpx.Client, cfg: dict, since: datetime) -> list[Item]:
    # arXiv announces in daily batches with a lag, so we don't filter by `since` here.
    # Instead we take the newest papers and rely on the "seen" store to skip repeats.
    query = " OR ".join(f"cat:{c}" for c in cfg["categories"])
    url = (
        "https://export.arxiv.org/api/query?search_query="
        + quote(query)
        + f"&sortBy=submittedDate&sortOrder=descending&max_results={cfg['max_results']}"
    )
    feed = feedparser.parse(client.get(url).text)
    items = []
    for e in feed.entries:
        cats = [t["term"] for t in e.get("tags", [])]
        items.append(
            Item(
                source="arxiv",
                title=clean_text(e.title, 300),
                url=e.link.replace("http://", "https://"),
                published=_struct_to_dt(e.get("published_parsed")) or datetime.now(timezone.utc),
                text=clean_text(e.get("summary", "")),
                origin=cats[0] if cats else "arxiv",
                signals={"authors": len(e.get("authors", []))},
            )
        )
    return items


# ---------------------------------------------------------------- Hacker News
def _keyword_regex(keywords: list[str]) -> re.Pattern:
    parts = []
    for kw in keywords:
        p = r"\b" + re.escape(kw)
        if len(kw) <= 3:  # short words like "AI" need a closing boundary too ("aim", "air")
            p += r"\b"
        parts.append(p)
    return re.compile("|".join(parts), re.IGNORECASE)


def fetch_hackernews(client: httpx.Client, cfg: dict, since: datetime) -> list[Item]:
    url = "https://hn.algolia.com/api/v1/search_by_date"
    params = {
        "tags": "story",
        "numericFilters": f"created_at_i>{int(since.timestamp())},points>={cfg['min_points']}",
        "hitsPerPage": 200,
    }
    hits = client.get(url, params=params).json().get("hits", [])
    kw = _keyword_regex(cfg["keywords"])
    items = []
    for h in hits:
        title = h.get("title") or ""
        if not kw.search(title):
            continue
        discussion = f"https://news.ycombinator.com/item?id={h['objectID']}"
        items.append(
            Item(
                source="hackernews",
                title=title,
                url=h.get("url") or discussion,
                published=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
                text=clean_text(h.get("story_text") or ""),
                origin=urlparse(h.get("url") or discussion).netloc,
                signals={
                    "points": h.get("points", 0),
                    "comments": h.get("num_comments", 0),
                    "discussion": discussion,
                },
            )
        )
    return items


# ---------------------------------------------------------------- GitHub releases
def fetch_github(client: httpx.Client, cfg: dict, since: datetime) -> list[Item]:
    headers = {"Accept": "application/vnd.github+json"}
    if token := os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    items = []
    for repo in cfg["repos"]:
        try:
            r = client.get(f"https://api.github.com/repos/{repo}/releases?per_page=5", headers=headers)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("github %s: %s", repo, e)
            continue
        for rel in r.json():
            # skip drafts and release candidates: only stable releases are news
            if rel.get("draft") or rel.get("prerelease") or not rel.get("published_at"):
                continue
            published = datetime.fromisoformat(rel["published_at"].replace("Z", "+00:00"))
            if published < since:
                continue
            items.append(
                Item(
                    source="github",
                    title=f"{repo} {rel.get('name') or rel['tag_name']}",
                    url=rel["html_url"],
                    published=published,
                    text=clean_text(rel.get("body") or ""),
                    origin=repo,
                    signals={"prerelease": rel.get("prerelease", False)},
                )
            )
    return items


# ---------------------------------------------------------------- RSS / Atom
def fetch_rss(client: httpx.Client, cfg: dict, since: datetime) -> list[Item]:
    items = []
    for feed_url in cfg["feeds"]:
        try:
            r = client.get(feed_url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("rss %s: %s", feed_url, e)
            continue
        feed = feedparser.parse(r.content)
        if not feed.entries:
            log.warning("rss %s: no entries parsed", feed_url)
        for e in feed.entries:
            published = _struct_to_dt(e.get("published_parsed") or e.get("updated_parsed"))
            if not published or published < since or not e.get("link"):
                continue
            items.append(
                Item(
                    source="rss",
                    title=clean_text(e.get("title", ""), 300),
                    url=e.link,
                    published=published,
                    text=clean_text(e.get("summary", "")),
                    origin=urlparse(feed_url).netloc,
                )
            )
    return items


FETCHERS = {
    "arxiv": fetch_arxiv,
    "hackernews": fetch_hackernews,
    "github": fetch_github,
    "rss": fetch_rss,
}


def fetch_all(cfg: dict, lookback_hours: int) -> tuple[list[Item], dict]:
    """Run every configured source. Returns (items, per-source stats)."""
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    items: list[Item] = []
    stats: dict = {}
    with make_client() as client:
        for name, fn in FETCHERS.items():
            if name not in cfg:
                continue
            try:
                got = fn(client, cfg[name], since)
                stats[name] = {"items": len(got)}
            except Exception as e:  # noqa: BLE001 - a source must never crash the run
                log.error("source %s failed: %s", name, e)
                got, stats[name] = [], {"items": 0, "error": str(e)[:200]}
            items.extend(got)
    return items, stats
