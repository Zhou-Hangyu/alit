from __future__ import annotations
"""SQLite database layer — sole source of truth for the literature review system.

Zero dependencies. Pure Python stdlib only.
"""

import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

DB_NAME = "papers.db"
SCHEMA_VERSION = 2


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

    """)
    conn.commit()
    _migrate_schema(conn)
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Version-aware schema migration. Handles column additions and FTS5 trigger rebuilds."""
    cur_version_row = conn.execute("SELECT value FROM meta WHERE key='_schema_version'").fetchone()
    cur_version = int(cur_version_row["value"]) if cur_version_row else 0

    if cur_version >= SCHEMA_VERSION:
        return

    existing = {r[1] for r in conn.execute("PRAGMA table_info(papers)").fetchall()}
    new_columns = [
        ("pdf_path", "TEXT DEFAULT ''"),
        ("pagerank", "REAL DEFAULT 0.0"),
        ("summary_l4", "TEXT DEFAULT ''"),
        ("summary_l4_model", "TEXT DEFAULT ''"),
        ("summary_l4_at", "TEXT DEFAULT ''"),
        ("summary_l2", "TEXT DEFAULT ''"),
        ("summary_l2_model", "TEXT DEFAULT ''"),
        ("summary_l2_at", "TEXT DEFAULT ''"),
    ]
    for col, typedef in new_columns:
        if col not in existing:
            conn.execute(f"ALTER TABLE papers ADD COLUMN {col} {typedef}")

    _rebuild_fts_triggers(conn)

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('_schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def _rebuild_fts_triggers(conn: sqlite3.Connection) -> None:
    """Drop and recreate FTS5 triggers + virtual table to match current schema."""
    conn.executescript("""
        DROP TRIGGER IF EXISTS papers_ai;
        DROP TRIGGER IF EXISTS papers_ad;
        DROP TRIGGER IF EXISTS papers_au;
        DROP TABLE IF EXISTS papers_fts;
    """)
    conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
        id UNINDEXED, title, abstract, notes, summary_l4, summary_l2, tags,
        content='papers', content_rowid='rowid',
        tokenize="unicode61 tokenchars '-_'"
    )""")
    conn.executescript("""
        CREATE TRIGGER papers_ai AFTER INSERT ON papers BEGIN
            INSERT INTO papers_fts(rowid, id, title, abstract, notes, summary_l4, summary_l2, tags)
            VALUES (new.rowid, new.id, new.title, new.abstract, new.notes, new.summary_l4, new.summary_l2, new.tags);
        END;

        CREATE TRIGGER papers_ad AFTER DELETE ON papers BEGIN
            INSERT INTO papers_fts(papers_fts, rowid, id, title, abstract, notes, summary_l4, summary_l2, tags)
            VALUES ('delete', old.rowid, old.id, old.title, old.abstract, old.notes, old.summary_l4, old.summary_l2, old.tags);
        END;

        CREATE TRIGGER papers_au AFTER UPDATE ON papers BEGIN
            INSERT INTO papers_fts(papers_fts, rowid, id, title, abstract, notes, summary_l4, summary_l2, tags)
            VALUES ('delete', old.rowid, old.id, old.title, old.abstract, old.notes, old.summary_l4, old.summary_l2, old.tags);
            INSERT INTO papers_fts(rowid, id, title, abstract, notes, summary_l4, summary_l2, tags)
            VALUES (new.rowid, new.id, new.title, new.abstract, new.notes, new.summary_l4, new.summary_l2, new.tags);
        END;

        INSERT INTO papers_fts(papers_fts) VALUES('rebuild');
    """)


def _clean_arxiv_id(raw: str) -> str:
    return re.sub(r"^(https?://)?arxiv\.org/(abs|pdf)/", "", raw).rstrip(".pdf").strip("/")


def _fetch_url(url: str, *, timeout: int = 30, max_retries: int = 3) -> bytes:
    """Fetch URL with retry + exponential backoff on 429/5xx."""
    import time
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "alit/0.2"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)
                print(f"    rate limited ({e.code}), waiting {wait}s...", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    return b""


def _enrich_one_arxiv(arxiv_id: str) -> dict | None:
    """Fetch metadata for one paper from arXiv API. Returns parsed dict or None."""
    import xml.etree.ElementTree as ET
    clean_id = _clean_arxiv_id(arxiv_id)
    url = f"https://export.arxiv.org/api/query?id_list={clean_id}&max_results=1"
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    xml_data = _fetch_url(url).decode("utf-8")
    root = ET.fromstring(xml_data)
    entry = root.find("atom:entry", ns)
    if entry is None:
        return None

    title_el = entry.find("atom:title", ns)
    title = " ".join(title_el.text.strip().split()) if title_el is not None and title_el.text else ""
    if "Error" in title:
        return None

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

    result: dict = {"authors": ", ".join(authors), "abstract": abstract, "url": entry_url}
    if title:
        result["title"] = title
    if year:
        result["year"] = year
    return result


def _enrich_one_s2(arxiv_id: str) -> dict | None:
    """Fetch metadata for one paper from Semantic Scholar API (no API key needed)."""
    import json as _json
    clean_id = _clean_arxiv_id(arxiv_id)
    url = f"https://api.semanticscholar.org/graph/v1/paper/ArXiv:{clean_id}?fields=title,abstract,year,authors,externalIds,url"

    try:
        data = _json.loads(_fetch_url(url).decode("utf-8"))
    except Exception:
        return None

    if "error" in data or not data.get("title"):
        return None

    authors = ", ".join(a.get("name", "") for a in (data.get("authors") or []))
    result: dict = {
        "authors": authors,
        "abstract": data.get("abstract") or "",
        "url": data.get("url") or "",
    }
    if data.get("title"):
        result["title"] = data["title"]
    if data.get("year"):
        result["year"] = data["year"]
    ext = data.get("externalIds") or {}
    if ext.get("DOI"):
        result["doi"] = ext["DOI"]
    return result


def _enrich_batch_arxiv(arxiv_ids: list[str]) -> dict[str, dict]:
    """Fetch metadata for up to 50 papers in one arXiv API call."""
    import xml.etree.ElementTree as ET
    clean_ids = [_clean_arxiv_id(aid) for aid in arxiv_ids]
    id_list = ",".join(clean_ids)
    url = f"https://export.arxiv.org/api/query?id_list={id_list}&max_results={len(clean_ids)}"
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    try:
        xml_data = _fetch_url(url, timeout=60).decode("utf-8")
    except Exception:
        return {}

    root = ET.fromstring(xml_data)
    results: dict[str, dict] = {}

    for entry in root.findall("atom:entry", ns):
        entry_id_el = entry.find("atom:id", ns)
        if entry_id_el is None or not entry_id_el.text:
            continue
        entry_url = entry_id_el.text

        title_el = entry.find("atom:title", ns)
        title = " ".join(title_el.text.strip().split()) if title_el is not None and title_el.text else ""
        if "Error" in title or not title:
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

        matched_id = None
        for orig, clean in zip(arxiv_ids, clean_ids):
            if clean in entry_url:
                matched_id = orig
                break
        if not matched_id:
            continue

        result: dict = {"authors": ", ".join(authors), "abstract": abstract, "url": entry_url}
        if title:
            result["title"] = title
        if year:
            result["year"] = year
        results[matched_id] = result

    return results


def enrich_papers(conn: sqlite3.Connection, db_path: Path, *, fetch_pdfs: bool = True) -> dict:
    """Batch-fetch metadata for papers missing abstracts. Batches arXiv calls, falls back to S2."""
    import time

    papers = conn.execute(
        "SELECT id, arxiv_id FROM papers WHERE arxiv_id != '' AND (abstract = '' OR abstract IS NULL)"
    ).fetchall()
    if not papers:
        return {"enriched": 0, "total": 0, "errors": []}

    id_to_paper = {r["arxiv_id"]: r["id"] for r in papers}
    arxiv_ids = list(id_to_paper.keys())
    enriched = 0
    errors = []

    BATCH_SIZE = 40
    arxiv_results: dict[str, dict] = {}
    for batch_start in range(0, len(arxiv_ids), BATCH_SIZE):
        batch = arxiv_ids[batch_start:batch_start + BATCH_SIZE]
        print(f"  Fetching arXiv batch {batch_start // BATCH_SIZE + 1} ({len(batch)} papers)...", flush=True)
        arxiv_results.update(_enrich_batch_arxiv(batch))
        if batch_start + BATCH_SIZE < len(arxiv_ids):
            time.sleep(3)

    for i, (arxiv_id, paper_id) in enumerate(id_to_paper.items()):
        source = "arxiv"
        result = arxiv_results.get(arxiv_id)
        if result is None:
            source = "s2"
            try:
                result = _enrich_one_s2(arxiv_id)
                time.sleep(1)
            except Exception as e:
                errors.append(f"{arxiv_id} ({paper_id}): S2 fallback failed: {e}")
                continue

        if result is None:
            errors.append(f"{arxiv_id}: not found on arXiv or S2")
            continue

        try:
            update_paper(conn, paper_id, **result)
            if fetch_pdfs:
                fetch_pdf_for_paper(conn, paper_id, db_path)
            enriched += 1
            print(f"  [{i + 1}/{len(id_to_paper)}] {paper_id} ({result.get('year', '?')}) via {source}", flush=True)
        except Exception as e:
            errors.append(f"{arxiv_id} ({paper_id}): {e}")

    return {"enriched": enriched, "total": len(papers), "errors": errors}


def _arxiv_pdf_url(arxiv_id: str) -> str:
    """Convert arXiv ID to PDF download URL."""
    clean = re.sub(r"^(https?://)?arxiv\.org/(abs|pdf)/", "", arxiv_id)
    clean = clean.rstrip(".pdf").strip("/")
    return f"https://arxiv.org/pdf/{clean}.pdf"


def download_pdf(url: str, dest: Path, *, timeout: int = 60) -> bool:
    """Download a PDF from url to dest. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "alit/0.2"})
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


_VALID_PAPER_FIELDS = frozenset({
    "id", "title", "authors", "year", "abstract", "url", "arxiv_id", "doi",
    "tags", "status", "notes", "summary_l4", "summary_l4_model", "summary_l4_at",
    "summary_l2", "summary_l2_model", "summary_l2_at", "pdf_path", "pagerank",
})


def _sanitize_id(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", raw).strip("_") or "paper"


def add_paper(conn: sqlite3.Connection, id: str, title: str, **kwargs) -> dict:
    """Insert a paper, or update fields if it already exists. Never loses existing data."""
    id = _sanitize_id(id)
    existing = get_paper(conn, id)
    if existing:
        updates = {k: v for k, v in kwargs.items() if v is not None and k in _VALID_PAPER_FIELDS}
        if title:
            updates["title"] = title
        return update_paper(conn, id, **updates)

    fields = {k: v for k, v in kwargs.items() if v is not None and k in _VALID_PAPER_FIELDS}
    fields["id"] = id
    fields["title"] = title
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    conn.execute(f"INSERT INTO papers ({cols}) VALUES ({placeholders})", list(fields.values()))
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
    """Delete a paper and its citation edges. Returns True if deleted."""
    cur = conn.execute("DELETE FROM papers WHERE id = ?", (id,))
    conn.execute("DELETE FROM citations WHERE from_id = ? OR to_id = ?", (id, id))
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
    orphans = conn.execute("""
        SELECT COUNT(*) FROM citations c
        LEFT JOIN papers p ON c.to_id = p.id WHERE p.id IS NULL
    """).fetchone()[0]
    with_pdf = conn.execute("SELECT COUNT(*) FROM papers WHERE pdf_path != '' AND pdf_path IS NOT NULL").fetchone()[0]
    with_l4 = conn.execute("SELECT COUNT(*) FROM papers WHERE summary_l4 != '' AND summary_l4 IS NOT NULL").fetchone()[0]
    with_l2 = conn.execute("SELECT COUNT(*) FROM papers WHERE summary_l2 != '' AND summary_l2 IS NOT NULL").fetchone()[0]
    with_abstract = conn.execute("SELECT COUNT(*) FROM papers WHERE abstract != '' AND abstract IS NOT NULL").fetchone()[0]
    purpose_row = conn.execute("SELECT value FROM meta WHERE key='purpose'").fetchone()
    purpose = purpose_row["value"] if purpose_row else ""
    return {
        "total": total,
        "by_status": by_status,
        "citations": citations,
        "orphan_citations": orphans,
        "with_pdf": with_pdf,
        "with_abstract": with_abstract,
        "with_l4": with_l4,
        "with_l2": with_l2,
        "has_purpose": bool(purpose),
    }
