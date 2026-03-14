# (-o-) alit

Your AI agent reads papers so you don't have to.

`pip install agent-lit` → zero dependencies, SQLite-only, works with any coding agent.

Same spirit as [autoresearch](https://github.com/karpathy/autoresearch) — but for the literature review that comes before experiments. Give your agent a research taste, point it at arXiv, and let it go. It reads papers, writes summaries, builds a citation graph, and ranks what to read next. You wake up to a structured knowledge base instead of 47 open browser tabs. The agent modifies the knowledge. You modify the taste. That's the whole loop.

Why not just web search? Your agent forgets everything next session. alit is persistent memory — one agent reads 50 papers, another queries that knowledge instantly. Knowledge compounds across sessions.

## Setup

```bash
pip install agent-lit    # or: uv add agent-lit
```

## Running the agent

Spin up Claude Code, opencode, Cursor, or whatever you use in your project, then prompt:

```
Set up alit for literature review in this project. See https://github.com/Zhou-Hangyu/alit
```

The agent will run `alit init`, set your taste, and start adding papers. From there you can prompt things like:

```
Find and add the top 10 papers on vision-language grounding from the last 2 years.
```

```
Read the next 5 recommended papers and summarize each one.
```

```
What does the literature say about cross-modal attention mechanisms?
```

```
Import my Zotero library from library.bib and enrich everything.
```

The `alit taste` is your research program — update it as your interests evolve:

```
Update my research taste: I'm now more interested in embodied AI
and less in pure vision-language benchmarks.
```

## How it works

Three things that matter:

- **`.alit/papers.db`** — one SQLite file. The entire knowledge base. Summaries, citations, PageRank scores, reading status. Agent reads and writes this.
- **`alit taste`** — your research program. What excites you, what to prioritize. You edit this, agent follows it. Like `program.md` but for literature.
- **`alit` CLI** — the agent's interface. Search, recommend, synthesize, add papers. All via Bash commands.

```
.alit/
├── papers.db    ← one file, entire knowledge base
└── pdfs/        ← auto-downloaded from arXiv
```

No servers. No API keys. No vector databases. Run `alit --help` for the full command list.

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
