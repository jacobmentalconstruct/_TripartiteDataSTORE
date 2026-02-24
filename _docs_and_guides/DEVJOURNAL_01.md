# Tripartite — Development Journal
*February 24, 2026*

---

## The Idea

It started with a design document. Two whitepapers, actually — a coherent ingestion architecture spec and a broader tripartite memory whitepaper — describing a local-first knowledge store that would hold files three ways simultaneously: verbatim (exact text, content-addressed line by line), semantic (vector embeddings for meaning-based retrieval), and relational (a knowledge graph of entities and relationships). Everything in a single portable `.db` file. No cloud, no API keys, no server. Models download once and run forever offline.

The prompt that kicked it off was essentially: *"Here are my whitepapers. Build it."*

---

## Session 1 — Building the Pipeline from Scratch

The first Claude instance read both whitepapers and immediately started laying down structure. The very first command it ran:

```bash
mkdir -p /home/claude/tripartite/{db,models,pipeline,chunkers}
```

Which promptly failed because the subdirectories didn't exist yet. A small omen of the debugging to come, and also a reminder that even the beginning of things is iterative.

Within that first session, an entire working pipeline was built from nothing:

**The schema** — 10 SQLite tables, carefully normalized across the three layers. `verbatim_lines` as the immutable content-addressed foundation. `source_files` holding ordered JSON arrays of line CIDs. `tree_nodes` as the logical hierarchy backbone. `chunk_manifest` as the central join record tying everything together. `embeddings` holding raw float32 blobs. `graph_nodes` and `graph_edges` for the knowledge graph. `fts_chunks` and `fts_lines` as FTS5 virtual tables for keyword fallback. The whole thing designed so each layer could be rebuilt independently without touching the others.

**The chunkers** — a Python AST-based chunker that walks the syntax tree and produces `function_def`, `class_def`, `method_def`, `import_block`, and `module_summary` chunks with full breadcrumb paths. A prose chunker that splits on ATX headings for Markdown and blank-line boundaries for plain text, with a sliding token window for sections that exceed the 512-token budget. Both producing `Chunk` objects with span references back to the verbatim layer — never storing text directly in the semantic layer.

**The pipeline** — 9 stages: detect → chunk → verbatim write → tree build → CID hash → context prefix → embed → entity extract → manifest write. Each stage isolated and testable. The whole thing orchestrated by `ingest.py`.

**The model manager** — download-on-first-run with a progress hook, size-based verification (SHA256 was abandoned early because HuggingFace model hashes change with updates), and sentinel flags to prevent retry loops on failure.

**The CLI** — `tripartite-ingest <source> [--lazy] [--output]` with a `--info` flag to inspect existing databases.

**36 tests, all passing.**

The session ended with a fully functional command-line tool. No GUI yet, but the engine was running.

---

## Session 2 — Getting It Actually Installed

First real-world encounter: `pip install -e .` failed immediately.

```
Cannot import 'setuptools.backends.legacy'
```

Wrong build backend string in `pyproject.toml`. Fixed to `"setuptools.build_meta"`.

Then: package structure was wrong. Source files were at the root instead of inside the `tripartite/` subdirectory, so all the relative imports were broken. A `reorganize.py` script was written to automate the restructuring — move files, create `__init__.py` files in every subdirectory, delete the stale egg-info.

Then: model download loops. The pipeline would start, download a model, verify it, fail verification, delete it, and re-download. Three times per run. Root cause was threefold: fake placeholder SHA256 hashes in the config that always failed, a sentinel flag that only got set inside the `Llama()` constructor try/except (so if `ensure_model()` raised, the flag was never set), and size thresholds set way too high for nomic-embed-text, which is only ~80 MB at Q4_K_M quantization.

Three-part fix: remove SHA256 entirely and use size-only verification, wrap the entire `get_embedder()` body in a single try/except to guarantee sentinel is set on any failure, lower the embedder threshold from 200 MB to 50 MB.

First successful ingest: 3 files, 19 chunks, 0 embedded. The pipeline ran without crashing. Embeddings were still zeroing out due to another threshold issue — fixed, and the second run produced 19 chunks, 19 embedded.

---

## The GUI

"Can you make a Tkinter GUI for this?"

What came out was a full dark-themed application with a folder picker, output path auto-fill, a live scrolling log that captured stdout from the background ingest thread via a queue, and a stats bar showing DB size, chunk counts, embedding counts, graph nodes, and edges after completion.

Dark palette: `#1e1e2e` background, `#7c6af7` accent purple, `#5de4c7` teal for action buttons, `#a6e3a1` success green, `#f38ba8` error red. Borrowed color philosophy from Catppuccin Mocha.

The key architectural decision was thread safety: the ingest runs in a daemon thread, communicates back to Tkinter exclusively via a `queue.Queue`, polled every 50ms with `self.after()`. This is the only safe pattern for Tkinter — you cannot touch widgets from non-main threads.

---

## The Chunk Stream Viewer

"What about a popup window that shows each chunk as it's produced, building a monolithic scrolling dump?"

The `chunk_viewer.py` Toplevel window was born. Each chunk renders as a labeled block:

```
━━━━━━━━━━━━━━━━━━━━ function_def ━━━━━━━━━━━━━━━━━━━━━
  sample_app/app.py > class TabbedUI > _build_layout()
  lines 40–68  │  289 tokens  │  chunk 4 of 14
──────────────────────────────────────────────────────
    def _build_layout(self) -> None:
        self.root.grid_rowconfigure(1, weight=1)
        ...
══════════════════════════════════════════════════════
```

Header color changes by chunk type — teal for functions, purple for classes, green for summaries, blue for sections. A Save Log button exports the full stream to a `.txt` file. The `on_chunk` callback was threaded all the way down through `ingest()` → `_ingest_file()` so it fires per-chunk with source, chunk object, chunk ID, index, and total.

The first real chunk stream log was beautiful — watching the chunker correctly identify `README.md > document_summary`, then `README.md > Sample Tkinter Tabbed App > File Structure`, then `app.py > imports`, then `app.py > main()`, then 14 chunks of `ui.py` with full class hierarchy breadcrumbs. The architecture was working exactly as designed.

---

## Graceful Close, Status Bar, Settings

Three more features added in the final stretch of the session:

**Graceful close** — `WM_DELETE_WINDOW` protocol handler intercepts the X button and the new Exit button. If an ingest is running, it shows a warning dialog explaining that only the current file is at risk (already-processed files are safe due to per-file transactions), and asks for confirmation before killing the thread.

**Status bar** — Three rows pinned to the bottom of the window. Row 1: a `Files:` progress bar driven by `file_start` and `file_done` events from the pipeline, showing `File 2 of 4 (50%) — app.py` with a live elapsed clock ticking every second. Row 2: a `Chunks:` sub-progress bar driven by `embedding_progress` events showing `Embedding chunk 9 of 14 (64%)`. Row 3: the DB stats summary after a completed run. All driven by real events from the pipeline, not text parsing.

**Settings dialog** — A modal Toplevel with separate dropdowns for embedder model (Nomic Embed Text v1.5 Q4_K_M, MixedBread Embed Large v1, All-MiniLM L6 v2) and extractor model (Qwen 2.5 0.5B, Qwen 2.5 1.5B). Each row shows cache status (✓ Cached with file size, or ✗ Not downloaded) and a Download button that streams progress into an inline log within the dialog. Settings persist to `~/.tripartite/settings.json`. Model mismatch detection warns before any ingest run if the selected embedder differs from what the existing DB was built with.

---

## The Full Run

The final test run: 4 files, full mode (embedding + entity extraction), Show Chunk Stream checked.

```
Files processed : 4
Files skipped   : 0
Chunks created  : 94
Chunks embedded : 88
Time            : 630.48s
DB: 1.0 MB  │  Files: 4  │  Chunks: 88  │  Graph nodes: 106  │  Edges: 111
```

Ten and a half minutes. The chunk stream scrolled 94 blocks. The status bar tracked every file and every embedding. The DB stats appeared in the footer. The app closed cleanly.

There were two known issues to carry into the next session: the model reloading between prose files (6 of 94 chunks not embedded due to silent sentinel reset), and lazy mode being exposed as a main UI checkbox when it's really a developer diagnostic tool that belongs in Settings.

But the core system — verbatim + semantic + graph, local, offline, portable — was working.

---

## Architecture Decisions Worth Remembering

**Why spans instead of storing text directly in chunk_manifest?**
Three reasons: deduplication (identical lines across files share one `verbatim_lines` row), integrity (the verbatim layer is immutable and content-addressed — the semantic layer can be fully rebuilt without touching it), and diffing (the `diff_chain` table operates on `line_cid` arrays at the verbatim level).

**Why size verification instead of SHA256?**
HuggingFace model hashes change when the repository is updated. A hardcoded SHA256 would break on every model version bump. Size verification catches truncated downloads (the only real failure mode) without requiring hash maintenance.

**Why per-file transactions?**
If a file fails mid-pipeline, the whole file rolls back. Already-completed files are safe. This makes the tool resilient to crashes and interruptions — you can re-run on the same source and it will skip already-ingested files via the deduplication logic.

**Why a separate `embeddings` table instead of a column in `chunk_manifest`?**
`chunk_manifest` needs to be fast to scan for status queries. A 768-float blob (3072 bytes) on every row would make table scans dramatically slower. Keeping vectors in a separate table with a matching primary key lets you ignore them entirely for metadata queries.

**Why llama-cpp-python instead of an API or sentence-transformers?**
Fully offline. No Python dependency on a CUDA stack (sentence-transformers requires PyTorch). The GGUF format is compact, the quantized models are small, and llama-cpp-python is a single pip install. The whole toolchain works on CPU with no GPU required.

---

## What Comes Next

The ingest side is complete. The next session builds the viewer/query layer:

- A Browse panel showing the source file tree, with clickable chunks that reconstruct their text from the verbatim layer on demand
- A Search panel with both semantic search (cosine similarity against the embeddings) and FTS keyword search against `fts_chunks`, results ranked and merged
- A Graph panel showing entity nodes with type, salience, and which chunks they appear in

And two bug fixes: the model reload sentinel issue in `manager.py`, and moving lazy mode from the main UI into a Diagnostics section of Settings.

The `.db` artifact itself is already useful. Everything built on top of it is the interface to a knowledge store that already exists.

---

*Built in a single day across two conversation contexts, starting from two whitepapers and ending with a working local AI knowledge store. Total code across all files: approximately 3,998 lines.*
