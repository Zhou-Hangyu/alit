---
name: alit
description: "SQLite-based literature review manager for research papers. Use when adding, searching, reading, summarizing, or synthesizing academic papers. Handles arXiv URLs, BibTeX import, citation graphs, and reading recommendations. Do not use for non-academic document management, note-taking apps, or reference formatting (use a citation manager instead)."
---

# alit — Literature Review System

Data lives in `.alit/papers.db`. PDFs in `.alit/pdfs/`. Zero external dependencies.

## Setup

1. Run `alit init` to create the database.
2. Run `alit taste "your research interests and what excites you"` to improve recommendations.

## Adding Papers

1. For arXiv papers, run `alit add "https://arxiv.org/abs/XXXX.XXXXX"`. This fetches metadata, downloads the PDF, and auto-tags from the abstract.
2. For non-arXiv papers, run `alit add "Title" --year 2024 --authors "Smith" --abstract "..."`.
3. To attach a local PDF, pass `--pdf /path/to/file.pdf`.
4. To bulk-add from a file of arXiv URLs (one per line, `#` comments), run `alit import papers.txt`.
5. To import from Zotero/Mendeley/Google Scholar, export as `.bib` and run `alit import library.bib`.
6. To search for papers by topic, run `alit find "query"` or `alit find "query" --source s2`.
7. To fetch metadata for papers missing abstracts, run `alit enrich`.
8. Skip PDF downloads on any command with `--no-pdf`.

## Reading Workflow

1. Run `alit recommend 5` to get the next papers to read, ranked by PageRank + relevance + recency.
2. Run `alit read <id>` to see the paper's abstract, citations, and summaries.
3. Read the PDF at `.alit/pdfs/<arxiv_id>.pdf` if available.
4. After reading, store findings:
   - `alit status <id> read`
   - `alit note <id> "key observations..."`
   - `alit summarize <id> --l4 "one sentence summary" --model "<model-name>"`
   - `alit summarize <id> --l2 '["claim 1", "claim 2"]' --model "<model-name>"`
5. Always pass `--model` when summarizing — provenance is tracked.

## Citations

1. Run `alit cite <from_id> <to_id> --type extends` to add a citation edge. Types: cites, extends, contradicts, uses_method, uses_dataset, surveys.
2. The cited paper does not need to exist in the database yet.
3. Run `alit orphans` to list cited papers not in the collection.
4. For each orphan, search online to verify the paper exists, then `alit add` it.

## Search and Synthesis

1. Run `alit search "query"` for BM25 full-text search.
2. Run `alit ask "research question" --depth 2` for cross-paper synthesis via funnel retrieval.
   - `--depth 1`: titles + one-liners (~500 tokens)
   - `--depth 2`: + abstracts for top-10 (~2.5K tokens)
   - `--depth 3`: + key claims for top-3 (~3.5K tokens)
   - `--depth 4`: + full notes for top-1 (~5K tokens)

## Commands

| Command | Description |
|---------|-------------|
| `alit init` | Create `.alit/papers.db` |
| `alit add <title-or-url>` | Add paper (auto-enriches arXiv, auto-tags) |
| `alit find <query>` | Search arXiv/S2 for papers by topic |
| `alit import <file>` | Bulk-add from URL file or BibTeX |
| `alit enrich` | Batch-fetch metadata for papers missing abstracts |
| `alit search <query>` | BM25 full-text search |
| `alit recommend [N]` | Reading queue ranked by score |
| `alit ask <question>` | Cross-paper synthesis |
| `alit read <id>` | Guided reading view |
| `alit show <id>` | Paper details + citations |
| `alit list` | List papers (default 20, `--all` for full) |
| `alit note <id> <text>` | Append notes |
| `alit summarize <id>` | Store L4/L2 summary with `--model` provenance |
| `alit cite <from> <to>` | Add citation edge with `--type` |
| `alit status <id> <s>` | Set status: unread, skimmed, read, synthesized |
| `alit tag <id> <tags>` | Set comma-separated tags |
| `alit taste [text]` | Set or show research taste |
| `alit progress` | Visual progress dashboard |
| `alit stats` | Collection overview |
| `alit orphans` | List citations to missing papers |
| `alit attach <id> <pdf>` | Attach local PDF |
| `alit fetch-pdf <id>` | Download PDF from arXiv |
| `alit delete <id>` | Remove paper + citations |
| `alit export [--format X]` | Export as JSON or markdown |

All commands support `--json` for machine-readable output.

## Conventions

- **IDs**: lowercase, no spaces (e.g. `vaswani2017attention`). Auto-generated if omitted.
- **Status progression**: unread → skimmed → read → synthesized.
- **Citation types**: cites, extends, contradicts, uses_method, uses_dataset, surveys.
- **Provenance**: always pass `--model` when summarizing.
- **PDFs**: stored in `.alit/pdfs/`, auto-downloaded for arXiv papers.
