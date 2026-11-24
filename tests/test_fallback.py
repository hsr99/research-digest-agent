"""The digest must still be published when the LLMs are down."""
import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from digest import pipeline
from digest.llm import Router
from digest.models import Item
from digest.store import Store

NOW = datetime.now(timezone.utc)
CFG = tomllib.loads((Path(__file__).parent.parent / "config.toml").read_text(encoding="utf-8"))
TEXT = "This is a long enough source text about the release. " * 5


def item(source, title, points=0, text=TEXT, n=0):
    return Item(source=source, title=title, url=f"https://example.com/{source}/{n}",
                published=NOW, text=text, signals={"points": points} if points else {})


def test_keyword_ranking_buries_drama_and_lifts_on_topic_papers():
    drama = item("hackernews", "Dario is hyping the dangers so OSS models are illegal", points=900, n=1)
    paper = item("arxiv", "Speculative decoding for LLM inference on a single GPU", n=2)
    vague = item("arxiv", "A note on graph colouring", text="Graph theory result. " * 10, n=3)
    pipeline.rank_heuristic([drama, paper, vague], CFG["fallback"])
    assert paper.score >= 5 > drama.score
    assert vague.score < 5
    assert "off-topic penalty" in drama.reason
    assert "inference" in paper.reason


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Fake sources (no network) and a fresh store."""
    # distinct titles, otherwise dedupe (correctly) merges them into one story
    blogs = ["Open weights LLM tops coding leaderboard", "vLLM release adds disaggregated serving",
             "Agent framework ships MCP tool use support", "New eval suite for long-context retrieval",
             "Quantization kernel doubles GPU throughput", "Fine-tuning recipe for small reasoning models"]
    papers = ["Speculative decoding with tree attention", "Distilling multimodal transformers cheaply",
              "RLHF reward hacking under GRPO training", "Benchmark for agentic web navigation",
              "Sparse attention for million-token inference", "Embedding models for code retrieval"]
    items = [item("rss", t, n=i) for i, t in enumerate(blogs)] + \
            [item("arxiv", t, n=10 + i) for i, t in enumerate(papers)]
    monkeypatch.setattr(pipeline, "fetch_all", lambda cfg, hours: (items, {"fake": {"items": len(items)}}))
    monkeypatch.setattr(pipeline, "enrich", lambda items: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("NVIDIA_API_KEY", "y")
    return Store(tmp_path / "t.db")


def make_router(store, handler):
    return Router(CFG["llm"], store, transport=httpx.MockTransport(handler), sleep=lambda s: None)


def ok(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


def is_rank_call(req):
    return "editor of a daily AI news digest" in req.content.decode()


def test_everything_down_still_publishes_a_reduced_digest(offline):
    router = make_router(offline, lambda req: httpx.Response(503, text="down"))
    digest = pipeline.run(CFG, offline, router)
    assert digest["ranking"] == "keywords (LLMs unavailable)"
    assert digest["degraded"] is True
    assert len(digest["stories"]) == CFG["topic"]["max_items"]
    assert all(s["model"] == "none" for s in digest["stories"])
    assert digest["stats"]["written_without_llm"] == len(digest["stories"])


def test_writer_down_keeps_llm_ranking_and_stops_calling_the_writer(offline):
    write_calls = []

    def handler(req):
        if is_rank_call(req):
            ids = [int(line.split("]")[0][1:]) for line in json.loads(req.content)["messages"][1]["content"]
                   .splitlines() if line.startswith("[")]
            return ok({"scores": [{"id": i, "score": 8, "tag": "Models", "reason": "r"} for i in ids]})
        write_calls.append(1)
        return httpx.Response(503, text="down")

    digest = pipeline.run(CFG, offline, make_router(offline, handler))
    assert digest["ranking"] == "llm"
    assert digest["degraded"] is True
    assert len(digest["stories"]) == CFG["topic"]["max_items"]
    n_write_models = len(CFG["llm"]["roles"]["write"]) - 1  # ollama isn't reachable in tests
    assert len(write_calls) <= n_write_models * 3  # one failed pass over the chain, not one per story
