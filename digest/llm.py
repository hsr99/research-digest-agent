"""Multi-provider LLM router for free-tier APIs.

Every provider speaks the OpenAI chat-completions format, so one client covers
Gemini, Groq, OpenRouter and Ollama. For each call the router:
  1. returns a cached answer if this exact request was made before (reruns cost nothing)
  2. otherwise tries the role's providers in order, skipping ones with no API key
  3. retries rate limits (429) and server errors with backoff, then fails over
  4. parses and validates the JSON answer; on bad JSON it asks the model once to fix it,
     then fails over to the next provider
  5. logs provider, model, tokens, latency and errors for every attempt
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Callable

import httpx

from .store import Store, dumps

log = logging.getLogger(__name__)

RETRYABLE = {429, 500, 502, 503, 504}


class AllProvidersFailed(RuntimeError):
    pass


class InvalidOutput(ValueError):
    """Raised by a validator when the model's JSON has the wrong shape."""


class PaidModelConfigured(ValueError):
    """The config names a model that could cost money. Refuse to run at all."""


def check_free_only(llm_cfg: dict) -> None:
    """Fail fast if any model in any role could be billed."""
    problems = []
    for role, chain in llm_cfg["roles"].items():
        for c in chain:
            p = llm_cfg["providers"].get(c["provider"])
            if p is None:
                problems.append(f"{role}: unknown provider '{c['provider']}'")
            elif p.get("free") is not True:
                problems.append(f"{role}: provider '{c['provider']}' is not marked free = true")
            elif (suffix := p.get("require_model_suffix")) and not c["model"].endswith(suffix):
                problems.append(f"{role}: '{c['model']}' on {c['provider']} must end with '{suffix}'")
    if problems:
        raise PaidModelConfigured("refusing to run, possible paid models:\n  " + "\n  ".join(problems))


def extract_json(text: str):
    """Parse JSON from a model reply, tolerating ```json fences and chatter around it."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # fall back to the outermost {...} or [...] block
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise InvalidOutput("reply was not valid JSON")


class Router:
    def __init__(self, llm_cfg: dict, store: Store, max_retries: int = 2,
                 transport: httpx.BaseTransport | None = None, sleep: Callable = time.sleep):
        check_free_only(llm_cfg)
        self.providers = llm_cfg["providers"]
        self.roles = llm_cfg["roles"]
        self.store = store
        self.max_retries = max_retries
        self.sleep = sleep
        self.http = httpx.Client(timeout=90, transport=transport)
        self.dead: set[str] = set()  # providers unreachable this run (e.g. Ollama not running)

    def available(self, role: str) -> list[dict]:
        out = []
        for c in self.roles[role]:
            p = self.providers[c["provider"]]
            if c["provider"] in self.dead:
                continue
            if p["key_env"] and not os.getenv(p["key_env"]):
                continue
            out.append(c)
        return out

    def complete_json(self, role: str, system: str, user: str,
                      validate: Callable[[object], object] = lambda x: x,
                      temperature: float = 0.2):
        """Run a JSON-returning prompt through the role's provider chain.
        Returns (validated_result, model_name)."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        key = hashlib.sha256(dumps({"role": role, "messages": messages}).encode()).hexdigest()

        if hit := self.store.cache_get(key):
            response, model = hit
            try:
                result = validate(extract_json(response))
                self.store.log_call(role, "cache", model, True, True, 0)
                return result, model
            except InvalidOutput:
                pass  # stale/bad cache entry: fall through and regenerate

        chain = self.available(role)
        if not chain:
            raise AllProvidersFailed(
                f"no provider available for role '{role}': set an API key in .env "
                f"(see .env.example) or start Ollama"
            )
        errors = []
        for cand in chain:
            name, model = cand["provider"], cand["model"]
            try:
                text = self._chat(role, name, model, messages, temperature)
                try:
                    result = validate(extract_json(text))
                except InvalidOutput as e:
                    # one repair attempt on the same model, telling it what was wrong
                    log.info("%s/%s bad output (%s), asking it to fix", name, model, e)
                    repair = messages + [
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": f"That output was invalid: {e}. "
                                                    "Reply again with only the corrected JSON."},
                    ]
                    text = self._chat(role, name, model, repair, temperature)
                    result = validate(extract_json(text))
                self.store.cache_put(key, text, f"{name}/{model}")
                return result, f"{name}/{model}"
            except (httpx.HTTPError, InvalidOutput, KeyError) as e:
                errors.append(f"{name}/{model}: {e}")
                log.warning("failover from %s/%s: %s", name, model, e)
        raise AllProvidersFailed("; ".join(errors))

    def _chat(self, role, provider, model, messages, temperature) -> str:
        p = self.providers[provider]
        headers = {"Content-Type": "application/json"}
        if p["key_env"]:
            headers["Authorization"] = f"Bearer {os.environ[p['key_env']]}"
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        url = p["base_url"].rstrip("/") + "/chat/completions"
        # per-provider override: for pools of free models (OpenRouter) it's better to move
        # straight to the next model than to spend daily quota retrying a busy one
        retries = p.get("retries", self.max_retries)

        for attempt in range(retries + 1):
            t0 = time.perf_counter()
            try:
                r = self.http.post(url, headers=headers, json=body)
            except httpx.ConnectError as e:
                self.dead.add(provider)  # don't keep knocking on a server that isn't there
                self.store.log_call(role, provider, model, False, False, 0, error=f"connect: {e}")
                raise
            latency = int((time.perf_counter() - t0) * 1000)

            if r.status_code == 200:
                try:
                    data = r.json()
                    text = data["choices"][0]["message"]["content"] or ""
                except (ValueError, KeyError, IndexError, TypeError):
                    # proxies and captive portals can answer 200 with a non-API body
                    self.store.log_call(role, provider, model, False, False, latency,
                                        error=f"malformed 200 body: {r.text[:100]!r}")
                    raise InvalidOutput(f"malformed response body: {r.text[:60]!r}")
                self.store.log_call(role, provider, model, True, False, latency, data.get("usage"))
                return text

            self.store.log_call(role, provider, model, False, False, latency,
                                error=f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code in RETRYABLE and attempt < retries:
                wait = float(r.headers.get("retry-after") or 2 ** (attempt + 1))
                log.info("%s/%s HTTP %s, retrying in %.0fs", provider, model, r.status_code, wait)
                self.sleep(min(wait, 30))
                continue
            # keep the provider's own reason (e.g. "model not found"): it's what you need to fix it
            raise httpx.HTTPStatusError(f"HTTP {r.status_code}: {r.text[:200].strip()}",
                                        request=r.request, response=r)
        raise httpx.HTTPError("retries exhausted")  # pragma: no cover
