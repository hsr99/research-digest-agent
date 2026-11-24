from datetime import datetime, timezone

from digest.dedupe import dedupe, normalize_url
from digest.models import Item

NOW = datetime.now(timezone.utc)


def item(source, title, url, **kw):
    return Item(source=source, title=title, url=url, published=NOW, **kw)


def test_normalize_strips_tracking_www_and_slash():
    assert normalize_url("http://www.Example.com/post/?utm_source=x&id=3#top") == "https://example.com/post?id=3"


def test_arxiv_versions_and_formats_are_one_paper():
    urls = ["https://arxiv.org/abs/2611.29793v1", "http://arxiv.org/pdf/2611.29793v2",
            "https://arxiv.org/html/2611.29793"]
    assert len({normalize_url(u) for u in urls}) == 1


def test_same_url_from_hn_merges_into_blog_and_keeps_points():
    blog = item("rss", "How to build and maintain an agentic evaluation", "https://huggingface.co/blog/agentic-evals")
    hn = item("hackernews", "How to build and maintain an agentic evaluation",
              "https://huggingface.co/blog/agentic-evals/?utm_source=hn", signals={"points": 210})
    out = dedupe([hn, blog])
    assert len(out) == 1
    assert out[0].source == "rss"          # primary source wins
    assert out[0].signals["points"] == 210  # HN signal carried over
    assert out[0].also_seen_at == [hn.url]


def test_near_identical_titles_merge_but_different_stories_dont():
    a = item("rss", "vLLM shows NVMe can replace the DRAM KV tier", "https://a.com/1")
    b = item("hackernews", "vLLM shows NVMe can replace the DRAM KV-tier!", "https://b.com/2")
    c = item("rss", "vLLM 0.12 released with speculative decoding", "https://a.com/3")
    assert len(dedupe([a, b, c])) == 2


def test_short_titles_dont_false_match():
    assert len(dedupe([item("rss", "GPT-6", "https://a.com"), item("rss", "GPT-5", "https://b.com")])) == 2
