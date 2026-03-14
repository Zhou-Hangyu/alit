from __future__ import annotations
"""Multi-stage funnel retrieval engine for cross-paper synthesis.

Zero dependencies. Pure Python stdlib only. Reads from DB directly.
The agent does the reasoning; this module does the retrieval.
"""

import sqlite3


def funnel_retrieve(
    conn: sqlite3.Connection,
    question: str,
    depth: int = 2,
    top_k: int = 20,
) -> dict:
    """Retrieve papers using multi-stage funnel for cross-paper synthesis.

    The agent does the reasoning; this function does the retrieval.
    No LLM called — only SQLite BM25 + record fetches.

    Depth controls token budget:
      1: titles + one-liners (~500 tokens)
      2: + abstracts for top-10 (~2.5K tokens) [DEFAULT]
      3: + key claims for top-3 (~3.5K tokens)
      4: + full notes for top-1 (~5K tokens)

    Args:
        conn: Open database connection.
        question: Research question to answer.
        depth: Funnel depth (1-4).
        top_k: BM25 candidates to retrieve at stage 1.

    Returns:
        Dict with keys: question, depth, candidates, shortlist, details, deep.
    """
    from literature.scripts.search import search

    result: dict = {
        "question": question,
        "depth": depth,
        "candidates": [],
        "shortlist": [],
        "details": [],
        "deep": [],
    }

    if not question or not question.strip():
        return result

    # Stage 1: BM25 candidates with L4 oneliners
    hits = search(conn, question, top_k=top_k)
    for h in hits:
        result["candidates"].append({
            "id": h["id"],
            "title": h["title"],
            "year": h["year"],
            "summary": h.get("summary_l4") or h.get("abstract", "")[:100] or "",
            "status": h.get("status", "unread"),
        })

    if depth < 2:
        return result

    top_ids = [c["id"] for c in result["candidates"][:10]]
    if top_ids:
        placeholders = ",".join("?" for _ in top_ids)
        rows = conn.execute(f"SELECT * FROM papers WHERE id IN ({placeholders})", top_ids).fetchall()
        paper_cache = {dict(r)["id"]: dict(r) for r in rows}
    else:
        paper_cache = {}

    for c in result["candidates"][:10]:
        p = paper_cache.get(c["id"])
        if p:
            result["shortlist"].append({
                "id": p["id"], "title": p["title"], "year": p["year"],
                "abstract": (p.get("abstract") or "")[:600],
            })

    if depth < 3:
        return result

    for c in result["candidates"][:3]:
        p = paper_cache.get(c["id"])
        if p:
            result["details"].append({
                "id": p["id"], "title": p["title"],
                "summary_l2": p.get("summary_l2", ""),
                "notes": (p.get("notes") or "")[:500],
            })

    if depth < 4:
        return result

    if result["candidates"]:
        p = paper_cache.get(result["candidates"][0]["id"])
        if p:
            result["deep"].append({
                "id": p["id"], "title": p["title"],
                "abstract": p.get("abstract", ""),
                "notes": p.get("notes", ""),
                "summary_l2": p.get("summary_l2", ""),
            })

    return result


def format_funnel_output(result: dict) -> str:
    """Format funnel results as human-readable markdown for agent consumption."""
    lines: list[str] = [f"## Research Query: {result['question']}", ""]

    candidates = result.get("candidates", [])
    if not candidates:
        return f"No relevant papers found for: {result['question']}"

    lines.append(f"### Stage 1 — {len(candidates)} candidates\n")
    for c in candidates:
        summary = c.get("summary", "")
        summary_display = f" — {summary[:100]}" if summary else " — (no summary)"
        lines.append(f"- **{c['id']}** ({c['year']}){summary_display}")

    if result.get("shortlist"):
        lines.append(f"\n### Stage 2 — Top {len(result['shortlist'])} abstracts\n")
        for s in result["shortlist"]:
            abstract = (s.get("abstract") or "")[:200]
            lines.append(f"**{s['id']}** — {abstract}...")

    if result.get("details"):
        lines.append(f"\n### Stage 3 — Key claims from top {len(result['details'])} papers\n")
        for d in result["details"]:
            lines.append(f"**{d['id']}**:")
            l2 = d.get("summary_l2", "")
            if l2:
                lines.append(f"  {l2[:300]}")
            else:
                lines.append("  (no key claims extracted yet)")

    if result.get("deep"):
        lines.append("\n### Stage 4 — Full detail: top paper\n")
        deep = result["deep"][0]
        lines.append(f"**{deep['id']}**\n")
        lines.append(f"Abstract: {(deep.get('abstract') or '')[:500]}\n")
        if deep.get("notes"):
            lines.append(f"Notes: {deep['notes'][:500]}")

    return "\n".join(lines)
