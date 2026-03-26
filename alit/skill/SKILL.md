---
name: alit
version: "0.6.2"
description: "Persistent knowledge base for literature review. Use when the user wants to review academic papers, find what to read next, build on prior reading sessions, or answer research questions from collected papers. Handles arXiv URLs, BibTeX import, citation graphs, and reading recommendations. Do not use for non-academic documents, note-taking, or reference formatting."
---

# alit — Literature Review System

Data lives in `.alit/papers.db`. PDFs in `.alit/pdfs/`. Zero external dependencies.

## Session Start

Always begin a session with:

1. Run `alit progress` to see current state (papers, coverage, what needs work).
2. Run `alit scrub` to check for abstract-based summaries that need resetting. If any are found, run `alit scrub --apply` before proceeding.
3. Decide what to do: find new papers, read existing ones, or answer a question.

## Pipeline

Follow this order. Do not skip steps or mix phases.

### Phase 1: Find papers

1. Check if already in DB first: `alit show <arxiv_id_or_url>` — returns the paper if it exists, error if not.
2. Add new papers: `alit add "https://arxiv.org/abs/XXXX.XXXXX"` — auto-fetches metadata + PDF.
3. For non-arXiv papers: `alit add "Title" --year 2024 --authors "Smith" --abstract "..."`.
4. To bulk-add: `alit import papers.txt` (one arXiv URL per line) or `alit import library.bib` (BibTeX).
5. To search for papers by topic: `alit find "query"`.
6. After adding papers, run `alit enrich` to backfill any missing metadata.
7. Run `alit auto-cite` to extract citation edges from PDFs.

### Phase 2: Read papers

**PDF required.** Only read and summarize papers that have a downloaded PDF. Summaries must come from reading the full paper — never from the abstract alone.

1. Run `alit recommend 5` to pick what to read next. Papers with PDFs are marked 📄.
2. **Pick a paper that has a PDF.** If the top recommendation has no PDF, either run `alit fetch-pdf <id>` or skip to the next paper that does.
3. Run `alit read <id>` to see the paper's details. Confirm a PDF path is shown.
4. **Read the full PDF** using the Read tool on `.alit/pdfs/<filename>.pdf`. You MUST actually open and read the PDF file — do not skip this step.
5. Write notes and summaries **based on PDF content only**. Your L4 summary must reflect the paper's methods, results, and contributions — not just restate the abstract. Your L2 claims must reference specific findings, theorems, or experiments from the paper body.
6. After reading the full paper, store findings in this order:
   - `alit status <id> read`
   - `alit note <id> "key observations from the full paper..."` — mention specific sections, figures, tables, or results
   - `alit summarize <id> --l4 "one sentence summary" --model "<model-name>"`
   - `alit summarize <id> --l2 '["claim 1", "claim 2"]' --model "<model-name>"`
7. Always pass `--model` when summarizing.

**Self-check before summarizing:** If your summary could have been written from the abstract alone, you have not read the paper. Go back and read the PDF. A good summary includes details only found in the paper body (e.g., specific numbers, method details, ablation results, limitations discussed in later sections).

**Do not:**
- Mark a paper as `read` or `skimmed` based only on its abstract.
- Write L4/L2 summaries without reading the full PDF. The CLI will block this.
- Bulk-summarize papers that lack PDFs. Fetch PDFs first or skip them.
- Restate the abstract as a summary. Summaries must add value beyond the abstract.

### Phase 3: Verify citations

1. Run `alit orphans` to find cited papers not in the collection.
2. For each orphan, search online to verify it exists, then `alit add` it.
3. Run `alit auto-cite` again if new PDFs were added.

## Search and Synthesis

1. Run `alit search "query"` for BM25 full-text search.
2. Run `alit ask "research question" --depth 2` for cross-paper synthesis via funnel retrieval.
   - `--depth 1`: titles + one-liners (~500 tokens)
   - `--depth 2`: + abstracts for top-10 (~2.5K tokens)
   - `--depth 3`: + key claims for top-3 (~3.5K tokens)
   - `--depth 4`: + full notes for top-1 (~5K tokens)

## Setup (first time only)

1. Run `alit init` to create the database.
2. Run `alit taste "your research interests and what excites you"` to set recommendations.

## Commands

| Command | Description |
|---------|-------------|
| `alit init` | Create `.alit/papers.db` |
| `alit progress` | Visual progress dashboard |
| `alit taste [text]` | Set or show research taste |
| `alit add <title-or-url>` | Add paper (auto-enriches arXiv, auto-tags) |
| `alit show <id-or-arxiv>` | Paper details (accepts paper ID, arXiv ID, or URL) |
| `alit find <query>` | Search arXiv/S2 for papers by topic |
| `alit import <file>` | Bulk-add from URL file or BibTeX |
| `alit sync` | Import from remembered BibTeX source |
| `alit enrich` | Batch-fetch metadata for papers missing abstracts |
| `alit auto-cite` | Extract citations from PDFs automatically |
| `alit search <query>` | BM25 full-text search |
| `alit recommend [N]` | Reading queue ranked by score |
| `alit ask <question>` | Cross-paper synthesis |
| `alit read <id>` | Guided reading view |
| `alit list` | List papers (default 20, `--all` for full) |
| `alit note <id> <text>` | Append notes |
| `alit summarize <id>` | Store L4/L2 summary with `--model` provenance |
| `alit cite <from> <to>` | Add citation edge with `--type` |
| `alit status <id> <s>` | Set status: unread, skimmed, read, synthesized |
| `alit tag <id> <tags>` | Set comma-separated tags |
| `alit orphans` | List citations to missing papers |
| `alit attach <id> <pdf>` | Attach local PDF |
| `alit fetch-pdf <id>` | Download PDF from arXiv |
| `alit fetch-pdfs` | Batch-download all missing PDFs |
| `alit attach-dir <path>` | Scan directory and attach PDFs by arXiv ID |
| `alit delete <id>` | Remove paper + citations |
| `alit export [--format X]` | Export as JSON, markdown, or bib |
| `alit lint` | Check collection for data quality issues |
| `alit dedup` | Find and merge duplicate papers |
| `alit scrub` | Reset abstract-based summaries (dry run; `--apply` to execute) |

All commands support `--json` for machine-readable output.

## Quality Assurance

Run `alit scrub` to detect and reset summaries that were written from abstracts instead of full PDFs:
- Papers with no PDF that have summaries or read/skimmed status
- Papers where the L4 summary has >70% word overlap with the abstract
- Use `alit scrub --apply` to reset them (dry run by default)
- Use `alit scrub --threshold 0.5 --apply` to be stricter about overlap detection

Run `alit lint` after bulk operations to catch issues early:
- Truncated authors ("et al.")
- Missing locators (no url, doi, or arxiv_id)
- Empty venues, missing abstracts or PDFs
- Non-ASCII characters that may break pdflatex

The bib export (`alit export --format bib`) auto-handles:
- Unicode→LaTeX escaping (é → {\'e}) for pdflatex compatibility
- Entry type detection: `@inproceedings` for conferences, `@article` for journals
- Venue field: uses `booktitle` for conferences, `journal` for journals

## Conventions

- **IDs**: lowercase, no spaces (e.g. `vaswani2017attention`). Auto-generated if omitted.
- **Deduplication**: `alit add` merges if paper already exists — safe to call multiple times.
- **Status progression**: unread → skimmed → read → synthesized.
- **Citation types**: cites, extends, contradicts, uses_method, uses_dataset, surveys.
- **Provenance**: always pass `--model` when summarizing.
- **PDFs**: stored in `.alit/pdfs/`, auto-downloaded for arXiv papers.
- **Venue**: auto-populated from Semantic Scholar during `enrich`. Used for BibTeX entry type.
- **Check before adding**: `alit show <arxiv_id>` to avoid redundant work.
