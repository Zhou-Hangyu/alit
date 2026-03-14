from __future__ import annotations
"""SQLite database layer — sole source of truth for the literature review system.

Zero dependencies. Pure Python stdlib only.
"""

import re
import sqlite3
import urllib.request
from pathlib import Path

DB_NAME = "papers.db"


def get_db(path: Path | None = None) -> sqlite3.Connection:
    """Open the papers database (must already exist)."""
    db_path = (path or Path.cwd()) / DB_NAME
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | None = None) -> sqlite3.Connection:
    """Create papers.db and all tables if they don't exist. Idempotent."""
    db_path = (path or Path.cwd()) / DB_NAME
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT DEFAULT '',
            year INTEGER,
            abstract TEXT DEFAULT '',
            url TEXT DEFAULT '',
            arxiv_id TEXT DEFAULT '',
            doi TEXT DEFAULT '',
            tags TEXT DEFAULT '',
            status TEXT DEFAULT 'unread',
            notes TEXT DEFAULT '',
            summary_l4 TEXT DEFAULT '',
            summary_l4_model TEXT DEFAULT '',
            summary_l4_at TEXT DEFAULT '',
            summary_l2 TEXT DEFAULT '',
            summary_l2_model TEXT DEFAULT '',
            summary_l2_at TEXT DEFAULT '',
            pdf_path TEXT DEFAULT '',
            pagerank REAL DEFAULT 0.0,
            added_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );

        CREATE TABLE IF NOT EXISTS citations (
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            type TEXT DEFAULT 'cites',
            PRIMARY KEY (from_id, to_id)
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
            id UNINDEXED,
            title,
            abstract,
            notes,
            summary_l4,
            summary_l2,
            tags,
            content='papers',
            content_rowid='rowid',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
            INSERT INTO papers_fts(rowid, id, title, abstract, notes, summary_l4, summary_l2, tags)
            VALUES (new.rowid, new.id, new.title, new.abstract, new.notes, new.summary_l4, new.summary_l2, new.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
            INSERT INTO papers_fts(papers_fts, rowid, id, title, abstract, notes, summary_l4, summary_l2, tags)
            VALUES ('delete', old.rowid, old.id, old.title, old.abstract, old.notes, old.summary_l4, old.summary_l2, old.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
            INSERT INTO papers_fts(papers_fts, rowid, id, title, abstract, notes, summary_l4, summary_l2, tags)
            VALUES ('delete', old.rowid, old.id, old.title, old.abstract, old.notes, old.summary_l4, old.summary_l2, old.tags);
            INSERT INTO papers_fts(rowid, id, title, abstract, notes, summary_l4, summary_l2, tags)
            VALUES (new.rowid, new.id, new.title, new.abstract, new.notes, new.summary_l4, new.summary_l2, new.tags);
        END;
    """)
    conn.commit()
    return conn


def _clean_arxiv_id(raw: str) -> str:
    return re.sub(r"^(https?://)?arxiv\.org/(abs|pdf)/", "", raw).rstrip(".pdf").strip("/")


def enrich_from_arxiv(conn: sqlite3.Connection, db_path: Path, *, fetch_pdfs: bool = True) -> dict:
    """Batch-fetch metadata from arXiv API for papers with arxiv_id but missing abstracts."""
    import time
    import xml.etree.ElementTree as ET

    papers = conn.execute(
        "SELECT id, arxiv_id FROM papers WHERE arxiv_id != '' AND (abstract = '' OR abstract IS NULL)"
    ).fetchall()
    if not papers:
        return {"enriched": 0, "total": 0, "errors": []}

    arxiv_map = {r["arxiv_id"]: r["id"] for r in papers}
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    enriched = 0
    errors = []

    for i, (arxiv_id, paper_id) in enumerate(arxiv_map.items()):
        clean_id = _clean_arxiv_id(arxiv_id)
        url = f"https://export.arxiv.org/api/query?id_list={clean_id}&max_results=1"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "alit/0.2"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                xml_data = resp.read().decode("utf-8")

            root = ET.fromstring(xml_data)
            entry = root.find("atom:entry", ns)
            if entry is None:
                errors.append(f"{arxiv_id}: no entry in response")
                time.sleep(3)
                continue

            title_el = entry.find("atom:title", ns)
            title = " ".join(title_el.text.strip().split()) if title_el is not None and title_el.text else ""
            if "Error" in title:
                errors.append(f"{arxiv_id}: {title}")
                time.sleep(3)
                continue

            summary_el = entry.find("atom:summary", ns)
            abstract = " ".join(summary_el.text.strip().split()) if summary_el is not None and summary_el.text else ""

            pub_el = entry.find("atom:published", ns)
            year = int(pub_el.text[:4]) if pub_el is not None and pub_el.text else None

            authors = [
                a.find("atom:name", ns).text
                for a in entry.findall("atom:author", ns)
                if a.find("atom:name", ns) is not None and a.find("atom:name", ns).text
            ]

            entry_url_el = entry.find("atom:id", ns)
            entry_url = entry_url_el.text if entry_url_el is not None else ""

            kwargs: dict = {"authors": ", ".join(authors), "abstract": abstract, "url": entry_url}
            if title:
                kwargs["title"] = title
            if year:
                kwargs["year"] = year

            update_paper(conn, paper_id, **kwargs)

            if fetch_pdfs:
                fetch_pdf_for_paper(conn, paper_id, db_path)

            enriched += 1
            print(f"  [{i + 1}/{len(arxiv_map)}] {paper_id} ({year or '?'})", flush=True)
        except Exception as e:
            errors.append(f"{arxiv_id} ({paper_id}): {e}")

        time.sleep(3)

    return {"enriched": enriched, "total": len(arxiv_map), "errors": errors}


def _arxiv_pdf_url(arxiv_id: str) -> str:
    """Convert arXiv ID to PDF download URL."""
    clean = re.sub(r"^(https?://)?arxiv\.org/(abs|pdf)/", "", arxiv_id)
    clean = clean.rstrip(".pdf").strip("/")
    return f"https://arxiv.org/pdf/{clean}.pdf"


def download_pdf(url: str, dest: Path, *, timeout: int = 60) -> bool:
    """Download a PDF from url to dest. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agent-litreview/0.2"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = resp.read()
            if len(data) < 1000:  # too small to be a real PDF
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return True
    except Exception:
        return False


def fetch_pdf_for_paper(
    conn: sqlite3.Connection,
    paper_id: str,
    db_path: Path,
) -> str | None:
    """Try to download PDF for a paper. Returns relative pdf_path or None.

    Checks arxiv_id first, then url. Stores PDF in papers/ next to papers.db.
    """
    paper = get_paper(conn, paper_id)
    if not paper:
        return None

    # Already have a PDF?
    existing = paper.get("pdf_path") or ""
    if existing and (db_path / existing).exists():
        return existing

    papers_dir = db_path / "papers"
    papers_dir.mkdir(exist_ok=True)

    # Try arXiv
    arxiv_id = paper.get("arxiv_id") or ""
    if arxiv_id:
        pdf_url = _arxiv_pdf_url(arxiv_id)
        filename = re.sub(r"[^a-zA-Z0-9._-]", "_", arxiv_id) + ".pdf"
        dest = papers_dir / filename
        if download_pdf(pdf_url, dest):
            rel = f"papers/{filename}"
            update_paper(conn, paper_id, pdf_path=rel)
            return rel

    # Try direct URL if it looks like a PDF
    url = paper.get("url") or ""
    if url and url.lower().endswith(".pdf"):
        filename = paper_id + ".pdf"
        dest = papers_dir / filename
        if download_pdf(url, dest):
            rel = f"papers/{filename}"
            update_paper(conn, paper_id, pdf_path=rel)
            return rel

    return None


def add_paper(conn: sqlite3.Connection, id: str, title: str, **kwargs) -> dict:
    """Insert or replace a paper. Returns the row as dict."""
    fields = {k: v for k, v in kwargs.items() if v is not None}
    fields["id"] = id
    fields["title"] = title
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    conn.execute(
        f"INSERT OR REPLACE INTO papers ({cols}) VALUES ({placeholders})",
        list(fields.values()),
    )
    conn.execute(
        "UPDATE papers SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (id,),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM papers WHERE id = ?", (id,)).fetchone())


def get_paper(conn: sqlite3.Connection, id: str) -> dict | None:
    """Fetch a single paper by id."""
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (id,)).fetchone()
    return dict(row) if row else None


def list_papers(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    """List all papers, optionally filtered by status."""
    if status:
        rows = conn.execute(
            "SELECT * FROM papers WHERE status = ? ORDER BY year DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM papers ORDER BY year DESC").fetchall()
    return [dict(r) for r in rows]


def update_paper(conn: sqlite3.Connection, id: str, **kwargs) -> dict | None:
    """Update specific fields of a paper."""
    if not kwargs:
        return get_paper(conn, id)
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [id]
    conn.execute(
        f"UPDATE papers SET {sets}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        vals,
    )
    conn.commit()
    return get_paper(conn, id)


def add_citation(conn: sqlite3.Connection, from_id: str, to_id: str, type: str = "cites") -> None:
    """Add a citation edge between two papers."""
    conn.execute(
        "INSERT OR REPLACE INTO citations (from_id, to_id, type) VALUES (?, ?, ?)",
        (from_id, to_id, type),
    )
    conn.commit()


def get_citations(conn: sqlite3.Connection, id: str) -> dict:
    """Get all incoming and outgoing citations for a paper."""
    outgoing = [
        dict(r)
        for r in conn.execute("SELECT * FROM citations WHERE from_id = ?", (id,)).fetchall()
    ]
    incoming = [
        dict(r)
        for r in conn.execute("SELECT * FROM citations WHERE to_id = ?", (id,)).fetchall()
    ]
    return {"cites": outgoing, "cited_by": incoming}


def attach_pdf(conn: sqlite3.Connection, paper_id: str, src: Path, db_path: Path) -> str:
    """Copy a local PDF into papers/ and set pdf_path. Returns the relative path."""
    import shutil
    papers_dir = db_path / "papers"
    papers_dir.mkdir(exist_ok=True)
    filename = paper_id + ".pdf"
    dest = papers_dir / filename
    shutil.copy2(str(src), str(dest))
    rel = f"papers/{filename}"
    update_paper(conn, paper_id, pdf_path=rel)
    return rel


def get_orphan_citations(conn: sqlite3.Connection) -> list[dict]:
    """Find citation edges where to_id doesn't exist in papers table."""
    rows = conn.execute("""
        SELECT c.from_id, c.to_id, c.type
        FROM citations c
        LEFT JOIN papers p ON c.to_id = p.id
        WHERE p.id IS NULL
    """).fetchall()
    return [dict(r) for r in rows]


def delete_paper(conn: sqlite3.Connection, id: str) -> bool:
    """Delete a paper by id. Returns True if deleted."""
    cur = conn.execute("DELETE FROM papers WHERE id = ?", (id,))
    conn.commit()
    return cur.rowcount > 0


def get_stats(conn: sqlite3.Connection) -> dict:
    """Collection overview stats."""
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    by_status = {
        r["status"]: r["cnt"]
        for r in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM papers GROUP BY status"
        ).fetchall()
    }
    citations = conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]
    purpose_row = conn.execute("SELECT value FROM meta WHERE key='purpose'").fetchone()
    purpose = purpose_row["value"] if purpose_row else ""
    return {
        "total": total,
        "by_status": by_status,
        "citations": citations,
        "has_purpose": bool(purpose),
    }
