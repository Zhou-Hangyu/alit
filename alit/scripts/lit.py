#!/usr/bin/env python3
"""lit — lightweight CLI for the literature review system.

Zero dependencies. SQLite is the sole source of truth.
The agent does all the intelligence — this is pure data plumbing.

Usage:
    lit init
    lit add "Paper Title" --year 2024 --abstract "..."
    lit search "attention"
    lit recommend 5
    lit ask "what approaches exist for X?"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

from alit.scripts.db import DB_NAME, add_citation, add_paper, attach_dir, attach_pdf
from alit.scripts.db import auto_cite_from_pdfs, delete_paper, enrich_papers
from alit.scripts.db import fetch_all_pdfs, fetch_pdf_for_paper, get_db
from alit.scripts.db import get_orphan_citations, get_paper, get_stats
from alit.scripts.db import init_db, list_papers, update_paper


# ── Helper ─────────────────────────────────────────────────────────────────────


def _auto_id(title: str, conn=None) -> str:
    import re
    slug = re.sub(r"[^a-z0-9\s]", "", title.lower())
    words = slug.split()[:4]
    base = "_".join(words) or "paper"
    if conn is None:
        return base
    candidate = base
    counter = 2
    while conn.execute("SELECT 1 FROM papers WHERE id = ?", (candidate,)).fetchone():
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


# ── Commands ───────────────────────────────────────────────────────────────────


def _cmd_init(args: argparse.Namespace) -> int:
    from alit.scripts.db import LIT_DIR
    target = Path(getattr(args, "path", None) or ".")
    target.mkdir(parents=True, exist_ok=True)
    db_path = target / LIT_DIR / DB_NAME
    if db_path.exists():
        print(f"Already initialized at {target / LIT_DIR}")
        return 0
    conn = init_db(target)
    conn.close()

    (target / LIT_DIR / "pdfs").mkdir(parents=True, exist_ok=True)

    gitignore = target / ".gitignore"
    entry = ".alit/"
    if gitignore.exists():
        content = gitignore.read_text()
        if entry not in content:
            with gitignore.open("a") as f:
                f.write(f"\n{entry}\n")
    else:
        gitignore.write_text(f"{entry}\n")

    print(f"(-o-) Initialized {target / LIT_DIR}/")
    return 0


def _is_arxiv_url(text: str) -> str | None:
    import re
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", text)
    return m.group(1) if m else None


_STOPWORDS = frozenset(
    "a an the of in on at to for with and or but is are was were be been "
    "have has had do does did will would can could should may might this that "
    "these those we you it its they their what how when where which who from as "
    "by not no more also than into about use using used".split()
)


def _extract_taste_keywords(text: str) -> list[str]:
    import re
    text = re.sub(r"#+\s+.*", "", text)
    text = re.sub(r"[*_`\[\]()>]", " ", text)
    text = re.sub(r"\bhttps?://\S+", "", text)
    text = re.sub(r"^[-\d.]+\s+", "", text, flags=re.MULTILINE)

    phrases = []
    for line in text.split("\n"):
        line = line.strip().strip("-").strip()
        if not line or len(line) < 5:
            continue
        words = [w.strip(".,;:()[]\"'") for w in line.lower().split()]
        meaningful = [w for w in words if w and w not in _STOPWORDS and len(w) > 2]
        if len(meaningful) >= 2:
            phrases.append(" ".join(meaningful[:5]))
        elif meaningful:
            phrases.append(meaningful[0])

    return phrases[:40]


def _cmd_add(args: argparse.Namespace, conn) -> int:
    title = args.title

    arxiv = getattr(args, "arxiv", None)
    detected_arxiv = _is_arxiv_url(title)
    if detected_arxiv and not arxiv:
        arxiv = detected_arxiv
        if title.startswith("http"):
            title = f"arXiv:{detected_arxiv}"

    paper_id = getattr(args, "id", None) or (f"arxiv_{detected_arxiv.replace('.', '_')}" if detected_arxiv else _auto_id(title, conn))

    kwargs = {}
    for field in ("year", "authors", "abstract", "url", "doi", "tags"):
        val = getattr(args, field, None)
        if val is not None:
            kwargs[field] = val
    if arxiv:
        kwargs["arxiv_id"] = arxiv
        if "url" not in kwargs:
            kwargs["url"] = f"https://arxiv.org/abs/{arxiv}"

    no_enrich = getattr(args, "no_enrich", False)

    if not no_enrich and arxiv and not kwargs.get("abstract"):
        from alit.scripts.db import _enrich_one_arxiv, _enrich_one_s2
        enriched = _enrich_one_arxiv(arxiv) or _enrich_one_s2(arxiv)
        if enriched:
            if enriched.get("title") and title.startswith("arXiv:"):
                title = enriched["title"]
            kwargs.update({k: v for k, v in enriched.items() if v and k != "title"})

    paper = add_paper(conn, paper_id, title, **kwargs)

    if not kwargs.get("tags") and paper and paper.get("abstract"):
        from alit.scripts.db import _auto_tag_from_abstract
        auto_tags = _auto_tag_from_abstract(paper["abstract"], paper["title"])
        if auto_tags:
            update_paper(conn, paper_id, tags=",".join(auto_tags))
            paper = get_paper(conn, paper_id)

    db_path = Path(args._db_path) if hasattr(args, "_db_path") else Path.cwd()
    local_pdf = getattr(args, "pdf", None)
    no_pdf = getattr(args, "no_pdf", False)

    if local_pdf:
        src = Path(local_pdf)
        if src.exists():
            attach_pdf(conn, paper_id, src, db_path)
            paper = get_paper(conn, paper_id)
        else:
            print(f"Warning: PDF not found at {src}", file=sys.stderr)
    elif not no_enrich and not no_pdf:
        pdf = fetch_pdf_for_paper(conn, paper_id, db_path)
        if pdf:
            paper = get_paper(conn, paper_id)

    if getattr(args, "json", False):
        print(json.dumps(paper, ensure_ascii=False))
    else:
        pdf_msg = f" | pdf: {paper.get('pdf_path')}" if paper and paper.get("pdf_path") else ""
        print(f"(-o+) Added: {paper_id}{pdf_msg}")
    return 0


def _cmd_show(args: argparse.Namespace, conn) -> int:
    paper = get_paper(conn, args.id)
    if paper is None:
        paper_row = conn.execute(
            "SELECT * FROM papers WHERE arxiv_id = ?", (args.id,)
        ).fetchone()
        if paper_row is None:
            clean = re.sub(r"^(https?://)?arxiv\.org/(abs|pdf)/", "", args.id).rstrip(".pdf").strip("/")
            paper_row = conn.execute(
                "SELECT * FROM papers WHERE arxiv_id = ?", (clean,)
            ).fetchone()
        if paper_row:
            paper = dict(paper_row)
            args.id = paper["id"]
        else:
            print(f"(xox) Not found: {args.id}", file=sys.stderr)
            return 1
    if getattr(args, "json", False):
        from alit.scripts.db import get_citations
        cites = get_citations(conn, args.id)
        print(json.dumps({**paper, "citations": cites}, ensure_ascii=False))
    else:
        from alit.scripts.db import get_citations
        print(f"id:         {paper['id']}")
        print(f"title:      {paper['title']}")
        print(f"authors:    {paper['authors']}")
        print(f"year:       {paper['year']}")
        print(f"status:     {paper['status']}")
        print(f"tags:       {paper['tags']}")
        print(f"url:        {paper['url']}")
        pdf = paper.get("pdf_path", "")
        if pdf:
            print(f"pdf:        {pdf}")
        print(f"pagerank:   {paper['pagerank']:.6f}")
        if paper.get("summary_l4"):
            print(f"summary_l4: {paper['summary_l4']}")
            print(f"  model:    {paper.get('summary_l4_model', '')}")
        if paper.get("summary_l2"):
            print(f"summary_l2: {paper['summary_l2']}")
        print(f"\nabstract:\n  {paper['abstract'] or '(none)'}")
        if paper.get("notes"):
            print(f"\nnotes:\n  {paper['notes']}")
        cites = get_citations(conn, args.id)
        if cites["cites"]:
            print(f"\ncites ({len(cites['cites'])}):")
            for c in cites["cites"]:
                print(f"  → {c['to_id']} [{c['type']}]")
        if cites["cited_by"]:
            print(f"\ncited by ({len(cites['cited_by'])}):")
            for c in cites["cited_by"]:
                print(f"  ← {c['from_id']} [{c['type']}]")
    return 0


def _cmd_list(args: argparse.Namespace, conn) -> int:
    status = getattr(args, "status", None)
    tag = getattr(args, "tag", None)
    show_all = getattr(args, "all", False)
    limit = None if show_all else 20

    if tag:
        q = "SELECT * FROM papers WHERE tags LIKE ? "
        params: list = [f"%{tag}%"]
        if status:
            q += "AND status = ? "
            params.append(status)
        q += "ORDER BY year DESC"
        if limit:
            q += f" LIMIT {limit}"
        papers = [dict(r) for r in conn.execute(q, params).fetchall()]
    else:
        papers = list_papers(conn, status=status)
        if limit and len(papers) > limit:
            papers = papers[:limit]

    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

    if getattr(args, "json", False):
        print(json.dumps(papers, ensure_ascii=False))
    else:
        if not papers:
            print("(xox) No papers found.")
            return 0
        for p in papers:
            year = p["year"] or "????"
            st = (p["status"] or "unread")[:8]
            pdf = "📄" if p.get("pdf_path") else "  "
            l4 = "✓" if p.get("summary_l4") else " "
            print(f"[{st:8s}] {pdf}{l4} {p['id']:<38s} ({year})  {(p['title'] or '')[:55]}")
        if not show_all and len(papers) < total:
            print(f"\n({len(papers)} of {total} shown. Use --all for full list)")
    return 0


def _cmd_search(args: argparse.Namespace, conn) -> int:
    from alit.scripts.search import search

    top_k = getattr(args, "top_k", 20)
    results = search(conn, args.query, top_k=top_k)
    if getattr(args, "json", False):
        print(json.dumps(results, ensure_ascii=False))
    else:
        if not results:
            print("(xox) No results found.")
            return 0
        for r in results:
            year = r.get("year") or "????"
            st = (r.get("status") or "unread")[:8]
            print(f"[{st:8s}] {r['id']:<40s} ({year})  {(r.get('title') or '')[:60]}")
    return 0


def _cmd_note(args: argparse.Namespace, conn) -> int:
    paper = get_paper(conn, args.id)
    if paper is None:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1
    existing = paper.get("notes") or ""
    new_notes = (existing + "\n" + args.text).strip()
    update_paper(conn, args.id, notes=new_notes)
    print(f"(-o+) Note added to {args.id}")
    return 0


def _cmd_summarize(args: argparse.Namespace, conn) -> int:
    paper = get_paper(conn, args.id)
    if paper is None:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1

    if not paper.get("pdf_path"):
        force = getattr(args, "force", False)
        if not force:
            print(f"⚠ No PDF for {args.id}. Summaries should be based on full paper reading, not abstracts.", file=sys.stderr)
            print(f"  Fetch the PDF first:  alit fetch-pdf {args.id}", file=sys.stderr)
            print(f"  Or override with:     alit summarize {args.id} --force ...", file=sys.stderr)
            return 1

    model = getattr(args, "model", "") or ""
    l4 = getattr(args, "l4", None)
    l2_raw = getattr(args, "l2", None)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    kwargs: dict = {}
    if l4 is not None:
        kwargs["summary_l4"] = l4
        kwargs["summary_l4_model"] = model
        kwargs["summary_l4_at"] = now
    if l2_raw is not None:
        import json as _json
        claims = l2_raw
        if len(claims) == 1 and claims[0].startswith("["):
            try:
                claims = _json.loads(claims[0])
            except Exception:
                pass
        l2_content = _json.dumps(claims)
        kwargs["summary_l2"] = l2_content
        kwargs["summary_l2_model"] = model
        kwargs["summary_l2_at"] = now

    if not kwargs:
        print("Error: provide --l4 or --l2", file=sys.stderr)
        return 1

    # Warn if summary looks like it's just restating the abstract
    abstract = (paper.get("abstract") or "").lower().split()
    if l4 and abstract:
        summary_words = set(l4.lower().split())
        abstract_words = set(abstract)
        if abstract_words and summary_words:
            overlap = len(summary_words & abstract_words) / max(len(summary_words), 1)
            if overlap > 0.8:
                print(f"⚠ Summary for {args.id} looks very similar to abstract ({overlap:.0%} word overlap).", file=sys.stderr)
                print(f"  Good summaries include details only found in the paper body.", file=sys.stderr)

    paper = update_paper(conn, args.id, **kwargs)
    if getattr(args, "json", False):
        print(json.dumps(paper, ensure_ascii=False))
    else:
        level = "l4" if l4 is not None else "l2"
        print(f"(-o+) Summary ({level}) stored for {args.id}")
    return 0



def _cmd_cite(args: argparse.Namespace, conn) -> int:
    batch_file = getattr(args, "batch", None)
    if batch_file:
        import json as _json
        data = _json.loads(Path(batch_file).read_text())
        added = 0
        for edge in data:
            from_id = edge.get("from") or edge.get("from_id", "")
            to_id = edge.get("to") or edge.get("to_id", "")
            type_ = edge.get("type", "cites")
            if from_id and to_id:
                add_citation(conn, from_id, to_id, type_)
                added += 1
        print(f"(-o+) Added {added} citation edges")
        return 0

    from_id = args.from_id
    to_id = args.to_id
    type_ = getattr(args, "type", "cites") or "cites"

    if not get_paper(conn, from_id):
        print(f"Paper not found: {from_id}", file=sys.stderr)
        return 1

    add_citation(conn, from_id, to_id, type_)
    if not get_paper(conn, to_id):
        print(f"Citation added: {from_id} --[{type_}]--> {to_id}  (⚠ {to_id} not in collection — run `alit orphans` to review)")
    else:
        print(f"Citation added: {from_id} --[{type_}]--> {to_id}")
    return 0


def _cmd_status(args: argparse.Namespace, conn) -> int:
    paper = get_paper(conn, args.id)
    if paper is None:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1
    if args.new_status in ("read", "skimmed", "synthesized") and not paper.get("pdf_path"):
        force = getattr(args, "force", False)
        if not force:
            print(f"⚠ No PDF for {args.id}. Cannot mark as '{args.new_status}' without reading the full paper.", file=sys.stderr)
            print(f"  Fetch the PDF first:  alit fetch-pdf {args.id}", file=sys.stderr)
            print(f"  Or override with:     alit status {args.id} {args.new_status} --force", file=sys.stderr)
            return 1
    update_paper(conn, args.id, status=args.new_status)
    print(f"(-o+) Status updated: {args.id} → {args.new_status}")
    return 0


def _cmd_tag(args: argparse.Namespace, conn) -> int:
    paper = get_paper(conn, args.id)
    if paper is None:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1
    update_paper(conn, args.id, tags=args.tags)
    print(f"(-o+) Tags updated: {args.id} → {args.tags}")
    return 0


def _cmd_recommend(args: argparse.Namespace, conn) -> int:
    from alit.scripts.recommend import recommend
    from alit.scripts.pagerank import update_pagerank

    citation_count = conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]
    last_pr = conn.execute("SELECT value FROM meta WHERE key='_pagerank_edge_count'").fetchone()
    last_count = int(last_pr["value"]) if last_pr else -1
    if citation_count != last_count:
        update_pagerank(conn)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('_pagerank_edge_count', ?)", (str(citation_count),))
        conn.commit()

    taste_row = conn.execute("SELECT value FROM meta WHERE key='taste'").fetchone()
    taste_keywords: list[str] | None = None
    if taste_row and taste_row["value"]:
        taste_keywords = _extract_taste_keywords(taste_row["value"])

    raw = getattr(args, "n", None)
    try:
        top_k = int(raw) if raw else 10
    except (ValueError, TypeError):
        top_k = 10

    results = recommend(conn, top_k=top_k, taste_keywords=taste_keywords)
    if getattr(args, "json", False):
        print(json.dumps(results, ensure_ascii=False))
        return 0

    if not results:
        print("(xox) No recommendations. All papers read or corpus empty.")
        return 0

    taste_text = taste_row["value"] if taste_row and taste_row["value"] else ""
    compact = getattr(args, "compact", False)

    if taste_text and not compact:
        print(f"Taste: {taste_text[:150]}")
        print()

    for rank, r in enumerate(results, start=1):
        year = r.get("year") or "????"
        score = r.get("score", 0)
        pdf = "📄" if r.get("pdf_path") else "  "
        print(f"  {rank:2d}. [{score:.3f}] {pdf} {r['id']:<38s} ({year}) {(r.get('title') or '')[:50]}")
        if not compact:
            abstract = (r.get("abstract") or "")[:150]
            if abstract:
                print(f"      {abstract}")

    return 0


def _cmd_ask(args: argparse.Namespace, conn) -> int:
    from alit.scripts.synthesize import format_funnel_output, funnel_retrieve

    depth = getattr(args, "depth", 2)
    result = funnel_retrieve(conn, args.question, depth=depth)
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(format_funnel_output(result))
    return 0


def _cmd_stats(args: argparse.Namespace, conn) -> int:
    stats = get_stats(conn)
    if getattr(args, "json", False):
        print(json.dumps(stats, ensure_ascii=False))
    else:
        t = stats["total"]
        print(f"Papers:       {t}")
        print(f"  abstracts:  {stats['with_abstract']}/{t}")
        print(f"  PDFs:       {stats['with_pdf']}/{t}")
        print(f"  L4 summary: {stats['with_l4']}/{t}")
        print(f"  L2 claims:  {stats['with_l2']}/{t}")
        print(f"Citations:    {stats['citations']}", end="")
        if stats.get("orphan_citations"):
            print(f"  ({stats['orphan_citations']} orphan)")
        else:
            print()
        print(f"Taste set:    {'yes' if stats['has_taste'] else 'no'}")
        print("Status:")
        for st, cnt in sorted(stats["by_status"].items()):
            print(f"  {st:15s}: {cnt}")

        missing_pdfs = t - stats["with_pdf"]
        missing_abstracts = t - stats["with_abstract"]
        if missing_pdfs > 0 or missing_abstracts > 0 or not stats["has_taste"]:
            print()
            if missing_pdfs > 0:
                print(f"  → {missing_pdfs} papers missing PDFs. Run: alit fetch-pdfs")
            if missing_abstracts > 0:
                print(f"  → {missing_abstracts} papers missing abstracts. Run: alit enrich")
            if not stats["has_taste"]:
                print(f"  → No taste set. Run: alit taste \"your research interests\"")
    return 0


def _cmd_delete(args: argparse.Namespace, conn) -> int:
    deleted = delete_paper(conn, args.id)
    if deleted:
        print(f"(-o-) Deleted: {args.id}")
        return 0
    else:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1


_BIB_SPECIAL = str.maketrans({"&": r"\&", "%": r"\%", "#": r"\#"})

# Unicode → LaTeX macro mapping for pdflatex compatibility.
_UNICODE_TO_LATEX: dict[str, str] = {
    "à": r"{\`a}", "á": r"{\'a}", "â": r"{\^a}", "ã": r"{\~a}", "ä": r'{\"a}', "å": r"{\aa}",
    "è": r"{\`e}", "é": r"{\'e}", "ê": r"{\^e}", "ë": r'{\"e}',
    "ì": r"{\`i}", "í": r"{\'i}", "î": r"{\^i}", "ï": r'{\"i}',
    "ò": r"{\`o}", "ó": r"{\'o}", "ô": r"{\^o}", "õ": r"{\~o}", "ö": r'{\"o}',
    "ù": r"{\`u}", "ú": r"{\'u}", "û": r"{\^u}", "ü": r'{\"u}',
    "ý": r"{\'y}", "ÿ": r'{\"y}',
    "ñ": r"{\~n}", "ć": r"{\'c}", "č": r"{\v{c}}", "š": r"{\v{s}}", "ž": r"{\v{z}}",
    "ł": r"{\l}", "ß": r"{\ss}",
    "À": r"{\`A}", "Á": r"{\'A}", "Â": r"{\^A}", "Ã": r"{\~A}", "Ä": r'{\"A}',
    "È": r"{\`E}", "É": r"{\'E}", "Ê": r"{\^E}", "Ë": r'{\"E}',
    "Ì": r"{\`I}", "Í": r"{\'I}", "Î": r"{\^I}", "Ï": r'{\"I}',
    "Ò": r"{\`O}", "Ó": r"{\'O}", "Ô": r"{\^O}", "Õ": r"{\~O}", "Ö": r'{\"O}',
    "Ù": r"{\`U}", "Ú": r"{\'U}", "Û": r"{\^U}", "Ü": r'{\"U}',
    "Ý": r"{\'Y}", "Ñ": r"{\~N}", "Ć": r"{\'C}", "Č": r"{\v{C}}", "Š": r"{\v{S}}",
    "Ł": r"{\L}",
}
_UNICODE_TRANS = str.maketrans(_UNICODE_TO_LATEX)


def _bib_escape(text: str) -> str:
    """Escape BibTeX/LaTeX special characters and non-ASCII in text."""
    return text.translate(_BIB_SPECIAL).translate(_UNICODE_TRANS)


_CONFERENCE_KEYWORDS = {
    "iclr", "neurips", "nips", "icml", "cvpr", "iccv", "eccv", "aaai", "ijcai",
    "acl", "emnlp", "naacl", "coling", "sigir", "kdd", "www", "uai", "aistats",
    "colt", "focs", "stoc", "soda", "isit", "interspeech", "icassp", "miccai",
    "wacv", "bmvc", "siggraph", "chi", "uist", "vldb", "sigmod", "icde",
    "conference", "proceedings", "workshop", "symposium",
}


def _bib_entry_type(venue: str) -> tuple[str, str]:
    """Determine BibTeX entry type from venue string.

    Returns (entry_type, venue_field_name) — e.g. ("inproceedings", "booktitle")
    or ("article", "journal").
    """
    if not venue:
        return "article", "journal"
    venue_lower = venue.lower()
    words = set(re.split(r"[\s/()]+", venue_lower))
    if words & _CONFERENCE_KEYWORDS:
        return "inproceedings", "booktitle"
    return "article", "journal"


def _authors_to_bib(authors_db: str) -> str:
    """Convert DB author string to BibTeX author field.

    DB stores authors in mixed formats:
      - 'First Last, First Last'          (comma-separated)
      - 'Last, First; Last, First'         (semicolon-separated)
      - 'First Last et al.'                (et al. shorthand)
    Each name is wrapped in {braces} so BibTeX treats it as a literal,
    avoiding misparse of compound/unicode names.
    """
    s = authors_db.strip()
    if not s:
        return ""
    # Semicolon-separated: split on ';'
    if ";" in s:
        names = [n.strip() for n in s.split(";") if n.strip()]
    # 'et al' without separator: keep as single unit
    elif re.match(r"^[^,]+\bet al\.?$", s):
        return "{" + _bib_escape(s) + "}"
    # Comma-separated 'First Last, First Last':
    # Heuristic: if commas present and no name part looks like 'Last, First'
    # (i.e., parts between commas each have >=2 words), treat as comma-separated list.
    # Otherwise it might be a single 'Last, First' name — keep as-is.
    elif "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        # Single comma with exactly 2 parts where first part is one word:
        # likely 'Last, First' format — keep as single name
        if len(parts) == 2 and len(parts[0].split()) == 1:
            return "{" + _bib_escape(s) + "}"
        names = parts
    else:
        return "{" + _bib_escape(s) + "}"
    # Filter out empty, wrap each, join with ' and '
    return " and ".join("{" + _bib_escape(n) + "}" for n in names if n)


def _bib_authors_to_db(authors_bib: str) -> str:
    """Convert BibTeX author field back to DB format.

    Detects whether names contain internal commas (Last, First style)
    and uses semicolon separator to avoid ambiguity. Otherwise uses commas.
    """
    if not authors_bib:
        return ""
    names = [n.strip().strip("{}") for n in authors_bib.split(" and ")]
    # If any name contains a comma, it's 'Last, First' style — use '; ' separator
    if any("," in n for n in names):
        return "; ".join(names)
    return ", ".join(names)


def _cmd_export(args: argparse.Namespace, conn) -> int:
    fmt = getattr(args, "format", "json") or "json"

    if fmt == "json":
        papers = [dict(r) for r in conn.execute("SELECT * FROM papers ORDER BY year DESC").fetchall()]
        citations = [dict(r) for r in conn.execute("SELECT * FROM citations").fetchall()]
        taste_row = conn.execute("SELECT value FROM meta WHERE key='taste'").fetchone()
        data = {
            "papers": papers,
            "citations": citations,
            "taste": taste_row["value"] if taste_row else "",
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    if fmt == "markdown":
        taste_row = conn.execute("SELECT value FROM meta WHERE key='taste'").fetchone()
        papers = [dict(r) for r in conn.execute("SELECT * FROM papers ORDER BY year DESC").fetchall()]
        stats = get_stats(conn)

        lines = ["# Literature Review", ""]
        if taste_row and taste_row["value"]:
            lines.append(f"> {taste_row['value'][:200]}")
            lines.append("")
        lines.append(f"**{stats['total']} papers** | {stats.get('with_l4', 0)} summarized | {stats['citations']} citations\n")

        for status in ("synthesized", "read", "skimmed", "unread"):
            group = [p for p in papers if p["status"] == status]
            if not group:
                continue
            lines.append(f"## {status.title()} ({len(group)})\n")
            for p in group:
                year = p["year"] or "?"
                line = f"- **{p['title']}** ({year})"
                if p.get("authors"):
                    line += f" — {p['authors'][:50]}"
                lines.append(line)
                if p.get("summary_l4"):
                    lines.append(f"  > {p['summary_l4']}")
                if p.get("tags"):
                    lines.append(f"  Tags: {p['tags']}")
                lines.append("")

        print("\n".join(lines))
        return 0

    if fmt == "bib":
        papers = [dict(r) for r in conn.execute("SELECT * FROM papers ORDER BY year DESC").fetchall()]
        entries = []
        for p in papers:
            key = p["id"].replace("/", "_").replace(":", "_").replace(" ", "_")
            entry_type, venue_field = _bib_entry_type(p.get("venue", ""))
            lines = [f"@{entry_type}{{{key},"]
            lines.append(f"  title = {{{_bib_escape(p['title'])}}},")
            if p.get("authors"):
                lines.append(f"  author = {{{_authors_to_bib(p['authors'])}}},")
            if p.get("year"):
                lines.append(f"  year = {{{p['year']}}},")
            if p.get("doi"):
                lines.append(f"  doi = {{{p['doi']}}},")
            if p.get("url"):
                lines.append(f"  url = {{{p['url']}}},")
            if p.get("venue"):
                lines.append(f"  {venue_field} = {{{_bib_escape(p['venue'])}}},")
            if p.get("arxiv_id"):
                lines.append(f"  eprint = {{{p['arxiv_id']}}},")
                lines.append("  archiveprefix = {arXiv},")
            lines.append("}")
            entries.append("\n".join(lines))
        print("\n\n".join(entries))
        return 0

    print(f"Unknown format: {fmt}. Use --format json, --format markdown, or --format bib", file=sys.stderr)
    return 1


def _cmd_lint(args: argparse.Namespace, conn) -> int:
    """Check the collection for data quality issues."""
    papers = [dict(r) for r in conn.execute("SELECT * FROM papers").fetchall()]
    issues: list[str] = []
    warnings: list[str] = []

    for p in papers:
        pid = p["id"]
        # Truncated authors
        if p.get("authors") and re.search(r"\bet al\.?\s*$", p["authors"]):
            issues.append(f"  [AUTHOR] {pid}: truncated author list ('{p['authors'][:40]}...')")
        # Missing authors
        if not p.get("authors"):
            warnings.append(f"  [AUTHOR] {pid}: no authors")
        # No locator
        has_locator = any(p.get(f) for f in ("url", "doi", "arxiv_id"))
        if not has_locator:
            warnings.append(f"  [LOCATOR] {pid}: no url, doi, or arxiv_id")
        # Missing abstract
        if not p.get("abstract"):
            warnings.append(f"  [ABSTRACT] {pid}: no abstract")
        # Empty venue
        if not p.get("venue"):
            warnings.append(f"  [VENUE] {pid}: no venue")
        # Non-ASCII in authors (pdflatex risk)
        if p.get("authors") and any(ord(c) > 127 for c in p["authors"]):
            chars = sorted(set(c for c in p["authors"] if ord(c) > 127))
            warnings.append(f"  [UNICODE] {pid}: non-ASCII in authors: {''.join(chars)}")
        # Missing PDF
        if not p.get("pdf_path"):
            warnings.append(f"  [PDF] {pid}: no PDF attached")

    # Print report
    total = len(papers)
    n_issues = len(issues)
    n_warnings = len(warnings)

    if issues:
        print(f"\nErrors ({n_issues}):")
        for line in sorted(issues):
            print(line)

    if warnings and not getattr(args, "errors_only", False):
        print(f"\nWarnings ({n_warnings}):")
        for line in sorted(warnings):
            print(line)

    print(f"\nSummary: {total} papers, {n_issues} errors, {n_warnings} warnings")
    if n_issues == 0 and n_warnings == 0:
        print("Collection is clean!")
    return 1 if n_issues > 0 else 0


def _cmd_attach(args: argparse.Namespace, conn) -> int:
    paper = get_paper(conn, args.id)
    if not paper:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1
    src = Path(args.path)
    if not src.exists():
        print(f"File not found: {src}", file=sys.stderr)
        return 1
    db_path = Path(args._db_path) if hasattr(args, "_db_path") else Path.cwd()
    rel = attach_pdf(conn, args.id, src, db_path)
    print(f"Attached: {rel}")
    return 0


def _cmd_orphans(args: argparse.Namespace, conn) -> int:
    orphans = get_orphan_citations(conn)
    if getattr(args, "json", False):
        print(json.dumps(orphans, ensure_ascii=False))
    else:
        if not orphans:
            print("No orphan citations. All cited papers exist in the collection.")
            return 0
        print(f"{len(orphans)} citations reference papers not in the collection:\n")
        for o in orphans:
            print(f"  {o['from_id']} --[{o['type']}]--> {o['to_id']}  (MISSING)")
        print(f"\nTo resolve: look up each missing paper and `alit add` it.")
    return 0


def _cmd_fetch_pdfs(args: argparse.Namespace, conn) -> int:
    db_path = Path(args._db_path) if hasattr(args, "_db_path") else Path.cwd()
    result = fetch_all_pdfs(conn, db_path)
    if result["downloaded"]:
        print(f"(-o+) Downloaded {result['downloaded']}/{result['total']} PDFs")
    else:
        print(f"(-o-) No PDFs to download ({result['total']} candidates)")
    if result.get("errors"):
        for e in result["errors"][:5]:
            print(f"  {e}")
    return 0


def _cmd_attach_dir(args: argparse.Namespace, conn) -> int:
    db_path = Path(args._db_path) if hasattr(args, "_db_path") else Path.cwd()
    dir_path = Path(args.path)
    if not dir_path.is_dir():
        print(f"(xox) Not a directory: {dir_path}", file=sys.stderr)
        return 1
    result = attach_dir(conn, dir_path, db_path)
    print(f"(-o+) Attached {result['attached']} PDFs from {dir_path}")
    return 0


def _cmd_enrich(args: argparse.Namespace, conn) -> int:
    db_path = Path(args._db_path) if hasattr(args, "_db_path") else Path.cwd()
    no_pdf = getattr(args, "no_pdf", False)
    result = enrich_papers(conn, db_path, fetch_pdfs=not no_pdf)
    print(f"\nEnriched {result['enriched']}/{result['total']} papers from arXiv", flush=True)
    if result["errors"]:
        print("Issues:")
        for e in result["errors"]:
            print(f"  {e}")
    return 0


def _cmd_fetch_pdf(args: argparse.Namespace, conn) -> int:
    db_path = Path(args._db_path) if hasattr(args, "_db_path") else Path.cwd()
    paper_id = args.id
    paper = get_paper(conn, paper_id)
    if not paper:
        print(f"Paper not found: {paper_id}", file=sys.stderr)
        return 1
    pdf = fetch_pdf_for_paper(conn, paper_id, db_path)
    if pdf:
        print(f"Downloaded: {pdf}")
    else:
        print(f"No PDF available for {paper_id} (needs --arxiv or --url ending in .pdf)")
    return 0


def _cmd_auto_cite(args: argparse.Namespace, conn) -> int:
    db_path = Path(args._db_path) if hasattr(args, "_db_path") else Path.cwd()
    result = auto_cite_from_pdfs(conn, db_path)
    if result["edges_added"]:
        print(f"(-o+) Scanned {result['scanned']} PDFs, added {result['edges_added']} citation edges")
    else:
        print(f"(-o-) Scanned {result['scanned']} PDFs, no new citations found")
    missing = result.get("missing", [])
    if missing:
        print(f"\nFrequently cited papers not in collection:")
        for arxiv_id, count in missing:
            print(f"  {count}x  arxiv:{arxiv_id}  → alit add \"https://arxiv.org/abs/{arxiv_id}\"")
    return 0


def _cmd_sync(args: argparse.Namespace, conn) -> int:
    source = getattr(args, "source", None)
    if source:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('sync_source', ?)", (source,))
        conn.commit()
        print(f"(-o+) Sync source set: {source}")
        return 0

    row = conn.execute("SELECT value FROM meta WHERE key='sync_source'").fetchone()
    if not row or not row["value"]:
        print("(xox) No sync source set. Use: alit sync --source /path/to/library.bib", file=sys.stderr)
        return 1

    bib_path = Path(row["value"])
    if not bib_path.exists():
        print(f"(xox) Sync source not found: {bib_path}", file=sys.stderr)
        return 1

    args.file = str(bib_path)
    args.bib = True
    result = _cmd_import(args, conn)

    # Auto-regenerate library.bib after sync
    from alit.scripts.db import LIT_DIR
    lib_bib = Path.cwd() / LIT_DIR / "library.bib"
    if lib_bib.exists():
        papers = [dict(r) for r in conn.execute("SELECT * FROM papers ORDER BY year DESC").fetchall()]
        entries = []
        for p in papers:
            key = p["id"].replace("/", "_").replace(":", "_").replace(" ", "_")
            bib_lines = [f"@article{{{key},"]
            bib_lines.append(f"  title = {{{_bib_escape(p['title'])}}},")
            if p.get("authors"):
                bib_lines.append(f"  author = {{{_authors_to_bib(p['authors'])}}},")
            if p.get("year"):
                bib_lines.append(f"  year = {{{p['year']}}},")
            if p.get("venue"):
                bib_lines.append(f"  journal = {{{_bib_escape(p['venue'])}}},")
            if p.get("doi"):
                bib_lines.append(f"  doi = {{{p['doi']}}},")
            if p.get("url"):
                bib_lines.append(f"  url = {{{p['url']}}},")
            if p.get("arxiv_id"):
                bib_lines.append(f"  eprint = {{{p['arxiv_id']}}},")
                bib_lines.append("  archiveprefix = {arXiv},")
            bib_lines.append("}")
            entries.append("\n".join(bib_lines))
        lib_bib.write_text("\n\n".join(entries) + "\n")
        print(f"(-o+) Updated {lib_bib}")

    return result


def _cmd_taste(args: argparse.Namespace, conn) -> int:
    text = getattr(args, "text", None)
    if not text:
        row = conn.execute("SELECT value FROM meta WHERE key='taste'").fetchone()
        if row and row["value"]:
            print(row["value"])
        else:
            print("No taste set. Use: alit taste \"what kind of research excites you\"")
        return 0
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('taste', ?)", (text,))
    conn.commit()
    print(f"(-o+) Taste set ({len(text)} chars)")
    return 0


def _import_bibtex(args: argparse.Namespace, conn, file_path: Path) -> int:
    import re as _re
    from alit.scripts.db import _parse_bibtex, _auto_tag_from_abstract, _sanitize_id

    text = file_path.read_text(encoding="utf-8", errors="replace")
    entries = _parse_bibtex(text)
    if not entries:
        print("No BibTeX entries found.")
        return 0

    db_path = Path(args._db_path) if hasattr(args, "_db_path") else Path.cwd()
    no_pdf = getattr(args, "no_pdf", False)
    added, skipped = 0, 0

    for entry in entries:
        paper_id = _sanitize_id(entry.get("_citekey", ""))
        if not paper_id or get_paper(conn, paper_id):
            skipped += 1
            continue

        title = entry.get("title", "Untitled")
        kwargs: dict = {}
        if entry.get("year"):
            try:
                kwargs["year"] = int(entry["year"])
            except ValueError:
                pass
        if entry.get("author"):
            kwargs["authors"] = _bib_authors_to_db(entry["author"])
        if entry.get("abstract"):
            kwargs["abstract"] = entry["abstract"]
        if entry.get("doi"):
            kwargs["doi"] = entry["doi"]
        if entry.get("url"):
            kwargs["url"] = entry["url"]
        venue = entry.get("journal") or entry.get("booktitle") or ""
        if venue:
            kwargs["venue"] = venue

        arxiv_id = entry.get("eprint", "")
        if not arxiv_id:
            url_val = entry.get("url", "")
            m = _re.search(r"(\d{4}\.\d{4,5})", url_val)
            if m:
                arxiv_id = m.group(1)
        if arxiv_id:
            kwargs["arxiv_id"] = arxiv_id

        auto_tags = _auto_tag_from_abstract(kwargs.get("abstract", ""), title)
        if auto_tags:
            kwargs["tags"] = ",".join(auto_tags)

        add_paper(conn, paper_id, title, **kwargs)

        if arxiv_id and not kwargs.get("abstract"):
            from alit.scripts.db import _enrich_one_arxiv, _enrich_one_s2
            enriched = _enrich_one_arxiv(arxiv_id) or _enrich_one_s2(arxiv_id)
            if enriched:
                update_paper(conn, paper_id, **{k: v for k, v in enriched.items() if k != "title" and v})

        if not no_pdf and arxiv_id:
            fetch_pdf_for_paper(conn, paper_id, db_path)

        added += 1
        print(f"  {paper_id}: {title[:60]}", flush=True)

    print(f"\nImported {added} from BibTeX, skipped {skipped} existing", flush=True)
    return 0


def _cmd_import(args: argparse.Namespace, conn) -> int:
    import time
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        return 1

    is_bib = getattr(args, "bib", False) or file_path.suffix in (".bib", ".bibtex")
    if is_bib:
        return _import_bibtex(args, conn, file_path)

    is_json = getattr(args, "json_import", False) or file_path.suffix == ".json"
    if is_json:
        import json as _json
        from alit.scripts.db import _VALID_PAPER_FIELDS, get_paper as _get_paper
        data = _json.loads(file_path.read_text())
        if not isinstance(data, list):
            print("JSON must be a list of paper objects", file=sys.stderr)
            return 1
        added, skipped = 0, 0
        for entry in data:
            entry_title = entry.get("title", "Untitled")
            paper_id = entry.get("id") or _auto_id(entry_title, conn)
            entry_kwargs = {k: v for k, v in entry.items() if k in _VALID_PAPER_FIELDS and k not in ("id", "title") and v}
            entry_arxiv = entry_kwargs.get("arxiv_id", "")
            already_by_id = _get_paper(conn, paper_id)
            already_by_arxiv = entry_arxiv and conn.execute("SELECT 1 FROM papers WHERE arxiv_id=?", (entry_arxiv,)).fetchone()
            if already_by_id or already_by_arxiv:
                skipped += 1
                continue
            add_paper(conn, paper_id, entry_title, **entry_kwargs)
            added += 1
        print(f"(-o+) Imported {added} from JSON, skipped {skipped} existing", flush=True)
        with_arxiv = conn.execute("SELECT COUNT(*) FROM papers WHERE arxiv_id != '' AND (pdf_path = '' OR pdf_path IS NULL)").fetchone()[0]
        if with_arxiv > 0:
            print(f"  → {with_arxiv} papers have arXiv IDs but no PDFs. Run: alit fetch-pdfs")
        return 0

    from alit.scripts.db import _enrich_batch_arxiv, _enrich_one_s2

    db_path = Path(args._db_path) if hasattr(args, "_db_path") else Path.cwd()
    no_pdf = getattr(args, "no_pdf", False)
    lines = [l.strip() for l in file_path.read_text().splitlines()]
    urls = [l.split()[0] for l in lines if l and not l.startswith("#")]

    to_import: dict[str, str] = {}
    skipped = 0
    errors = []
    for url in urls:
        arxiv_id = _is_arxiv_url(url)
        if not arxiv_id:
            errors.append(f"{url}: not an arXiv URL, skipping")
            continue
        paper_id = f"arxiv_{arxiv_id.replace('.', '_')}"
        if get_paper(conn, paper_id):
            skipped += 1
            continue
        to_import[arxiv_id] = paper_id

    if not to_import:
        print(f"Nothing to import ({skipped} already exist)", flush=True)
        return 0

    print(f"  Batch-fetching {len(to_import)} papers from arXiv...", flush=True)
    batch_results = _enrich_batch_arxiv(list(to_import.keys()))
    time.sleep(3)

    added = 0
    for arxiv_id, paper_id in to_import.items():
        meta = batch_results.get(arxiv_id)
        if meta is None:
            try:
                meta = _enrich_one_s2(arxiv_id)
                time.sleep(1)
            except Exception as e:
                errors.append(f"{arxiv_id}: {e}")
                continue
        if meta is None:
            errors.append(f"{arxiv_id}: not found")
            continue

        title = meta.get("title", f"arXiv:{arxiv_id}")
        kwargs = {k: v for k, v in meta.items() if k != "title" and v}
        kwargs["arxiv_id"] = arxiv_id
        kwargs["url"] = f"https://arxiv.org/abs/{arxiv_id}"
        add_paper(conn, paper_id, title, **kwargs)
        if not no_pdf:
            fetch_pdf_for_paper(conn, paper_id, db_path)
        added += 1
        print(f"  [{added}/{len(to_import)}] {paper_id} ({kwargs.get('year', '?')})", flush=True)

    print(f"\nImported {added}, skipped {skipped} existing, {len(errors)} errors", flush=True)
    for e in errors:
        print(f"  {e}")
    return 0


def _cmd_find(args: argparse.Namespace, conn) -> int:
    import xml.etree.ElementTree as ET
    import urllib.request
    import re as _re
    from urllib.parse import quote as _quote

    query = args.query
    source = getattr(args, "source", "arxiv") or "arxiv"
    limit = getattr(args, "limit", 10) or 10

    if source == "arxiv":
        encoded = _quote(query)
        url = f"https://export.arxiv.org/api/query?search_query=all:{encoded}&start=0&max_results={limit}&sortBy=relevance"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "alit/0.2"})
            resp = urllib.request.urlopen(req, timeout=30)
            xml_data = resp.read().decode("utf-8")
        except Exception as e:
            print(f"Search failed: {e}", file=sys.stderr)
            return 1

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_data)
        entries = root.findall("atom:entry", ns)

        if not entries:
            print("(xox) No results found.")
            return 0

        results = []
        for entry in entries:
            title_el = entry.find("atom:title", ns)
            title = " ".join(title_el.text.strip().split()) if title_el is not None and title_el.text else ""
            if "Error" in title:
                continue
            summary_el = entry.find("atom:summary", ns)
            abstract = " ".join(summary_el.text.strip().split()) if summary_el is not None and summary_el.text else ""
            pub_el = entry.find("atom:published", ns)
            year = int(pub_el.text[:4]) if pub_el is not None and pub_el.text else None
            id_el = entry.find("atom:id", ns)
            entry_url = (id_el.text or "") if id_el is not None else ""
            arxiv_match = _re.search(r"(\d{4}\.\d{4,5})", entry_url)
            arxiv_id = arxiv_match.group(1) if arxiv_match else ""
            author_names = []
            for a in entry.findall("atom:author", ns):
                name_el = a.find("atom:name", ns)
                if name_el is not None and name_el.text:
                    author_names.append(name_el.text)

            existing = None
            if arxiv_id:
                existing = conn.execute("SELECT id FROM papers WHERE arxiv_id = ?", (arxiv_id,)).fetchone()

            results.append({
                "arxiv_id": arxiv_id, "title": title, "year": year,
                "authors": ", ".join(author_names[:3]) + ("..." if len(author_names) > 3 else ""),
                "abstract": abstract[:150], "url": entry_url,
                "in_db": existing is not None,
            })

        if getattr(args, "json", False):
            print(json.dumps(results, ensure_ascii=False))
        else:
            for i, r in enumerate(results, 1):
                marker = " ✓" if r["in_db"] else ""
                first_author = r["authors"].split(",")[0].strip() if r["authors"] else ""
                print(f"  {i:2d}. [{r['year'] or '????'}] {r['title'][:60]} ({first_author}) arxiv:{r['arxiv_id']}{marker}")
            print(f"\nTo add: alit add \"https://arxiv.org/abs/<id>\"")

        if getattr(args, "add", False) and results:
            added = 0
            for r in results:
                if r.get("in_db"):
                    continue
                arxiv_id = r.get("arxiv_id", "")
                if not arxiv_id:
                    continue
                paper_id = f"arxiv_{arxiv_id.replace('.', '_')}"
                add_paper(conn, paper_id, r["title"], arxiv_id=arxiv_id, year=r.get("year"),
                          authors=r.get("authors", ""), abstract=r.get("abstract", ""),
                          url=r.get("url", ""))
                added += 1
            print(f"\n(-o+) Added {added} papers to collection")
    else:
        from alit.scripts.db import _fetch_url
        encoded = _quote(query)
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={encoded}&limit={limit}&fields=title,abstract,year,authors,externalIds,url"
        try:
            data = json.loads(_fetch_url(url).decode("utf-8"))
        except Exception as e:
            print(f"Search failed: {e}", file=sys.stderr)
            return 1

        papers = data.get("data", [])
        if not papers:
            print("(xox) No results found.")
            return 0

        if getattr(args, "json", False):
            print(json.dumps(papers, ensure_ascii=False))
        else:
            for i, p in enumerate(papers, 1):
                ext = p.get("externalIds") or {}
                arxiv_id = ext.get("ArXiv", "")
                year = p.get("year") or "????"
                title = (p.get("title") or "")[:60]
                aid = f" arxiv:{arxiv_id}" if arxiv_id else ""
                print(f"  {i:2d}. [{year}] {title}{aid}")
            print(f"\nTo add: alit add \"https://arxiv.org/abs/<id>\"")
    return 0


def _cmd_read(args: argparse.Namespace, conn) -> int:
    from alit.scripts.db import get_citations
    paper = get_paper(conn, args.id)
    if paper is None:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1

    print(f"{'='*70}")
    print(f"  {paper['title']}")
    print(f"  {paper['authors']} ({paper['year'] or '?'})")
    print(f"  Status: {paper['status']}  |  ID: {paper['id']}")
    pdf = paper.get("pdf_path", "")
    if pdf:
        print(f"  PDF: .alit/{pdf}")
    else:
        print(f"  PDF: ✗ NOT AVAILABLE — fetch before reading: alit fetch-pdf {paper['id']}")
    print(f"{'='*70}")

    if paper.get("abstract"):
        print(f"\nAbstract:\n{paper['abstract']}\n")
    else:
        print("\n(No abstract available. Run: alit enrich)\n")

    if paper.get("summary_l4"):
        print(f"Summary (L4): {paper['summary_l4']}")
        print(f"  — by {paper.get('summary_l4_model', '?')} at {paper.get('summary_l4_at', '?')}")

    if paper.get("summary_l2"):
        print(f"\nKey Claims (L2): {paper['summary_l2']}")

    if paper.get("notes"):
        print(f"\nNotes:\n{paper['notes']}")

    cites = get_citations(conn, args.id)
    if cites["cites"]:
        print(f"\nCites ({len(cites['cites'])}):")
        for c in cites["cites"]:
            cited = get_paper(conn, c["to_id"])
            label = f"{cited['title'][:50]}" if cited else f"{c['to_id']} (not in collection)"
            print(f"  → [{c['type']}] {label}")
    if cites["cited_by"]:
        print(f"\nCited by ({len(cites['cited_by'])}):")
        for c in cites["cited_by"]:
            citer = get_paper(conn, c["from_id"])
            label = f"{citer['title'][:50]}" if citer else c["from_id"]
            print(f"  ← [{c['type']}] {label}")

    return 0


def _cmd_progress(args: argparse.Namespace, conn) -> int:
    stats = get_stats(conn)
    total = stats["total"]
    if total == 0:
        print("(xox) No papers yet. Run: alit add \"https://arxiv.org/abs/...\"")
        return 0

    if getattr(args, "json", False):
        print(json.dumps(stats, ensure_ascii=False))
        return 0

    by_status = stats.get("by_status", {})
    read_count = by_status.get("read", 0) + by_status.get("synthesized", 0)
    skimmed = by_status.get("skimmed", 0)
    unread = by_status.get("unread", 0)

    def bar(done: int, tot: int, width: int = 30) -> str:
        if tot == 0:
            return "[" + " " * width + "]"
        filled = int(width * done / tot)
        return "[" + "█" * filled + "░" * (width - filled) + "]"

    print(f"Literature Review Progress\n")
    print(f"  Papers:     {bar(total, total)} {total}")
    print(f"  Read:       {bar(read_count, total)} {read_count}/{total}")
    print(f"  Skimmed:    {bar(skimmed, total)} {skimmed}/{total}")
    print(f"  Unread:     {bar(unread, total)} {unread}/{total}")
    print(f"  Abstracts:  {bar(stats['with_abstract'], total)} {stats['with_abstract']}/{total}")
    print(f"  PDFs:       {bar(stats['with_pdf'], total)} {stats['with_pdf']}/{total}")
    print(f"  Summarized: {bar(stats['with_l4'], total)} {stats['with_l4']}/{total}")
    print(f"  Citations:  {stats['citations']}", end="")
    if stats.get("orphan_citations"):
        print(f" ({stats['orphan_citations']} orphan)")
    else:
        print()
    if stats.get("has_taste"):
        print(f"  Taste:      ✓ set")
    else:
        print(f"  Taste:      ✗ not set (run: alit taste \"what excites you\")")
    return 0


def _cmd_dedup(args: argparse.Namespace, conn) -> int:
    from alit.scripts.db import _VALID_PAPER_FIELDS

    dupes = conn.execute("""
        SELECT arxiv_id, GROUP_CONCAT(id) as ids, COUNT(*) as cnt
        FROM papers WHERE arxiv_id != '' AND arxiv_id IS NOT NULL
        GROUP BY arxiv_id HAVING cnt > 1
    """).fetchall()

    if not dupes:
        print("(-o-) No duplicates found")
        return 0

    print(f"Found {len(dupes)} duplicate groups:\n")
    for d in dupes:
        ids = d["ids"].split(",")
        print(f"  arxiv:{d['arxiv_id']}:")
        for pid in ids:
            paper = get_paper(conn, pid)
            if paper:
                has_summary = "✓" if paper.get("summary_l4") else " "
                has_pdf = "📄" if paper.get("pdf_path") else "  "
                print(f"    {has_pdf}{has_summary} {pid}: {(paper.get('title') or '')[:50]}")

    if getattr(args, "merge", False):
        merged = 0
        for d in dupes:
            ids = d["ids"].split(",")
            papers = [get_paper(conn, pid) for pid in ids]
            papers = [p for p in papers if p]
            if len(papers) < 2:
                continue

            def richness(p: dict) -> int:
                return sum(1 for field in ("abstract", "summary_l4", "summary_l2", "notes", "pdf_path", "authors") if p.get(field))

            papers.sort(key=richness, reverse=True)
            keeper = papers[0]

            for other in papers[1:]:
                for field in _VALID_PAPER_FIELDS:
                    if not keeper.get(field) and other.get(field):
                        update_paper(conn, keeper["id"], **{field: other[field]})
                conn.execute("UPDATE OR IGNORE citations SET from_id = ? WHERE from_id = ?", (keeper["id"], other["id"]))
                conn.execute("UPDATE OR IGNORE citations SET to_id = ? WHERE to_id = ?", (keeper["id"], other["id"]))
                delete_paper(conn, other["id"])
                merged += 1

        print(f"\n(-o+) Merged {merged} duplicates")
    else:
        print(f"\nRun alit dedup --merge to auto-merge (keeps richest record)")
    return 0


def _cmd_install_skill(args: argparse.Namespace) -> int:
    import shutil

    skill_src = Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"
    if not skill_src.exists():
        print(f"Error: SKILL.md not found at {skill_src}", file=sys.stderr)
        return 1

    use_global = getattr(args, "global_install", False)
    if use_global:
        targets = [
            Path.home() / ".claude" / "skills" / "alit",
            Path.home() / ".agents" / "skills" / "alit",
        ]
    else:
        targets = [
            Path.cwd() / ".claude" / "skills" / "alit",
        ]

    for dest in targets:
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_src, dest / "SKILL.md")
        print(f"  → {dest / 'SKILL.md'}")
    return 0


# ── Parser ─────────────────────────────────────────────────────────────────────


_skill_checked = False


def _check_skill_version() -> None:
    global _skill_checked
    if _skill_checked:
        return
    _skill_checked = True

    pkg_skill = Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"
    if not pkg_skill.exists():
        return
    pkg_version = _read_skill_version(pkg_skill)
    if not pkg_version:
        return

    targets = [
        Path.cwd() / ".claude" / "skills" / "alit",
        Path.home() / ".claude" / "skills" / "alit",
        Path.home() / ".agents" / "skills" / "alit",
    ]
    any_installed = False
    for skill_dir in targets:
        installed = skill_dir / "SKILL.md"
        if installed.exists():
            any_installed = True
            installed_version = _read_skill_version(installed)
            if installed_version and installed_version != pkg_version:
                print(f"(-o-) Skill outdated ({installed_version} → {pkg_version}). Run: alit install-skill", file=sys.stderr)
            break

    if not any_installed:
        import shutil
        for dest in targets:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(pkg_skill), str(dest / "SKILL.md"))
        print("(-o+) Skill auto-installed for your coding agent", file=sys.stderr)


def _read_skill_version(path: Path) -> str:
    import re
    try:
        text = path.read_text(encoding="utf-8")[:500]
        m = re.search(r'^version:\s*["\']?([^"\'"\n]+)', text, re.MULTILINE)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alit",
        description="Lightweight literature review CLI. SQLite-only, zero dependencies.",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")

    sub = parser.add_subparsers(dest="cmd", metavar="COMMAND")
    sub.required = False

    # init
    p = sub.add_parser("init", help="Create papers.db in current directory")
    p.add_argument("--path", default=None, help="Target directory (default: .)")

    # add
    p = sub.add_parser("add", help="Add a paper")
    p.add_argument("title", help="Paper title")
    p.add_argument("--id", dest="id", default=None, help="Paper ID (auto-generated if omitted)")
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--authors", default=None)
    p.add_argument("--abstract", default=None)
    p.add_argument("--url", default=None)
    p.add_argument("--arxiv", default=None, dest="arxiv")
    p.add_argument("--doi", default=None)
    p.add_argument("--tags", default=None)
    p.add_argument("--pdf", default=None, help="Path to local PDF file")
    p.add_argument("--no-pdf", action="store_true", help="Skip PDF download")
    p.add_argument("--no-enrich", action="store_true", help="Skip metadata fetch (just store URL + arxiv_id)")

    # show
    p = sub.add_parser("show", help="Show paper details")
    p.add_argument("id", help="Paper ID")

    # list
    p = sub.add_parser("list", help="List papers")
    p.add_argument("--status", default=None, help="Filter by status")
    p.add_argument("--tag", default=None, help="Filter by tag")
    p.add_argument("--all", action="store_true", help="Show all (default: 20)")

    # search
    p = sub.add_parser("search", help="BM25 full-text search")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=10, dest="top_k")

    # note
    p = sub.add_parser("note", help="Append note to a paper")
    p.add_argument("id", help="Paper ID")
    p.add_argument("text", help="Note text")

    # summarize
    p = sub.add_parser("summarize", help="Store a summary with provenance")
    p.add_argument("id", help="Paper ID")
    p.add_argument("--l4", default=None, help="One-line summary (L4)")
    p.add_argument("--l2", nargs="*", default=None, help="Key claims (space-separated strings, or single JSON array for backward compat)")
    p.add_argument("--model", default="", help="Model name for provenance")
    p.add_argument("--force", action="store_true", help="Allow summarizing without PDF")

    # cite
    p = sub.add_parser("cite", help="Add citation edge")
    p.add_argument("from_id", nargs="?", default=None, help="Citing paper ID")
    p.add_argument("to_id", nargs="?", default=None, help="Cited paper ID")
    p.add_argument("--type", default="cites", dest="type",
                   choices=["cites", "extends", "contradicts", "uses_method", "uses_dataset", "surveys"])
    p.add_argument("--batch", default=None, help="JSON file of citation edges")

    # status
    p = sub.add_parser("status", help="Set reading status")
    p.add_argument("id", help="Paper ID")
    p.add_argument("new_status", help="New status (unread/skimmed/read/synthesized)")
    p.add_argument("--force", action="store_true", help="Allow status change without PDF")

    # auto-cite
    sub.add_parser("auto-cite", help="Extract citations from PDFs and build citation graph")

    # tag
    p = sub.add_parser("tag", help="Set tags on a paper")
    p.add_argument("id", help="Paper ID")
    p.add_argument("tags", help="Comma-separated tags")

    # sync
    p = sub.add_parser("sync", help="Import from a remembered BibTeX source")
    p.add_argument("--source", default=None, help="Set the .bib file path (remembered for future runs)")
    p.add_argument("--no-pdf", action="store_true", help="Skip PDF downloads")

    # recommend
    p = sub.add_parser("recommend", help="Reading recommendations")
    p.add_argument("n", nargs="?", default=None, help="Number of results (default: 10)")
    p.add_argument("--compact", "-c", action="store_true", help="IDs and titles only, no abstracts")

    # ask
    p = sub.add_parser("ask", help="Cross-paper synthesis")
    p.add_argument("question", help="Research question")
    p.add_argument("--depth", type=int, default=2, choices=[1, 2, 3, 4])

    # stats
    sub.add_parser("stats", help="Collection overview")

    # delete
    p = sub.add_parser("delete", help="Remove a paper")
    p.add_argument("id", help="Paper ID")

    # taste
    p = sub.add_parser("taste", help="Set or show your research taste")
    p.add_argument("text", nargs="?", default=None, help="What kind of research excites you (omit to show current)")

    # attach
    p = sub.add_parser("attach", help="Attach a local PDF to a paper")
    p.add_argument("id", help="Paper ID")
    p.add_argument("path", help="Path to PDF file")

    # enrich
    p = sub.add_parser("enrich", help="Batch-fetch metadata from arXiv for papers missing abstracts")
    p.add_argument("--no-pdf", action="store_true", help="Skip PDF downloads")

    # orphans
    sub.add_parser("orphans", help="List citations pointing to papers not in collection")

    # fetch-pdf
    p = sub.add_parser("fetch-pdf", help="Download PDF for a single paper")
    p.add_argument("id", help="Paper ID")

    # fetch-pdfs
    sub.add_parser("fetch-pdfs", help="Batch-download PDFs for all papers missing them")

    # attach-dir
    p = sub.add_parser("attach-dir", help="Scan a directory and attach PDFs to matching papers")
    p.add_argument("path", help="Directory containing PDF files")

    # import
    p = sub.add_parser("import", help="Bulk-add papers from URL file, BibTeX, or JSON")
    p.add_argument("file", help="Text file (arXiv URLs), .bib file (BibTeX), or .json file")
    p.add_argument("--bib", action="store_true", help="Force BibTeX parsing (auto-detected for .bib files)")
    p.add_argument("--json", action="store_true", dest="json_import", help="Force JSON parsing (auto-detected for .json files)")
    p.add_argument("--no-pdf", action="store_true", help="Skip PDF downloads")

    # export (updated to support --format)
    p = sub.add_parser("export", help="Export collection as JSON or markdown")
    p.add_argument("--format", choices=["json", "markdown", "bib"], default="json", dest="format",
                   help="Output format (default: json)")

    # find
    p = sub.add_parser("find", help="Search arXiv/S2 for papers by topic")
    p.add_argument("query", help="Search query")
    p.add_argument("--source", choices=["arxiv", "s2"], default="arxiv")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--add", action="store_true", help="Auto-add found papers to collection")

    # read
    p = sub.add_parser("read", help="Guided reading view for a paper")
    p.add_argument("id", help="Paper ID")

    # progress
    sub.add_parser("progress", help="Visual progress dashboard")

    # lint
    p = sub.add_parser("lint", help="Check collection for data quality issues")
    p.add_argument("--errors-only", action="store_true", dest="errors_only",
                   help="Only show errors, suppress warnings")

    # dedup
    p = sub.add_parser("dedup", help="Find and merge duplicate papers")
    p.add_argument("--merge", action="store_true", help="Auto-merge duplicates (keeps richest record)")

    # install-skill
    p = sub.add_parser("install-skill", help="Install SKILL.md for agent integration")
    p.add_argument("--global", action="store_true", dest="global_install",
                   help="Install globally (~/.claude/skills/) instead of project-local (.claude/skills/)")

    return parser


# ── Dispatch ───────────────────────────────────────────────────────────────────

HANDLERS = {
    "add": _cmd_add,
    "show": _cmd_show,
    "list": _cmd_list,
    "search": _cmd_search,
    "note": _cmd_note,
    "summarize": _cmd_summarize,
    "cite": _cmd_cite,
    "status": _cmd_status,
    "tag": _cmd_tag,
    "recommend": _cmd_recommend,
    "ask": _cmd_ask,
    "stats": _cmd_stats,
    "delete": _cmd_delete,
    "export": _cmd_export,
    "taste": _cmd_taste,
    "sync": _cmd_sync,
    "auto-cite": _cmd_auto_cite,
    "fetch-pdfs": _cmd_fetch_pdfs,
    "attach-dir": _cmd_attach_dir,
    "fetch-pdf": _cmd_fetch_pdf,
    "attach": _cmd_attach,
    "orphans": _cmd_orphans,
    "enrich": _cmd_enrich,
    "import": _cmd_import,
    "find": _cmd_find,
    "read": _cmd_read,
    "progress": _cmd_progress,
    "lint": _cmd_lint,
    "dedup": _cmd_dedup,
}


def run(argv: list[str] | None = None, *, root: str | Path | None = None) -> int:
    """Run the lit CLI.

    Args:
        argv: Command-line arguments (default: sys.argv[1:]).
        root: Path containing papers.db; overrides auto-detection.

    Returns:
        Exit code (0 = success).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    cmd = getattr(args, "cmd", None)

    _check_skill_version()

    if cmd == "init":
        return _cmd_init(args)
    if cmd == "install-skill":
        return _cmd_install_skill(args)
    if cmd is None:
        parser.print_help()
        return 0

    # All other commands need papers.db
    from alit.scripts.db import LIT_DIR
    db_path = Path(root) if root else Path.cwd()
    new_db = db_path / LIT_DIR / DB_NAME
    old_db = db_path / DB_NAME
    if not new_db.exists() and not old_db.exists():
        print("(xox) Not initialized. Run 'alit init' first.", file=sys.stderr)
        return 1

    conn = get_db(db_path)
    args._db_path = str(db_path)
    try:
        handler = HANDLERS.get(cmd)
        if handler is None:
            parser.print_help()
            return 1
        return handler(args, conn)
    finally:
        conn.close()


def main() -> None:
    """Entry point for the lit CLI."""
    sys.exit(run())


if __name__ == "__main__":
    main()
