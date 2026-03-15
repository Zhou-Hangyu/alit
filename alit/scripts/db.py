from __future__ import annotations
"""SQLite database layer — sole source of truth for the literature review system.

Zero dependencies. Pure Python stdlib only.
"""

import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LIT_DIR = ".alit"
DB_NAME = "papers.db"
SCHEMA_VERSION = 4
_migrated_dbs: set[str] = set()


def _resolve_db_path(path: Path | None = None) -> Path:
    base = path or Path.cwd()
    target = base / LIT_DIR / DB_NAME

    if target.exists():
        return target

    old_locations = [
        base / LIT_DIR / LIT_DIR / DB_NAME,
        base / ".lit" / LIT_DIR / DB_NAME,
        base / ".lit" / DB_NAME,
        base / DB_NAME,
    ]
    for old_path in old_locations:
        if old_path.exists():
            _migrate_file_layout(base, old_path)
            return target

    return target


def _migrate_file_layout(base: Path, old_db_path: Path) -> None:
    import shutil
    target_dir = base / LIT_DIR
    target_dir.mkdir(exist_ok=True)

    if old_db_path.exists() and old_db_path != target_dir / DB_NAME:
        shutil.move(str(old_db_path), str(target_dir / DB_NAME))
        for ext in ("-wal", "-shm"):
            wal = old_db_path.parent / (DB_NAME + ext)
            if wal.exists():
                shutil.move(str(wal), str(target_dir / (DB_NAME + ext)))

    old_parent = old_db_path.parent
    for pdfs_name in ("pdfs", "papers"):
        old_pdfs = old_parent / pdfs_name
        if old_pdfs.exists() and any(old_pdfs.glob("*.pdf")):
            new_pdfs = target_dir / "pdfs"
            new_pdfs.mkdir(exist_ok=True)
            for pdf in old_pdfs.glob("*.pdf"):
                dest = new_pdfs / pdf.name
                if not dest.exists():
                    shutil.move(str(pdf), str(dest))

    for d in (old_parent, old_parent.parent):
        if d != base and d != target_dir and d.exists() and d.name in (".lit", ".alit"):
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass


def get_db(path: Path | None = None) -> sqlite3.Connection:
    db_path = _resolve_db_path(path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    _migrate_schema(conn)
    return conn


def init_db(path: Path | None = None) -> sqlite3.Connection:
    base = path or Path.cwd()
    db_path = _resolve_db_path(base)
    db_path.parent.mkdir(parents=True, exist_ok=True)
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

        CREATE INDEX IF NOT EXISTS idx_citations_to_id ON citations(to_id);
        CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
        CREATE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id);

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
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    if db_path in _migrated_dbs:
        return

    cur_version_row = conn.execute("SELECT value FROM meta WHERE key='_schema_version'").fetchone()
    cur_version = int(cur_version_row["value"]) if cur_version_row else 0

    if cur_version >= SCHEMA_VERSION:
        _migrated_dbs.add(db_path)
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

    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_citations_to_id ON citations(to_id);
        CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
        CREATE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id);
    """)

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('_schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    _migrated_dbs.add(db_path)


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

    no_arxiv = conn.execute(
        "SELECT id, title FROM papers WHERE (arxiv_id = '' OR arxiv_id IS NULL) AND (abstract = '' OR abstract IS NULL) AND title != ''"
    ).fetchall()

    for row in no_arxiv:
        try:
            import json as _json
            encoded = urllib.parse.quote(row["title"])
            s2_url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={encoded}&limit=1&fields=title,abstract,year,authors,externalIds,url"
            data = _json.loads(_fetch_url(s2_url).decode("utf-8"))
            results = data.get("data", [])
            if not results:
                continue
            top = results[0]
            t1 = set(row["title"].lower().split())
            t2 = set((top.get("title") or "").lower().split())
            overlap = len(t1 & t2) / max(len(t1 | t2), 1)
            if overlap < 0.6:
                continue
            meta: dict = {"abstract": top.get("abstract") or "", "url": top.get("url") or ""}
            if top.get("year"):
                meta["year"] = top["year"]
            authors = ", ".join(a.get("name", "") for a in (top.get("authors") or []))
            if authors:
                meta["authors"] = authors
            ext = top.get("externalIds") or {}
            if ext.get("ArXiv"):
                meta["arxiv_id"] = ext["ArXiv"]
            if ext.get("DOI"):
                meta["doi"] = ext["DOI"]
            update_paper(conn, row["id"], **meta)
            enriched += 1
            print(f"  [{enriched}] {row['id']} (via title search)", flush=True)
            time.sleep(1)
        except Exception:
            continue

    return {"enriched": enriched, "total": len(papers) + len(no_arxiv), "errors": errors}


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
    if existing and (db_path / LIT_DIR / existing).exists():
        return existing

    pdfs_dir = db_path / LIT_DIR / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)

    arxiv_id = paper.get("arxiv_id") or ""
    if arxiv_id:
        pdf_url = _arxiv_pdf_url(arxiv_id)
        filename = re.sub(r"[^a-zA-Z0-9._-]", "_", arxiv_id) + ".pdf"
        dest = pdfs_dir / filename
        if download_pdf(pdf_url, dest):
            rel = f"pdfs/{filename}"
            update_paper(conn, paper_id, pdf_path=rel)
            return rel

    url = paper.get("url") or ""
    if url and url.lower().endswith(".pdf"):
        filename = paper_id + ".pdf"
        dest = pdfs_dir / filename
        if download_pdf(url, dest):
            rel = f"pdfs/{filename}"
            update_paper(conn, paper_id, pdf_path=rel)
            return rel

    return None


def extract_references_from_pdf(pdf_path: Path) -> list[str]:
    """Extract arXiv IDs from a PDF's text. Returns list of arXiv ID strings."""
    try:
        raw = pdf_path.read_bytes()
        text_chunks = re.findall(rb"[\x20-\x7E]{20,}", raw)
        text = b" ".join(text_chunks).decode("ascii", errors="ignore")
    except Exception:
        return []

    arxiv_ids = set()
    for m in re.finditer(r"(\d{4})\.(\d{4,5})(?:v\d+)?", text):
        yymm, seq = m.group(1), m.group(2)
        yy, mm = int(yymm[:2]), int(yymm[2:])
        if 7 <= yy <= 30 and 1 <= mm <= 12:
            arxiv_ids.add(f"{yymm}.{seq}")
    return sorted(arxiv_ids)


def auto_cite_from_pdfs(conn: sqlite3.Connection, db_path: Path) -> dict:
    """Scan all PDFs, extract arXiv references, create citation edges automatically."""
    papers = conn.execute(
        "SELECT id, arxiv_id, pdf_path FROM papers WHERE pdf_path != '' AND pdf_path IS NOT NULL"
    ).fetchall()

    known_arxiv = {}
    for r in conn.execute("SELECT id, arxiv_id FROM papers WHERE arxiv_id != ''").fetchall():
        known_arxiv[r["arxiv_id"]] = r["id"]

    edges_added = 0
    papers_scanned = 0
    missing_refs: dict[str, int] = {}

    for paper in papers:
        pdf_file = db_path / LIT_DIR / paper["pdf_path"]
        if not pdf_file.exists():
            continue

        own_arxiv = _clean_arxiv_id(paper["arxiv_id"] or "")
        refs = extract_references_from_pdf(pdf_file)
        papers_scanned += 1

        for ref_arxiv in refs:
            if ref_arxiv == own_arxiv:
                continue
            target_id = known_arxiv.get(ref_arxiv)
            if target_id:
                existing = conn.execute(
                    "SELECT 1 FROM citations WHERE from_id = ? AND to_id = ?",
                    (paper["id"], target_id),
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO citations (from_id, to_id, type) VALUES (?, ?, 'cites')",
                        (paper["id"], target_id),
                    )
                    edges_added += 1
            else:
                missing_refs[ref_arxiv] = missing_refs.get(ref_arxiv, 0) + 1

    if edges_added:
        conn.commit()

    top_missing = sorted(missing_refs.items(), key=lambda x: x[1], reverse=True)[:10]
    return {"scanned": papers_scanned, "edges_added": edges_added, "missing": top_missing}


def fetch_all_pdfs(conn: sqlite3.Connection, db_path: Path) -> dict:
    """Download PDFs for all papers with arxiv_id but no pdf_path."""
    import time
    papers = conn.execute(
        "SELECT id, arxiv_id FROM papers WHERE arxiv_id != '' AND (pdf_path = '' OR pdf_path IS NULL)"
    ).fetchall()
    if not papers:
        return {"downloaded": 0, "total": 0, "errors": []}

    downloaded = 0
    errors = []
    for i, row in enumerate(papers):
        try:
            result = fetch_pdf_for_paper(conn, row["id"], db_path)
            if result:
                downloaded += 1
                print(f"  [{i + 1}/{len(papers)}] {row['id']}", flush=True)
            else:
                errors.append(f"{row['id']}: download failed")
        except Exception as e:
            errors.append(f"{row['id']}: {e}")
        time.sleep(1)
    return {"downloaded": downloaded, "total": len(papers), "errors": errors}


def attach_dir(conn: sqlite3.Connection, dir_path: Path, db_path: Path) -> dict:
    """Scan a directory for PDFs and attach them to matching papers by arXiv ID."""
    import shutil
    pdfs_dir = db_path / LIT_DIR / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)

    known = {}
    for row in conn.execute("SELECT id, arxiv_id FROM papers WHERE arxiv_id != ''").fetchall():
        clean = _clean_arxiv_id(row["arxiv_id"])
        known[clean] = row["id"]
        known[clean.replace(".", "_")] = row["id"]

    attached = 0
    for pdf in dir_path.glob("*.pdf"):
        stem = pdf.stem.replace("v1", "").replace("v2", "").replace("v3", "")
        paper_id = known.get(stem) or known.get(stem.replace(".", "_"))
        if not paper_id:
            continue
        existing = get_paper(conn, paper_id)
        if existing and existing.get("pdf_path"):
            continue
        filename = paper_id + ".pdf"
        dest = pdfs_dir / filename
        shutil.copy2(str(pdf), str(dest))
        rel = f"pdfs/{filename}"
        update_paper(conn, paper_id, pdf_path=rel)
        attached += 1
        print(f"  {paper_id} ← {pdf.name}", flush=True)

    return {"attached": attached}


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

    arxiv_id = kwargs.get("arxiv_id", "")
    if arxiv_id:
        existing_row = conn.execute("SELECT id FROM papers WHERE arxiv_id = ?", (arxiv_id,)).fetchone()
        if existing_row:
            updates = {k: v for k, v in kwargs.items() if v is not None and k in _VALID_PAPER_FIELDS}
            if title:
                updates["title"] = title
            return update_paper(conn, existing_row["id"], **updates)

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
    """Copy a local PDF into .alit/pdfs/ and set pdf_path. Returns the relative path."""
    import shutil
    pdfs_dir = db_path / LIT_DIR / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    filename = paper_id + ".pdf"
    dest = pdfs_dir / filename
    shutil.copy2(str(src), str(dest))
    rel = f"pdfs/{filename}"
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


_TAG_KEYWORDS = {
    "transformer": ["transformer", "attention mechanism", "self-attention"],
    "diffusion": ["diffusion model", "denoising", "score-based", "ddpm"],
    "reinforcement-learning": ["reinforcement learning", "policy gradient", "q-learning", "rl agent"],
    "nlp": ["natural language", "language model", "text generation", "tokenization"],
    "computer-vision": ["image classification", "object detection", "convolutional", "visual"],
    "generative": ["generative model", "gan", "vae", "variational autoencoder"],
    "graph-neural-network": ["graph neural", "gnn", "node embedding", "graph convolution"],
    "optimization": ["optimization", "gradient descent", "convergence", "learning rate"],
    "finance": ["financial", "trading", "market", "portfolio", "stock", "order book", "lob"],
    "simulation": ["simulation", "simulator", "synthetic data", "agent-based"],
    "foundation-model": ["foundation model", "pretrained", "large language model", "llm"],
    "survey": ["survey", "review", "overview", "taxonomy"],
}


def _auto_tag_from_abstract(abstract: str, title: str = "") -> list[str]:
    text = f"{title} {abstract}".lower()
    tags = []
    for tag, keywords in _TAG_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            tags.append(tag)
    return tags[:8]


def _parse_bibtex(text: str) -> list[dict]:
    entries = []
    raw_entries = re.split(r'\n\s*@', text)
    for raw in raw_entries:
        raw = raw.strip()
        if not raw:
            continue
        if not raw.startswith('@'):
            raw = '@' + raw

        header_match = re.match(r'@(\w+)\s*\{\s*([^,\s]+)\s*,', raw)
        if not header_match:
            continue
        entry_type = header_match.group(1).lower()
        citekey = header_match.group(2).strip()

        entry: dict = {"_type": entry_type, "_citekey": citekey}
        for field_match in re.finditer(
            r'(\w+)\s*=\s*(?:\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}|"([^"]*)"|(\d+))', raw
        ):
            field_name = field_match.group(1).lower()
            value = field_match.group(2) or field_match.group(3) or field_match.group(4) or ""
            value = re.sub(r'\s+', ' ', value).strip()
            value = value.replace('{', '').replace('}', '')
            entry[field_name] = value
        entries.append(entry)
    return entries


def get_stats(conn: sqlite3.Connection) -> dict:
    """Collection overview stats — single query."""
    row = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN pdf_path != '' AND pdf_path IS NOT NULL THEN 1 ELSE 0 END) as with_pdf,
            SUM(CASE WHEN abstract != '' AND abstract IS NOT NULL THEN 1 ELSE 0 END) as with_abstract,
            SUM(CASE WHEN summary_l4 != '' AND summary_l4 IS NOT NULL THEN 1 ELSE 0 END) as with_l4,
            SUM(CASE WHEN summary_l2 != '' AND summary_l2 IS NOT NULL THEN 1 ELSE 0 END) as with_l2
        FROM papers
    """).fetchone()
    by_status = {
        r["status"]: r["cnt"]
        for r in conn.execute("SELECT status, COUNT(*) as cnt FROM papers GROUP BY status").fetchall()
    }
    citations = conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]
    orphans = conn.execute("""
        SELECT COUNT(*) FROM citations c LEFT JOIN papers p ON c.to_id = p.id WHERE p.id IS NULL
    """).fetchone()[0]
    taste_row = conn.execute("SELECT value FROM meta WHERE key='taste'").fetchone()
    return {
        "total": row["total"],
        "by_status": by_status,
        "citations": citations,
        "orphan_citations": orphans,
        "with_pdf": row["with_pdf"] or 0,
        "with_abstract": row["with_abstract"] or 0,
        "with_l4": row["with_l4"] or 0,
        "with_l2": row["with_l2"] or 0,
        "has_taste": bool(taste_row and taste_row["value"]),
    }
