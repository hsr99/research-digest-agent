from datetime import datetime, timezone

import pytest

from digest.llm import InvalidOutput
from digest.models import Item
from digest.pipeline import article_text, make_rank_validator, select, validate_story


def test_article_text_drops_page_chrome_and_scripts():
    page = """<html><header><p>Log in. Sign up. Pricing and more stuff here for you.</p></header>
    <nav><p>Models Datasets Spaces Docs Enterprise Pricing Website Tasks HuggingChat.</p></nav>
    <script>const x = "<p>not text, this is javascript code in a script tag.</p>";</script>
    <article><p>The new model loops its 28 layers twice, doubling depth without new weights.</p>
    <p><a>Share</a></p></article><footer><p>Copyright 2026, all rights reserved by the company.</p></footer>"""
    assert article_text(page) == "The new model loops its 28 layers twice, doubling depth without new weights."

NOW = datetime.now(timezone.utc)


def scored(source, score):
    return Item(source=source, title=f"{source} {score}", url=f"https://x/{source}/{score}",
                published=NOW, score=score)


def test_select_caps_each_source_and_drops_low_scores():
    items = [scored("arxiv", s) for s in (9.5, 9.4, 9.3, 9.2, 9.1, 9.0)] + \
            [scored("rss", 7.0), scored("hackernews", 6.0), scored("rss", 3.0)]
    picked = select(items, max_items=6)
    assert sum(i.source == "arxiv" for i in picked) == 3   # cap = ceil(6/2)
    assert all(i.score >= 5 for i in picked)
    assert len(picked) == 5


def test_reselecting_a_pool_keeps_the_final_cap():
    # regression: selecting a 2x pool then slicing let 6 arXiv papers into an 8-story digest
    items = [scored("arxiv", 9 - i * 0.1) for i in range(10)] + [scored("rss", 6.0 - i * 0.1) for i in range(6)]
    final = select(select(items, 16), 8)
    assert sum(i.source == "arxiv" for i in final) == 4
    assert len(final) == 8


def test_rank_validator_clamps_and_rejects_too_many_missing():
    v = make_rank_validator({0, 1, 2, 3, 4})
    out = v({"scores": [{"id": i, "score": 15, "tag": "Bogus"} for i in range(5)]})
    assert out[0][0] == 10.0 and out[0][1] == "Research"
    with pytest.raises(InvalidOutput, match="missing"):
        v({"scores": [{"id": 0, "score": 5}]})


def test_story_validator_requires_fields():
    with pytest.raises(InvalidOutput):
        validate_story({"headline": "x" * 200, "summary": "fine summary", "why_it_matters": "fine reason"})
    with pytest.raises(InvalidOutput):
        validate_story({"headline": "ok headline", "summary": ""})
