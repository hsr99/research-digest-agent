from __future__ import annotations


def to_markdown(digest: dict) -> str:
    lines = [f"# AI Digest: {digest['date']}", ""]
    if digest.get("degraded"):
        n = digest["stats"].get("written_without_llm", 0)
        lines += [f"> **Reduced edition:** the AI models were unavailable today. Ranking: "
                  f"{digest['ranking']}; {n} of {len(digest['stories'])} stories use the source's "
                  f"own text instead of an AI summary.", ""]
    if digest["tldr"]:
        lines += ["## 30-second version", ""] + [f"- {l}" for l in digest["tldr"]] + [""]
    for i, s in enumerate(digest["stories"], 1):
        lines += [f"## {i}. {s['headline']}", "",
                  f"`{s['tag'] or s['source']}` · [{s['source']}]({s['url']}) · score {s['score']:.1f}", "",
                  s["summary"], ""]
        if s["why_it_matters"]:
            lines += [f"**Why it matters:** {s['why_it_matters']}", ""]
        if s["also_seen_at"]:
            lines += ["Also at: " + ", ".join(f"<{u}>" for u in s["also_seen_at"][:3]), ""]
    st = digest["stats"]
    lines += ["---", "",
              f"{st['fetched']} fetched → {st['unique']} unique → {st['unseen']} new → "
              f"{st['candidates']} ranked → {st['published']} published in {st['seconds']}s"]
    if st.get("llm"):
        for m in st["llm"]["by_model"]:
            lines.append(f"- `{m['provider']}/{m['model']}`: {m['calls']} calls ({m['cached']} cached), "
                         f"{m['prompt_tokens'] + m['completion_tokens']} tokens, ~{m['avg_latency_ms']} ms avg")
    return "\n".join(lines) + "\n"
