from __future__ import annotations
"""Pure Python PageRank for the literature citation graph.

Zero dependencies. No scipy, no numpy. Pure Python stdlib only.
"""

import sqlite3


def compute_pagerank(
    conn: sqlite3.Connection,
    damping: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> dict[str, float]:
    """Compute PageRank scores for all papers. Pure Python power iteration.

    Args:
        conn: Open database connection.
        damping: Damping factor (default 0.85).
        max_iter: Maximum iterations (default 100).
        tol: Convergence tolerance (default 1e-6).

    Returns:
        Dict mapping paper id to PageRank score. Empty dict if no papers.
    """
    papers = [r["id"] for r in conn.execute("SELECT id FROM papers").fetchall()]
    n = len(papers)
    if n == 0:
        return {}

    idx = {p: i for i, p in enumerate(papers)}

    out_edges: dict[int, set[int]] = {i: set() for i in range(n)}
    in_edges: dict[int, set[int]] = {i: set() for i in range(n)}
    for row in conn.execute("SELECT from_id, to_id FROM citations").fetchall():
        fi = idx.get(row["from_id"])
        ti = idx.get(row["to_id"])
        if fi is not None and ti is not None:
            out_edges[fi].add(ti)
            in_edges[ti].add(fi)

    out_degree = {i: max(len(out_edges[i]), 1) for i in range(n)}
    rank = {i: 1.0 / n for i in range(n)}
    base = (1 - damping) / n

    for _ in range(max_iter):
        new_rank: dict[int, float] = {}
        for i in range(n):
            new_rank[i] = base + damping * sum(rank[j] / out_degree[j] for j in in_edges[i])

        diff = sum(abs(new_rank[i] - rank[i]) for i in range(n))
        rank = new_rank
        if diff < tol:
            break

    return {papers[i]: rank[i] for i in range(n)}


def update_pagerank(conn: sqlite3.Connection) -> None:
    """Compute and store PageRank scores in the papers table."""
    scores = compute_pagerank(conn)
    for paper_id, score in scores.items():
        conn.execute("UPDATE papers SET pagerank = ? WHERE id = ?", (score, paper_id))
    conn.commit()
