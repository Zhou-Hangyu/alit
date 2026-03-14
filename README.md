# (-o-) alit

Persistent memory for AI agents doing literature review.

Your agent can search the web and find papers — but it forgets everything next session. alit is the shared brain that accumulates knowledge across sessions and across agents.

```
Reading agent  →  reads 50 papers, stores summaries, builds citation graph
Experiment agent  →  alit ask "what baselines exist?" → instant answer from 50 papers
```

One agent's work benefits every other agent. Knowledge compounds.

Tell your agent:

```
Use alit to manage my literature review. See https://github.com/Zhou-Hangyu/alit
```

## Why alit (and why not)

**Use alit if:** you're doing a multi-session research project where an agent reads papers over days/weeks and you need that knowledge to persist and be queryable.

**Don't need alit if:** you just want to look up one paper right now — your agent's web search already does that.

## How it works

```
.alit/
├── papers.db    ← one SQLite file, entire knowledge base
└── pdfs/        ← auto-downloaded from arXiv
```

No servers. No API keys. No vector databases. Zero dependencies. Pure Python stdlib.

## Install

```bash
pip install alit         # or: uv add alit
alit init                # creates .alit/ in your project
alit install-skill       # teaches your agent the full workflow
```

## Set your taste

Tell alit what kind of research excites you. Recommendations rank papers matching your taste higher.

```bash
alit taste "I'm into multimodal foundation models and how they learn cross-modal
representations. Love papers with clean ablations over pure benchmark chasing.
Especially interested in vision-language grounding and embodied AI."
```

Change it anytime. The reading queue reranks instantly.

## Quick start

```bash
alit add "https://arxiv.org/abs/1706.03762"     # fetches metadata + PDF
alit import library.bib                          # or dump your Zotero/Mendeley
alit recommend 5                                 # ranked by your taste
alit ask "What are the key attention mechanisms?" --depth 2
```

## Update

Not on PyPI yet. If installed from source:

```bash
cd path/to/alit && git pull
pip install -e .         # or: uv sync --reinstall-package alit
alit install-skill       # update the agent skill
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
