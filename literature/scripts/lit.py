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
import sys
from pathlib import Path

from literature.scripts.db import DB_NAME, add_citation, add_paper, attach_pdf
from literature.scripts.db import delete_paper, enrich_papers
from literature.scripts.db import fetch_pdf_for_paper, get_db
from literature.scripts.db import get_orphan_citations, get_paper, get_stats
from literature.scripts.db import init_db, list_papers, update_paper


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
    from literature.scripts.db import LIT_DIR
    target = Path(getattr(args, "path", None) or ".")
    target.mkdir(parents=True, exist_ok=True)
    db_path = target / LIT_DIR / DB_NAME
    if db_path.exists():
        print(f"Already initialized at {target / LIT_DIR}")
        return 0
    conn = init_db(target)
    conn.close()
    print(f"Initialized {target / LIT_DIR}/")
    print()
    print("Next steps:")
    print('  alit add "Paper Title" --year 2024 --abstract "..."')
    print('  alit search "topic"')
    print("  alit recommend 5")
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


def _extract_purpose_keywords(text: str) -> list[str]:
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

    if arxiv and not kwargs.get("abstract"):
        from literature.scripts.db import _enrich_one_arxiv, _enrich_one_s2
        enriched = _enrich_one_arxiv(arxiv) or _enrich_one_s2(arxiv)
        if enriched:
            if enriched.get("title") and title.startswith("arXiv:"):
                title = enriched["title"]
            kwargs.update({k: v for k, v in enriched.items() if v and k != "title"})

    paper = add_paper(conn, paper_id, title, **kwargs)

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
    elif not no_pdf:
        pdf = fetch_pdf_for_paper(conn, paper_id, db_path)
        if pdf:
            paper = get_paper(conn, paper_id)

    if getattr(args, "json", False):
        print(json.dumps(paper, ensure_ascii=False))
    else:
        pdf_msg = f" | pdf: {paper.get('pdf_path')}" if paper.get("pdf_path") else ""
        print(f"Added: {paper_id}{pdf_msg}")
    return 0


def _cmd_show(args: argparse.Namespace, conn) -> int:
    paper = get_paper(conn, args.id)
    if paper is None:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        from literature.scripts.db import get_citations
        cites = get_citations(conn, args.id)
        print(json.dumps({**paper, "citations": cites}, ensure_ascii=False))
    else:
        from literature.scripts.db import get_citations
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
    papers = list_papers(conn, status=status)
    if tag:
        papers = [p for p in papers if tag in (p.get("tags") or "")]
    if getattr(args, "json", False):
        print(json.dumps(papers, ensure_ascii=False))
    else:
        if not papers:
            print("No papers found.")
        for p in papers:
            year = p["year"] or "????"
            st = (p["status"] or "unread")[:8]
            pdf = "📄" if p.get("pdf_path") else "  "
            l4 = "✓" if p.get("summary_l4") else " "
            print(f"[{st:8s}] {pdf}{l4} {p['id']:<38s} ({year})  {(p['title'] or '')[:55]}")
    return 0


def _cmd_search(args: argparse.Namespace, conn) -> int:
    from literature.scripts.search import search

    top_k = getattr(args, "top_k", 20)
    results = search(conn, args.query, top_k=top_k)
    if getattr(args, "json", False):
        print(json.dumps(results, ensure_ascii=False))
    else:
        if not results:
            print("No results found.")
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
    print(f"Note added to {args.id}")
    return 0


def _cmd_summarize(args: argparse.Namespace, conn) -> int:
    paper = get_paper(conn, args.id)
    if paper is None:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1

    model = getattr(args, "model", "") or ""
    l4 = getattr(args, "l4", None)
    l2 = getattr(args, "l2", None)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    kwargs: dict = {}
    if l4 is not None:
        kwargs["summary_l4"] = l4
        kwargs["summary_l4_model"] = model
        kwargs["summary_l4_at"] = now
    if l2 is not None:
        kwargs["summary_l2"] = l2
        kwargs["summary_l2_model"] = model
        kwargs["summary_l2_at"] = now

    if not kwargs:
        print("Error: provide --l4 or --l2", file=sys.stderr)
        return 1

    paper = update_paper(conn, args.id, **kwargs)
    if getattr(args, "json", False):
        print(json.dumps(paper, ensure_ascii=False))
    else:
        level = "l4" if l4 is not None else "l2"
        print(f"Summary ({level}) stored for {args.id}")
    return 0


def _cmd_cite(args: argparse.Namespace, conn) -> int:
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
    update_paper(conn, args.id, status=args.new_status)
    print(f"Status updated: {args.id} → {args.new_status}")
    return 0


def _cmd_tag(args: argparse.Namespace, conn) -> int:
    paper = get_paper(conn, args.id)
    if paper is None:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1
    update_paper(conn, args.id, tags=args.tags)
    print(f"Tags updated: {args.id} → {args.tags}")
    return 0


def _cmd_recommend(args: argparse.Namespace, conn) -> int:
    from literature.scripts.recommend import recommend
    from literature.scripts.pagerank import update_pagerank

    citation_count = conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]
    last_pr = conn.execute("SELECT value FROM meta WHERE key='_pagerank_edge_count'").fetchone()
    last_count = int(last_pr["value"]) if last_pr else -1
    if citation_count != last_count:
        update_pagerank(conn)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('_pagerank_edge_count', ?)", (str(citation_count),))
        conn.commit()

    purpose_row = conn.execute("SELECT value FROM meta WHERE key='purpose'").fetchone()
    purpose_keywords: list[str] | None = None
    if purpose_row and purpose_row["value"]:
        purpose_keywords = _extract_purpose_keywords(purpose_row["value"])

    raw = getattr(args, "n", None)
    try:
        top_k = int(raw) if raw else 10
    except (ValueError, TypeError):
        top_k = 10
    batch_size = getattr(args, "batch", 5) or 5

    results = recommend(conn, top_k=top_k, purpose_keywords=purpose_keywords)
    if getattr(args, "json", False):
        print(json.dumps(results, ensure_ascii=False))
        return 0

    if not results:
        print("No recommendations. All papers read or corpus empty.")
        return 0

    total_unread = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE status NOT IN ('read', 'synthesized')"
    ).fetchone()[0]

    has_purpose = bool(purpose_keywords)
    if has_purpose:
        print(f"Reading Queue — {len(results)} of {total_unread} unread | scoring: 40% relevance + 30% pagerank + 30% recency\n")
    else:
        print(f"Reading Queue — {len(results)} of {total_unread} unread | scoring: 50% pagerank + 50% recency (set purpose for relevance)\n")

    for batch_idx in range(0, len(results), batch_size):
        batch = results[batch_idx:batch_idx + batch_size]
        batch_num = batch_idx // batch_size + 1
        print(f"── Batch {batch_num} ──")
        for rank, r in enumerate(batch, start=batch_idx + 1):
            year = r.get("year") or "????"
            score = r.get("score", 0)
            bd = r.get("breakdown", {})
            pdf = "📄" if r.get("pdf_path") else "  "
            status = (r.get("status") or "unread")[:4]
            print(f"  {rank:2d}. [{score:.3f}] {pdf} {r['id']:<38s} ({year}) {(r.get('title') or '')[:50]}")
            parts = []
            if bd.get("relevance", 0) > 0:
                parts.append(f"rel={bd['relevance']:.2f}")
            if bd.get("pagerank", 0) > 0:
                parts.append(f"pr={bd['pagerank']:.2f}")
            if bd.get("recency", 0) > 0:
                parts.append(f"rec={bd['recency']:.2f}")
            if parts:
                print(f"              {' | '.join(parts)}")
        print()

    return 0


def _cmd_ask(args: argparse.Namespace, conn) -> int:
    from literature.scripts.synthesize import format_funnel_output, funnel_retrieve

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
        print(f"Purpose set:  {'yes' if stats['has_purpose'] else 'no'}")
        print("Status:")
        for st, cnt in sorted(stats["by_status"].items()):
            print(f"  {st:15s}: {cnt}")
    return 0


def _cmd_delete(args: argparse.Namespace, conn) -> int:
    deleted = delete_paper(conn, args.id)
    if deleted:
        print(f"Deleted: {args.id}")
        return 0
    else:
        print(f"Paper not found: {args.id}", file=sys.stderr)
        return 1


def _cmd_export(args: argparse.Namespace, conn) -> int:
    papers = [dict(r) for r in conn.execute("SELECT * FROM papers ORDER BY year DESC").fetchall()]
    citations = [dict(r) for r in conn.execute("SELECT * FROM citations").fetchall()]
    purpose_row = conn.execute("SELECT value FROM meta WHERE key='purpose'").fetchone()
    data = {
        "papers": papers,
        "citations": citations,
        "purpose": purpose_row["value"] if purpose_row else "",
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


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
        print(f"\nTo resolve: look up each missing paper and `lit add` it.")
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


def _cmd_purpose(args: argparse.Namespace, conn) -> int:
    text = getattr(args, "text", None)
    if not text:
        row = conn.execute("SELECT value FROM meta WHERE key='purpose'").fetchone()
        if row and row["value"]:
            print(row["value"])
        else:
            print("No purpose set. Use: alit purpose \"your research goals here\"")
        return 0
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('purpose', ?)", (text,))
    conn.commit()
    print(f"Purpose set ({len(text)} chars)")
    return 0


def _cmd_import(args: argparse.Namespace, conn) -> int:
    import time
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        return 1

    db_path = Path(args._db_path) if hasattr(args, "_db_path") else Path.cwd()
    no_pdf = getattr(args, "no_pdf", False)
    lines = [l.strip() for l in file_path.read_text().splitlines()]
    urls = [l.split()[0] for l in lines if l and not l.startswith("#")]

    added, skipped, errors = 0, 0, []
    for i, url in enumerate(urls):
        arxiv_id = _is_arxiv_url(url)
        if not arxiv_id:
            errors.append(f"{url}: not an arXiv URL, skipping")
            continue

        paper_id = f"arxiv_{arxiv_id.replace('.', '_')}"
        if get_paper(conn, paper_id):
            skipped += 1
            continue

        try:
            from literature.scripts.db import _enrich_one_arxiv, _enrich_one_s2
            meta = _enrich_one_arxiv(arxiv_id) or _enrich_one_s2(arxiv_id)
            title = (meta or {}).get("title", f"arXiv:{arxiv_id}")
            kwargs = {k: v for k, v in (meta or {}).items() if k != "title"}
            kwargs["arxiv_id"] = arxiv_id
            kwargs["url"] = f"https://arxiv.org/abs/{arxiv_id}"

            add_paper(conn, paper_id, title, **kwargs)
            if not no_pdf:
                fetch_pdf_for_paper(conn, paper_id, db_path)

            added += 1
            year = kwargs.get("year", "?")
            print(f"  [{i+1}/{len(urls)}] {paper_id} ({year})", flush=True)
        except Exception as e:
            errors.append(f"{arxiv_id}: {e}")

        time.sleep(3)

    print(f"\nImported {added}, skipped {skipped} existing, {len(errors)} errors", flush=True)
    for e in errors:
        print(f"  {e}")
    return 0


def _cmd_install_skill(args: argparse.Namespace) -> int:
    import shutil

    skill_src = Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"
    if not skill_src.exists():
        print(f"Error: SKILL.md not found at {skill_src}", file=sys.stderr)
        return 1
    skill_dest = Path.home() / ".agents" / "skills" / "literature-review"
    skill_dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(skill_src, skill_dest / "SKILL.md")
    print(f"Installed SKILL.md to {skill_dest / 'SKILL.md'}")
    return 0


# ── Parser ─────────────────────────────────────────────────────────────────────


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

    # show
    p = sub.add_parser("show", help="Show paper details")
    p.add_argument("id", help="Paper ID")

    # list
    p = sub.add_parser("list", help="List papers")
    p.add_argument("--status", default=None, help="Filter by status")
    p.add_argument("--tag", default=None, help="Filter by tag")

    # search
    p = sub.add_parser("search", help="BM25 full-text search")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=20, dest="top_k")

    # note
    p = sub.add_parser("note", help="Append note to a paper")
    p.add_argument("id", help="Paper ID")
    p.add_argument("text", help="Note text")

    # summarize
    p = sub.add_parser("summarize", help="Store a summary with provenance")
    p.add_argument("id", help="Paper ID")
    p.add_argument("--l4", default=None, help="One-line summary (L4)")
    p.add_argument("--l2", default=None, help="Key claims JSON string (L2)")
    p.add_argument("--model", default="", help="Model name for provenance")

    # cite
    p = sub.add_parser("cite", help="Add citation edge")
    p.add_argument("from_id", help="Citing paper ID")
    p.add_argument("to_id", help="Cited paper ID")
    p.add_argument("--type", default="cites", dest="type",
                   choices=["cites", "extends", "contradicts", "uses_method", "uses_dataset", "surveys"])

    # status
    p = sub.add_parser("status", help="Set reading status")
    p.add_argument("id", help="Paper ID")
    p.add_argument("new_status", help="New status (unread/skimmed/read/synthesized)")

    # tag
    p = sub.add_parser("tag", help="Set tags on a paper")
    p.add_argument("id", help="Paper ID")
    p.add_argument("tags", help="Comma-separated tags")

    # recommend
    p = sub.add_parser("recommend", help="Reading recommendations")
    p.add_argument("n", nargs="?", default=None, help="Number of results (default: 10)")
    p.add_argument("--batch", type=int, default=5, help="Papers per batch (default: 5)")

    # ask
    p = sub.add_parser("ask", help="Cross-paper synthesis")
    p.add_argument("question", help="Research question")
    p.add_argument("--depth", type=int, default=2, choices=[1, 2, 3, 4])

    # stats
    sub.add_parser("stats", help="Collection overview")

    # delete
    p = sub.add_parser("delete", help="Remove a paper")
    p.add_argument("id", help="Paper ID")

    # export
    sub.add_parser("export", help="Export collection as JSON")

    # purpose
    p = sub.add_parser("purpose", help="Set or show research purpose")
    p.add_argument("text", nargs="?", default=None, help="Purpose text (omit to show current)")

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
    p = sub.add_parser("fetch-pdf", help="Download PDF for a paper")
    p.add_argument("id", help="Paper ID")

    # import
    p = sub.add_parser("import", help="Bulk-add papers from a file of arXiv URLs")
    p.add_argument("file", help="Text file with one arXiv URL per line (# comments ignored)")
    p.add_argument("--no-pdf", action="store_true", help="Skip PDF downloads")

    # install-skill
    sub.add_parser("install-skill", help="Install SKILL.md for agent integration")

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
    "purpose": _cmd_purpose,
    "fetch-pdf": _cmd_fetch_pdf,
    "attach": _cmd_attach,
    "orphans": _cmd_orphans,
    "enrich": _cmd_enrich,
    "import": _cmd_import,
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

    # These don't need an existing DB
    if cmd == "init":
        return _cmd_init(args)
    if cmd == "install-skill":
        return _cmd_install_skill(args)
    if cmd is None:
        parser.print_help()
        return 0

    # All other commands need papers.db
    from literature.scripts.db import LIT_DIR
    db_path = Path(root) if root else Path.cwd()
    new_db = db_path / LIT_DIR / DB_NAME
    old_db = db_path / DB_NAME
    if not new_db.exists() and not old_db.exists():
        print("Not initialized. Run 'alit init' first.", file=sys.stderr)
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
