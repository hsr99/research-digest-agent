"""SQLite store: LLM response cache, per-call metrics, and URLs already published."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY, response TEXT NOT NULL, model TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS calls (
    ts REAL, run_id TEXT, role TEXT, provider TEXT, model TEXT, ok INTEGER, cached INTEGER,
    latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS seen (
    url TEXT PRIMARY KEY, first_seen REAL, published_in TEXT
);
"""


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.run_id = time.strftime("%Y%m%dT%H%M%S")

    # --- cache
    def cache_get(self, key: str) -> tuple[str, str] | None:
        row = self.db.execute("SELECT response, model FROM cache WHERE key=?", (key,)).fetchone()
        return (row[0], row[1]) if row else None

    def cache_put(self, key: str, response: str, model: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO cache VALUES (?,?,?,?)", (key, response, model, time.time())
        )
        self.db.commit()

    # --- metrics
    def log_call(self, role, provider, model, ok, cached, latency_ms, usage=None, error=""):
        usage = usage or {}
        self.db.execute(
            "INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), self.run_id, role, provider, model, int(ok), int(cached), latency_ms,
             usage.get("prompt_tokens"), usage.get("completion_tokens"), error[:300]),
        )
        self.db.commit()

    def run_summary(self) -> dict:
        rows = self.db.execute(
            """SELECT provider, model, COUNT(*), SUM(ok), SUM(cached),
                      COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0),
                      CAST(AVG(latency_ms) AS INTEGER)
               FROM calls WHERE run_id=? GROUP BY provider, model""",
            (self.run_id,),
        ).fetchall()
        keys = ["provider", "model", "calls", "ok", "cached", "prompt_tokens",
                "completion_tokens", "avg_latency_ms"]
        return {"run_id": self.run_id, "by_model": [dict(zip(keys, r)) for r in rows]}

    # --- seen URLs (so tomorrow's digest doesn't repeat today's)
    def filter_unseen(self, urls: list[str]) -> set[str]:
        if not urls:
            return set()
        q = ",".join("?" * len(urls))
        seen = {r[0] for r in self.db.execute(f"SELECT url FROM seen WHERE url IN ({q})", urls)}
        return set(urls) - seen

    def mark_seen(self, urls: list[str], digest_date: str) -> None:
        self.db.executemany(
            "INSERT OR IGNORE INTO seen VALUES (?,?,?)",
            [(u, time.time(), digest_date) for u in urls],
        )
        self.db.commit()


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)
