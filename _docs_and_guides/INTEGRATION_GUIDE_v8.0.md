# Tripartite v0.3.0 → v0.3.1 Integration Patch

## Files Modified / Added

### 1. `tripartite/chunkers/compound.py` — **NEW** (was in outputs, now placed)
**Location:** `tripartite/chunkers/compound.py`
**Action:** Drop this file into your chunkers directory.

**P2 Hardening changes from the original:**

- **`_get_sub_chunker()` → Registry-based dispatch (was: fragile `importlib` scanning)**
  The old version iterated `dir(mod)` over dynamically imported modules to find
  any `BaseChunker` subclass — fragile, order-dependent, and could grab the wrong
  class. Now uses an explicit `dict[tuple[str, str], BaseChunker]` registry that
  maps `(source_type, language)` → chunker instance, with `None` wildcards for
  fallback. Registry is built lazily on first call or injected via `__init__` for
  testing.

- **`_TreeSitterProxy` lazy wrapper**
  Instead of eagerly constructing TreeSitterChunker instances for every language
  during registry build, uses a lightweight proxy that resolves at chunk-time.
  Falls back to ProseChunker if tree-sitter can't handle the language.

- **`_detect_repetition_sections()` edge case hardening:**
  - **Adjacent delimiter dedup:** If two delimiter positions are ≤2 lines apart,
    keeps only the first (they're the same header block, e.g. `---`/`FILE:`/`---`).
  - **Empty section filtering:** Sections with fewer than `_MIN_SECTION_CONTENT_LINES`
    (2) content lines are dropped instead of creating hollow chunks.
  - **Bounds clamping:** `content_start` clamped to `len(lines) - 1` to prevent
    index overflow on files that end with a delimiter.

- **`_remap_chunks()` span clamping:**
  All remapped span coordinates are now clamped to `[0, max_line]` with an
  `ensure start <= end` guard. Prevents any out-of-bounds SpanRef from reaching
  the verbatim layer.

- **`language_tier` confirmed present** on `Chunk` dataclass in `base.py` (v0.2.0
  already added it). No changes needed to `base.py`.

---

### 2. `tripartite/pipeline/ingest.py` — **MODIFIED**
**Location:** `tripartite/pipeline/ingest.py`
**Action:** Replace the existing file.

**What changed — `_get_chunker()` only:**

```python
# ── v0.3.0: Compound document detection ──────────────────────────────
# Check if this is a multi-file dump before falling through to prose.
# This runs on prose, generic, and structured files that weren't handled
# by tree-sitter above.  The check is lightweight (line scanning, no ML).
try:
    from ..chunkers.compound import CompoundDocumentChunker, is_compound_document
    if is_compound_document(source):
        return CompoundDocumentChunker(), "compound_v1"
except ImportError:
    pass  # compound.py not yet installed — skip gracefully
```

This block is inserted **after** the tree-sitter checks and **before** the
`ProseChunker()` fallback. The `try/except ImportError` means the existing
pipeline still works even if `compound.py` isn't deployed yet — graceful
degradation.

The compound check runs on:
- `prose` files (markdown, text, etc.)
- `generic` files (unknown extension)
- `structured` files that tree-sitter couldn't handle

It does NOT run on files already claimed by tree-sitter or the Python AST chunker.

**Design decision:** Detection lives in `_get_chunker()`, not in `detect.py`.
Rationale: `detect.py` is extension-based (fast, no content reading beyond encoding).
Compound detection requires content scanning (line patterns, CID repetition) which
is appropriate for the chunker selection stage, not the detection stage.

Nothing else in `ingest.py` changed — `_ingest_file()`, `ingest()`, the progress
callbacks, manifest writing, embedding, graph — all identical.

---

### 3. `tripartite/chunkers/__init__.py` — **MODIFIED**
**Location:** `tripartite/chunkers/__init__.py`
**Action:** Replace the existing file.

**What changed:**
```python
from .compound import CompoundDocumentChunker, is_compound_document
```
Added to imports and `__all__`. This makes `CompoundDocumentChunker` importable
from `tripartite.chunkers` directly.

---

### 4. `tripartite/explorer.py` — **REPLACED** (v0.3.1)
**Location:** `tripartite/explorer.py`
**Action:** Replace the existing file (the old v0.3.0 flat-mode version).

**What changed from old explorer.py:**
- **JOIN fix:** `LEFT JOIN chunk_manifest cm ON cm.node_id = tn.node_id`
  (was incorrectly joining on `tn.chunk_id` which is often NULL)
- **"Flat mode" → "Outline mode":** Single-file view now shows full chunk-level
  structure (functions, classes, sections) instead of an empty tree.
- **Compound document support:** `virtual_file` and `compound_summary` node types
  are recognized in mode detection, sorting, icons, and context menus.
- **Context menus:** Directory nodes get Open Terminal / Open PowerShell / venv
  activation. File nodes get Open in Editor / Open Containing Folder. Chunk nodes
  get Copy Chunk Text / Find Similar.

---

## What's NOT Changed

These files are untouched by this patch:
- `base.py` — `language_tier` already exists on `Chunk` ✓
- `detect.py` — `source_type` stays as `code|prose|structured|generic` (no `"compound"` type needed; detection is in `_get_chunker`)
- `config.py` — no new constants needed
- `utils.py` — no changes
- `prose.py` / `treesitter.py` / `code.py` — no changes
- `verbatim.py` / `embed.py` / `extract.py` / `manifest.py` — no changes
- `studio.py` / `gui.py` — no changes
- `db/schema.py` / `db/query.py` — no schema changes needed

---

## Testing Checklist

1. **Smoke test — normal ingest still works:**
   Ingest a regular codebase (no compound files). Verify tree-sitter routing,
   prose fallback, and chunk counts are identical to v0.2.0.

2. **Compound document test — file dump ingest:**
   Ingest a file dump (like `_TripartiteDataSTORE_filedump.txt` itself!).
   Verify:
   - `is_compound_document()` returns `True`
   - `compound_v1` appears as the chunker name in `chunk_manifest`
   - `compound_summary` and `virtual_file` chunk types appear
   - Sub-chunks have correct span offsets (spot-check a few SpanRefs
     against actual line numbers in the compound file)

3. **Explorer test:**
   Open the GUI after ingesting a compound document. Verify:
   - Project mode is auto-detected (virtual_file nodes exist)
   - Virtual files appear with 📎 icon
   - Compound summary appears with 📋 icon
   - Right-click on virtual files shows file menu
   - Right-click on sub-chunks shows chunk menu with Copy Chunk Text

4. **Edge case test — repetition detection:**
   Create a synthetic compound file with:
   - Adjacent delimiters (double separator lines with no content)
   - Very short sections (< 2 content lines)
   - Sections at end of file (no trailing content)
   Verify these are handled gracefully (skipped, not crash).

5. **Fallback test — compound detection fails gracefully:**
   Temporarily rename `compound.py` and ingest a compound file.
   Verify the `ImportError` catch in `_get_chunker()` fires and
   the file falls through to `ProseChunker` without error.

---

## Next Up: P3 + P4

- **P3 — Explorer flat/outline mode fix:** Already addressed in this patch.
  The new explorer never shows an empty tree — outline mode expands all nodes.

- **P4 — Semantic Boundary Detection curation tool:** Post-embedding cosine
  distance analysis. Goes in `curate_tools/semantic_boundaries.py`. This is
  a Layer 2 tool that reads from `semantic.db` — completely separate from
  the Layer 1 compound detection. Ready to implement next.
