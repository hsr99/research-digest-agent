import json

from digest.site import build


def digest(date, title="Speculative decoding lands in vLLM", url="https://example.com/a", degraded=False):
    story = {"headline": title, "summary": "s", "why_it_matters": "w", "tag": "Infra", "url": url,
             "source": "rss", "published": f"{date}T00:00:00+00:00", "score": 8.0, "also_seen_at": [],
             "model": "openrouter/x:free"}
    return {"date": date, "generated_at": f"{date}T13:30:00+00:00",
            "ranking": "keywords (LLMs unavailable)" if degraded else "llm", "degraded": degraded,
            "tldr": ["one line"], "stories": [story],
            "candidates": [{"source": "arxiv", "title": "Cut paper", "url": "https://arxiv.org/abs/1",
                            "score": 6.0, "reason": "niche"}],
            "stats": {"sources": {"rss": {"items": 1}}, "fetched": 2, "unique": 2, "unseen": 2, "candidates": 2,
                      "published": 1, "written_without_llm": 1 if degraded else 0, "seconds": 12.0, "llm": None}}


def write(out, d, name=None):
    (out / f"{name or d['date']}.json").write_text(json.dumps(d), encoding="utf-8")


def test_index_is_newest_day_and_every_day_gets_a_page(tmp_path):
    out, site = tmp_path / "out", tmp_path / "site"
    out.mkdir()
    write(out, digest("2026-11-23", title="Older story"))
    write(out, digest("2026-11-24", title="Newer story"))
    write(out, digest("2026-11-24", title="Test run"), name="2026-11-24-nollm")  # local test runs stay off the site
    write(out, digest("2026-11-24"), name="latest")

    assert build(out, site) == 2
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "Newer story" in index and "Test run" not in index
    assert 'href="days/2026-11-23.html"' in index
    older = (site / "days" / "2026-11-23.html").read_text(encoding="utf-8")
    assert "Older story" in older and 'href="../index.html"' in older and 'href="../style.css"' in older
    assert json.loads((site / "data" / "latest.json").read_text(encoding="utf-8"))["date"] == "2026-11-24"
    assert "Cut paper" in index  # close calls table


def test_feed_content_is_escaped_and_bad_links_neutralized(tmp_path):
    out, site = tmp_path / "out", tmp_path / "site"
    out.mkdir()
    write(out, digest("2026-11-24", title='<script>alert(1)</script>', url="javascript:alert(1)"))
    build(out, site)
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in index
    assert "&lt;script&gt;" in index
    assert "javascript:alert" not in index.split("<script>")[0]


def test_reduced_edition_is_flagged(tmp_path):
    out, site = tmp_path / "out", tmp_path / "site"
    out.mkdir()
    write(out, digest("2026-11-24", degraded=True))
    build(out, site)
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "Reduced edition" in index and "No LLM calls" in index
