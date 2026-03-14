# (-o-) alit

Your agent forgets every paper it's ever read.

alit is a local knowledge base for AI agents doing literature review. One agent reads 50 papers and stores structured summaries, citations, and reading status. The next agent — or the same agent next week — queries that knowledge instantly.

The agent builds the knowledge. You set the taste. Knowledge compounds.

`pip install agent-lit` → zero dependencies, SQLite-only, works with any coding agent.

## The core loop

```bash
alit taste "vision-language grounding, embodied AI"   # you set direction
alit recommend 5                                       # agent picks what to read
alit summarize <id> --l4 "..." --model claude          # agent stores findings
alit ask "what approaches exist for X?" --depth 2      # agent synthesizes
```

Run `alit --help` for the full command list (25 commands for search, import, export, citations, and more).

## What alit does and doesn't do

| | alit | The agent |
|--|------|-----------|
| **Stores** papers, summaries, citations, taste | ✓ | |
| **Ranks** recommendations (PageRank + taste + recency) | ✓ | |
| **Retrieves** context for synthesis | ✓ | |
| **Persists** across sessions | ✓ | |
| **Reads** papers | | ✓ |
| **Writes** summaries | | ✓ |
| **Decides** what to cite | | ✓ |
| **Answers** research questions | | ✓ |

alit stores and retrieves. The agent thinks. You set the taste.

## Setup

```bash
pip install agent-lit    # or: uv add agent-lit
```

Spin up Claude Code, opencode, Cursor, or whatever you use, then prompt:

```
Set up alit for literature review in this project. See https://github.com/Zhou-Hangyu/alit
```

From there:

```
Find and add the top 10 papers on vision-language grounding from the last 2 years.
```

```
Read the next 5 recommended papers and summarize each one.
```

```
What does the literature say about cross-modal attention mechanisms?
```

## How it works

```
.alit/
├── papers.db    ← one SQLite file, entire knowledge base
└── pdfs/        ← auto-downloaded from arXiv
```

No servers. No API keys. No vector databases.

## Update

```bash
pip install --upgrade agent-lit
```

## Under the hood

- **Search**: BM25 via SQLite FTS5
- **Ranking**: PageRank on citation graph (pure Python)
- **Recommendations**: PageRank + recency + taste matching
- **Synthesis**: multi-stage funnel retrieval (~5K tokens to query 10K papers)
- **Enrichment**: arXiv API (batched) with Semantic Scholar fallback
- **Backward compatible**: schema auto-migrates on upgrade

## License

MIT
