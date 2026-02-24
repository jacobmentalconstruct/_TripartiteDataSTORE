# Tripartite Export Feature - Documentation

## New Files Added

1. **export.py** → `tripartite/export.py` - Core export functionality
2. **export_cli.py** → `tripartite/export_cli.py` - Standalone CLI tool
3. **viewer.py** (updated) - Added Export button and dialog

---

## Installation

```bash
# Copy new files
cp export.py tripartite/export.py
cp export_cli.py tripartite/export_cli.py

# Update viewer (already includes export button)
cp viewer.py tripartite/viewer.py
```

---

## Usage

### From the Viewer (GUI)

1. Open viewer: `python -m tripartite.viewer --db your_store.db`
2. Click **📤 Export** button in top-right
3. Choose export mode:
   - **Hierarchy Dump** - Generates folder tree + file dump (like your input format)
   - **Reconstruct Files** - Writes original files back to disk
   - **Both** - Does both exports
4. Select output directory
5. Click **Export**

**What you get:**

**Hierarchy Dump mode:**
- `export_folder_tree.txt` - Tree visualization of your project structure
- `export_filedump.txt` - All files concatenated with separators

**Reconstruct Files mode:**
- All original files written to disk
- Preserves filenames (flattened structure by default)

**Both mode:**
- All of the above

---

### From CLI

```bash
# Generate hierarchy dump (default)
python -m tripartite.export_cli your_store.db ./output

# Reconstruct original files
python -m tripartite.export_cli your_store.db ./output --mode files

# Do both
python -m tripartite.export_cli your_store.db ./output --mode both

# Quiet mode (no progress output)
python -m tripartite.export_cli your_store.db ./output --quiet
```

---

## Export Modes Explained

### 1. Hierarchy Dump (`--mode dump`)

**Generates two text files:**

**`export_folder_tree.txt`:**
```
Project Tree: Tripartite Export
Generated: 2026-02-24 16:45:00

├── 📁 tripartite/
│   ├── 📁 db/
│   │   ├── 📄 __init__.py
│   │   ├── 📄 query.py
│   │   └── 📄 schema.py
│   ├── 📁 models/
│   │   ├── 📄 __init__.py
│   │   └── 📄 manager.py
│   └── 📄 gui.py
```

**`export_filedump.txt`:**
```
Dump: Tripartite Export

--------------------------------------------------------------------------------
FILE: /path/to/tripartite/gui.py
--------------------------------------------------------------------------------
"""
tripartite/gui.py — Tkinter ingest launcher
...
(full file content)
...

--------------------------------------------------------------------------------
FILE: /path/to/tripartite/models/manager.py
--------------------------------------------------------------------------------
...
```

**Use cases:**
- Documentation generation
- Code review
- Archiving snapshots
- Sharing project overview
- Input for other tools

---

### 2. Reconstruct Files (`--mode files`)

**Writes actual files to disk:**

```
output_dir/
├── gui.py
├── manager.py
├── query.py
├── schema.py
└── ...
```

**How it works:**
1. Reads `source_files` table for all ingested files
2. Gets `line_cids` JSON array for each file
3. Fetches corresponding lines from `verbatim_lines`
4. Joins lines with `\n`
5. Writes to disk with original filename

**Use cases:**
- Backup/recovery
- Migrating data between systems
- Extracting subset of files
- Round-trip verification (ingest → export → compare)

---

### 3. Both (`--mode both`)

Combines both export modes. Useful for complete archival.

---

## Technical Details

### Text Reconstruction Path

**Same as viewer chunk reconstruction:**
```
source_files.line_cids (JSON array)
  → ["sha256:abc123...", "sha256:def456...", ...]
  → verbatim_lines WHERE line_cid IN (...)
  → .content fields joined with \n
```

### Lossless Round-Trip

The export is **lossless** for file content:
- Original line content preserved byte-for-byte
- Line endings normalized to `\n`
- Trailing whitespace preserved (stored in line content)

**What's NOT preserved:**
- Original directory structure (files are flattened by default)
- File metadata (timestamps, permissions)
- Binary files (not ingested in the first place)

### Performance

**Small DBs (<100 files):** Near-instant  
**Medium DBs (100-1000 files):** Few seconds  
**Large DBs (1000+ files):** May take 10-30 seconds

Progress is shown in CLI mode.

---

## Export Stats

Before exporting, you can check what will be exported:

```python
from tripartite import export
import sqlite3

conn = sqlite3.connect("your_store.db")
stats = export.get_export_stats(conn)

print(stats)
# {
#   'file_count': 42,
#   'line_count': 8453,
#   'total_bytes': 256789,
#   'by_type': {'code': 35, 'prose': 7},
#   'by_language': {'python': 30, 'markdown': 7, 'javascript': 5}
# }
```

The viewer export dialog shows these stats.

---

## Programmatic Usage

```python
from pathlib import Path
import sqlite3
from tripartite import export

conn = sqlite3.connect("store.db")

# Just generate hierarchy dump
result = export.export_hierarchy_dump(
    conn, 
    output_dir=Path("./output"),
    prefix="my_export"
)
print(f"Tree: {result['tree_path']}")
print(f"Dump: {result['dump_path']}")

# Reconstruct files with progress callback
def progress(current, total, filename):
    print(f"[{current}/{total}] {filename}")

result = export.export_to_files(
    conn,
    output_dir=Path("./reconstructed"),
    on_progress=progress
)
print(f"Wrote {result['files_written']} files")

# All-in-one
stats = export.export_all(
    db_path=Path("store.db"),
    output_dir=Path("./export"),
    mode="both",
    verbose=True
)
```

---

## Error Handling

**Graceful degradation:**
- If a file's `line_cids` JSON is corrupt → skip file, log error
- If a line is missing from `verbatim_lines` → skip line, continue
- If output directory can't be created → fail with clear error

**Errors are collected, not fatal:**
```python
result = export.export_to_files(conn, output_dir)

if result['errors']:
    for err in result['errors']:
        print(f"Failed: {err['file']} - {err['error']}")
```

---

## Use Cases

### 1. Backup & Recovery
```bash
# Export everything
python -m tripartite.export_cli store.db ./backup --mode both

# Later: verify round-trip
diff -r original_project backup/
```

### 2. Code Review / Documentation
```bash
# Generate hierarchy dump
python -m tripartite.export_cli store.db ./review --mode dump

# Share the two .txt files with reviewers
```

### 3. Partial Extraction
```python
# Export only Python files (custom logic)
import sqlite3
from tripartite import export

conn = sqlite3.connect("store.db")

# Get Python files
rows = conn.execute("""
    SELECT file_cid, path, name, line_cids
    FROM source_files
    WHERE language = 'python'
""").fetchall()

# Reconstruct each
for file_cid, path, name, line_cids_json in rows:
    # ... custom export logic
```

### 4. Migration / Format Conversion
```bash
# Export as hierarchy dump
python -m tripartite.export_cli old_store.db ./temp --mode dump

# Process the dump
cat temp/export_filedump.txt | process_and_transform.py > new_format.txt

# Re-ingest into new system
```

### 5. Verification
```bash
# Ingest
python -m tripartite.gui  # ingest project → store.db

# Export
python -m tripartite.export_cli store.db ./exported --mode files

# Compare
diff -r original_project exported/
# Should show only:
# - Line ending normalization (\r\n → \n)
# - Directory structure (flattened)
```

---

## Troubleshooting

### "JSON decode error on line_cids"
The `source_files.line_cids` field is corrupt. This shouldn't happen in normal operation. Check the ingest pipeline.

### "Missing lines from verbatim_lines"
The database is incomplete. Either:
- Partial ingest that failed mid-run
- Database corruption
- Manual DB edits

### "Files have different content after round-trip"
Check:
- Line ending handling (CR/LF vs LF)
- Encoding issues (UTF-8 vs latin-1)
- Trailing whitespace

The export should be byte-for-byte identical except line endings.

### "Export is slow"
For large DBs:
- Use `--quiet` to skip progress output (small speedup)
- Export in `files` mode is faster than `dump` (no tree building)
- Consider exporting subsets programmatically

---

## Future Enhancements

### Planned
- [ ] Preserve directory structure option (`--preserve-structure`)
- [ ] Export specific files only (`--filter "*.py"`)
- [ ] Export by date range (once ingest tracks timestamps)
- [ ] Compressed archive output (`.tar.gz`)
- [ ] Incremental export (delta since last export)

### Ideas
- Export to Git repository (one commit per file)
- Export graph as GraphML/DOT
- Export embeddings as numpy/torch format
- Export search index for external tools

---

## Summary

Export gives you three ways to get data out:

1. **Hierarchy Dump** - Human-readable tree + concatenated files
2. **Reconstruct Files** - Original files back to disk
3. **Both** - Complete export

All accessible via:
- Viewer GUI (📤 Export button)
- CLI (`python -m tripartite.export_cli`)
- Python API (`from tripartite import export`)

Round-trip tested, lossless for content, production-ready. 🚀
