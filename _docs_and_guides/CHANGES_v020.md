# Tripartite v0.2.0 — Structural Layer: Language-Tier-Aware Hierarchy

## Overview

This update adds **language-tier-aware hierarchy handling** to the Tripartite
structural layer.  Every chunk now carries three new metadata fields that
distinguish *semantic* depth from *structural* depth and classify the source
language into one of four tiers.

## New Fields on Every Chunk

| Field | Type | Meaning |
|---|---|---|
| `semantic_depth` | int | Meaningful nesting in code hierarchy (0 for data/markup) |
| `structural_depth` | int | Raw AST nesting depth regardless of semantic meaning |
| `language_tier` | text | `deep_semantic` \| `shallow_semantic` \| `structural` \| `hybrid` \| `unknown` |

## The Four Tiers

| Tier | Languages | Strategy | Semantic Depth |
|---|---|---|---|
| `deep_semantic` | Python, JS, TS, Java, Go, Rust, C++, C#, Kotlin, Scala, Swift | Hierarchical (class→method→nested) | Matches structural depth |
| `shallow_semantic` | Bash, R, Ruby, PHP, C | Flat (functions only) | Capped at 1 |
| `structural` | JSON, YAML, TOML | Top-level keys/sections | Always 0 |
| `hybrid` | HTML, CSS, XML | Semantic elements / rulesets | Always 0 |

## Files Modified (7 total)

### Drop-in Replacements

Copy each file to the corresponding location in your project:

```
tripartite_update/                   →  tripartite/
├── chunkers/
│   ├── base.py                      →  chunkers/base.py
│   └── treesitter.py                →  chunkers/treesitter.py
├── db/
│   ├── schema.py                    →  db/schema.py
│   └── query.py                     →  db/query.py
└── pipeline/
    ├── ingest.py                    →  pipeline/ingest.py
    ├── manifest.py                  →  pipeline/manifest.py
    └── verbatim.py                  →  pipeline/verbatim.py
```

### What Changed in Each File

**`chunkers/base.py`**
- Added `semantic_depth`, `structural_depth`, `language_tier` fields to the
  `Chunk` dataclass with sensible defaults (0, 0, "unknown").
- No changes to `SpanRef`, `BaseChunker`, or `_link_siblings`.

**`chunkers/treesitter.py`** (largest change)
- Added `LANGUAGE_TIERS` configuration dict and `get_language_tier()` helper.
- `TreeSitterChunker.__init__` now stores `self.tier_config`.
- `chunk()` now dispatches to one of four strategy methods based on tier:
  - `_chunk_hierarchical()` — reuses existing extraction helpers, annotates
    chunks with `semantic_depth = depth`.
  - `_chunk_flat()` — skips class extraction, caps `semantic_depth` at 1.
  - `_chunk_structural()` — NEW: extracts top-level JSON keys, YAML mapping
    pairs, TOML tables. Sets `semantic_depth = 0`.
  - `_chunk_markup()` — NEW: extracts semantic HTML5 elements (`<header>`,
    `<main>`, `<section>`, etc.), CSS rule sets, XML top-level elements.
    Sets `semantic_depth = 0`.
- All existing extraction helpers (`_extract_imports`, `_extract_classes`,
  `_extract_methods`, `_extract_functions`) are unchanged.
- `_fallback_line_chunker` now sets tier fields on fallback chunks.

**`db/schema.py`**
- `SCHEMA_SQL` now includes `semantic_depth`, `structural_depth`,
  `language_tier` columns on `chunk_manifest` and `language_tier` on
  `tree_nodes`, with corresponding indexes.
- `open_db()` now calls `_migrate_v020_tier_columns()` after schema creation.
- Migration is safe to run repeatedly — uses `PRAGMA table_info` to detect
  existing columns and only ALTERs if missing.
- Backfill logic populates existing rows based on `chunker` name patterns.

**`db/query.py`**
- `get_chunks_for_file()` and `get_chunk_detail()` now return the three new
  fields.
- NEW: `get_chunks_by_tier()` — filter chunks by tier, depth range, and type.
- NEW: `get_tier_summary()` — chunk counts grouped by tier (for sidebar stats).
- NEW: `get_file_tree()` — full tree_nodes dump with tier info (for explorer).
- `get_db_stats()` now includes `tier_summary`.

**`pipeline/manifest.py`**
- `write_manifest()` INSERT now includes the three new columns.
- Hierarchy JSON blob also includes the tier fields (redundant but backward
  compatible — older viewers that only read the JSON still work).

**`pipeline/verbatim.py`**
- `build_tree()` now writes `language_tier` to every `tree_nodes` record.
- File-level node inherits tier from its first chunk.

**`pipeline/ingest.py`**
- Added `_TREESITTER_EXTRA_EXTENSIONS` set for JSON, YAML, TOML, HTML, CSS, XML.
- `_get_chunker()` now tries tree-sitter for structured and markup files, not
  just code files. This is what makes the tier system actually activate for
  those file types.
- Chunker version string bumped to `_v2` for tree-sitter routed files.

## Files NOT Modified

These files are unchanged and don't need updating:

- `chunkers/code.py` — PythonChunker (still used as fallback)
- `chunkers/prose.py` — ProseChunker (still used for markdown/text)
- `chunkers/__init__.py` — exports are fine as-is
- `pipeline/detect.py` — source type detection unchanged
- `pipeline/embed.py` — embedding logic unchanged
- `pipeline/extract.py` — entity extraction unchanged
- `config.py` — no changes needed
- `utils.py` — no changes needed
- All viewer/GUI files — no changes needed (they'll show new data automatically
  once the query layer surfaces it)

## Migration for Existing Databases

**Automatic.** When `open_db()` opens an existing database, it detects missing
columns and runs the migration transparently. Existing chunk data gets
backfilled with best-guess tier assignments based on the `chunker` field.

To get full-quality tier metadata on existing data, re-ingest the files:
```bash
python -m tripartite.cli ingest /path/to/source --db existing.db
```

## Testing

After dropping in the files, verify with a quick ingest:

```python
from tripartite.pipeline.ingest import ingest

# Ingest a mixed folder with .py, .json, .html, .sh files
result = ingest(Path("./test_folder"), Path("./test.db"), lazy=True)

# Check tier distribution
from tripartite.db.schema import open_db
from tripartite.db.query import get_tier_summary

conn = open_db(Path("./test.db"))
print(get_tier_summary(conn))
# Expected: {'deep_semantic': {...}, 'structural': {...}, 'hybrid': {...}, ...}
```

## What's Next

With this structural layer in place, the explorer/tree view can now:
1. Query `get_file_tree()` to build the tree widget
2. Use `language_tier` on each node to decide rendering strategy
3. Filter views by tier (e.g., "show only code" vs "show only config")
4. Display semantic depth badges to indicate nesting significance
