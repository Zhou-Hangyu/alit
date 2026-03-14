# (-o-) alit roadmap

Features under consideration. Not committed to — needs battle testing first.

## Reading quality

- **Summarization prompts** — Guide agents on how to read papers and write good L4/L2. Different LLMs produce different quality. Needs real-world data before prescribing a format. Would live in `references/reading-guide.md` with just-in-time loading.
- **Structured L2** — Convention for agents to write L2 as JSON with methods/datasets/results/gaps. Enables experiment agents to query structured data directly.

## Discovery

- **`alit watch`** — Monitor topics, surface new papers matching taste. Self-contained: `alit find` with memory (tracks seen IDs, only shows new).
- **`alit related <id>`** — Paper-to-paper similarity within collection. BM25 on abstract + shared citations.

## Multi-session

- **`alit diff`** — What changed since last session. New papers, new summaries, status changes. Agents run this at session start to orient.
- **`alit map`** — Cluster papers by topic, show landscape. Useful at 30+ papers.

## Distribution

- **PyPI publish** — `pip install alit` for everyone, not just source installs.
