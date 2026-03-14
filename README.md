# alit

Your AI agent reads papers so you don't have to.

`pip install alit` → zero dependencies, SQLite-only, works with any coding agent.

Got tokens to burn? Let your agent read 50 papers overnight and hand you a synthesis in the morning.

Tell your agent:

```
Use alit to manage my literature review. See https://github.com/Zhou-Hangyu/alit
```

## How it works

```
You add papers → alit stores in SQLite → agent reads, summarizes, builds citation graph
                                       → PDFs auto-downloaded from arXiv
                                       → PageRank ranks what to read next
                                       → BM25 search across 10K+ papers in milliseconds
```

```
.alit/
├── papers.db    ← one file, entire literature collection
└── pdfs/        ← auto-downloaded from arXiv
```

No servers. No API keys. No vector databases. No setup beyond `pip install`.

## Install

```bash
pip install alit         # or: uv add alit
alit init                # creates .alit/ in your project
alit install-skill       # teaches your agent the full workflow
```

## Set your taste

Tell alit what kind of research excites you. This drives recommendations — papers matching your taste rank higher.

```bash
alit taste "I'm into generative models for financial markets. Love papers that combine
transformers with market microstructure. Prefer mathematical rigor over pure empirical
benchmarks. Especially interested in order book simulation and agent-based models."
```

Change it anytime as your interests evolve. The reading queue reranks instantly.

## Quick start

```bash
alit add "https://arxiv.org/abs/1706.03762"     # fetches metadata + PDF
alit import library.bib                          # or dump your Zotero/Mendeley
alit recommend 5                                 # ranked by your taste
alit ask "What are the key attention mechanisms?" --depth 2
```

## Commands

| Command | What it does |
|---------|-------------|
| `alit init` | Initialize `.alit/` |
| `alit add <title-or-url>` | Add paper (auto-enriches arXiv, auto-tags) |
| `alit find <query>` | Search arXiv/S2 for papers by topic |
| `alit import <file>` | Bulk-add from URL file or BibTeX (.bib) |
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
- **Ranking**: PageRank on citation graph (pure Python, no scipy)
- **Recommendations**: PageRank + recency + research purpose matching
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
