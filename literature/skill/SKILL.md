---
name: alit
description: "Lightweight literature review system. Zero dependencies, SQLite-only. Use when managing research papers — adding, searching, reading, summarizing, synthesizing. Run `alit init` to start."
---

# Literature Review System

Zero dependencies. SQLite-only. You are the intelligence — the system is data plumbing.

## Quick Start

```bash
alit init                    # creates papers.db
alit add "Paper Title" --year 2024 --abstract "..." --authors "Smith, Jones" --arxiv "2401.12345"
alit search "attention"      # BM25 search
alit recommend 5             # what to read next
```

## Adding Papers

Simplest way — just paste an arXiv URL:

```bash
alit add "https://arxiv.org/abs/1706.03762"
```

This auto-fetches title, abstract, authors, year from arXiv + downloads the PDF. Auto-tags are added from the abstract. One command, done.

For non-arXiv papers, provide metadata yourself:

```bash
alit add "Some Workshop Paper" --year 2024 --authors "Smith, Jones" --abstract "..."
```

Bulk import from a file or BibTeX:

```bash
alit import papers.txt          # one arXiv URL per line, # comments
alit import papers.txt --no-pdf # skip PDF downloads
alit import library.bib         # BibTeX export from Zotero/Mendeley/Google Scholar
alit import refs.bib --no-pdf   # BibTeX, skip PDF downloads
```

PDFs:
- arXiv URLs → auto-downloaded
- `--pdf /path/to/local.pdf` → copies a PDF handed to you in the session
- `alit attach <id> /path/to/file.pdf` → attach PDF to existing paper
- `alit fetch-pdf <id>` → download for existing paper
- `--no-pdf` → skip download

## Importing from Other Tools

Export your library as BibTeX from Zotero, Mendeley, Google Scholar, etc., then:

```bash
alit import library.bib                # auto-detects .bib format
alit import references.bib --no-pdf    # skip PDF downloads
```

Papers are deduplicated by citekey. arXiv papers are auto-enriched with full metadata.

## After Reading a Paper

```bash
alit status vaswani2017attention read

alit note vaswani2017attention "Key insight: self-attention replaces recurrence entirely. O(1) sequential ops for long-range deps."

alit summarize vaswani2017attention --l4 "Transformer replaces recurrence with self-attention, achieving BLEU SOTA with greater parallelism." --model "claude-opus-4-6"

alit summarize vaswani2017attention --l2 '["Self-attention O(1) vs RNN O(n)", "Multi-head attention for subspace diversity", "28.4 BLEU on WMT EN-DE"]' --model "claude-opus-4-6"

alit cite vaswani2017attention bahdanau2014attention --type extends
```

## Citation Verification

When you add citations, the cited paper doesn't have to exist yet. Use `alit orphans` to find missing papers:

```bash
alit orphans
# Output: vaswani2017attention --[extends]--> bahdanau2014attention  (MISSING)
```

**Workflow**: After adding all citations for a paper, run `alit orphans`. For each missing paper, search online (arXiv, Google Scholar) to verify it exists, then `alit add` it to the collection. This ensures your citation graph is complete and accurate.

## Searching and Synthesis

```bash
alit search "limit order book simulation"

alit ask "What generative models exist for LOB data?" --depth 2
```

Depth controls token budget:
- `--depth 1`: titles + one-liners (~500 tokens)
- `--depth 2`: + abstracts for top-10 (~2.5K tokens) — DEFAULT
- `--depth 3`: + key claims for top-3 (~3.5K tokens)
- `--depth 4`: + full notes for top-1 (~5K tokens)

## Recommendations

```bash
alit recommend 5

alit purpose "Research on generative models for limit order book simulation, market microstructure, and agent-based financial systems"
alit recommend 5
```

## All Commands

| Command | What it does |
|---------|-------------|
| `alit init` | Create papers.db |
| `alit add <title-or-url>` | Add paper (auto-enriches arXiv URLs, auto-tags from abstract) |
| `alit find <query>` | Search arXiv/S2 for papers by topic |
| `alit import <file> [--bib]` | Bulk-add from URL file or BibTeX (.bib) |
| `alit read <id>` | Guided reading view with citations |
| `alit progress` | Visual progress dashboard |
| `alit enrich` | Batch-fetch metadata for papers missing abstracts |
| `alit show <id>` | Paper details |
| `alit list [--status X]` | List papers |
| `alit search <query>` | BM25 search |
| `alit note <id> <text>` | Append notes |
| `alit summarize <id> --l4/--l2` | Store summary with provenance |
| `alit cite <from> <to>` | Add citation edge |
| `alit status <id> <status>` | Set reading status |
| `alit tag <id> <tags>` | Set tags |
| `alit recommend [N]` | Reading recommendations |
| `alit ask <question>` | Cross-paper synthesis |
| `alit stats` | Collection overview |
| `alit delete <id>` | Remove paper |
| `alit purpose <text>` | Set research purpose |
| `alit attach <id> <path>` | Attach local PDF to paper |
| `alit orphans` | List citations to papers not in collection |
| `alit fetch-pdf <id>` | Download PDF for existing paper |
| `alit export [--format X]` | Export as JSON or shareable markdown |

All commands support `--json` for machine-readable output.

## Conventions

- **IDs**: lowercase, no spaces (e.g. `vaswani2017attention`). Auto-generated if omitted.
- **Status**: unread → skimmed → read → synthesized
- **Citation types**: cites, extends, contradicts, uses_method, uses_dataset, surveys
- **Provenance**: always pass `--model` when summarizing — it's tracked
- **PDFs**: auto-downloaded from arXiv, or attached from local files via `--pdf` or `alit attach`
- **Orphan citations**: `alit orphans` shows cited papers not in collection — verify and add them
