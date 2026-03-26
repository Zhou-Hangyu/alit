from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

from alit.scripts.db import (
    add_citation,
    add_paper,
    delete_paper,
    get_citations,
    get_paper,
    get_stats,
    init_db,
    list_papers,
    update_paper,
)
from alit.scripts.pagerank import compute_pagerank, update_pagerank
from alit.scripts.recommend import recommend
from alit.scripts.search import search
from alit.scripts.synthesize import funnel_retrieve


@pytest.fixture
def db(tmp_path):
    conn = init_db(tmp_path)
    yield conn
    conn.close()


def test_init_creates_db(tmp_path):
    conn = init_db(tmp_path)
    conn.close()
    assert (tmp_path / ".alit" / "papers.db").exists()


def test_add_paper(db):
    paper = add_paper(
        db,
        "vaswani2017attention",
        "Attention Is All You Need",
        year=2017,
        authors="Vaswani, Shazeer",
        abstract="The dominant sequence transduction models...",
        url="https://arxiv.org/abs/1706.03762",
        arxiv_id="1706.03762",
        tags="transformers,attention,nlp",
    )
    assert paper["id"] == "vaswani2017attention"
    assert paper["title"] == "Attention Is All You Need"
    assert paper["year"] == 2017
    assert paper["authors"] == "Vaswani, Shazeer"
    assert paper["arxiv_id"] == "1706.03762"
    assert paper["tags"] == "transformers,attention,nlp"
    assert paper["status"] == "unread"


def test_add_paper_auto_id(tmp_path):
    from alit.scripts.lit import _auto_id

    auto_id = _auto_id("Attention Is All You Need")
    assert auto_id != ""
    assert " " not in auto_id

    conn = init_db(tmp_path)
    paper = add_paper(conn, auto_id, "Attention Is All You Need", year=2017)
    assert paper["id"] == auto_id
    conn.close()


def test_show_paper(db):
    add_paper(db, "p1", "Test Paper", year=2020, abstract="Abstract text")
    paper = get_paper(db, "p1")
    assert paper is not None
    assert paper["title"] == "Test Paper"
    assert paper["year"] == 2020
    assert paper["abstract"] == "Abstract text"


def test_list_papers(db):
    add_paper(db, "p1", "Paper One", year=2020, status="unread")
    add_paper(db, "p2", "Paper Two", year=2021, status="read")

    all_papers = list_papers(db)
    assert len(all_papers) == 2

    unread = list_papers(db, status="unread")
    assert len(unread) == 1
    assert unread[0]["id"] == "p1"

    read = list_papers(db, status="read")
    assert len(read) == 1
    assert read[0]["id"] == "p2"


def test_search_finds_paper(db):
    add_paper(db, "att2017", "Attention Is All You Need", year=2017,
              abstract="Self-attention mechanism for sequence transduction")
    results = search(db, "attention", top_k=10)
    assert len(results) > 0
    ids = [r["id"] for r in results]
    assert "att2017" in ids


def test_search_no_results(db):
    add_paper(db, "p1", "Some Paper", year=2020, abstract="Some abstract")
    results = search(db, "xyzzy_nonexistent_token_99", top_k=10)
    assert results == []


def test_search_hyphenated(db):
    add_paper(db, "selfattn", "Self-Attention Networks", year=2019,
              abstract="We propose self-attention as the core component")
    results = search(db, "self-attention", top_k=10)
    assert len(results) > 0
    assert results[0]["id"] == "selfattn"


def test_note_appends(db):
    add_paper(db, "p1", "Test Paper")
    update_paper(db, "p1", notes="First note")
    paper = get_paper(db, "p1")
    assert paper is not None
    assert "First note" in paper["notes"]

    existing = paper["notes"]
    new_notes = (existing + "\nSecond note").strip()
    update_paper(db, "p1", notes=new_notes)
    paper = get_paper(db, "p1")
    assert paper is not None
    assert "First note" in paper["notes"]
    assert "Second note" in paper["notes"]


def test_summarize_l4(db):
    add_paper(db, "p1", "Test Paper")
    update_paper(db, "p1",
                 summary_l4="This paper proposes X.",
                 summary_l4_model="claude-opus-4-6",
                 summary_l4_at="2026-01-01T00:00:00Z")
    paper = get_paper(db, "p1")
    assert paper is not None
    assert paper["summary_l4"] == "This paper proposes X."
    assert paper["summary_l4_model"] == "claude-opus-4-6"
    assert paper["summary_l4_at"] == "2026-01-01T00:00:00Z"


def test_summarize_l2(db):
    add_paper(db, "p1", "Test Paper")
    claims = json.dumps(["Claim 1", "Claim 2", "Claim 3"])
    update_paper(db, "p1",
                 summary_l2=claims,
                 summary_l2_model="claude-opus-4-6",
                 summary_l2_at="2026-01-01T00:00:00Z")
    paper = get_paper(db, "p1")
    assert paper is not None
    loaded = json.loads(paper["summary_l2"])
    assert loaded == ["Claim 1", "Claim 2", "Claim 3"]
    assert paper["summary_l2_model"] == "claude-opus-4-6"


def test_cite(db):
    add_paper(db, "p1", "Paper One")
    add_paper(db, "p2", "Paper Two")
    add_citation(db, "p1", "p2", "extends")

    citations = get_citations(db, "p1")
    assert len(citations["cites"]) == 1
    assert citations["cites"][0]["to_id"] == "p2"
    assert citations["cites"][0]["type"] == "extends"

    citations_p2 = get_citations(db, "p2")
    assert len(citations_p2["cited_by"]) == 1
    assert citations_p2["cited_by"][0]["from_id"] == "p1"


def test_status_update(db):
    add_paper(db, "p1", "Test Paper")
    p = get_paper(db, "p1")
    assert p is not None
    assert p["status"] == "unread"

    update_paper(db, "p1", status="read")
    p2 = get_paper(db, "p1")
    assert p2 is not None
    assert p2["status"] == "read"


def test_tag(db):
    add_paper(db, "p1", "Test Paper")
    update_paper(db, "p1", tags="ml,nlp,transformers")
    paper = get_paper(db, "p1")
    assert paper is not None
    assert paper["tags"] == "ml,nlp,transformers"


def test_recommend_basic(db):
    add_paper(db, "p1", "Paper One", year=2023, status="unread")
    add_paper(db, "p2", "Paper Two", year=2022, status="unread")
    add_paper(db, "p3", "Paper Three", year=2021, status="unread")

    results = recommend(db, top_k=10)
    assert len(results) == 3
    ids = [r["id"] for r in results]
    assert "p1" in ids
    assert "p2" in ids
    assert "p3" in ids


def test_recommend_excludes_read(db):
    add_paper(db, "p1", "Paper One", year=2023, status="unread")
    add_paper(db, "p2", "Paper Two", year=2022, status="read")
    add_paper(db, "p3", "Paper Three", year=2021, status="unread")

    results = recommend(db, top_k=10)
    ids = [r["id"] for r in results]
    assert "p1" in ids
    assert "p2" not in ids
    assert "p3" in ids


def test_pagerank(db):
    add_paper(db, "p1", "Paper One")
    add_paper(db, "p2", "Paper Two")
    add_paper(db, "p3", "Paper Three")
    add_citation(db, "p1", "p2")
    add_citation(db, "p3", "p2")

    scores = compute_pagerank(db)
    assert set(scores.keys()) == {"p1", "p2", "p3"}
    assert all(v > 0 for v in scores.values())
    assert scores["p2"] > scores["p1"]
    assert scores["p2"] > scores["p3"]


def test_funnel_depth1(db):
    add_paper(db, "p1", "Attention Mechanism Paper", year=2017,
              abstract="Self-attention is the key innovation",
              summary_l4="Transformer uses self-attention")
    add_paper(db, "p2", "Another Paper", year=2018,
              abstract="Different topic entirely about diffusion")

    result = funnel_retrieve(db, "attention mechanism", depth=1)
    assert result["question"] == "attention mechanism"
    assert len(result["candidates"]) > 0
    assert result["shortlist"] == []
    assert result["details"] == []
    assert result["deep"] == []


def test_funnel_depth2(db):
    add_paper(db, "p1", "Attention Mechanism Paper", year=2017,
              abstract="Self-attention is the key innovation for transformers")

    result = funnel_retrieve(db, "attention mechanism", depth=2)
    assert len(result["candidates"]) > 0
    assert len(result["shortlist"]) > 0
    assert result["details"] == []


def test_stats(db):
    add_paper(db, "p1", "Paper One", status="unread")
    add_paper(db, "p2", "Paper Two", status="read")
    add_paper(db, "p3", "Paper Three", status="unread")
    add_citation(db, "p1", "p2")

    stats = get_stats(db)
    assert stats["total"] == 3
    assert stats["citations"] == 1
    assert stats["by_status"].get("unread") == 2
    assert stats["by_status"].get("read") == 1


def test_delete(db):
    add_paper(db, "p1", "Paper One")
    assert get_paper(db, "p1") is not None

    deleted = delete_paper(db, "p1")
    assert deleted is True
    assert get_paper(db, "p1") is None


def test_export_json(tmp_path):
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Paper One", year=2021)
    add_paper(conn, "p2", "Paper Two", year=2022)
    add_citation(conn, "p1", "p2")
    conn.close()

    import io
    from unittest.mock import patch

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["export"], root=tmp_path)
    assert code == 0
    data = json.loads(output.getvalue())
    assert len(data["papers"]) == 2
    assert len(data["citations"]) == 1


def test_taste(db):
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('taste', ?)",
               ("Research on multimodal foundation models and vision-language grounding",))
    db.commit()
    row = db.execute("SELECT value FROM meta WHERE key='taste'").fetchone()
    assert "multimodal" in row["value"]


def test_cli_help(tmp_path):
    from alit.scripts.lit import run

    with pytest.raises(SystemExit) as exc:
        run(["--help"])
    assert exc.value.code == 0


def test_cli_init(tmp_path):
    from alit.scripts.lit import run

    target = tmp_path / "myproject"
    code = run(["init", "--path", str(target)])
    assert code == 0
    assert (target / ".alit" / "papers.db").exists()


def test_upsert_preserves_existing_data(db):
    add_paper(db, "p1", "Original Title", year=2020, abstract="Original abstract",
              notes="My important notes", status="read")
    add_paper(db, "p1", "Updated Title", year=2021)
    paper = get_paper(db, "p1")
    assert paper["title"] == "Updated Title"
    assert paper["year"] == 2021
    assert paper["notes"] == "My important notes"
    assert paper["status"] == "read"
    assert paper["abstract"] == "Original abstract"


def test_delete_cascades_citations(db):
    add_paper(db, "p1", "Paper One")
    add_paper(db, "p2", "Paper Two")
    add_paper(db, "p3", "Paper Three")
    add_citation(db, "p1", "p2")
    add_citation(db, "p3", "p1")
    assert db.execute("SELECT COUNT(*) FROM citations").fetchone()[0] == 2
    delete_paper(db, "p1")
    assert db.execute("SELECT COUNT(*) FROM citations").fetchone()[0] == 0


def test_orphan_citations(db):
    from alit.scripts.db import get_orphan_citations
    add_paper(db, "p1", "Paper One")
    add_citation(db, "p1", "missing_paper")
    orphans = get_orphan_citations(db)
    assert len(orphans) == 1
    assert orphans[0]["to_id"] == "missing_paper"


def test_sanitize_id(db):
    from alit.scripts.db import _sanitize_id
    assert _sanitize_id("hello world!@#") == "hello_world"
    assert _sanitize_id("valid_id-123") == "valid_id-123"
    assert _sanitize_id("") == "paper"


def test_auto_id_uniqueness(tmp_path):
    from alit.scripts.lit import _auto_id
    conn = init_db(tmp_path)
    add_paper(conn, "attention_is_all", "Attention Is All You Need")
    second_id = _auto_id("Attention Is All You Need", conn)
    assert second_id != "attention_is_all"
    assert second_id.startswith("attention_is_all")
    conn.close()


def test_url_auto_detect():
    from alit.scripts.lit import _is_arxiv_url
    assert _is_arxiv_url("https://arxiv.org/abs/1706.03762") == "1706.03762"
    assert _is_arxiv_url("https://arxiv.org/pdf/2301.00001.pdf") == "2301.00001"
    assert _is_arxiv_url("not a url") is None
    assert _is_arxiv_url("https://example.com/paper") is None


def test_recommend_with_taste_keywords(db):
    add_paper(db, "p1", "Vision-Language Grounding with Transformers", year=2024,
              abstract="Multimodal grounding using cross-attention", status="unread")
    add_paper(db, "p2", "Cat Classification", year=2024,
              abstract="Deep learning for cat photos", status="unread")
    results = recommend(db, top_k=10, taste_keywords=["vision", "language", "grounding", "multimodal"])
    assert results[0]["id"] == "p1"
    assert results[0]["breakdown"]["relevance"] > results[1]["breakdown"]["relevance"]


def test_stats_coverage(db):
    add_paper(db, "p1", "Paper One", abstract="Has abstract", pdf_path="papers/p1.pdf")
    add_paper(db, "p2", "Paper Two")
    update_paper(db, "p1", summary_l4="One liner")
    stats = get_stats(db)
    assert stats["total"] == 2
    assert stats["with_abstract"] == 1
    assert stats["with_pdf"] == 1
    assert stats["with_l4"] == 1
    assert stats["with_l2"] == 0


def test_pagerank_update_stored(db):
    add_paper(db, "p1", "Paper One")
    add_paper(db, "p2", "Paper Two")
    add_citation(db, "p1", "p2")
    update_pagerank(db)
    p2 = get_paper(db, "p2")
    assert p2["pagerank"] > 0


def test_import_file(tmp_path):
    from alit.scripts.lit import run
    conn = init_db(tmp_path)
    conn.close()

    import_file = tmp_path / "papers.txt"
    import_file.write_text("# Comment line\nhttps://arxiv.org/abs/1706.03762\n\n")

    code = run(["import", str(import_file), "--no-pdf"], root=tmp_path)
    assert code == 0
    conn = init_db(tmp_path)
    papers = list_papers(conn)
    assert len(papers) >= 1
    conn.close()


def test_auto_tag(db):
    from alit.scripts.db import _auto_tag_from_abstract
    tags = _auto_tag_from_abstract(
        "This paper introduces a transformer-based attention mechanism for image classification and simulation"
    )
    assert "transformer" in tags
    assert "computer-vision" in tags
    assert "simulation" in tags


def test_auto_tag_empty(db):
    from alit.scripts.db import _auto_tag_from_abstract
    tags = _auto_tag_from_abstract("")
    assert tags == []


def test_auto_tag_title_only(db):
    from alit.scripts.db import _auto_tag_from_abstract
    tags = _auto_tag_from_abstract("", "Survey of large language models")
    assert "survey" in tags
    assert "foundation-model" in tags


def test_auto_tag_max_8(db):
    from alit.scripts.db import _auto_tag_from_abstract
    text = ("transformer attention self-attention diffusion model denoising reinforcement learning "
            "natural language image classification graph neural optimization survey")
    tags = _auto_tag_from_abstract(text)
    assert len(tags) <= 8


def test_parse_bibtex(db):
    from alit.scripts.db import _parse_bibtex
    bib = """
@article{vaswani2017attention,
  title={Attention Is All You Need},
  author={Vaswani, Ashish and Shazeer, Noam},
  year={2017},
  journal={NeurIPS},
  abstract={The dominant sequence transduction models}
}
"""
    entries = _parse_bibtex(bib)
    assert len(entries) == 1
    assert entries[0]["_citekey"] == "vaswani2017attention"
    assert entries[0]["title"] == "Attention Is All You Need"
    assert entries[0]["year"] == "2017"
    assert entries[0]["author"] == "Vaswani, Ashish and Shazeer, Noam"


def test_parse_bibtex_multiple(db):
    from alit.scripts.db import _parse_bibtex
    bib = """
@article{paper1,
  title={First Paper},
  year={2020}
}

@inproceedings{paper2,
  title={Second Paper},
  year={2021}
}
"""
    entries = _parse_bibtex(bib)
    assert len(entries) == 2


def test_parse_bibtex_empty():
    from alit.scripts.db import _parse_bibtex
    assert _parse_bibtex("") == []
    assert _parse_bibtex("no bibtex here") == []


def test_progress_command(db):
    add_paper(db, "p1", "Paper One", year=2024, status="read")
    add_paper(db, "p2", "Paper Two", year=2024, status="unread")
    stats = get_stats(db)
    assert stats["total"] == 2
    assert stats["by_status"]["read"] == 1
    assert stats["by_status"]["unread"] == 1


def test_progress_cli(tmp_path):
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Paper One", year=2021, status="read")
    add_paper(conn, "p2", "Paper Two", year=2022, status="unread")
    conn.close()

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["progress"], root=tmp_path)
    assert code == 0
    text = output.getvalue()
    assert "Literature Review Progress" in text
    assert "2" in text


def test_export_markdown(tmp_path):
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Paper One", year=2021, status="read",
              summary_l4="This is a summary", tags="ml,nlp")
    add_paper(conn, "p2", "Paper Two", year=2022, status="unread")
    conn.close()

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["export", "--format", "markdown"], root=tmp_path)
    assert code == 0
    md = output.getvalue()
    assert "# Literature Review" in md
    assert "Paper One" in md
    assert "This is a summary" in md


def test_read_command(tmp_path):
    import io
    from unittest.mock import patch
    from alit.scripts.lit import _cmd_read
    import argparse

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Test Paper", year=2024, abstract="Some abstract text",
              authors="Smith, Jones")

    output = io.StringIO()
    with patch("sys.stdout", output):
        args = argparse.Namespace(id="p1", json=False)
        code = _cmd_read(args, conn)
    assert code == 0
    text = output.getvalue()
    assert "Test Paper" in text
    assert "Smith, Jones" in text
    conn.close()


def test_read_not_found(tmp_path):
    import io
    from unittest.mock import patch
    from alit.scripts.lit import _cmd_read
    import argparse

    conn = init_db(tmp_path)

    with patch("sys.stderr", io.StringIO()):
        args = argparse.Namespace(id="nonexistent", json=False)
        code = _cmd_read(args, conn)
    assert code == 1
    conn.close()


def test_import_bib(tmp_path):
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    conn.close()

    bib_file = tmp_path / "refs.bib"
    bib_file.write_text("""
@article{smith2020paper,
  title={A Test Paper on Neural Networks},
  author={Smith, John and Doe, Jane},
  year={2020},
  abstract={Neural networks are powerful models for sequence modeling.}
}
""")
    code = run(["import", str(bib_file), "--no-pdf"], root=tmp_path)
    assert code == 0

    conn = init_db(tmp_path)
    paper = get_paper(conn, "smith2020paper")
    assert paper is not None
    assert paper["title"] == "A Test Paper on Neural Networks"
    assert paper["authors"] == "Smith, John; Doe, Jane"
    assert paper["year"] == 2020
    conn.close()


def test_export_json_format(tmp_path):
    from alit.scripts.lit import run
    import io
    from unittest.mock import patch

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Paper One", year=2021)
    conn.close()

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["export", "--format", "json"], root=tmp_path)
    assert code == 0
    data = json.loads(output.getvalue())
    assert len(data["papers"]) == 1


def test_dedup_by_arxiv_id(db):
    p1 = add_paper(db, "paper_one", "Attention Is All You Need", arxiv_id="1706.03762", year=2017)
    assert p1["id"] == "paper_one"

    p2 = add_paper(db, "paper_two_different_id", "Attention Is All You Need v2", arxiv_id="1706.03762", year=2018)
    assert p2["id"] == "paper_one"
    assert p2["year"] == 2018

    all_papers = list_papers(db)
    assert len(all_papers) == 1
    assert all_papers[0]["id"] == "paper_one"


def test_import_json(tmp_path):
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    conn.close()

    json_file = tmp_path / "papers.json"
    json_file.write_text(json.dumps([
        {"title": "Paper One", "arxiv_id": "1706.03762", "year": 2017, "tags": "transformers,attention"},
        {"title": "Paper Two", "year": 2024, "authors": "Smith, Jones"},
    ]))

    import io
    from unittest.mock import patch

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["import", str(json_file)], root=tmp_path)
    assert code == 0
    assert "Imported 2" in output.getvalue()

    conn = init_db(tmp_path)
    papers = list_papers(conn)
    assert len(papers) == 2
    ids = [p["id"] for p in papers]
    p1 = next(p for p in papers if p.get("arxiv_id") == "1706.03762")
    assert p1["year"] == 2017
    assert p1["tags"] == "transformers,attention"
    conn.close()


def test_import_json_skips_existing(tmp_path):
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "paper_one", "Paper One", arxiv_id="1706.03762")
    conn.close()

    json_file = tmp_path / "papers.json"
    json_file.write_text(json.dumps([
        {"title": "Paper One Again", "arxiv_id": "1706.03762"},
        {"title": "Paper Two"},
    ]))

    import io
    from unittest.mock import patch

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["import", str(json_file)], root=tmp_path)
    assert code == 0
    text = output.getvalue()
    assert "Imported 1" in text
    assert "skipped 1" in text


def test_summarize_variadic_l2(tmp_path):
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Test Paper")
    conn.close()

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["summarize", "p1", "--l2", "claim1", "claim2", "claim3", "--force"], root=tmp_path)
    assert code == 0
    assert "l2" in output.getvalue()

    conn = init_db(tmp_path)
    paper = get_paper(conn, "p1")
    assert paper is not None
    claims = json.loads(paper["summary_l2"])
    assert claims == ["claim1", "claim2", "claim3"]
    conn.close()


def test_summarize_blocked_without_pdf(tmp_path):
    """Summarize should fail when paper has no PDF (unless --force)."""
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Test Paper")
    conn.close()

    err = io.StringIO()
    with patch("sys.stderr", err):
        code = run(["summarize", "p1", "--l4", "summary text"], root=tmp_path)
    assert code == 1
    assert "No PDF" in err.getvalue()


def test_summarize_allowed_with_pdf(tmp_path):
    """Summarize should succeed when paper has a PDF."""
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Test Paper")
    update_paper(conn, "p1", pdf_path="pdfs/test.pdf")
    conn.close()

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["summarize", "p1", "--l4", "summary text", "--model", "test"], root=tmp_path)
    assert code == 0


def test_summarize_warns_abstract_overlap(tmp_path):
    """Summarize should warn when L4 summary is too similar to abstract."""
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run

    abstract = "This paper proposes a novel method for image classification using transformers"
    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Test Paper")
    update_paper(conn, "p1", pdf_path="pdfs/test.pdf", abstract=abstract)
    conn.close()

    err = io.StringIO()
    with patch("sys.stderr", err), patch("sys.stdout", io.StringIO()):
        # Summary that mostly copies the abstract
        code = run(["summarize", "p1", "--l4", abstract, "--model", "test"], root=tmp_path)
    assert code == 0  # warning only, not a block
    assert "similar to abstract" in err.getvalue()


def test_status_blocked_without_pdf(tmp_path):
    """Status change to read/skimmed should fail without PDF (unless --force)."""
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Test Paper")
    conn.close()

    err = io.StringIO()
    with patch("sys.stderr", err):
        code = run(["status", "p1", "read"], root=tmp_path)
    assert code == 1
    assert "No PDF" in err.getvalue()

    # --force should override
    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["status", "p1", "read", "--force"], root=tmp_path)
    assert code == 0


def test_summarize_l2_backward_compat_json(tmp_path):
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Test Paper")
    conn.close()

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["summarize", "p1", "--l2", '["old_claim1", "old_claim2"]', "--force"], root=tmp_path)
    assert code == 0

    conn = init_db(tmp_path)
    paper = get_paper(conn, "p1")
    assert paper is not None
    claims = json.loads(paper["summary_l2"])
    assert claims == ["old_claim1", "old_claim2"]
    conn.close()


def test_dedup_command(tmp_path):
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Attention Paper", arxiv_id="1706.03762", year=2017)
    add_paper(conn, "p2_dup", "Attention Paper Duplicate", arxiv_id="1706.03762", year=2017)
    conn.close()

    conn = init_db(tmp_path)
    conn.execute("INSERT INTO papers (id, title, arxiv_id) VALUES ('p2_force', 'Attention Dup', '1706.03762')")
    conn.commit()
    conn.close()

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["dedup"], root=tmp_path)
    assert code == 0
    text = output.getvalue()
    assert "duplicate" in text.lower() or "arxiv:1706.03762" in text


def test_dedup_merge(tmp_path):
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run, _cmd_dedup
    import argparse

    conn = init_db(tmp_path)
    conn.execute("INSERT INTO papers (id, title, arxiv_id, abstract) VALUES ('p1', 'Paper One', '1706.03762', 'Has abstract')")
    conn.execute("INSERT INTO papers (id, title, arxiv_id, abstract) VALUES ('p2', 'Paper Two Dup', '1706.03762', '')")
    conn.commit()

    output = io.StringIO()
    with patch("sys.stdout", output):
        args = argparse.Namespace(merge=True)
        code = _cmd_dedup(args, conn)
    assert code == 0
    text = output.getvalue()
    assert "Merged" in text

    papers = list_papers(conn)
    assert len(papers) == 1
    conn.close()


def test_cite_batch(tmp_path):
    import io
    from unittest.mock import patch
    from alit.scripts.lit import run

    conn = init_db(tmp_path)
    add_paper(conn, "p1", "Paper One")
    add_paper(conn, "p2", "Paper Two")
    add_paper(conn, "p3", "Paper Three")
    conn.close()

    batch_file = tmp_path / "edges.json"
    batch_file.write_text(json.dumps([
        {"from": "p1", "to": "p2", "type": "cites"},
        {"from": "p1", "to": "p3", "type": "extends"},
    ]))

    output = io.StringIO()
    with patch("sys.stdout", output):
        code = run(["cite", "--batch", str(batch_file)], root=tmp_path)
    assert code == 0
    assert "Added 2" in output.getvalue()

    conn = init_db(tmp_path)
    cites = conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]
    assert cites == 2
    conn.close()
