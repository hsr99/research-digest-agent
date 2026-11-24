"""The digest pipeline: fetch -> dedupe -> skip already-published -> rank -> select -> enrich -> write."""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from . import prompts
from .dedupe import dedupe, normalize_url
from .llm import AllProvidersFailed, InvalidOutput, Router
from .models import Item, Story
from .sources import USER_AGENT, clean_text, fetch_all, keyword_regex
from .store import Store

log = logging.getLogger(__name__)

RANK_BATCH = 20
MIN_SOURCE_CHARS = 150
PARAGRAPH = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
BOILERPLATE = re.compile(
    r"<(script|style|noscript|nav|header|footer|aside|form|svg)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
MAIN_BLOCK = [re.compile(rf"<{t}\b[^>]*>(.*)</{t}>", re.DOTALL | re.IGNORECASE) for t in ("article", "main")]
# pages that need JavaScript to render: fetching them only yields app code
JS_ONLY_HOSTS = {"twitter.com", "x.com", "www.threads.net", "bsky.app"}


# ---------------------------------------------------------------- ranking
def format_candidate(i: int, item: Item) -> str:
    sig = ", ".join(f"{k}={v}" for k, v in item.signals.items() if k in ("points", "comments"))
    return f"[{i}] ({item.source}, {item.origin}{', ' + sig if sig else ''}) {item.title}\n    {item.text[:350]}"


def make_rank_validator(ids: set[int]):
    def validate(data):
        if not isinstance(data, dict) or not isinstance(data.get("scores"), list):
            raise InvalidOutput('expected {"scores": [...]}')
        out = {}
        for s in data["scores"]:
            try:
                i, score = int(s["id"]), float(s["score"])
            except (KeyError, TypeError, ValueError):
                continue
            if i in ids:
                tag = s.get("tag") if s.get("tag") in prompts.TAGS else "Research"
                out[i] = (max(0.0, min(10.0, score)), tag, str(s.get("reason", ""))[:200])
        missing = ids - out.keys()
        if len(missing) > len(ids) * 0.2:
            raise InvalidOutput(f"missing scores for ids {sorted(missing)}")
        return out
    return validate


def rank_llm(items: list[Item], router: Router, topic: str) -> None:
    system = prompts.RANK_SYSTEM.format(topic=topic.strip(), tags=", ".join(prompts.TAGS))
    for start in range(0, len(items), RANK_BATCH):
        batch = items[start : start + RANK_BATCH]
        ids = set(range(start, start + len(batch)))
        text = "\n".join(format_candidate(start + k, it) for k, it in enumerate(batch))
        scores, model = router.complete_json(
            "rank", system, prompts.RANK_USER.format(items=text),
            validate=make_rank_validator(ids), temperature=0.0,
        )
        for k, it in enumerate(batch):
            it.score, it.tag, it.reason = scores.get(start + k, (0.0, "", "not scored"))


SOURCE_BASE = {"rss": 6.0, "github": 5.5, "hackernews": 4.0, "arxiv": 4.0}


def rank_heuristic(items: list[Item], fallback_cfg: dict) -> None:
    """No-LLM ranking: used when every LLM is down, and by --no-llm runs.

    score = source base           hand-picked feeds > firehoses (HN, arXiv)
          + popularity            log10(HN points), capped at +3
          + duplicate bonus       +0.5 per extra source carrying the story
          + topic relevance       topic keywords in the title (+1 each) or text (+0.5), cap +2.5
          - off-topic penalty     -3 if the title matches funding/drama/opinion words
    """
    relevant = keyword_regex(fallback_cfg["relevant"])
    off_topic = keyword_regex(fallback_cfg["off_topic"])
    for it in items:
        pts = it.signals.get("points", 0)
        in_title = {m.group(0).lower() for m in relevant.finditer(it.title)}
        in_text = {m.group(0).lower() for m in relevant.finditer(it.text[:600])} - in_title
        relevance = min(2.5, len(in_title) + 0.5 * len(in_text))
        penalty = 3.0 if off_topic.search(it.title) else 0.0
        it.score = round(SOURCE_BASE.get(it.source, 4.0) + min(3.0, math.log10(pts + 1))
                         + 0.5 * len(it.also_seen_at) + relevance - penalty, 2)
        it.tag = ""
        it.reason = f"keywords: {', '.join(sorted(in_title | in_text)) or 'none'}" + \
                    (" | off-topic penalty" if penalty else "")


def select(items: list[Item], max_items: int, min_score: float = 5.0,
           per_source_cap: int | None = None) -> list[Item]:
    """Top stories by score, capped per source so arXiv can't crowd out everything else."""
    per_source_cap = per_source_cap or max(2, math.ceil(max_items / 2))
    picked, counts = [], {}
    for it in sorted(items, key=lambda x: x.score or 0, reverse=True):
        if (it.score or 0) < min_score or counts.get(it.source, 0) >= per_source_cap:
            continue
        picked.append(it)
        counts[it.source] = counts.get(it.source, 0) + 1
        if len(picked) == max_items:
            break
    return picked


# ---------------------------------------------------------------- enrichment
def article_text(page: str) -> str:
    """Rough readability: drop page chrome, prefer <article>/<main>, keep real paragraphs."""
    page = BOILERPLATE.sub(" ", page)
    for pattern in MAIN_BLOCK:
        if m := pattern.search(page):
            page = m.group(1)
            break
    paras = [clean_text(p, 2000) for p in PARAGRAPH.findall(page)]
    # real prose has sentences; menus and buttons don't
    return " ".join(p for p in paras if len(p) > 60 and "." in p)


def enrich(items: list[Item]) -> None:
    """Feeds and HN often give only a teaser; pull the article's paragraphs so the writer
    has real source text to stay faithful to."""
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as c:
        for it in items:
            if len(it.text) >= 800 or it.source in ("arxiv", "github"):
                continue
            if urlparse(it.url).netloc.lower() in JS_ONLY_HOSTS:
                continue
            try:
                r = c.get(it.url)
                if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                    continue
                body = article_text(r.text)
                if len(body) > len(it.text):
                    it.text = body[:4000]
            except httpx.HTTPError as e:
                log.info("enrich %s: %s", it.url, e)


# ---------------------------------------------------------------- writing
def validate_story(data):
    if not isinstance(data, dict):
        raise InvalidOutput("expected a JSON object")
    for k in ("headline", "summary", "why_it_matters"):
        if not isinstance(data.get(k), str) or len(data[k].strip()) < 5:
            raise InvalidOutput(f"field '{k}' missing or empty")
    if len(data["headline"]) > 140:
        raise InvalidOutput("headline longer than 140 characters")
    if data.get("tag") not in prompts.TAGS:
        data["tag"] = "Research"
    return data


def write_story(item: Item, router: Router) -> Story:
    sig = item.signals
    signals = f"Hacker News: {sig['points']} points, {sig['comments']} comments\n" if "points" in sig else ""
    data, model = router.complete_json(
        "write",
        prompts.WRITE_SYSTEM.format(tags=", ".join(prompts.TAGS)),
        prompts.WRITE_USER.format(source=item.source, origin=item.origin, title=item.title,
                                  url=item.url, signals=signals, text=item.text[:4000]),
        validate=validate_story,
    )
    return Story(
        headline=data["headline"].strip(), summary=data["summary"].strip(),
        why_it_matters=data["why_it_matters"].strip(), tag=data["tag"], url=item.url,
        source=item.source, published=item.published.isoformat(), score=item.score or 0,
        also_seen_at=item.also_seen_at, model=model,
    )


def plain_story(item: Item) -> Story:
    sentences = re.split(r"(?<=[.!?])\s+", item.text)
    return Story(
        headline=item.title, summary=" ".join(sentences[:2])[:400], why_it_matters="",
        tag=item.tag, url=item.url, source=item.source, published=item.published.isoformat(),
        score=item.score or 0, also_seen_at=item.also_seen_at, model="none",
    )


def validate_tldr(data):
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list) or not data["lines"]:
        raise InvalidOutput('expected {"lines": [...]}')
    return [str(x) for x in data["lines"]][:5]


def tldr(stories: list[Story], router: Router) -> list[str]:
    facts = "\n".join(f"- {s.headline}: {s.summary}" for s in stories)
    try:
        lines, _ = router.complete_json("write", prompts.TLDR_SYSTEM, facts, validate=validate_tldr)
        return lines
    except AllProvidersFailed as e:
        log.warning("tldr skipped: %s", e)
        return [s.headline for s in stories[:5]]


# ---------------------------------------------------------------- run
def run(cfg: dict, store: Store, router: Router | None, use_llm: bool = True,
        lookback_hours: int | None = None) -> dict:
    topic = cfg["topic"]
    started = datetime.now(timezone.utc)

    raw, source_stats = fetch_all(cfg["sources"], lookback_hours or topic["lookback_hours"])
    unique = dedupe(raw)
    fresh_urls = store.filter_unseen([normalize_url(i.url) for i in unique])
    fresh = [i for i in unique if normalize_url(i.url) in fresh_urls]

    # keep every non-arXiv item, fill the rest of the candidate budget with newest papers
    non_arxiv = [i for i in fresh if i.source != "arxiv"]
    arxiv = sorted((i for i in fresh if i.source == "arxiv"), key=lambda i: i.published, reverse=True)
    candidates = (non_arxiv + arxiv)[: topic["max_candidates"]]
    log.info("fetched %d, unique %d, unseen %d, candidates %d",
             len(raw), len(unique), len(fresh), len(candidates))

    ranking = "llm" if use_llm else "keywords"
    if use_llm:
        try:
            rank_llm(candidates, router, topic["description"])
        except AllProvidersFailed as e:
            # all-or-nothing: LLM scores (relevance 0-10) and keyword scores (popularity-based)
            # aren't on the same scale, so if any batch fails, re-rank everything without the LLM
            log.error("every rank model failed, falling back to keyword ranking: %s", e)
            ranking = "keywords (LLMs unavailable)"
    if ranking != "llm":
        rank_heuristic(candidates, cfg["fallback"])
    # pick extra, then drop stories with no readable source text (e.g. tweets): a writer
    # with nothing to read can only make things up
    n = topic["max_items"]
    pool = select(candidates, n * 2)
    enrich(pool)
    readable = [it for it in pool if len(it.text) >= MIN_SOURCE_CHARS]
    picked = select(readable, n)  # re-apply the per-source cap for the final size
    log.info("skipped %d stories with no readable source text",
             sum(len(it.text) < MIN_SOURCE_CHARS for it in pool))

    # writing: once the whole write chain has failed, stop calling it (it's down) and use
    # the source's own first sentences for the remaining stories instead of dropping them
    stories, plain_count = [], 0
    write_up = use_llm
    for it in picked:
        if write_up:
            try:
                stories.append(write_story(it, router))
                continue
            except AllProvidersFailed as e:
                log.error("every write model failed, using source text from here on: %s", e)
                write_up = False
        stories.append(plain_story(it))
        plain_count += 1
    summary_lines = (tldr(stories, router) if write_up and stories
                     else [s.headline for s in stories[:5]])

    date = started.strftime("%Y-%m-%d")
    if use_llm:  # --no-llm test runs shouldn't hide stories from tomorrow's real digest
        store.mark_seen([normalize_url(it.url) for it in picked], date)
    return {
        "date": date,
        "generated_at": started.isoformat(timespec="seconds"),
        "ranking": ranking,
        "degraded": use_llm and (ranking != "llm" or plain_count > 0),
        "tldr": summary_lines,
        "stories": [s.__dict__ for s in stories],
        "candidates": [c.to_dict() for c in sorted(candidates, key=lambda x: -(x.score or 0))],
        "stats": {
            "sources": source_stats,
            "fetched": len(raw), "unique": len(unique), "unseen": len(fresh),
            "candidates": len(candidates), "published": len(stories),
            "written_without_llm": plain_count,
            "llm": store.run_summary() if use_llm else None,
            "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        },
    }
