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
"""

import sqlite3
from pathlib import Path


# ── DDL ────────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

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

-- ── Layer 2a: Chunk Manifest ───────────────────────────────────────────────

-- Central join record across all three storage layers.
CREATE TABLE IF NOT EXISTS chunk_manifest (
    chunk_id        TEXT PRIMARY KEY,      -- cid:sha256:<hash of canonical span text>
    node_id         TEXT NOT NULL REFERENCES tree_nodes(node_id),
    chunk_type      TEXT NOT NULL,         -- function_def | section | paragraph | …
    context_prefix  TEXT NOT NULL,         -- prepended to text before embedding
    token_count     INTEGER NOT NULL,
    spans           TEXT NOT NULL,         -- JSON array of span reference objects
    hierarchy       TEXT NOT NULL,         -- JSON: {parent_chunk_id, heading_path, depth}
    overlap         TEXT NOT NULL,         -- JSON: {prev_chunk_id, next_chunk_id, prefix_lines, suffix_lines}

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

-- ── Ingest run log ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at    TEXT,
    source_root     TEXT NOT NULL,
    files_processed INTEGER NOT NULL DEFAULT 0,
    chunks_created  INTEGER NOT NULL DEFAULT 0,
    chunks_embedded INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running',  -- running | done | failed
    error           TEXT
);
"""


# ── Connection factory ─────────────────────────────────────────────────────────

def open_db(db_path: Path) -> sqlite3.Connection:
    """
    Open (or create) a Tripartite SQLite database at db_path.
    Applies the full schema and returns a ready connection.
    Row factory is set so rows behave like dicts.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def get_or_create_db(db_path: Path) -> sqlite3.Connection:
    """
    Alias for open_db — name used in CLI contexts to make intent clear.
    """
    return open_db(db_path)
