# Tripartite DataSTORE — Agent Onboarding Prompt

> **Paste this into a new conversation to onboard the agent on the codebase.**
> The agent has direct file access — this prompt navigates them to what matters.

---

## WHO YOU ARE AND WHAT THIS APP IS

You are working on **Tripartite DataSTORE**, a Python 3.11+ desktop application (Tkinter GUI + CLI) that ingests files into a portable SQLite knowledge store with 4 layers: **verbatim** (exact lines), **semantic** (chunks + embeddings), **graph** (entities + relationships), and **temporal** (version diffs). The store is a single `.db` file that can be transported via flash drive.

The app has a **pluggable curation tool system** (`BaseCurationTool`) that allows drop-in tools for deduplication, reorganization, transformation, and export. This is the primary extension point for new functionality.

**Repo root:** `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataSTORE`
**Branch:** `sleepy-chatelet-integration`
**Entry point:** `python -m tripartite.datastore` (GUI) or `tripartite-ingest` (CLI)

---

## CRITICAL: READ THESE FILES FIRST

Before writing ANY code, read these files to understand the architecture:

1. **`tripartite/db/schema.py`** — The authoritative database schema. Every column name in your SQL MUST match this file exactly. Previous bugs were caused by agents writing SQL with wrong column names.

2. **`tripartite/datastore.py`** (~3500 lines) — Main GUI app. Has 3-column layout: sidebar (explorer/DB list/graph) | center (ViewerStack) | right workspace (Query/Ingest/Curate/Export/Patch tabs + output log).

3. **`tripartite/config.py`** — Model registry, chunking tuning, edge types, source type detection rules.

4. **`tripartite/pipeline/ingest.py`** — The 9-stage ingest pipeline. This is the CORRECT way to store data. Never write raw INSERT SQL for ingestion — always use `_ingest_file()` or the stage helpers.

---

## ARCHITECTURE OVERVIEW

```
datastore.py (GUI shell + wiring, ~3500 lines)
  ├── explorer.py        — HierarchyExplorer widget, TreeItem dataclass
  ├── viewer.py          — Standalone viewer app (Browse/Search/Graph)
  ├── export.py          — File reconstruction + structured export
  ├── hitl.py            — Human-in-the-loop gateway (confirm/choose/review_queue)
  ├── diff_engine.py     — Layer 4 temporal versioning
  ├── tokenizing_patcher.py — Whitespace-immune patching
  ├── settings_dialog.py — Model picker UI
  ├── settings_store.py  — Persistent JSON settings
  │
  ├── pipeline/
  │   ├── ingest.py      — Orchestrator: ingest() and _ingest_file()
  │   ├── detect.py      — Source file detection + directory walking
  │   ├── verbatim.py    — Line dedup, tree building, source_files records
  │   ├── manifest.py    — Chunk manifest: CID hashing, context prefix, hierarchy
  │   ├── embed.py       — Embedding stage (batched, model-managed)
  │   └── extract.py     — Entity extraction + graph write
  │
  ├── chunkers/
  │   ├── base.py        — Chunker ABC, Chunk dataclass, SpanRef dataclass
  │   ├── treesitter.py  — 20+ languages (primary chunker)
  │   ├── compound.py    — Multi-file dump detection
  │   ├── code.py        — Python AST fallback
  │   └── prose.py       — Markdown/text chunking
  │
  ├── models/
  │   └── manager.py     — HuggingFace model download + cache management
  │
  └── db/
      ├── schema.py      — DDL + open_db() + migrations
      └── query.py       — Query helpers for viewer
```

---

## DATABASE SCHEMA (CRITICAL REFERENCE)

**WARNING:** Previous sessions had massive bugs from using wrong column names. Always verify against this.

### Layer 1: Verbatim
- **`verbatim_lines`**: `line_cid` (PK), `content`, `byte_len`, `created_at`
- **`source_files`**: `file_cid` (PK), `path`, `name`, `source_type`, `language`, `encoding`, `line_count`, `byte_size`, `line_cids` (JSON array), `ingested_at`, `pipeline_ver`

### Logical Tree
- **`tree_nodes`**: `node_id` (PK), `node_type`, `name`, `parent_id`, `path`, `depth`, `file_cid`, `line_start`, `line_end`, `language_tier`, `chunk_id`, `graph_node_id`, `diff_chain_head`, `created_at`, `updated_at`

### Layer 2: Semantic
- **`chunk_manifest`**: `chunk_id` (PK), `node_id`, `chunk_type`, `context_prefix`, `token_count`, `spans` (JSON), `hierarchy` (JSON), `overlap` (JSON), `semantic_depth`, `structural_depth`, `language_tier`, `embed_status`, `embed_model`, `embed_dims`, `embed_error`, `graph_status`, `chunker`, `pipeline_ver`, `ingested_at`
- **`embeddings`**: `chunk_id` (PK), `model`, `dims`, `vector` (BLOB, float32 LE)

**`chunk_manifest` does NOT have:** `content`, `name`, `heading_path`, `embedding` columns. Text is reconstructed from `spans` JSON → `verbatim_lines`.

### Layer 3: Knowledge Graph
- **`graph_nodes`**: `node_id` (PK), `node_type`, `label` (NOT `name`), `entity_type`, `chunk_id`, `salience`, `created_at`
- **`graph_edges`**: `edge_id` (PK), `src_node_id` (NOT `source_id`), `dst_node_id` (NOT `target_id`), `edge_type` (NOT `relation`), `weight`, `predicate`, `created_at`

### Layer 4: Temporal
- **`diff_chain`**: `diff_id` (PK), `node_id`, `parent_diff`, `timestamp`, `changes` (JSON)
- **`snapshots`**: `snapshot_id` (PK), `node_id`, `timestamp`, `line_cids` (JSON)

### FTS + Logging
- **`fts_lines`**: FTS5 on verbatim line content
- **`fts_chunks`**: FTS5 on context_prefix + chunk_text
- **`ingest_runs`**: `run_id`, `started_at`, `completed_at`, `source_root`, `files_processed`, `chunks_created`, `chunks_embedded`, `status`, `error`

---

## HOW TO RECONSTRUCT CHUNK TEXT

There is NO `content` column on `chunk_manifest`. To get chunk text:

```python
# In datastore.py, use the existing helper:
text = self._reconstruct_chunk_text(chunk_id)

# Or manually:
# 1. Read spans JSON from chunk_manifest
# 2. For each span: get source_cid, line_start, line_end
# 3. Look up line_cids from source_files
# 4. Fetch verbatim_lines by line_cid
# 5. Join in order
```

See `datastore.py` method `_reconstruct_chunk_text()` (~line 2077) for the implementation.

---

## CURATION TOOL SYSTEM (PRIMARY EXTENSION POINT)

All 3 phases of the user's work involve building **curation tools** that plug into the Curate tab.

### How to create a curation tool:

1. Create `tripartite/curate_tools/` package (if it doesn't exist yet)
2. Add `__init__.py`
3. Create a module per tool (e.g., `dedup_tool.py`)
4. Each tool subclasses `BaseCurationTool`:

```python
# tripartite/curate_tools/dedup_tool.py
from tripartite.datastore import BaseCurationTool
import tkinter as tk
import sqlite3

class DeduplicationTool(BaseCurationTool):
    @property
    def name(self) -> str:
        return "Deduplicate Files"

    @property
    def description(self) -> str:
        return "Find and remove duplicate files based on content hash"

    @property
    def icon(self) -> str:
        return "🔍"

    @property
    def priority(self) -> int:
        return 10  # Lower = higher in tool list

    def build_config_ui(self, parent: tk.Frame) -> tk.Frame:
        frame = tk.Frame(parent)
        # Add config widgets here
        return frame

    def run(self, conn: sqlite3.Connection, selection,
            on_progress=None, on_log=None) -> dict:
        # Do the work here
        # Use on_progress(pct) for progress bar
        # Use on_log(msg, tag) for curate log output
        # Return results dict
        return {"duplicates_found": 0, "removed": 0}
```

### Tool discovery:

`discover_tools()` in `datastore.py` (line ~148) scans `curate_tools/` for `BaseCurationTool` subclasses and auto-populates the Curate tab dropdown. Tools are sorted by `priority`.

### Tool execution flow:

1. User selects tool from Curate tab dropdown
2. Tool's `build_config_ui()` renders in the config area
3. User clicks "Run Tool"
4. HITL gateway confirms execution
5. Tool's `run()` executes with DB connection + progress callbacks
6. Results displayed in curate log

---

## EXPORT SYSTEM

**`tripartite/export.py`** provides:

- `export_to_files(conn, output_dir, on_progress)` — Reconstructs original files from verbatim layer
- `export_with_structure(conn, output_dir, preserve_paths, on_progress)` — Preserves directory hierarchy
- `export_json(conn, output_dir, ...)` — Full graph + metadata as JSON

The Export tab in the GUI (built by `_build_export_tab()` in datastore.py ~line 1255) lets users pick format and destination.

---

## INGEST PIPELINE

**Never write raw INSERT SQL for ingestion.** Use the pipeline:

```python
from tripartite.pipeline.ingest import ingest, _ingest_file
from tripartite.pipeline.detect import walk_source, detect

# Top-level (whole directory):
result = ingest(source_root=Path(...), db_path=Path(...), lazy=False)

# Per-file (inside a connection):
source = detect(file_path)
chunks_created, chunks_embedded = _ingest_file(conn, source, lazy=False)
```

**Pipeline stages** (in order): detect → verbatim write → tree build → chunk → assign CIDs → write manifest → embed → extract graph → log run

**Supported source types:** Code (20+ languages via tree-sitter), Prose (markdown/text), Structured (JSON/YAML/XML/CSV), Compound (concatenated dumps)

---

## HITL GATEWAY

All destructive or significant operations should go through `hitl.py`:

```python
# In datastore.py, self.hitl is the gateway instance
if self.hitl.confirm("Delete Files", f"Remove {count} duplicates?", destructive=True):
    # proceed

choice = self.hitl.choose("Pick Format", "Export as:", ["JSON", "CSV", "Markdown"])

result = self.hitl.review_queue(items)  # Batch review UI
```

---

## KEY DATACLASSES

### TreeItem (from explorer.py)
```
node_id, node_type, name, parent_id, path, depth, file_cid,
line_start, line_end, language_tier, chunk_id, token_count,
embed_status, semantic_depth, structural_depth, context_prefix, children
```

### SpanRef (from chunkers/base.py)
```
source_cid, line_start, line_end, char_start, char_end
```
**WARNING:** Uses `line_start`/`line_end`, NOT `.start`/`.end`

### Chunk (from chunkers/base.py)
```
chunk_type, source, spans (list[SpanRef]), context_prefix,
hierarchy (dict), overlap (dict)
```
Has `.text` property that reconstructs from `source.lines` via spans.

---

## COMMON PITFALLS (BUGS WE ALREADY FIXED)

1. **`chunk_manifest` has no `content` column** — use `_reconstruct_chunk_text()` or spans → verbatim_lines
2. **`graph_nodes` uses `label` not `name`** — `gn.label`, not `gn.name`
3. **`graph_edges` uses `src_node_id`/`dst_node_id`/`edge_type`** — not `source_id`/`target_id`/`relation`
4. **`embeddings` is a separate table** — not a column on `chunk_manifest`
5. **SpanRef uses `line_start`/`line_end`** — not `.start`/`.end`
6. **Always use `open_db()`** from `db/schema.py` to create/open databases — not raw `sqlite3.connect()`
7. **Pipeline functions handle all storage** — never write INSERT SQL for ingestion manually

---

## THE USER'S 3-PHASE ROADMAP

The user has 3 integration phases planned (one per conversation):

### Phase 1: Office Document Migration
- Ingest ALL documents from old office PC into a .db
- Build curation tools: **dedup** (content-hash based), **folder reorganizer** (new hierarchy), **Word doc transformer**, **cleanup** (remove junk files)
- Export clean folder structure to flash drive → inject into new PC's Documents folder
- **Key extension points:** New curation tools in `curate_tools/`, enhanced export with restructured paths

### Phase 2: Thunderbird Email Migration
- Ingest Thunderbird profile directory (mbox/maildir format)
- **Requires:** New ingest source type for email (detect.py + new chunker for email messages)
- Build curation tools: **email dedup**, **garbage filter**, **client-email keeper**
- Export emails in reimportable format (mbox, EML, or target mail client format)
- **Key extension points:** New chunker in `chunkers/`, new source_type in `config.py`, custom export format

### Phase 3: Helper Script Decomposition
- Ingest the user's collection of utility scripts
- Parse and separate: **logic**, **wiring/glue code**, **UI components**
- Export as modularly reconstitutable components
- **Key extension points:** Enhanced tree-sitter analysis, new export format that preserves dependency graph

---

## HOW TO LOG AND REPORT PROGRESS

```python
# Main output log (visible in Output tab):
self._log("Source", "Message text", "tag")
# Tags: "dim" (gray), "accent" (blue), "warning" (yellow), "error" (red)

# Ingest log (visible in Ingest tab):
self._ingest_log_append("Message", "tag")

# Curate log (visible in Curate tab):
self._curate_log_append("Message", "tag")

# Status bar:
self._update_status("Processing...", "curate")
```

---

## THREAD SAFETY

- `self._db_lock = threading.Lock()` exists on the app instance
- Background operations (ingest, curate, export) run in threads
- Always use `self.root.after(0, callback)` to update UI from background threads
- The `_log`, `_ingest_log_append`, and `_curate_log_append` methods are already thread-safe

---

## QUICK START FOR THE AGENT

1. Read `tripartite/db/schema.py` to internalize the schema
2. Read `tripartite/datastore.py` lines 116-194 for `BaseCurationTool` and `discover_tools()`
3. Read `tripartite/pipeline/ingest.py` for the pipeline flow
4. Read `tripartite/config.py` for source type detection and model config
5. Check if `tripartite/curate_tools/` exists — if not, create it with `__init__.py`
6. Build the curation tool(s) needed for the current phase
7. Test by running `python -m tripartite.datastore`
