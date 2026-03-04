"""
SQLite schema for the Tripartite knowledge store.

All three memory layers plus the logical tree and diff chain live in a single
.db file.  This module creates the schema and provides the DB connection factory.

Layer mapping:
  verbatim_lines + source_files  →  Verbatim Layer (Layer 1)
  tree_nodes                     →  Logical Tree Layer (namespace / join key)
  chunk_manifest + embeddings    →  Semantic Layer (Layer 2)
  graph_nodes + graph_edges      →  Knowledge Graph Layer (Layer 3)
  diff_chain + snapshots         →  Temporal evolution

v0.2.0 — Added language-tier columns to chunk_manifest and tree_nodes:
  semantic_depth, structural_depth, language_tier

v0.3.0 — Added manifest contract layer:
  cartridge_manifest (single-row metadata)
  Enhanced ingest_runs with stage tracking
"""

import sqlite3
from pathlib import Path
import json


# ── Manifest Enums ──────────────────────────────────────────────────────────

# Embedding status values in chunk_manifest
EMBED_STATUS_ENUM = {
    "pending": 0,      # Not yet embedded
    "done": 1,         # Successfully embedded
    "stale": 2,        # Was embedded, but source changed
    "error": 3,        # Embedding failed
}

# Graph status values in chunk_manifest
GRAPH_STATUS_ENUM = {
    "pending": 0,           # Awaiting graph extraction
    "structural": 1,        # Only structural nodes created (some chunks)
    "done": 2,              # Full graph extraction complete
    "error": 3,             # Graph extraction failed
}

# Ingest run status
INGEST_STATUS_ENUM = {
    "running": 0,
    "success": 1,
    "failed": 2,
    "partial": 3,
}

# Deployment rules for Airlock validation
DEPLOYMENT_RULES = {
    "embeddings_required": True,         # All chunks must be embedded
    "graph_required": "structural",      # Graph must be at least "structural"
    "all_tables_required": [
        "source_files",
        "tree_nodes",
        "chunk_manifest",
        "embeddings",
        "graph_nodes",
        "graph_edges",
        "cartridge_manifest",
        "ingest_runs",
    ],
    "last_run_status_required": "success",  # Last ingest_runs.status must be 'success'
}


# ── DDL ────────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;
PRAGMA mmap_size = 30000000000;
PRAGMA temp_store = MEMORY;
PRAGMA user_version = 1;

-- ── Layer 1: Verbatim ──────────────────────────────────────────────────────

-- One row per unique line of content across all ingested sources.
-- Identical lines across files share a single record (deduplication).
CREATE TABLE IF NOT EXISTS verbatim_lines (
    line_cid    TEXT PRIMARY KEY,          -- sha256:<hash> of normalized line
    content     TEXT NOT NULL,             -- the actual line text
    byte_len    INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- One row per ingested source file.  The line_cids column holds the ordered
-- JSON array of line_cid values representing the file at ingest time.
CREATE TABLE IF NOT EXISTS source_files (
    file_cid        TEXT PRIMARY KEY,      -- sha256:<hash> of raw file bytes
    path            TEXT NOT NULL,         -- original path (absolute or URL)
    name            TEXT NOT NULL,         -- basename
    source_type     TEXT NOT NULL,         -- 'code' | 'prose' | 'structured' | 'conversation'
    language        TEXT,                  -- e.g. 'python', 'markdown', null
    encoding        TEXT NOT NULL DEFAULT 'utf-8',
    line_count      INTEGER NOT NULL,
    byte_size       INTEGER NOT NULL,
    line_cids       TEXT NOT NULL,         -- JSON array of line_cid strings (ordered)
    ingested_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    pipeline_ver    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_files_path ON source_files(path);

-- ── Logical Tree Layer ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tree_nodes (
    node_id         TEXT PRIMARY KEY,      -- stable UUID (survives renames)
    node_type       TEXT NOT NULL,         -- see config.py node type registry
    name            TEXT NOT NULL,
    parent_id       TEXT REFERENCES tree_nodes(node_id),
    path            TEXT NOT NULL,         -- derived, human-readable
    depth           INTEGER NOT NULL DEFAULT 0,

    -- Verbatim reference (where in a source file this node lives)
    file_cid        TEXT REFERENCES source_files(file_cid),
    line_start      INTEGER,
    line_end        INTEGER,

    -- Language-tier metadata (v0.2.0)
    language_tier   TEXT DEFAULT 'unknown',

    -- Cross-layer join keys (populated as pipeline stages complete)
    chunk_id        TEXT,                  -- → chunk_manifest.chunk_id
    graph_node_id   TEXT,                  -- → graph_nodes.node_id

    -- Temporal
    diff_chain_head TEXT,                  -- CID of latest diff or snapshot
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_tree_nodes_parent ON tree_nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_tree_nodes_path   ON tree_nodes(path);
CREATE INDEX IF NOT EXISTS idx_tree_nodes_file   ON tree_nodes(file_cid);
CREATE INDEX IF NOT EXISTS idx_tree_nodes_tier   ON tree_nodes(language_tier);

-- ── Layer 2a: Chunk Manifest ───────────────────────────────────────────────

-- Central join record across all three storage layers.
CREATE TABLE IF NOT EXISTS chunk_manifest (
    chunk_id        TEXT PRIMARY KEY,      -- cid:sha256:<hash of canonical span text>
    node_id         TEXT NOT NULL REFERENCES tree_nodes(node_id),
    chunk_type      TEXT NOT NULL,         -- function_def | section | paragraph | …
    context_prefix  TEXT NOT NULL,         -- prepended to text before embedding
    token_count     INTEGER NOT NULL,
    spans           TEXT NOT NULL,         -- JSON array of span reference objects
    hierarchy       TEXT NOT NULL,         -- JSON: {parent_chunk_id, heading_path, depth, ...}
    overlap         TEXT NOT NULL,         -- JSON: {prev_chunk_id, next_chunk_id, prefix_lines, suffix_lines}

    -- Language-tier metadata (v0.2.0)
    semantic_depth  INTEGER NOT NULL DEFAULT 0,
    structural_depth INTEGER NOT NULL DEFAULT 0,
    language_tier   TEXT NOT NULL DEFAULT 'unknown',

    -- Embedding status
    embed_status    TEXT NOT NULL DEFAULT 'pending',  -- pending | done | stale | error
    embed_model     TEXT,
    embed_dims      INTEGER,
    embed_error     TEXT,

    -- Graph status
    graph_status    TEXT NOT NULL DEFAULT 'pending',

    -- Pipeline provenance
    chunker         TEXT NOT NULL,
    pipeline_ver    TEXT NOT NULL,
    ingested_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_manifest_node   ON chunk_manifest(node_id);
CREATE INDEX IF NOT EXISTS idx_manifest_type   ON chunk_manifest(chunk_type);
CREATE INDEX IF NOT EXISTS idx_manifest_status ON chunk_manifest(embed_status);
CREATE INDEX IF NOT EXISTS idx_manifest_tier   ON chunk_manifest(language_tier);
CREATE INDEX IF NOT EXISTS idx_manifest_depth  ON chunk_manifest(language_tier, semantic_depth);

-- ── Layer 2b: Embeddings ───────────────────────────────────────────────────

-- Stores the raw embedding vector as a BLOB of 32-bit floats (little-endian).
-- Kept separate from the manifest so the manifest table stays fast to scan.
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id    TEXT PRIMARY KEY REFERENCES chunk_manifest(chunk_id),
    model       TEXT NOT NULL,
    dims        INTEGER NOT NULL,
    vector      BLOB NOT NULL,             -- dims × 4 bytes, float32 LE
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ── Layer 3: Knowledge Graph ───────────────────────────────────────────────

-- Graph nodes map 1-to-1 to either a tree_node or an entity mention.
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id     TEXT PRIMARY KEY,          -- UUID
    node_type   TEXT NOT NULL,             -- 'chunk' | 'entity'
    label       TEXT NOT NULL,             -- display name / entity text
    entity_type TEXT,                      -- PERSON | ORG | TECH | … (null for chunk nodes)
    chunk_id    TEXT REFERENCES chunk_manifest(chunk_id),
    salience    REAL,                      -- 0.0–1.0, null for chunk nodes
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_label ON graph_nodes(label);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_chunk ON graph_nodes(chunk_id);

-- Typed edges between graph nodes.
CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id         TEXT PRIMARY KEY,      -- UUID
    src_node_id     TEXT NOT NULL REFERENCES graph_nodes(node_id),
    dst_node_id     TEXT NOT NULL REFERENCES graph_nodes(node_id),
    edge_type       TEXT NOT NULL,         -- PART_OF | PRECEDES | MENTIONS | …
    weight          REAL NOT NULL DEFAULT 1.0,
    predicate       TEXT,                  -- natural-language relation (from extraction)
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_edges_src  ON graph_edges(src_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst  ON graph_edges(dst_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON graph_edges(edge_type);

-- ── Temporal: Diff Chain ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS diff_chain (
    diff_id         TEXT PRIMARY KEY,      -- cid:sha256:<hash>
    node_id         TEXT NOT NULL REFERENCES tree_nodes(node_id),
    parent_diff     TEXT,                  -- previous diff_id or snapshot_id
    timestamp       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    changes         TEXT NOT NULL          -- JSON array of change records
);
CREATE INDEX IF NOT EXISTS idx_diff_node ON diff_chain(node_id);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id     TEXT PRIMARY KEY,      -- cid:sha256:<hash>
    node_id         TEXT NOT NULL REFERENCES tree_nodes(node_id),
    timestamp       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    line_cids       TEXT NOT NULL          -- JSON array — complete state at this point
);
CREATE INDEX IF NOT EXISTS idx_snapshot_node ON snapshots(node_id);

-- ── Full-text search ───────────────────────────────────────────────────────

-- FTS5 over verbatim content for exact / keyword search fallback.
CREATE VIRTUAL TABLE IF NOT EXISTS fts_lines USING fts5(
    content,
    line_cid UNINDEXED,
    tokenize = 'porter unicode61'
);

-- FTS5 over context_prefix + chunk text for structural search.
CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
    context_prefix,
    chunk_text,                            -- populated at embed time from spans
    chunk_id UNINDEXED,
    tokenize = 'porter unicode61'
);

-- ── Ingest run log (Enhanced v0.3.0) ───────────────────────────────────────

-- Detailed run tracking with stage-by-stage progress for resumability and audit.
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at    TEXT,

    -- Source Context
    source_root     TEXT NOT NULL,

    -- File-Level Counts (detailed)
    files_discovered INTEGER NOT NULL DEFAULT 0,    -- Files found (pre-filtering)
    files_processed INTEGER NOT NULL DEFAULT 0,     -- Files successfully ingested
    files_skipped   INTEGER NOT NULL DEFAULT 0,     -- Files skipped (binary, etc.)

    -- Pipeline artifact counts
    chunks_created  INTEGER NOT NULL DEFAULT 0,
    chunks_embedded INTEGER NOT NULL DEFAULT 0,
    graph_nodes_created INTEGER NOT NULL DEFAULT 0,
    graph_edges_created INTEGER NOT NULL DEFAULT 0,

    -- Pipeline Configuration Snapshot (captured at ingest time)
    pipeline_ver    TEXT,
    embed_model     TEXT,
    embed_dims      INTEGER,
    git_commit      TEXT,

    -- Status & Error Tracking
    status          TEXT NOT NULL DEFAULT 'running',  -- running | success | failed | partial
    error           TEXT,                              -- Error message if status != success
    error_count     INTEGER DEFAULT 0,                 -- Count of errors encountered

    -- Stage Progress (for resumability and validation)
    stage_detect_complete BOOLEAN DEFAULT 0,           -- Stage 1: Detect & normalize
    stage_structural_complete BOOLEAN DEFAULT 0,       -- Stage 2-3: Parse & chunk
    stage_verbatim_complete BOOLEAN DEFAULT 0,         -- Stage 4: Write verbatim layer
    stage_embed_complete BOOLEAN DEFAULT 0,            -- Stage 7: Embeddings
    stage_graph_complete BOOLEAN DEFAULT 0,            -- Stage 8: Graph extraction
    stage_manifest_complete BOOLEAN DEFAULT 0,         -- Stage 9: Manifest finalization

    -- Performance Metrics
    duration_seconds REAL,                             -- Total runtime
    embedding_rate REAL,                               -- Chunks per second (for graphs)

    -- Metadata
    metadata_json   TEXT                               -- Free-form JSON for extensibility
);

-- ── Cartridge Manifest (Single-Row Metadata) ────────────────────────────────

-- Central metadata hub for the cartridge. Must contain exactly one row.
-- Enables orchestrators (like Node Walker Airlock) to validate and assess
-- the cartridge without scanning the entire database.
CREATE TABLE IF NOT EXISTS cartridge_manifest (
    cartridge_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    title TEXT,
    description TEXT,

    -- Schema & Pipeline Versioning
    schema_ver INTEGER NOT NULL DEFAULT 1,             -- Schema version (e.g., 1)
    pipeline_ver TEXT NOT NULL,                        -- Pipeline version (e.g., "0.1.0")

    -- Source Configuration
    source_root TEXT NOT NULL,                         -- Primary ingestion root
    source_roots_json TEXT,                            -- JSON array of all roots (multi-source)

    -- Embedding Configuration (global defaults)
    embed_model TEXT NOT NULL,                         -- e.g., "nomic-embed-text-v1.5.Q4_K_M.gguf"
    embed_dims INTEGER NOT NULL,                       -- e.g., 768

    -- Node Type Registry (Optional)
    node_types_registry_ver TEXT,                      -- e.g., "1.0"

    -- Layer Completion State
    structural_complete BOOLEAN DEFAULT 0,             -- Are all tree_nodes complete?
    semantic_complete BOOLEAN DEFAULT 0,               -- Are embeddings complete?
    graph_complete BOOLEAN DEFAULT 0,                  -- Are graph layers complete?
    search_index_complete BOOLEAN DEFAULT 0,           -- Are FTS indices built?

    -- Deployment Readiness
    is_deployable BOOLEAN DEFAULT 0,                   -- Can Airlock deploy this?
    deployment_notes TEXT,                             -- Why it is/isn't deployable

    -- Integrity Checksums (from last successful ingest)
    file_count INTEGER,                                -- Total files ingested
    tree_node_count INTEGER,                           -- Total tree nodes
    chunk_count INTEGER,                               -- Total chunks
    embedding_count INTEGER,                           -- Embedded chunks
    graph_node_count INTEGER,                          -- Graph nodes
    graph_edge_count INTEGER,                          -- Graph edges

    -- Source Code Version
    git_commit TEXT,                                   -- Ingestion source code version
    git_tag TEXT,

    -- Extensibility
    metadata_json TEXT                                 -- Free-form JSON
);

-- Ensure only one row can exist
CREATE UNIQUE INDEX IF NOT EXISTS idx_cartridge_manifest_singleton
ON cartridge_manifest(0);
"""


# ── Connection factory ─────────────────────────────────────────────────────────

def open_db(db_path: Path) -> sqlite3.Connection:
    """
    Open (or create) a Tripartite SQLite database at db_path.
    Applies the full schema, runs any pending migrations, and returns
    a ready connection.  Row factory is set so rows behave like dicts.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Apply schema (which includes PRAGMA user_version = 1 for v0.3.0)
    conn.executescript(SCHEMA_SQL)
    conn.commit()

    # Run migrations for existing databases that predate v0.2.0
    _migrate_v020_tier_columns(conn)

    # Initialize cartridge_manifest if it doesn't exist
    _initialize_cartridge_manifest(conn)

    return conn


def get_or_create_db(db_path: Path) -> sqlite3.Connection:
    """
    Alias for open_db — name used in CLI contexts to make intent clear.
    """
    return open_db(db_path)


# ── Migrations ─────────────────────────────────────────────────────────────────

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists on a table."""
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in info)


def _migrate_v020_tier_columns(conn: sqlite3.Connection) -> None:
    """
    v0.2.0 migration: Add semantic_depth, structural_depth, language_tier
    columns to chunk_manifest and language_tier to tree_nodes.

    Safe to call repeatedly — skips columns that already exist.
    """
    changed = False

    # ── chunk_manifest columns ────────────────────────────────────────────
    if not _column_exists(conn, "chunk_manifest", "semantic_depth"):
        conn.execute(
            "ALTER TABLE chunk_manifest ADD COLUMN semantic_depth INTEGER NOT NULL DEFAULT 0"
        )
        changed = True

    if not _column_exists(conn, "chunk_manifest", "structural_depth"):
        conn.execute(
            "ALTER TABLE chunk_manifest ADD COLUMN structural_depth INTEGER NOT NULL DEFAULT 0"
        )
        changed = True

    if not _column_exists(conn, "chunk_manifest", "language_tier"):
        conn.execute(
            "ALTER TABLE chunk_manifest ADD COLUMN language_tier TEXT NOT NULL DEFAULT 'unknown'"
        )
        changed = True

    # ── tree_nodes column ─────────────────────────────────────────────────
    if not _column_exists(conn, "tree_nodes", "language_tier"):
        conn.execute(
            "ALTER TABLE tree_nodes ADD COLUMN language_tier TEXT DEFAULT 'unknown'"
        )
        changed = True

    # ── Backfill existing data with best-guess tier info ──────────────────
    if changed:
        conn.execute("""
            UPDATE chunk_manifest SET
                language_tier = CASE
                    WHEN chunker LIKE '%python%'     THEN 'deep_semantic'
                    WHEN chunker LIKE '%javascript%'  THEN 'deep_semantic'
                    WHEN chunker LIKE '%typescript%'  THEN 'deep_semantic'
                    WHEN chunker LIKE '%java%'        THEN 'deep_semantic'
                    WHEN chunker LIKE '%go%'          THEN 'deep_semantic'
                    WHEN chunker LIKE '%rust%'        THEN 'deep_semantic'
                    WHEN chunker LIKE '%cpp%'         THEN 'deep_semantic'
                    WHEN chunker LIKE '%c_sharp%'     THEN 'deep_semantic'
                    WHEN chunker LIKE '%kotlin%'      THEN 'deep_semantic'
                    WHEN chunker LIKE '%scala%'       THEN 'deep_semantic'
                    WHEN chunker LIKE '%swift%'       THEN 'deep_semantic'
                    WHEN chunker LIKE '%bash%'        THEN 'shallow_semantic'
                    WHEN chunker LIKE '%ruby%'        THEN 'shallow_semantic'
                    WHEN chunker LIKE '%php%'         THEN 'shallow_semantic'
                    WHEN chunker LIKE '%_c_%'         THEN 'shallow_semantic'
                    WHEN chunker LIKE '%_r_%'         THEN 'shallow_semantic'
                    WHEN chunker LIKE '%json%'        THEN 'structural'
                    WHEN chunker LIKE '%yaml%'        THEN 'structural'
                    WHEN chunker LIKE '%toml%'        THEN 'structural'
                    WHEN chunker LIKE '%html%'        THEN 'hybrid'
                    WHEN chunker LIKE '%css%'         THEN 'hybrid'
                    WHEN chunker LIKE '%xml%'         THEN 'hybrid'
                    ELSE 'unknown'
                END
            WHERE language_tier = 'unknown'
        """)

        # For deep_semantic, depth IS semantic depth
        conn.execute("""
            UPDATE chunk_manifest SET
                semantic_depth = json_extract(hierarchy, '$.depth'),
                structural_depth = json_extract(hierarchy, '$.depth')
            WHERE language_tier = 'deep_semantic'
              AND semantic_depth = 0
        """)

        # For shallow_semantic, cap semantic depth at 1
        conn.execute("""
            UPDATE chunk_manifest SET
                structural_depth = json_extract(hierarchy, '$.depth'),
                semantic_depth = MIN(json_extract(hierarchy, '$.depth'), 1)
            WHERE language_tier = 'shallow_semantic'
              AND structural_depth = 0
        """)

        # structural & hybrid: semantic depth stays 0
        conn.execute("""
            UPDATE chunk_manifest SET
                structural_depth = json_extract(hierarchy, '$.depth')
            WHERE language_tier IN ('structural', 'hybrid')
              AND structural_depth = 0
        """)

        # Propagate tier to tree_nodes via the chunk join
        conn.execute("""
            UPDATE tree_nodes SET
                language_tier = (
                    SELECT cm.language_tier
                    FROM chunk_manifest cm
                    WHERE cm.node_id = tree_nodes.node_id
                    LIMIT 1
                )
            WHERE language_tier = 'unknown'
              AND EXISTS (
                  SELECT 1 FROM chunk_manifest cm
                  WHERE cm.node_id = tree_nodes.node_id
              )
        """)

        # Create indexes if missing (safe for existing DBs)
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_manifest_tier ON chunk_manifest(language_tier)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_manifest_depth ON chunk_manifest(language_tier, semantic_depth)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tree_nodes_tier ON tree_nodes(language_tier)"
            )
        except sqlite3.OperationalError:
            pass  # Indexes already exist

        conn.commit()


def _initialize_cartridge_manifest(conn: sqlite3.Connection) -> None:
    """
    Initialize cartridge_manifest table with a single row if it doesn't exist.

    This is called on every database open and is idempotent.
    If a row exists, it's left untouched (for resumability).
    """
    # Check if cartridge_manifest already has a row
    count = conn.execute("SELECT COUNT(*) FROM cartridge_manifest").fetchone()[0]

    if count == 0:
        # Initialize with defaults
        import uuid
        cartridge_id = str(uuid.uuid4())

        # Get default values - these will be updated by ingest pipeline
        pipeline_ver = "0.1.0"  # Will be updated during ingest
        embed_model = "nomic-embed-text-v1.5.Q4_K_M.gguf"  # Default
        embed_dims = 768
        source_root = ""  # Will be set at first ingest

        conn.execute(
            """
            INSERT INTO cartridge_manifest (
                cartridge_id, pipeline_ver, embed_model, embed_dims, source_root,
                schema_ver, structural_complete, semantic_complete,
                graph_complete, search_index_complete, is_deployable
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0)
            """,
            (cartridge_id, pipeline_ver, embed_model, embed_dims, source_root, 1)
        )
        conn.commit()
