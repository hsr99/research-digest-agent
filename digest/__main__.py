"""Run the digest:  python -m digest [--no-llm] [--hours 48]"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tomllib
from pathlib import Path

from dotenv import load_dotenv

from .llm import AllProvidersFailed, Router
from .pipeline import run
from .render import to_markdown
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="digest", description="Build today's AI research digest.")
    ap.add_argument("--config", default=ROOT / "config.toml", type=Path)
    ap.add_argument("--out", default=ROOT / "out", type=Path)
    ap.add_argument("--db", default=ROOT / "data" / "digest.db", type=Path)
    ap.add_argument("--hours", type=int, help="override lookback window")
    ap.add_argument("--no-llm", action="store_true", help="heuristic ranking, no summaries, no API keys needed")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")
    # utf-8-sig: Windows editors (Notepad, PowerShell 5) may save with a BOM that tomllib rejects
    cfg = tomllib.loads(args.config.read_text(encoding="utf-8-sig"))
    store = Store(args.db)
    router = None if args.no_llm else Router(cfg["llm"], store)

    if router and not router.available("rank"):
        print("No LLM provider is configured. Copy .env.example to .env and add at least one free "
              "API key, or run with --no-llm to test without one.", file=sys.stderr)
        return 2
    try:
        digest = run(cfg, store, router, use_llm=not args.no_llm, lookback_hours=args.hours)
    except AllProvidersFailed as e:
        print(f"All LLM providers failed: {e}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    suffix = "-nollm" if args.no_llm else ""
    for name in (f"{digest['date']}{suffix}", f"latest{suffix}"):
        (args.out / f"{name}.json").write_text(json.dumps(digest, indent=2, ensure_ascii=False), encoding="utf-8")
        (args.out / f"{name}.md").write_text(to_markdown(digest), encoding="utf-8")
    st = digest["stats"]
    print(f"{st['published']} stories from {st['candidates']} candidates "
          f"({st['fetched']} fetched) in {st['seconds']}s -> {args.out / (digest['date'] + suffix)}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
