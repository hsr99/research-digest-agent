"""Merge the same story reported by several sources (e.g. a blog post that also hit HN)."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import Item

TRACKING = re.compile(r"^(utm_|ref$|ref_src$|source$|fbclid$|gclid$|mc_)")
ARXIV_ID = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})")
NON_WORD = re.compile(r"[^a-z0-9 ]+")

# when two items are the same story, keep the URL from the more primary source
SOURCE_PRIORITY = {"rss": 0, "github": 1, "arxiv": 2, "hackernews": 3}


def normalize_url(url: str) -> str:
    if m := ARXIV_ID.search(url):
        return f"arxiv:{m.group(1)}"  # abs/pdf/html and v1/v2 are the same paper
    p = urlparse(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)])
    path = p.path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", query, ""))


def normalize_title(title: str) -> str:
    return " ".join(NON_WORD.sub(" ", title.lower()).split())


def same_story(a: Item, b: Item, threshold: float) -> bool:
    if normalize_url(a.url) == normalize_url(b.url):
        return True
    ta, tb = normalize_title(a.title), normalize_title(b.title)
    if min(len(ta), len(tb)) < 15:  # very short titles match too easily
        return False
    return SequenceMatcher(None, ta, tb).ratio() >= threshold


def merge(keep: Item, other: Item) -> Item:
    keep.also_seen_at.append(other.url)
    keep.also_seen_at.extend(other.also_seen_at)
    for k, v in other.signals.items():
        keep.signals.setdefault(k, v)  # e.g. carry HN points onto the blog post
    if len(other.text) > len(keep.text):
        keep.text = other.text
    return keep


def dedupe(items: list[Item], threshold: float = 0.85) -> list[Item]:
    items = sorted(items, key=lambda i: SOURCE_PRIORITY.get(i.source, 9))
    kept: list[Item] = []
    for item in items:
        for existing in kept:
            if same_story(existing, item, threshold):
                merge(existing, item)
                break
        else:
            kept.append(item)
    return kept
