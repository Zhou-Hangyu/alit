from __future__ import annotations
"""BM25 full-text search over the SQLite FTS5 index.

Zero dependencies. Pure Python stdlib only.
"""

import sqlite3


def search(conn: sqlite3.Connection, query: str, top_k: int = 20) -> list[dict]:
    """BM25 search over FTS5 index.

    Args:
        conn: Open database connection.
        query: Free-text search query.
        top_k: Maximum number of results to return.

    Returns:
        List of paper dicts sorted by relevance. Empty list if no results.
    """
    escaped = " ".join(f'"{w}"' for w in query.strip().split() if w)
    if not escaped:
        return []
    try:
        rows = conn.execute(
            """
            SELECT p.*, bm25(papers_fts) as score
            FROM papers_fts
            JOIN papers p ON papers_fts.id = p.id
            WHERE papers_fts MATCH ?
            ORDER BY bm25(papers_fts)
            LIMIT ?
            """,
            (escaped, top_k),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
