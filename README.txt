================================================================================
                    TRIPARTITE DATA STORE (v0.3.1)
           Production-Ready Source Code Ingestion & Semantic Search
================================================================================

TABLE OF CONTENTS
================================================================================
1. Overview
2. System Requirements
3. Installation & Setup
4. Quick Start
5. Features & Capabilities
6. Detailed Usage Guide
7. Advanced Options
8. Database Architecture
9. Troubleshooting
10. Performance Tuning
11. Development & Contributing

================================================================================
1. OVERVIEW
================================================================================

Tripartite Data Store is a sophisticated source code ingestion and semantic
search engine designed for developers, architects, and documentation teams.

WHAT IT DOES:
- Ingest entire codebases (all file types, recursive directories)
- Extract structural information (files, chunks, hierarchy)
- Generate semantic embeddings for intelligent searching
- Build knowledge graphs from code relationships
- Store everything in a unified, queryable SQLite database
- Support semantic search across millions of lines of code

WHY "TRIPARTITE"?
The system uses three complementary data layers:

  1. STRUCTURAL LAYER (Files → Tree Nodes → Chunks)
     Navigation: File system paths, directory structure, code hierarchy

  2. SEMANTIC LAYER (Embeddings → Vectors → Similarities)
     Intelligence: Meaning-based search, concept similarity, clustering

  3. GRAPH LAYER (Nodes → Edges → Relationships)
     Knowledge: Entity relationships, dependencies, call graphs

These three layers work together to provide both structured navigation AND
intelligent semantic understanding of your codebase.

================================================================================
2. SYSTEM REQUIREMENTS
================================================================================

HARDWARE:
- Minimum: 4GB RAM (for small codebases <100MB)
- Recommended: 8GB+ RAM (for medium codebases 100MB-1GB)
- Large codebases (>1GB): 16GB+ RAM and SSD storage

CPU:
- Multi-core recommended (4+ cores for parallel processing)
- Embedding generation is CPU-intensive; faster = better

STORAGE:
- SQLite database grows proportionally to ingested code size
- General ratio: ~5-10x the original source code size (includes embeddings)
- Example: 100MB source → 500MB-1GB database

PYTHON:
- Python 3.8 or higher
- Required packages: sqlite3 (built-in), tkinter (built-in)
- Optional: llama-cpp-python (for semantic embeddings)

OPERATING SYSTEM:
- Windows (tested on Windows 10+)
- Linux/Mac (should work; platform-specific paths may vary)

================================================================================
3. INSTALLATION & SETUP
================================================================================

STEP 1: Environment Setup
------------------------------
Run the setup script to configure your Python environment:

  Windows:  setup_env.bat
  Linux/Mac: bash setup_env.sh

This will:
- Create/activate Python virtual environment
- Install required dependencies
- Download embedding models (if not cached)
- Verify environment is ready

STEP 2: Verify Installation
------------------------------
Test that the application launches:

  Windows:  python -m src.app
  Linux/Mac: python -m src.app

You should see the graphical interface open. If it fails, check:
- Python version (python --version should be 3.8+)
- Virtual environment activated
- tkinter installed (python -m tkinter should open a window)

STEP 3: (Optional) Download Embedding Model
------------------------------
For semantic search capabilities, you need an embedding model:

  Windows:  download_models.bat
  Linux/Mac: bash download_models.sh

Models available:
- nomic-embed-text-v1.5.Q4_K_M.gguf (recommended, 116MB)
- Other GGUF-format embeddings compatible with llama-cpp-python

Without a model, basic ingestion and structural search still works.
Embedding stage will be skipped with a warning.

================================================================================
4. QUICK START
================================================================================

SCENARIO A: Using the GUI
------------------------------
1. Run: python -m src.app
2. Click "Choose Folder..." and select your source code directory
3. Click "Start Ingest"
4. Watch progress as files are discovered, analyzed, and indexed
5. When complete, use "Search" tab to query your code semantically

SCENARIO B: Command-Line Ingestion (Recommended for Large Codebases)
------------------------------
1. Open terminal/command prompt
2. Run:
     python -m src.ingest_runner --source "C:\path\to\source" --db "C:\path\to\db.sqlite"

3. Watch detailed progress output
4. When complete, open database with GUI:
     python -m src.app --db "C:\path\to\db.sqlite"

SCENARIO C: Batch Processing (Multiple Codebases)
------------------------------
Create a batch_ingest.py script:

    from pathlib import Path
    from src.pipeline.ingest import ingest

    sources = [
        Path("C:/projects/app1"),
        Path("C:/projects/app2"),
        Path("C:/projects/app3"),
    ]

    db = Path("C:/data/combined.db")

    for source in sources:
        print(f"\nIngesting {source.name}...")
        ingest(source, db, verbose=True)

Then run:
    python batch_ingest.py

================================================================================
5. FEATURES & CAPABILITIES
================================================================================

SUPPORTED FILE TYPES:
- Code: Python, Java, JavaScript, C++, C#, Go, Rust, and 20+ languages
- Structured: JSON, YAML, TOML, XML, HTML, CSS
- Markup: Markdown, reStructuredText, plain text
- Config: .env, .ini, .cfg, .conf files
- Special: Shell scripts (.sh, .bash), batch files (.bat), PowerShell (.ps1)

INGESTION CAPABILITIES:
✓ Recursive directory traversal
✓ Automatic file type detection
✓ Binary file skipping (safe)
✓ Multi-language support with AST/TreeSitter parsing
✓ Intelligent chunking (respects code structure)
✓ Compound document detection (multi-file dumps)
✓ Unicode normalization (handles various encodings)

PROCESSING CAPABILITIES:
✓ Per-file progress tracking
✓ Per-stage visibility (detect → chunk → embed → extract)
✓ Detailed error logging and recovery
✓ Callback error reporting (no silent failures)
✓ Timeout protection (prevents hanging)
✓ Partial ingestion recovery (resumable)
✓ Performance timing breakdown

SEARCH CAPABILITIES:
✓ Semantic similarity search (find related code by meaning)
✓ Full-text search (traditional keyword search)
✓ Entity extraction (identify objects, functions, classes)
✓ Relationship graphs (understand dependencies)
✓ Multi-layer filtering (by file type, size, content)

DATABASE CAPABILITIES:
✓ SQLite-based (portable, no server needed)
✓ ACID transactions (data integrity)
✓ Foreign key enforcement (referential integrity)
✓ WAL mode (concurrent access safe)
✓ Schema versioning (production-ready)
✓ Metadata tracking (deployment readiness)

================================================================================
6. DETAILED USAGE GUIDE
================================================================================

LAUNCHING THE GUI
------------------------------
Command:
    python -m src.app

Optional arguments:
    python -m src.app "C:\path\to\database.db"  # Open specific database
    python -m src.app --db "path"                # Same as above

The GUI will show:
- Welcome tab: Database selection and new database creation
- Ingest tab: File selection and ingestion configuration
- Search tab: Full-text and semantic search (after ingestion)
- Explore tab: Visual database browser
- Settings tab: Model selection, theme, preferences

GUI WORKFLOW:
1. Choose or create a database
2. Select source directory to ingest
3. Click "Start Ingest"
4. Monitor progress in real-time
5. Search or explore when complete

COMMAND-LINE INGESTION (Recommended)
------------------------------
For detailed progress and better control, use command-line:

    python -m src.ingest_runner --source "C:\code" --db "C:\data\db.sqlite"

This shows:
- File discovery progress
- Per-directory traversal
- Stage-by-stage processing
- Detailed timing breakdown
- Error messages with context

OPTIONS FOR COMMAND-LINE INGESTION:
    --source PATH       Source directory to ingest (required)
    --db PATH           SQLite database path (required)
    --verbose           Show progress (default: enabled)
    --very-verbose      Show detailed per-stage timing
    --lazy              Skip embedding (fast, no semantic search)
    --timeout SECONDS   Stop after N seconds (useful for CI/CD)

EXAMPLES:

Example 1: Basic ingestion (100% output)
    python -m src.ingest_runner \
        --source "C:\repos\myproject" \
        --db "C:\databases\myproject.db"

Example 2: Verbose with timing
    python -m src.ingest_runner \
        --source "C:\repos\myproject" \
        --db "C:\databases\myproject.db" \
        --very-verbose

Example 3: Quick scan without embeddings
    python -m src.ingest_runner \
        --source "C:\repos\myproject" \
        --db "C:\databases\myproject.db" \
        --lazy

Example 4: With timeout protection (for automation)
    python -m src.ingest_runner \
        --source "C:\repos\myproject" \
        --db "C:\databases\myproject.db" \
        --timeout 300          # Stop after 5 minutes

PYTHON API (For Custom Scripts)
------------------------------
Use the Python API for programmatic access:

    from pathlib import Path
    from src.pipeline.ingest import ingest

    # Basic usage
    result = ingest(
        source_root=Path("C:/code"),
        db_path=Path("C:/data/db.sqlite"),
    )

    print(f"Processed {result['files_processed']} files")
    print(f"Created {result['chunks_created']} chunks")
    print(f"Status: {result['status']}")

    # Advanced usage with callbacks
    def on_progress(event):
        if event["type"] == "file_start":
            print(f"Processing {event['filename']}...")
        elif event["type"] == "embedding_progress":
            progress = event['chunk_idx'] / event['chunk_total'] * 100
            print(f"  Embedding: {progress:.0f}%")

    result = ingest(
        source_root=Path("C:/code"),
        db_path=Path("C:/data/db.sqlite"),
        verbose=True,
        very_verbose=True,
        timeout_seconds=300,
        on_progress=on_progress,
    )

================================================================================
7. ADVANCED OPTIONS
================================================================================

TIMEOUT SUPPORT (NEW!)
------------------------------
The timeout feature prevents the ingestion process from running indefinitely,
which is crucial for:
- Automated CI/CD pipelines
- Server deployments with time limits
- Preventing resource exhaustion
- Graceful degradation

How it works:
1. Set timeout_seconds parameter
2. Ingest runs normally until timeout is approached
3. When timeout is reached:
   - Current file completes (respects atomicity)
   - Remaining files are skipped
   - Remaining chunks marked as "pending" (can resume later)
   - Database remains consistent

Usage:
    python -m src.ingest_runner \
        --source "C:\code" \
        --db "C:\data\db.sqlite" \
        --timeout 300              # 5 minutes

What happens if timeout is exceeded:
    [ingest] Crawling: subdir1/
    [1/250] file1.py
    [ingest] TIMEOUT: Ingest exceeded 300s limit (elapsed: 305.2s)
    [2/250] file2.py (skipped - timeout exceeded)
    [3/250] file3.py (skipped - timeout exceeded)
    ...

    ─────────────────────────────────────────────────
    Status: partial (timeout occurred)
    Files processed: 1 / 250
    Chunks pending: 47 (can resume later)
    ─────────────────────────────────────────────────

Resuming after timeout:
Simply run the ingest again - it will:
1. Skip already-processed files
2. Continue with pending chunks
3. Complete remaining work

VERY-VERBOSE MODE
------------------------------
For detailed per-stage timing and visibility:

    python -m src.ingest_runner \
        --source "C:\code" \
        --db "C:\data\db.sqlite" \
        --very-verbose

Output shows:
- File discovery time
- Per-directory traversal
- Stage transitions with timing
- Chunk generation details
- Embedding progress with rates

Example output:
    [ingest] Discovery time: 0.042s

    [ingest] Crawling: /
    [1/250] setup.py
      [stage] Starting detect...
      [detect] Analyzing setup.py... (code)
      [stage] detect complete in 0.012s

      [stage] Starting chunk...
      [chunk] Using treesitter_python_v2, chunking content...
      [chunk] Generated 12 chunks
      [stage] chunk complete in 0.078s

    ─────────────────────────────────────────────────
    Stage Timings:
      discovery            :    0.042s
      processing           :  128.234s

    ─────────────────────────────────────────────────

LAZY MODE (No Embeddings)
------------------------------
Skip semantic embedding for speed:

    python -m src.ingest_runner \
        --source "C:\code" \
        --db "C:\data\db.sqlite" \
        --lazy

Use when:
- You just need structural analysis
- Speed is critical
- Embedding model unavailable
- Quick preview before full ingest

Performance: ~5-10x faster than full ingest

COMPOUND DOCUMENT DETECTION
------------------------------
The system automatically detects "compound documents" - files that contain
multiple source files concatenated together (common in ML datasets).

Behavior:
- Non-compound files: Use intelligent language-specific chunking
- Compound files: Use multi-file aware chunking
- Shell/batch scripts: Skip compound detection (optimization)

What's detected as "non-compound" (skips expensive scanning):
- .bat, .cmd (Windows batch)
- .sh, .bash (Shell scripts)
- .ps1 (PowerShell)
- .env, .cfg, .conf, .ini (Config files)
- .exe, .dll, .so, .dylib (Binaries)

CUSTOM CHUNKING
------------------------------
The system intelligently selects chunkers based on file type:

    Python Files (.py)
    └─ AST-based chunking → respects functions/classes

    Code Files (20+ languages supported)
    └─ TreeSitter-based → intelligent language-aware chunks

    Structured Files (JSON, YAML, HTML, CSS)
    └─ TreeSitter → respects document structure

    Markdown/Text
    └─ Prose chunker → paragraph-aware splitting

    Other Files
    └─ Compound or prose → auto-detected

Chunk size targets:
- Goal: ~500-1000 tokens per chunk
- Respects natural boundaries (functions, classes, paragraphs)
- Prevents splitting important units

================================================================================
8. DATABASE ARCHITECTURE
================================================================================

SCHEMA OVERVIEW
------------------------------
The SQLite database contains 11 core tables:

1. source_files
   Tracks ingested source files
   - Columns: source_id, path, source_type, file_cid, etc.
   - Purpose: Know what files are in the database

2. tree_nodes
   Hierarchical representation of code structure
   - Columns: node_id, parent_id, depth, file_id, chunk_id, etc.
   - Purpose: Navigate code hierarchy

3. chunk_manifest
   Metadata for all chunks
   - Columns: chunk_id, embed_status, graph_status, etc.
   - Purpose: Track chunk processing status

4. embeddings
   Semantic vector embeddings
   - Columns: chunk_id, model, dims, vector (float32 blob)
   - Purpose: Enable semantic search

5. graph_nodes
   Entity nodes (functions, classes, variables, etc.)
   - Columns: node_id, entity_type, entity_name, chunk_id, etc.
   - Purpose: Understand entities and relationships

6. graph_edges
   Relationships between entities
   - Columns: edge_id, source_node, target_node, relationship_type
   - Purpose: Model dependencies and relationships

7. fts_chunks
   Full-text search index
   - Columns: docid, context_prefix, chunk_text, chunk_id
   - Purpose: Enable fast keyword search

8. ingest_runs
   Track every ingestion run
   - Columns: run_id, started_at, completed_at, status, etc.
   - Purpose: Audit trail and resumable ingestion

9. cartridge_manifest
   Single-row metadata for production readiness
   - Columns: schema_ver, pipeline_ver, file_count, is_deployable, etc.
   - Purpose: Airlock deployment validation

10. verbatim_lines
    Original source text with line-level CIDs
    - Columns: line_id, source_id, line_num, text, line_cid
    - Purpose: Preserve exact source for reference

11. diff_tables (optional)
    Version tracking if DiffEngine enabled
    - Purpose: Track changes across ingestion runs

DATABASE PROPERTIES
------------------------------
File Format: SQLite 3
Location: User-specified path (e.g., C:\data\myproject.db)
Portability: Fully portable (single file)
Access: ACID transactions, safe concurrent access (WAL mode)
Schema Version: 1 (tracked in PRAGMA user_version)
Application ID: 0x5452494101 ("TRIA" + version)

Can verify cartridge type:
    sqlite3 myproject.db "PRAGMA application_id;"
    # Should return: 1484751105 (0x5452494101)

INGESTION TRACKING
------------------------------
Every ingest run creates a row in ingest_runs with:
- run_id: Unique run identifier
- started_at: When ingestion started
- completed_at: When ingestion finished
- files_discovered: Total files found
- files_processed: Successfully processed
- files_skipped: Skipped (binary, etc.)
- chunks_created: Total chunks generated
- chunks_embedded: Successfully embedded
- status: "running" → "success" | "failed" | "partial"
- error_count: Number of errors encountered
- error: Details of first error (if any)
- stage_*_complete: Flags for each pipeline stage
- duration_seconds: Total runtime
- metadata_json: Custom metadata

Query last ingest result:
    sqlite3 myproject.db "SELECT status, duration_seconds, chunks_created FROM ingest_runs ORDER BY completed_at DESC LIMIT 1;"

DEPLOYMENT READINESS
------------------------------
Before Airlock can deploy a cartridge, it validates:

✓ Schema version matches (PRAGMA user_version = 1)
✓ cartridge_manifest exists and has valid data
✓ All required tables present
✓ All chunks embedded (embed_status = 'done')
✓ Graph extraction complete
✓ Last ingest_runs.status = 'success'
✓ No orphaned records (FK integrity)

Check deployment status:
    sqlite3 myproject.db "SELECT is_deployable, deployment_notes FROM cartridge_manifest;"

================================================================================
9. TROUBLESHOOTING
================================================================================

PROBLEM: GUI won't launch
------------------------------
Error: "ModuleNotFoundError: No module named 'tkinter'"

Solution:
  Windows: tkinter comes with Python. Ensure Python installed via microsoft.com
  Linux: sudo apt-get install python3-tk
  Mac: brew install python-tk

PROBLEM: Application hangs on a file
------------------------------
Error: No progress for 5+ minutes on a small file

Root cause: Compound document detection running on file that shouldn't have it

Solution:
  1. Use --timeout to prevent infinite hangs:
     python -m src.ingest_runner --source "C:\code" --db "data.db" --timeout 300

  2. Use --lazy to skip slow embedding:
     python -m src.ingest_runner --source "C:\code" --db "data.db" --lazy

  3. Check verbose output:
     python -m src.ingest_runner --source "C:\code" --db "data.db" --very-verbose

PROBLEM: Embedding model not found
------------------------------
Error: "[embed] Warning: could not load embedder"
       "Marking all chunks as pending"

Solution:
  1. Download embedding model:
     download_models.bat (Windows)
     bash download_models.sh (Linux/Mac)

  2. Or, use --lazy to skip embeddings:
     python -m src.ingest_runner --source "C:\code" --db "data.db" --lazy

Note: Structural search still works without embeddings

PROBLEM: Database locked
------------------------------
Error: "database is locked" or "cannot acquire database lock"

Cause: Another process has the database open (GUI, script, etc.)

Solution:
  1. Close the GUI (src.app)
  2. Close any other Python scripts using the database
  3. Kill any lingering Python processes: taskkill /F /IM python.exe
  4. Retry the ingest

Prevention:
  - Use different database files for different projects
  - Use WAL mode (enabled by default) for better concurrency

PROBLEM: Out of memory during embedding
------------------------------
Error: "MemoryError" or system freezes

Cause: Trying to embed too many chunks at once

Solution:
  1. Ingest in smaller batches:
     - Split source directory into subdirectories
     - Run separate ingest for each subdirectory

  2. Use lazy mode:
     python -m src.ingest_runner --source "C:\code" --db "data.db" --lazy

  3. Increase available RAM (close other applications)

PROBLEM: Very slow embedding
------------------------------
Issue: Embedding takes hours for medium codebase

Cause: CPU-bound operation, slow storage

Solution:
  1. Use SSD for database file (vs. HDD)
  2. Close other CPU-intensive processes
  3. Use faster CPU (multi-core helps)
  4. Use --lazy mode for first pass
  5. Embed in multiple smaller batches

Typical performance:
  - Single core: ~100-200 chunks/sec
  - 4 cores: ~300-500 chunks/sec (depends on chunk size)
  - With GPU acceleration: 1000+ chunks/sec (future enhancement)

PROBLEM: Callback errors in summary
------------------------------
Error: "⚠ 3 callback error(s): Progress callback error..."

Cause: UI callbacks failing (usually UI thread issues)

Solution (usually automatic):
  1. Check if GUI is responsive
  2. If using custom callbacks, verify they don't raise exceptions
  3. Try again - often transient

The ingest continues despite callback errors (this is intentional).

PROBLEM: "No module named 'src'"
------------------------------
Error: When running from wrong directory

Solution:
  1. Make sure current directory is the project root:
     cd "C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataSTORE"

  2. Or, run with full path:
     python -m src.app

  3. Or, from project root:
     python -m src.ingest_runner --source "..." --db "..."

PROBLEM: Files not being ingested
------------------------------
Issue: Source directory shows 50 files, but only 10 processed

Cause: Files skipped due to type or readability

Common skip reasons:
  - Binary files (.exe, .dll, .so)
  - Non-UTF-8 encoding
  - Unreadable (permission denied)
  - Duplicate detection
  - Filtered by extension

Solution:
  1. Check verbose output:
     python -m src.ingest_runner --source "C:\code" --db "data.db" --very-verbose

  2. Look for "skipped (binary or unreadable)"

  3. Check file permissions:
     - Ensure read access on all files
     - Run terminal as Administrator if needed

PROBLEM: Search returns no results
------------------------------
Issue: Semantic search finds nothing

Solution:
  1. Verify embeddings were created:
     sqlite3 db.sqlite "SELECT COUNT(*) FROM embeddings;"
     # Should be > 0

  2. Check if chunks exist:
     sqlite3 db.sqlite "SELECT COUNT(*) FROM chunk_manifest;"
     # Should match chunks_created in summary

  3. Try full-text search instead:
     Use "Search" tab with exact keywords

  4. Re-ingest if chunks are pending:
     python -m src.ingest_runner --source "C:\code" --db "data.db" --very-verbose

================================================================================
10. PERFORMANCE TUNING
================================================================================

MEASURING PERFORMANCE
------------------------------
Use --very-verbose to see detailed timings:

    python -m src.ingest_runner \
        --source "C:\code" \
        --db "data.db" \
        --very-verbose

Output shows stage timings:
    Stage Timings:
      discovery        :    0.042s  (finding files)
      processing       :  128.234s  (analyze + chunk)

Total time = discovery + processing + embedding + graph

OPTIMIZATION STRATEGIES
------------------------------

Strategy 1: Reduce Processing Time
  - Use --lazy mode (skip embedding) → 5-10x faster
  - Ingest subdirectories separately
  - Exclude large vendor/node_modules directories

Strategy 2: Reduce Embedding Time
  - Embedding is 60-80% of total time
  - Use faster CPU (8+ cores recommended)
  - Use SSD for database file
  - Close other CPU-intensive processes

Strategy 3: Optimize Storage
  - Use SSD (vs HDD) → 2-3x faster
  - Enable WAL mode (default) → better concurrency
  - Keep database on local disk (not network drive)

Strategy 4: Batch Processing
  Instead of:    python ingest big_dir
  Do:            python ingest subdir1 & python ingest subdir2 & ...
  Parallel processing leverages all CPU cores

PROFILING
------------------------------
To identify bottlenecks, compare stage timings:

  discovery < 1s         (expected - file scanning)
  processing 10-100s     (expected - parsing + chunking)
  embedding  100-1000s   (expected - semantic vectors)
  graph      10-100s     (expected - entity extraction)

If discovery is slow:
  - Large number of files (>100k)
  - Network drive (move to local)
  - Antivirus scanning (whitelist directory)

If processing is slow:
  - Complex code (nested structures)
  - Compound document detection (use skip list)
  - Slow parser (use --lazy to skip)

If embedding is slow:
  - CPU bottleneck (expected behavior)
  - Slow storage (use SSD)
  - Insufficient RAM (causes paging)

If graph is slow:
  - Large number of entities
  - Complex relationships
  - This is usually fast (<5% of total time)

EXPECTED PERFORMANCE
------------------------------
Typical timings for 1GB codebase:
  - Fast (SSD, 8-core, 16GB RAM): 30-60 minutes
  - Medium (HDD, 4-core, 8GB RAM): 90-180 minutes
  - Slow (old CPU, 2-core, 4GB RAM): 4-8 hours

Per-language performance (approximate):
  - Python: 150-250 chunks/sec (tree-sitter)
  - Java: 100-200 chunks/sec (tree-sitter)
  - JavaScript: 200-300 chunks/sec (tree-sitter)
  - C++: 50-150 chunks/sec (complex parsing)

These are "analysis" speeds, not including embedding.
Embedding typically dominates (10-100x slower).

MEMORY USAGE
------------------------------
Typical memory usage:
  - Base application: 100-200MB
  - Per ingest: +50-100MB (buffers, caches)
  - Embedding stage: +200-500MB (temporary vectors)

Peak memory = base + active processing + embedding buffers

If running low on memory:
  1. Use --lazy mode (saves 200MB)
  2. Close other applications
  3. Process smaller batches
  4. Increase virtual memory (Windows: Settings > System > About)

================================================================================
11. DEVELOPMENT & CONTRIBUTING
================================================================================

PROJECT STRUCTURE
------------------------------
src/
  ├── app.py              (Application entry point & main orchestrator)
  ├── data_store.py       (Core database manager & UI controller)
  ├── gui_constants.py    (UI theme & styling constants)
  ├── cli.py              (Command-line interface)
  ├── ingest_runner.py    (CLI-based ingestion runner)
  ├── viewer.py           (Chunk/database viewer)
  ├── explorer.py         (Visual database browser)
  ├── settings_dialog.py  (Settings UI)
  ├── export.py           (Database export utilities)
  ├── hitl.py             (Human-in-the-loop tools)
  ├── diff_engine.py      (Version tracking)
  ├── tokenizing_patcher.py  (LLM integration)
  │
  ├── pipeline/
  │   ├── ingest.py       (Main ingestion orchestrator)
  │   ├── detect.py       (File type detection)
  │   ├── embed.py        (Semantic embedding)
  │   ├── extract.py      (Entity extraction & graph building)
  │   ├── manifest.py     (Chunk manifest management)
  │   └── verbatim.py     (Source preservation)
  │
  ├── chunkers/
  │   ├── base.py         (Base chunker interface)
  │   ├── prose.py        (Prose/markdown chunker)
  │   ├── code.py         (Language-specific chunkers)
  │   ├── treesitter.py   (TreeSitter-based chunking)
  │   └── compound.py     (Multi-file dump detection)
  │
  ├── db/
  │   ├── schema.py       (SQLite schema & initialization)
  │   ├── connection.py   (Database lifecycle management)
  │   └── search.py       (Query utilities)
  │
  ├── models/
  │   ├── manager.py      (Embedding model management)
  │   └── registry.py     (Model registry & loading)
  │
  ├── utils/
  │   ├── __init__.py     (Common utilities & helpers)
  │   └── ...
  │
  ├── components/
  │   ├── progress_bar.py (UI progress indicators)
  │   ├── search_ui.py    (Search interface)
  │   └── ...
  │
  └── curate_tools/
      ├── __init__.py     (Tool framework & discovery)
      ├── stats_report.py (Statistical analysis)
      └── ...             (User-contributed tools)

ARCHITECTURE OVERVIEW
------------------------------
The system uses a three-tier architecture:

  UI Layer (Tkinter GUI)
  ↓
  Data Manager Layer (TripartiteDataStore)
  ↓
  Pipeline & DB Layer (Ingestion, Search, Persistence)

Dependencies flow downward only (clean architecture).

UI communicates with TripartiteDataStore via method calls.
Pipeline modules don't know about UI (completely decoupled).

This enables:
- Headless operation (CLI-only)
- Programmatic access (Python API)
- Custom UI integration
- Server/API deployment

DEVELOPMENT WORKFLOW
------------------------------
1. Make changes to pipeline modules
2. Test with: python -m pytest tests/
3. Verify GUI still works: python -m src.app
4. Check imports: python -c "from src.pipeline.ingest import ingest"
5. Run end-to-end test:
   python -m src.ingest_runner --source test_data --db test.db --verbose
6. Commit changes

KEY EXTENSION POINTS
------------------------------

Custom Chunkers:
  Inherit from src.chunkers.base.BaseChunker
  Implement chunk(source: SourceFile) → List[Chunk]
  Register in pipeline/ingest.py _get_chunker()

Custom Curation Tools:
  Inherit from BaseCurationTool (in data_store.py)
  Implement: name, description, build_config_ui(), run()
  Drop .py file in src/curate_tools/ → auto-discovered

Custom Search Backends:
  Modify src/db/search.py
  Implement cosine_similarity, vector_search, etc.

Custom Export Formats:
  Modify src/export.py
  Add new export_as_* methods

VERSION HISTORY
------------------------------
v0.3.1 (Current - Production Ready)
  ✓ Fixed embedding indentation bug (critical)
  ✓ Added Phase 1 visibility improvements
  ✓ Added Phase 2 detailed logging & timing
  ✓ Added Phase 3 timeout support
  ✓ Added cartridge manifest layer
  ✓ Added ingest_runs tracking
  ✓ Optimized compound document detection
  ✓ Improved error reporting

v0.3.0
  ✓ Compound document detection
  ✓ Multi-language TreeSitter support
  ✓ Performance optimizations

v0.2.0
  ✓ Structured file support (JSON, YAML, HTML)
  ✓ TreeSitter integration

v0.1.0
  ✓ Initial release
  ✓ Basic file ingestion
  ✓ Semantic search
  ✓ SQLite backend

KNOWN LIMITATIONS
------------------------------
1. Embedding Model Support
   - Only GGUF format via llama-cpp-python
   - No GPU acceleration (CPU only)
   - Models must fit in system RAM

2. Timeout Mechanism
   - Respects file-level atomicity (current file completes)
   - No per-chunk timeout (would require threading)
   - Workaround: Use --timeout for overall limit

3. Concurrency
   - Single ingest process at a time per database
   - Multiple processes reading is safe (WAL mode)
   - Parallel ingests to same DB not supported

4. Scale Limits
   - Tested to 10GB+ codebases
   - SQLite practical limit: 2TB (not a real constraint)
   - RAM is limiting factor (embeddings storage)

5. Language Support
   - 20+ code languages via TreeSitter
   - But, AST chunking only for Python
   - Other languages use TreeSitter (universal)

CONTRIBUTING
------------------------------
To contribute improvements:

1. Fork and branch: git checkout -b feature/my-feature
2. Make changes, test thoroughly
3. Verify: python -m pytest tests/
4. Check code quality: python -m pylint src/
5. Create PR with detailed description

Priority improvements:
  - GPU acceleration for embeddings
  - Async/streaming ingestion
  - Additional language parsers
  - Performance optimizations
  - Better error messages

================================================================================
12. GETTING HELP
================================================================================

COMMON QUESTIONS
------------------------------
Q: How long does ingestion take?
A: Depends on size and CPU. See "Performance Tuning" section.
   Typical: 30-60 min for 1GB codebase.

Q: Can I resume an interrupted ingest?
A: Yes! Run ingest again. It skips processed files and resumes pending chunks.

Q: Is my data safe?
A: Yes. SQLite is ACID-compliant. WAL mode prevents corruption.
   Always backup: copy database file to backup location.

Q: Can I search without semantic embeddings?
A: Yes! Full-text search works without embeddings.
   Use --lazy mode to skip embedding entirely.

Q: How much disk space do I need?
A: Database is ~5-10x source code size (including embeddings).
   Example: 100MB code → 500MB-1GB database.

Q: Can I ingest multiple codebases to same database?
A: Yes! Each ingest run is tracked separately.
   They share the same database file, allowing cross-codebase search.

Q: What if my codebase keeps growing?
A: Re-run ingest periodically. It will:
   1. Skip already-processed files
   2. Ingest new files
   3. Re-embed everything for consistency

Q: Can I use this in production?
A: Yes! Schema is versioned, deployment checks are built-in.
   See "Database Architecture" section for deployment validation.

Q: Is there an API?
A: Yes! Use Python API: from src.pipeline.ingest import ingest
   See "Detailed Usage Guide" section for Python examples.

SUPPORT & REPORTING ISSUES
------------------------------
For bugs or questions:

1. Check "Troubleshooting" section (Section 9)
2. Enable --very-verbose mode for detailed output
3. Check database status:
   - Files: sqlite3 db.sqlite "SELECT COUNT(*) FROM source_files;"
   - Chunks: sqlite3 db.sqlite "SELECT COUNT(*) FROM chunk_manifest;"
   - Embeddings: sqlite3 db.sqlite "SELECT COUNT(*) FROM embeddings;"
4. Check last ingest run:
   - sqlite3 db.sqlite "SELECT * FROM ingest_runs ORDER BY started_at DESC LIMIT 1;"

When reporting issues, include:
- Python version: python --version
- OS and version
- Error message (full text)
- Output of last --very-verbose run
- Database schema version: sqlite3 db.sqlite "PRAGMA user_version;"

================================================================================
13. QUICK REFERENCE
================================================================================

COMMAND-LINE QUICK START
------------------------------
# Launch GUI
python -m src.app

# Open specific database
python -m src.app --db "C:\data\myproject.db"

# Ingest with full output
python -m src.ingest_runner --source "C:\code" --db "data.db" --verbose

# Detailed timing breakdown
python -m src.ingest_runner --source "C:\code" --db "data.db" --very-verbose

# Quick scan (no embedding)
python -m src.ingest_runner --source "C:\code" --db "data.db" --lazy

# With timeout protection
python -m src.ingest_runner --source "C:\code" --db "data.db" --timeout 300

PYTHON API QUICK START
------------------------------
from pathlib import Path
from src.pipeline.ingest import ingest

result = ingest(
    source_root=Path("C:/code"),
    db_path=Path("C:/data/db.sqlite"),
    verbose=True,
)

print(f"Status: {result['status']}")
print(f"Processed: {result['files_processed']} files")
print(f"Created: {result['chunks_created']} chunks")

DATABASE QUERIES
------------------------------
# Check ingestion progress
sqlite3 db.sqlite "SELECT COUNT(*) FROM source_files;"

# View embeddings
sqlite3 db.sqlite "SELECT COUNT(*) FROM embeddings WHERE embed_status='done';"

# See last ingest status
sqlite3 db.sqlite "SELECT status, duration_seconds FROM ingest_runs ORDER BY completed_at DESC LIMIT 1;"

# Check deployment readiness
sqlite3 db.sqlite "SELECT is_deployable, deployment_notes FROM cartridge_manifest;"

# Search for specific chunk
sqlite3 db.sqlite "SELECT chunk_id, chunk_text FROM fts_chunks WHERE chunk_text LIKE '%search_term%' LIMIT 10;"

================================================================================
END OF README
================================================================================

For latest updates and documentation, visit:
https://github.com/yourusername/tripartite-datastore

Version: 0.3.1 (Production Ready)
Last Updated: March 2026

================================================================================
