# (-o-) alit

Your AI agent reads papers so you don't have to.

`pip install agent-lit` → zero dependencies, SQLite-only, works with any coding agent.

Got tokens to burn? Let your agent read 50 papers overnight and hand you a synthesis in the morning.

Tell your agent:

```
Use alit to manage my literature review. See https://github.com/Zhou-Hangyu/alit
```

## Why alit

Your agent can web-search papers anytime — but forgets everything next session. alit is persistent memory. One agent reads 50 papers, another agent queries that knowledge instantly. Knowledge compounds across sessions.

## How it works

```
.alit/
├── papers.db    ← one SQLite file, entire knowledge base
└── pdfs/        ← auto-downloaded from arXiv
```

No servers. No API keys. No vector databases. No setup beyond `pip install`.

## Install

```bash
pip install agent-lit    # or: uv add agent-lit
alit init                # creates .alit/ in your project
```

The agent skill auto-installs on first run.

## Set your taste

```bash
alit taste "I'm into multimodal foundation models and how they learn cross-modal
representations. Love papers with clean ablations over pure benchmark chasing.
Especially interested in vision-language grounding and embodied AI."
```

## Quick start

```bash
alit add "https://arxiv.org/abs/1706.03762"     # fetches metadata + PDF
alit import library.bib                          # or dump your Zotero/Mendeley
alit recommend 5                                 # ranked by your taste
alit ask "What are the key attention mechanisms?" --depth 2
```

## Update

```bash
pip install --upgrade agent-lit
```

## Commands

| Command | What it does |
|---------|-------------|
| `alit init` | Initialize `.alit/` |
| `alit add <title-or-url>` | Add paper (auto-enriches arXiv, auto-tags) |
| `alit find <query>` | Search arXiv/S2 for papers by topic |
| `alit import <file>` | Bulk-add from URL file or BibTeX (.bib) |
| `alit sync` | Import from remembered BibTeX source (Zotero, etc.) |
| `alit enrich` | Batch-fetch metadata for papers missing abstracts |
| `alit search <query>` | BM25 full-text search |
| `alit recommend [N]` | Reading queue ranked by score |
| `alit ask <question>` | Cross-paper synthesis via funnel retrieval |
| `alit read <id>` | Guided reading view |
| `alit show <id>` | Paper details + citations |
| `alit list` | List papers |
| `alit note <id> <text>` | Append reading notes |
| `alit summarize <id>` | Store summary with model provenance |
| `alit cite <from> <to>` | Add citation edge |
| `alit status <id> <s>` | Set reading status |
| `alit tag <id> <tags>` | Set tags |
| `alit taste [text]` | Set or show your research taste |
| `alit progress` | Visual progress dashboard |
| `alit stats` | Collection overview |
| `alit orphans` | Find citations to missing papers |
| `alit attach <id> <pdf>` | Attach local PDF |
| `alit fetch-pdf <id>` | Download PDF from arXiv |
| `alit delete <id>` | Remove paper + citations |
| `alit export [--format X]` | Export as JSON or markdown |

All commands support `--json`.

## Under the hood

- **Search**: BM25 via SQLite FTS5
- **Ranking**: PageRank on citation graph (pure Python)
- **Recommendations**: PageRank + recency + taste matching
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
