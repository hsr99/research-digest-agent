"""Build the public dashboard from the digests in out/:  python -m digest.site

Writes a static site (no server, no build tools) that GitHub Pages can host:
  index.html            today's digest
  days/<date>.html      one page per past digest
  data/<date>.json      the raw digests, for anyone who wants the data
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAY_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")  # skips latest.json and -nollm test runs
REPO_URL = "https://github.com/hsr99/research-digest-agent"


def load_digests(out_dir: Path) -> list[dict]:
    """Every published digest, newest first."""
    days = [json.loads(p.read_text(encoding="utf-8"))
            for p in out_dir.glob("*.json") if DAY_FILE.match(p.name)]
    return sorted(days, key=lambda d: d["date"], reverse=True)


def e(value) -> str:
    return escape(str(value), quote=True)


def safe_url(url: str) -> str:
    """Only link to http(s): story URLs come from outside feeds."""
    return e(url) if str(url).startswith(("https://", "http://")) else "#"


def host(url: str) -> str:
    m = re.match(r"^https?://(?:www\.)?([^/]+)", str(url))
    return m.group(1) if m else ""


def short_model(model: str) -> str:
    return model.split("/")[-1].removesuffix(":free") if model and model != "none" else "source text"


def llm_totals(d: dict) -> dict:
    rows = (d["stats"].get("llm") or {}).get("by_model", [])
    return {"calls": sum(r["calls"] for r in rows),
            "tokens": sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows)}


def fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M UTC")
    except ValueError:
        return iso


def bars(rows: list[tuple[str, int]], max_value: int | None = None) -> str:
    """Horizontal bar chart in plain HTML: one series, so one color and no legend."""
    top = max_value or max((v for _, v in rows), default=0) or 1
    out = []
    for label, value in rows:
        pct = max(value / top * 100, 0.8 if value else 0)
        out.append(f'<div class="bar-row" title="{e(label)}: {value}"><span class="bar-label">{e(label)}</span>'
                   f'<span class="bar-track"><span class="bar" style="width:{pct:.1f}%"></span></span>'
                   f'<span class="bar-value">{value}</span></div>')
    return "".join(out)


def story_card(i: int, s: dict) -> str:
    tag = s.get("tag") or s["source"]
    also = "".join(f'<a href="{safe_url(u)}">{e(host(u))}</a>' for u in s.get("also_seen_at", [])[:3])
    why = f'<p class="why"><strong>Why it matters:</strong> {e(s["why_it_matters"])}</p>' if s.get("why_it_matters") else ""
    return f"""
<article class="story" data-tag="{e(tag)}">
  <div class="story-meta"><span class="num">{i:02d}</span><span class="chip">{e(tag)}</span>
    <span title="{e(s["source"])}">{e(host(s["url"]))}</span><span>score {s["score"]:.1f}</span>
    <span title="model that wrote this summary">{e(short_model(s.get("model", "")))}</span></div>
  <h3><a href="{safe_url(s["url"])}">{e(s["headline"])}</a></h3>
  <p>{e(s["summary"])}</p>{why}
  {f'<p class="also">Also at: {also}</p>' if also else ""}
</article>"""


def render_day(d: dict, history: list[dict], root: str) -> str:
    """One dashboard page. `root` is the relative path back to the site root ("" or "../")."""
    st = d["stats"]
    totals = llm_totals(d)
    tags = sorted({s.get("tag") or s["source"] for s in d["stories"]})
    published = {s["url"] for s in d["stories"]}
    cut = sorted((c for c in d.get("candidates", []) if c["url"] not in published),
                 key=lambda c: c.get("score") or 0, reverse=True)[:8]
    idx = next(i for i, h in enumerate(history) if h["date"] == d["date"])
    newer = history[idx - 1]["date"] if idx > 0 else None
    older = history[idx + 1]["date"] if idx + 1 < len(history) else None

    def day_href(date: str) -> str:
        return f"{root}index.html" if date == history[0]["date"] else f"{root}days/{date}.html"

    banner = ""
    if d.get("degraded"):
        banner = (f'<div class="banner"><strong>Reduced edition.</strong> The AI models were unavailable. '
                  f'Ranking: {e(d["ranking"])}; {st.get("written_without_llm", 0)} of {len(d["stories"])} '
                  f'stories use the source\'s own text.</div>')
    kpis = [("Fetched", st["fetched"]), ("New", st["unseen"]), ("Ranked", st["candidates"]),
            ("Published", st["published"]), ("LLM calls", totals["calls"]), ("Runtime", f'{st["seconds"]:.0f}s')]
    models = "".join(
        f'<li><div class="mono" title="{e(m["model"])}">{e(short_model(m["model"]))}</div>'
        f'<div class="muted">{e(m["provider"])} · {m["calls"]} calls · '
        f'{m["prompt_tokens"] + m["completion_tokens"]:,} tokens · {m["avg_latency_ms"] / 1000:.1f}s avg</div></li>'
        for m in (st.get("llm") or {}).get("by_model", [])) or '<li class="muted">No LLM calls in this run.</li>'
    cut_rows = "".join(
        f'<tr><td class="n">{(c.get("score") or 0):.1f}</td><td><a href="{safe_url(c["url"])}">{e(c["title"])}</a>'
        f'<div class="muted">{e(c.get("reason") or "")}</div></td><td>{e(c["source"])}</td></tr>' for c in cut)
    hist_rows = "".join(
        f'<tr{" class=current" if h["date"] == d["date"] else ""}><td><a href="{day_href(h["date"])}">{e(h["date"])}</a></td>'
        f'<td class="n">{h["stats"]["published"]}</td><td class="n">{h["stats"]["candidates"]}</td>'
        f'<td class="n">{llm_totals(h)["calls"]}</td><td class="n">{h["stats"]["seconds"]:.0f}s</td>'
        f'<td>{"reduced" if h.get("degraded") else "full"}</td></tr>' for h in history[:30])
    sources = [(name, info.get("items", 0)) for name, info in st.get("sources", {}).items()]
    source_errors = [name for name, info in st.get("sources", {}).items() if info.get("error")]
    tldr = "".join(f"<li>{e(line)}</li>" for line in d.get("tldr") or [])

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Research Digest · {e(d["date"])}</title>
<meta name="description" content="A daily AI digest for engineers, built by an agent that runs on free LLMs.">
<link rel="stylesheet" href="{root}style.css">
</head><body>
<header class="top">
  <div><h1>AI Research Digest</h1>
    <p class="sub">What changed in AI today, for engineers. Fetched, deduplicated, ranked and summarized by an agent on free models.</p></div>
  <nav class="days">
    {f'<a href="{day_href(older)}">← {e(older)}</a>' if older else '<span></span>'}
    <strong>{e(d["date"])}</strong>
    {f'<a href="{day_href(newer)}">{e(newer)} →</a>' if newer else '<span></span>'}
  </nav>
</header>
<main>
{banner}
<section class="status">
  <span class="pill {"warn" if d.get("degraded") else "ok"}">{"Reduced edition" if d.get("degraded") else "Full edition"}</span>
  <span>Ranking: {"LLM" if d["ranking"] == "llm" else e(d["ranking"])}</span>
  <span>Generated {e(fmt_time(d["generated_at"]))}</span>
  <span>API cost: $0.00 (free models only)</span>
</section>
<section class="kpis">{"".join(f'<div class="kpi"><div class="kpi-v">{e(v)}</div><div class="kpi-l">{e(k)}</div></div>' for k, v in kpis)}</section>

<div class="grid">
<div class="col-main">
  {f'<section class="card tldr"><h2>30-second version</h2><ul>{tldr}</ul></section>' if tldr else ""}
  <section>
    <div class="filters" role="group" aria-label="Filter stories by tag">
      <button class="on" data-filter="all">All {len(d["stories"])}</button>
      {"".join(f'<button data-filter="{e(t)}">{e(t)}</button>' for t in tags)}
    </div>
    {"".join(story_card(i, s) for i, s in enumerate(d["stories"], 1))}
  </section>
</div>
<aside class="col-side">
  <section class="card"><h2>Pipeline</h2>
    {bars([("Fetched", st["fetched"]), ("Unique", st["unique"]), ("Not seen before", st["unseen"]),
           ("Sent to ranker", st["candidates"]), ("Published", st["published"])])}
  </section>
  <section class="card"><h2>Sources</h2>{bars(sources)}
    {f'<p class="muted">Failed this run: {e(", ".join(source_errors))}</p>' if source_errors else ""}</section>
  <section class="card"><h2>Models used</h2><ul class="models">{models}</ul></section>
</aside>
</div>

{f'<section class="card"><h2>Close calls</h2><p class="muted">Highest-scored stories that did not make the cut, with the ranker\'s reason.</p><table><thead><tr><th class="n">Score</th><th>Story</th><th>Source</th></tr></thead><tbody>{cut_rows}</tbody></table></section>' if cut_rows else ""}

<section class="card"><h2>Run history</h2>
  <table><thead><tr><th>Date</th><th class="n">Published</th><th class="n">Ranked</th><th class="n">LLM calls</th><th class="n">Runtime</th><th>Edition</th></tr></thead>
  <tbody>{hist_rows}</tbody></table></section>
</main>
<footer>Raw data: <a href="{root}data/{e(d["date"])}.json">{e(d["date"])}.json</a> ·
  <a href="{REPO_URL}">Source code</a> · Summaries are AI-written from the linked sources; check the source before relying on a claim.</footer>
<script>
document.querySelectorAll(".filters button").forEach(b => b.addEventListener("click", () => {{
  document.querySelectorAll(".filters button").forEach(x => x.classList.toggle("on", x === b));
  document.querySelectorAll(".story").forEach(s => {{
    s.hidden = b.dataset.filter !== "all" && s.dataset.tag !== b.dataset.filter;
  }});
}}));
</script>
</body></html>
"""


CSS = """
:root { color-scheme: light; --bg:#fcfcfb; --card:#ffffff; --ink:#0b0b0b; --ink-2:#52514e; --muted:#76756f;
  --line:#e6e5e0; --accent:#2a78d6; --track:#eeede8; --ok:#008300; --warn:#b26b00; --warn-bg:#fff4e0; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --bg:#1a1a19; --card:#222220; --ink:#f0efec;
  --ink-2:#c3c2b7; --muted:#9a998f; --line:#34332f; --accent:#3987e5; --track:#2c2b28; --ok:#0ca30c;
  --warn:#eda100; --warn-bg:#2e2510; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
.top, main, footer { max-width: 1180px; margin: 0 auto; padding: 0 20px; }
.top { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; padding-top: 28px; }
h1 { margin: 0; font-size: 26px; letter-spacing: -0.01em; }
h2 { margin: 0 0 12px; font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-2); }
h3 { margin: 6px 0 6px; font-size: 18px; line-height: 1.35; } h3 a { color: var(--ink); }
.sub { margin: 4px 0 0; color: var(--ink-2); }
.days { display: flex; gap: 14px; align-items: center; font-variant-numeric: tabular-nums; }
.status { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; margin: 20px 0 14px; color: var(--ink-2); font-size: 14px; }
.pill { padding: 2px 10px; border-radius: 999px; font-weight: 600; font-size: 13px; border: 1px solid currentColor; }
.pill.ok { color: var(--ok); } .pill.warn { color: var(--warn); }
.pill.ok::before { content: "✓ "; } .pill.warn::before { content: "! "; }
.banner { margin-top: 18px; padding: 12px 14px; border-radius: 8px; background: var(--warn-bg); border: 1px solid var(--warn); }
.kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 20px; }
.kpi { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.kpi-v { font-size: 24px; font-weight: 650; font-variant-numeric: tabular-nums; }
.kpi-l { color: var(--muted); font-size: 13px; }
.grid { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 20px; align-items: start; }
.col-side { display: grid; gap: 16px; }
.models { list-style: none; margin: 0; padding: 0; } .models li { padding: 8px 0; border-top: 1px solid var(--line); }
.models li:first-child { border-top: 0; padding-top: 0; } .models .mono { font-size: 13px; color: var(--ink); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; margin-bottom: 16px; }
.col-side .card { margin-bottom: 0; }
.tldr ul { margin: 0; padding-left: 18px; } .tldr li { margin: 4px 0; }
.filters { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 12px; }
.filters button { font: inherit; font-size: 13px; padding: 4px 12px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--line); background: var(--card); color: var(--ink-2); }
.filters button.on { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.story { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; margin-bottom: 12px; }
.story p { margin: 6px 0; color: var(--ink); } .story .why { color: var(--ink-2); }
.story-meta { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; color: var(--muted); font-size: 13px; }
.num { font-weight: 700; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.chip { padding: 1px 9px; border-radius: 999px; background: var(--track); color: var(--ink); font-weight: 600; }
.also { font-size: 13px; color: var(--muted); } .also a { margin-right: 10px; }
.bar-row { display: grid; grid-template-columns: 120px 1fr 40px; gap: 10px; align-items: center; margin: 7px 0; font-size: 13px; }
.bar-label { color: var(--ink-2); }
.bar-track { height: 10px; background: var(--track); border-radius: 4px; }
.bar { display: block; height: 100%; background: var(--accent); border-radius: 0 4px 4px 0; }
.bar-value { text-align: right; font-variant-numeric: tabular-nums; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: left; font-weight: 600; color: var(--muted); font-size: 12px; padding: 6px 8px; border-bottom: 1px solid var(--line); }
td { padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
tr.current td { background: var(--track); }
.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.mono { font-family: ui-monospace, Consolas, monospace; font-size: 12px; word-break: break-all; }
.muted { color: var(--muted); font-size: 13px; }
footer { padding: 24px 20px 40px; color: var(--muted); font-size: 13px; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; }
  .kpis { grid-template-columns: repeat(3, 1fr); } }
"""


def build(out_dir: Path, site_dir: Path) -> int:
    digests = load_digests(out_dir)
    if not digests:
        raise SystemExit(f"No digests in {out_dir}; run `python -m digest` first.")
    if site_dir.exists():
        shutil.rmtree(site_dir)
    (site_dir / "days").mkdir(parents=True)
    (site_dir / "data").mkdir()
    (site_dir / "style.css").write_text(CSS.strip() + "\n", encoding="utf-8")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    for d in digests:
        (site_dir / "days" / f"{d['date']}.html").write_text(render_day(d, digests, "../"), encoding="utf-8")
        (site_dir / "data" / f"{d['date']}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    (site_dir / "index.html").write_text(render_day(digests[0], digests, ""), encoding="utf-8")
    (site_dir / "data" / "latest.json").write_text(json.dumps(digests[0], ensure_ascii=False), encoding="utf-8")
    return len(digests)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="digest.site", description="Build the static dashboard.")
    ap.add_argument("--out", default=ROOT / "out", type=Path, help="folder with the digest JSON files")
    ap.add_argument("--site", default=ROOT / "site", type=Path, help="where to write the website")
    args = ap.parse_args(argv)
    n = build(args.out, args.site)
    print(f"Built {n} day(s) -> {args.site / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
