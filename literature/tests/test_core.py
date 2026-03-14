from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

from literature.scripts.db import (
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
from literature.scripts.pagerank import compute_pagerank, update_pagerank
from literature.scripts.recommend import recommend
from literature.scripts.search import search
from literature.scripts.synthesize import funnel_retrieve


@pytest.fixture
def db(tmp_path):
    conn = init_db(tmp_path)
    yield conn
    conn.close()


def test_init_creates_db(tmp_path):
    conn = init_db(tmp_path)
    conn.close()
    assert (tmp_path / "papers.db").exists()


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
    from literature.scripts.lit import _auto_id

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
    from literature.scripts.lit import run

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


def test_purpose(db):
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('purpose', ?)",
               ("Research on limit order book simulation and market microstructure",))
    db.commit()
    row = db.execute("SELECT value FROM meta WHERE key='purpose'").fetchone()
    assert "limit order book" in row["value"]


def test_cli_help(tmp_path):
    from literature.scripts.lit import run

    with pytest.raises(SystemExit) as exc:
        run(["--help"])
    assert exc.value.code == 0


def test_cli_init(tmp_path):
    from literature.scripts.lit import run

    target = tmp_path / "myproject"
    code = run(["init", "--path", str(target)])
    assert code == 0
    assert (target / "papers.db").exists()
