# alit

Literature review tool for AI coding agents. Zero dependencies. SQLite-only.

The agent is the intelligence — alit is data plumbing.

```
Tell your agent: "Use alit to manage my literature review. See https://github.com/Zhou-Hangyu/alit"
```

## Install

```bash
pip install alit    # or: uv add alit
alit init           # creates .alit/ in your project
alit install-skill  # teaches your agent how to use alit
```

## Commands

| Command | What it does |
|---------|-------------|
| `alit init` | Initialize `.alit/` in current project |
| `alit add <title-or-url>` | Add paper (auto-enriches arXiv URLs, auto-tags) |
| `alit find <query>` | Search arXiv/S2 for papers by topic |
| `alit import <file>` | Bulk-add from URL file or BibTeX (.bib) |
| `alit enrich` | Batch-fetch metadata for papers missing abstracts |
| `alit search <query>` | BM25 full-text search |
| `alit recommend [N]` | Reading queue ranked by PageRank + relevance + recency |
| `alit ask <question>` | Cross-paper synthesis via funnel retrieval |
| `alit read <id>` | Guided reading view with citations |
| `alit show <id>` | Paper details |
| `alit list` | List all papers |
| `alit note <id> <text>` | Append reading notes |
| `alit summarize <id>` | Store L4/L2 summary with model provenance |
| `alit cite <from> <to>` | Add citation edge |
| `alit status <id> <s>` | Set reading status (unread/skimmed/read/synthesized) |
| `alit tag <id> <tags>` | Set tags |
| `alit purpose [text]` | Set or show research purpose |
| `alit progress` | Visual progress dashboard |
| `alit stats` | Collection overview with coverage |
| `alit orphans` | Citations pointing to missing papers |
| `alit attach <id> <pdf>` | Attach local PDF |
| `alit fetch-pdf <id>` | Download PDF from arXiv |
| `alit delete <id>` | Remove paper + citations |
| `alit export [--format X]` | Export as JSON or markdown |
| `alit install-skill` | Install SKILL.md for coding agents |

All commands support `--json` for machine-readable output.

## Importing Papers

```bash
# arXiv URL (auto-fetches metadata + PDF)
alit add "https://arxiv.org/abs/1706.03762"

# Local PDF
alit add "Paper Title" --pdf /path/to/paper.pdf

# Bulk from file (one arXiv URL per line)
alit import papers.txt

# From Zotero / Mendeley / Google Scholar (.bib export)
alit import library.bib
```

## Architecture

```
.alit/
├── papers.db    ← SQLite (sole source of truth)
└── pdfs/        ← downloaded PDFs
```

No servers. No API keys. No vector databases. Scales to 10K+ papers.

- **Search**: BM25 via SQLite FTS5
- **Ranking**: PageRank on citation graph (pure Python)
- **Recommendations**: PageRank + recency + purpose keyword matching
- **Synthesis**: multi-stage funnel retrieval (~5K tokens to query 10K papers)
- **Enrichment**: arXiv API (batched) with Semantic Scholar fallback
- **Backward compatible**: schema auto-migrates on upgrade

## Development

```bash
git clone https://github.com/Zhou-Hangyu/alit
cd alit
uv sync
uv run pytest
```

## License

MIT
