# Tripartite Knowledge Store

A local-first, offline, portable tool that ingests files into a structured SQLite knowledge artifact — organized across three memory layers simultaneously.

---

## What It Does

Point Tripartite at a folder or file and it produces a single `.tripartite.db` file containing your content three ways:

- **Verbatim** — every line of every file, content-addressed and deduplicated. Identical lines across different files are stored exactly once.
- **Semantic** — vector embeddings of every chunk, ready for meaning-based similarity search.
- **Graph** — entities and relationships extracted from your content, stored as a typed knowledge graph.

The output artifact is fully self-contained and portable. No server required. No cloud. Models download once to `~/.tripartite/models/` and run completely offline from then on.

---

## Requirements

- Python 3.11+
- `llama-cpp-python` — provides both embedding and entity extraction

```bash
pip install llama-cpp-python
```

For GPU acceleration (optional, CPU works fine):
```bash
CMAKE_ARGS="-DLLAMA_CUDA=on" pip install llama-cpp-python
```

---

## Installation

```bash
git clone <your-repo>
cd _TripartiteDataStore
pip install -e .
```

---

## First Run

The first time you run an ingest, two models will be downloaded automatically to `~/.tripartite/models/`:

| Model | Role | Size |
|---|---|---|
| `nomic-embed-text-v1.5.Q4_K_M.gguf` | Embedder | ~80 MB |
| `qwen2.5-0.5b-instruct-q4_k_m.gguf` | Entity extractor | ~398 MB |

Subsequent runs are fully offline.

---

## Usage

### GUI (recommended)

```bash
python -m tripartite.gui
```

1. Click **Pick Folder** or **Pick File** to select your source
2. The output `.db` path is auto-filled — edit if needed
3. Click **▶ Run Ingest**
4. Watch the live log and progress bars
5. DB stats appear in the footer when complete

**Options:**
- **Show chunk stream** — opens a second window showing each chunk as it is produced, with full hierarchy breadcrumbs, line spans, and token counts. The stream can be saved to a `.txt` log file.
- **⚙ Settings** — select which embedding and extraction models to use, download models, and access diagnostic options.

### CLI

```bash
tripartite-ingest <source> [--output <path>] [--lazy] [--verbose]
```

```bash
# Ingest a folder
tripartite-ingest ./my_project

# Ingest a single file
tripartite-ingest ./notes.md --output notes.db

# Structural pass only (no embedding or entity extraction — fast, for testing)
tripartite-ingest ./my_project --lazy

# Inspect an existing .db
tripartite-ingest ./my_project.tripartite.db --info
```

---

## What Gets Ingested

| File type | Chunking strategy |
|---|---|
| `.py` | AST-based — functions, classes, methods, import blocks, module summary |
| `.md`, `.markdown` | Heading-aware — document summary + one chunk per heading section |
| `.txt`, `.rst`, `.adoc` | Paragraph-based — blank-line boundaries, sliding window for large sections |
| `.js`, `.ts`, `.go`, `.rs`, `.java`, `.rb`, and most other code | Prose chunker (heading/paragraph fallback) |
| `.json`, `.yaml`, `.toml`, `.csv` | Prose chunker |

**Skipped automatically:** binary files, hidden files and directories, `__pycache__`, `.git`, `node_modules`, `.venv`, and common build output directories.

---

## Output Schema

The `.tripartite.db` file is a standard SQLite database. You can open it with any SQLite browser or query it directly.

```
verbatim_lines     — every unique line of content, content-addressed
source_files       — one row per ingested file, with ordered line CID index
tree_nodes         — logical hierarchy (file → class → method etc.)
chunk_manifest     — central join table: chunk metadata + span references
embeddings         — raw float32 embedding vectors (768-dim by default)
graph_nodes        — entities and chunk nodes
graph_edges        — typed relationships (MENTIONS, PART_OF, PRECEDES, ...)
fts_chunks         — FTS5 full-text index over chunk content
fts_lines          — FTS5 full-text index over verbatim lines
ingest_runs        — log of every ingest run with counts and timing
```

### Reconstructing chunk text

Chunks do not store text directly — text is always reconstructed from the verbatim layer:

```python
import sqlite3, json

conn = sqlite3.connect("my_project.tripartite.db")

# Get a chunk
chunk = conn.execute(
    "SELECT spans FROM chunk_manifest LIMIT 1"
).fetchone()

spans = json.loads(chunk["spans"])
for span in spans:
    # Get ordered line CIDs for this file
    file_row = conn.execute(
        "SELECT line_cids FROM source_files WHERE file_cid = ?",
        (span["source_cid"],)
    ).fetchone()

    line_cids = json.loads(file_row["line_cids"])
    chunk_cids = line_cids[span["line_start"] : span["line_end"] + 1]

    # Fetch the actual lines
    placeholders = ",".join("?" * len(chunk_cids))
    lines = conn.execute(
        f"SELECT line_cid, content FROM verbatim_lines WHERE line_cid IN ({placeholders})",
        chunk_cids
    ).fetchall()

    # Reassemble in order
    cid_to_content = {r["line_cid"]: r["content"] for r in lines}
    text = "\n".join(cid_to_content[c] for c in chunk_cids)
    print(text)
```

---

## Model Settings

Open **⚙ Settings** in the GUI to choose from the available models:

**Embedders:**
| Model | Dims | Size | Notes |
|---|---|---|---|
| Nomic Embed Text v1.5 (Q4_K_M) | 768 | ~80 MB | Default. Fast, good all-round quality. |
| MixedBread Embed Large v1 (Q4_K_M) | 1024 | ~670 MB | Higher quality, better for technical docs. |
| All-MiniLM L6 v2 (Q4_K_M) | 384 | ~22 MB | Tiny and very fast. Good for large codebases. |

**Extractors:**
| Model | Size | Notes |
|---|---|---|
| Qwen 2.5 0.5B Instruct (Q4_K_M) | ~398 MB | Default. Fast, lower extraction accuracy. |
| Qwen 2.5 1.5B Instruct (Q4_K_M) | ~1 GB | Better entity extraction quality. |

> ⚠ **Model mismatch warning:** If you re-ingest files into an existing `.db` with a different embedder than was used originally, the new vectors will be incompatible with the old ones and semantic search results will be unreliable. The GUI will warn you before proceeding.

---

## Development

```bash
# Run tests (no models required — runs in lazy mode)
pytest

# Run with verbose output
pytest -v
```

Tests cover: file detection and walking, Python AST chunking, prose chunking, full lazy-mode pipeline ingest, verbatim deduplication, manifest integrity, span JSON validity, and CID correctness. 36 tests, all passing on CPU without any model downloads.

---

## Project Structure

```
_TripartiteDataStore/
├── pyproject.toml
├── README.md
├── DEVJOURNAL.md          ← development history and architecture notes
└── tripartite/
    ├── cli.py             ← command-line entry point
    ├── gui.py             ← Tkinter GUI
    ├── chunk_viewer.py    ← live chunk stream viewer window
    ├── settings_store.py  ← persistent settings (model selection etc.)
    ├── settings_dialog.py ← settings UI
    ├── config.py          ← model registry, paths, pipeline constants
    ├── utils.py           ← hashing, token estimation, CID helpers
    ├── chunkers/
    │   ├── base.py        ← Chunk dataclass, BaseChunker
    │   ├── code.py        ← Python AST chunker
    │   └── prose.py       ← Markdown/text chunker
    ├── db/
    │   └── schema.py      ← SQLite DDL and connection factory
    ├── models/
    │   └── manager.py     ← model download, caching, llama-cpp loading
    └── pipeline/
        ├── detect.py      ← source type detection and normalization
        ├── embed.py       ← embedding stage
        ├── extract.py     ← entity extraction and graph writing
        ├── ingest.py      ← pipeline orchestrator
        ├── manifest.py    ← chunk manifest writer
        └── verbatim.py    ← verbatim layer writer and tree builder
```

---

## Cache Directory

All models and settings are stored in `~/.tripartite/`:

```
~/.tripartite/
├── settings.json          ← selected models and preferences
└── models/
    ├── nomic-embed-text-v1.5.Q4_K_M.gguf
    ├── qwen2.5-0.5b-instruct-q4_k_m.gguf
    └── ...
```

Set the `TRIPARTITE_CACHE` environment variable to use a different location.

---

## License

MIT
