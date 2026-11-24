"""Router tests with a fake HTTP transport: no network, no API keys."""
import json

import httpx
import pytest

from digest.llm import (AllProvidersFailed, InvalidOutput, PaidModelConfigured, Router,
                        check_free_only, extract_json)
from digest.store import Store

CFG = {
    "providers": {
        "a": {"base_url": "https://a.test/v1", "key_env": "A_KEY", "free": True},
        "b": {"base_url": "https://b.test/v1", "key_env": "B_KEY", "free": True},
        "nokey": {"base_url": "https://n.test/v1", "key_env": "MISSING_KEY", "free": True},
    },
    "roles": {"write": [{"provider": "nokey", "model": "m0"},
                        {"provider": "a", "model": "m1"},
                        {"provider": "b", "model": "m2"}]},
}


def reply(content, status=200):
    if status != 200:
        return httpx.Response(status, text="error")
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("A_KEY", "x")
    monkeypatch.setenv("B_KEY", "y")
    monkeypatch.delenv("MISSING_KEY", raising=False)
    return Store(tmp_path / "t.db")


def router(store, handler):
    return Router(CFG, store, transport=httpx.MockTransport(handler), sleep=lambda s: None)


def test_extract_json_handles_fences_and_chatter():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go: {"a": [1, 2]} hope that helps') == {"a": [1, 2]}
    with pytest.raises(InvalidOutput):
        extract_json("no json here")


def test_skips_provider_without_key_and_uses_first_available(env):
    hosts = []

    def handler(req):
        hosts.append(req.url.host)
        return reply('{"ok": true}')

    result, model = router(env, handler).complete_json("write", "s", "u")
    assert result == {"ok": True} and model == "a/m1" and hosts == ["a.test"]


def test_rate_limit_retries_then_fails_over(env):
    calls = []

    def handler(req):
        calls.append(req.url.host)
        return reply("", 429) if req.url.host == "a.test" else reply('{"ok": 1}')

    _, model = router(env, handler).complete_json("write", "s", "u")
    assert model == "b/m2"
    assert calls == ["a.test"] * 3 + ["b.test"]  # 1 try + 2 retries, then failover


def test_provider_with_zero_retries_fails_over_immediately(env):
    cfg = {**CFG, "providers": {**CFG["providers"], "a": {**CFG["providers"]["a"], "retries": 0}}}
    calls = []

    def handler(req):
        calls.append(req.url.host)
        return reply("", 429) if req.url.host == "a.test" else reply('{"ok": 1}')

    r = Router(cfg, env, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    r.complete_json("write", "s", "u")
    assert calls == ["a.test", "b.test"]


def test_bad_json_gets_one_repair_attempt(env):
    replies = iter(["not json at all", '{"fixed": true}'])
    _, model = router(env, lambda r: reply(next(replies))).complete_json("write", "s", "u")
    assert model == "a/m1"


def test_validator_failure_fails_over(env):
    def validate(d):
        if "good" not in d:
            raise InvalidOutput("missing good")
        return d

    def handler(req):
        return reply('{"bad": 1}' if req.url.host == "a.test" else '{"good": 1}')

    result, model = router(env, handler).complete_json("write", "s", "u", validate=validate)
    assert result == {"good": 1} and model == "b/m2"


def test_second_identical_call_hits_cache(env):
    count = {"n": 0}

    def handler(req):
        count["n"] += 1
        return reply('{"v": 1}')

    r = router(env, handler)
    r.complete_json("write", "s", "u")
    r.complete_json("write", "s", "u")
    assert count["n"] == 1
    by_model = {m["provider"]: m for m in env.run_summary()["by_model"]}
    assert by_model["cache"]["cached"] == 1


def test_non_api_200_body_fails_over_instead_of_crashing(env):
    def handler(req):
        if req.url.host == "a.test":
            return httpx.Response(200, text="OK\r\n", headers={"content-type": "text/plain"})
        return reply('{"ok": 1}')

    _, model = router(env, handler).complete_json("write", "s", "u")
    assert model == "b/m2"


def test_all_failing_raises_with_every_error(env):
    with pytest.raises(AllProvidersFailed, match="a/m1.*b/m2"):
        router(env, lambda r: reply("", 400)).complete_json("write", "s", "u")


def test_real_config_passes_the_free_only_guard():
    import tomllib
    from pathlib import Path
    cfg = tomllib.loads((Path(__file__).parent.parent / "config.toml").read_text(encoding="utf-8"))
    check_free_only(cfg["llm"])  # must not raise


def test_guard_rejects_provider_not_marked_free(env):
    cfg = {"providers": {"paid": {"base_url": "https://p.test", "key_env": "A_KEY"}},
           "roles": {"write": [{"provider": "paid", "model": "big"}]}}
    with pytest.raises(PaidModelConfigured, match="not marked free"):
        Router(cfg, env)


def test_guard_rejects_openrouter_model_without_free_suffix():
    cfg = {"providers": {"openrouter": {"base_url": "x", "key_env": "K", "free": True,
                                        "require_model_suffix": ":free"}},
           "roles": {"rank": [{"provider": "openrouter", "model": "anthropic/claude-opus"}]}}
    with pytest.raises(PaidModelConfigured, match="must end with ':free'"):
        check_free_only(cfg)
