# alit

Lightweight literature review system for AI coding agents.

Zero dependencies. SQLite-only. The agent is the intelligence — alit is data plumbing.

## Install

```bash
pip install alit
# or
uv add alit
```

## 30-Second Start

```bash
alit init                                              # create papers.db
alit add "https://arxiv.org/abs/1706.03762"            # add paper (auto-fetches metadata + PDF)
alit search "attention"                                # BM25 search
alit recommend 5                                       # what to read next
alit ask "What are the key transformer innovations?"   # cross-paper synthesis
```

## Agent Integration

```bash
alit install-skill   # installs SKILL.md for opencode / Claude Code
```

Agents load the `literature-review` skill, then use `alit` commands via Bash. The agent reads papers, generates summaries, builds citation graphs — alit stores and retrieves.

## How It Works

```
You (or your agent) add papers → alit stores in SQLite → search/recommend/synthesize
                                                      → PDFs auto-downloaded from arXiv
                                                      → PageRank on citation graph
                                                      → BM25 full-text search via FTS5
```

**No servers. No API keys. No vector databases.** Just a `papers.db` file and a `papers/` directory for PDFs.

## Adding Papers

```bash
# From arXiv URL (auto-fetches title, abstract, authors, year + PDF)
alit add "https://arxiv.org/abs/1706.03762"

# With explicit metadata
alit add "Attention Is All You Need" \
  --id vaswani2017attention \
  --year 2017 \
  --authors "Vaswani, Shazeer, Parmar" \
  --abstract "The dominant sequence transduction models..." \
  --arxiv "1706.03762" \
  --tags "transformers,attention"

# Attach a local PDF
alit add "Some Paper" --id smith2024 --pdf /path/to/paper.pdf

# Bulk import from a file
alit import papers.txt --no-pdf
```

**papers.txt** format (one URL per line, `#` comments):
```
# Core papers
https://arxiv.org/abs/1706.03762
https://arxiv.org/abs/1810.04805

# LOB papers
https://arxiv.org/abs/2502.07071
```

## Reading Workflow

```bash
# 1. See what to read next (ranked by relevance + PageRank + recency)
alit recommend 5

# 2. Read a paper, then store your findings
alit status vaswani2017attention read
alit note vaswani2017attention "Self-attention replaces recurrence. O(1) sequential ops."
alit summarize vaswani2017attention \
  --l4 "Transformer replaces recurrence with self-attention, achieving BLEU SOTA." \
  --model "claude-opus-4-6"

# 3. Link papers
alit cite vaswani2017attention bahdanau2014attention --type extends

# 4. Verify cited papers exist in collection
alit orphans
```

## Searching & Synthesis

```bash
# BM25 full-text search
alit search "limit order book simulation"

# Cross-paper synthesis — agent reads the output and reasons
alit ask "What generative models exist for LOB data?" --depth 2
```

Depth controls token budget:
| Depth | What you get | ~Tokens |
|-------|-------------|---------|
| 1 | Titles + one-liners | 500 |
| 2 | + abstracts for top-10 (default) | 2,500 |
| 3 | + key claims for top-3 | 3,500 |
| 4 | + full notes for top-1 | 5,000 |

## Commands

| Command | What it does |
|---------|-------------|
| `alit init` | Create papers.db |
| `alit add <title-or-url>` | Add paper (auto-enriches arXiv URLs) |
| `alit import <file>` | Bulk-add from file of arXiv URLs |
| `alit enrich` | Batch-fetch metadata for papers missing abstracts |
| `alit show <id>` | Full paper details + citations |
| `alit list` | List all papers (📄=PDF, ✓=summarized) |
| `alit search <query>` | BM25 full-text search |
| `alit recommend [N]` | Reading queue ranked by score |
| `alit ask <question>` | Cross-paper synthesis |
| `alit note <id> <text>` | Append reading notes |
| `alit summarize <id>` | Store L4/L2 summary with provenance |
| `alit cite <from> <to>` | Add citation edge |
| `alit status <id> <s>` | Set reading status |
| `alit tag <id> <tags>` | Set comma-separated tags |
| `alit purpose [text]` | Set or show research purpose |
| `alit stats` | Collection overview with coverage |
| `alit orphans` | Citations pointing to missing papers |
| `alit attach <id> <pdf>` | Attach local PDF to existing paper |
| `alit fetch-pdf <id>` | Download PDF from arXiv |
| `alit delete <id>` | Remove paper + its citations |
| `alit export` | Dump everything as JSON |
| `alit install-skill` | Install agent SKILL.md |

All commands support `--json` for machine-readable output.

## Architecture

```
papers.db (SQLite)
├── papers       — metadata, notes, summaries, pdf_path
├── papers_fts   — FTS5 index (auto-synced via triggers)
├── citations    — typed edges between papers
└── meta         — key-value store (purpose, etc.)

papers/          — downloaded PDFs
```

- **Search**: BM25 via SQLite FTS5 — no vector DB
- **Ranking**: PageRank on citation graph — pure Python
- **Recommendations**: PageRank + recency + purpose keyword matching
- **Synthesis**: Multi-stage funnel retrieval (5K tokens for 10K papers)
- **Enrichment**: arXiv API (batched) with Semantic Scholar fallback
- **Schema migration**: auto-adds new columns on upgrade

## Development

```bash
git clone https://github.com/Zhou-Hangyu/alit
cd alit
uv sync
uv run pytest
```

## License

MIT
