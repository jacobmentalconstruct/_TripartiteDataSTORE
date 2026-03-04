"""
tripartite/db/query.py

Database query functions for the viewer/query app.
All logic for reconstructing chunks, searching, and navigating the graph.

v0.2.0 — Chunk queries now surface semantic_depth, structural_depth, and
  language_tier.  New helpers for tier-based filtering added.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from typing import Optional


# ── Text Reconstruction ────────────────────────────────────────────────────────

def reconstruct_chunk_text(conn: sqlite3.Connection, chunk_id: str) -> str:
    """
    Reconstruct the full text of a chunk from the verbatim layer.

    Path: chunk_manifest.spans → source_files.line_cids → verbatim_lines.content
    """
    # Get the spans JSON from chunk_manifest
    row = conn.execute(
        "SELECT spans FROM chunk_manifest WHERE chunk_id = ?",
        (chunk_id,)
    ).fetchone()

    if not row or not row[0]:
        return ""

    spans = json.loads(row[0])
    if not spans:
        return ""

    # Reconstruct text from each span
    all_lines = []
    for span in spans:
        source_cid = span["source_cid"]
        line_start = span["line_start"]
        line_end = span["line_end"]

        # Get the source file's line_cids array
        src_row = conn.execute(
            "SELECT line_cids FROM source_files WHERE file_cid = ?",
            (source_cid,)
        ).fetchone()

        if not src_row or not src_row[0]:
            continue

        line_cids = json.loads(src_row[0])

        # Slice the line_cids for this span (inclusive end)
        span_line_cids = line_cids[line_start:line_end + 1]

        # Fetch the actual line content
        if span_line_cids:
            placeholders = ",".join("?" * len(span_line_cids))
            lines = conn.execute(
                f"SELECT content FROM verbatim_lines WHERE line_cid IN ({placeholders})",
                span_line_cids
            ).fetchall()
            all_lines.extend([line[0] for line in lines])

    return "\n".join(all_lines)


# ── File / Line Reconstruction ────────────────────────────────────────────────

def reconstruct_file_from_db(
    conn: sqlite3.Connection, file_cid: str
) -> Optional[str]:
    """Reconstruct full file content from verbatim_lines via source_files."""
    try:
        row = conn.execute(
            "SELECT line_cids FROM source_files WHERE file_cid = ?",
            (file_cid,)
        ).fetchone()
        if not row:
            return None
        cids = json.loads(row[0])
        placeholders = ",".join("?" * len(cids))
        lines_map = {}
        for r in conn.execute(
                f"SELECT line_cid, content FROM verbatim_lines "
                f"WHERE line_cid IN ({placeholders})", cids):
            lines_map[r[0]] = r[1]
        return "\n".join(lines_map.get(cid, "") for cid in cids)
    except Exception:
        return None


def reconstruct_lines(
    conn: sqlite3.Connection,
    file_cid: str,
    line_start: int,
    line_end: int,
) -> Optional[str]:
    """Reconstruct a range of lines from a source file (1-indexed)."""
    try:
        row = conn.execute(
            "SELECT line_cids FROM source_files WHERE file_cid = ?",
            (file_cid,)
        ).fetchone()
        if not row:
            return None
        cids = json.loads(row[0])
        subset = cids[max(0, line_start - 1):line_end]
        if not subset:
            return None
        placeholders = ",".join("?" * len(subset))
        lines_map = {}
        for r in conn.execute(
                f"SELECT line_cid, content FROM verbatim_lines "
                f"WHERE line_cid IN ({placeholders})", subset):
            lines_map[r[0]] = r[1]
        return "\n".join(lines_map.get(cid, "") for cid in subset)
    except Exception:
        return None


# ── Browse Panel Queries ───────────────────────────────────────────────────────

def list_source_files(conn: sqlite3.Connection) -> list[dict]:
    """Return all source files in the database."""
    rows = conn.execute("""
        SELECT file_cid, path, name, source_type, language, line_count, byte_size
        FROM source_files
        ORDER BY path
    """).fetchall()

    return [
        {
            "file_cid": r[0],
            "path": r[1],
            "name": r[2],
            "source_type": r[3],
            "language": r[4],
            "line_count": r[5],
            "byte_size": r[6],
        }
        for r in rows
    ]


def get_chunks_for_file(conn: sqlite3.Connection, file_cid: str) -> list[dict]:
    """Return all chunks for a given source file, including tier metadata."""
    rows = conn.execute("""
        SELECT
            cm.chunk_id,
            cm.chunk_type,
            cm.context_prefix,
            cm.token_count,
            cm.embed_status,
            cm.semantic_depth,
            cm.structural_depth,
            cm.language_tier,
            tn.line_start,
            tn.line_end
        FROM chunk_manifest cm
        JOIN tree_nodes tn ON cm.node_id = tn.node_id
        WHERE tn.file_cid = ?
        ORDER BY tn.line_start
    """, (file_cid,)).fetchall()

    return [
        {
            "chunk_id": r[0],
            "chunk_type": r[1],
            "context_prefix": r[2],
            "token_count": r[3],
            "embed_status": r[4],
            "semantic_depth": r[5],
            "structural_depth": r[6],
            "language_tier": r[7],
            "line_start": r[8],
            "line_end": r[9],
        }
        for r in rows
    ]


def get_chunk_detail(conn: sqlite3.Connection, chunk_id: str) -> Optional[dict]:
    """Return full details for a chunk including reconstructed text and neighbors."""
    row = conn.execute("""
        SELECT
            chunk_id,
            chunk_type,
            context_prefix,
            token_count,
            embed_status,
            embed_model,
            embed_error,
            chunker,
            node_id,
            semantic_depth,
            structural_depth,
            language_tier
        FROM chunk_manifest
        WHERE chunk_id = ?
    """, (chunk_id,)).fetchone()

    if not row:
        return None

    # Get line range from tree_nodes
    lines_row = conn.execute("""
        SELECT line_start, line_end, graph_node_id
        FROM tree_nodes
        WHERE node_id = ?
    """, (row[8],)).fetchone()

    line_start = lines_row[0] if lines_row else None
    line_end = lines_row[1] if lines_row else None
    graph_node_id = lines_row[2] if lines_row else None

    # Reconstruct the text
    text = reconstruct_chunk_text(conn, chunk_id)

    # Get graph neighbors if this chunk has a graph node
    neighbors = get_graph_neighbors(conn, graph_node_id) if graph_node_id else {}

    return {
        "chunk_id": row[0],
        "chunk_type": row[1],
        "context_prefix": row[2],
        "token_count": row[3],
        "embed_status": row[4],
        "embed_model": row[5],
        "embed_error": row[6],
        "chunker": row[7],
        "line_start": line_start,
        "line_end": line_end,
        "semantic_depth": row[9],
        "structural_depth": row[10],
        "language_tier": row[11],
        "text": text,
        "neighbors": neighbors,
    }


# ── Tier-based Queries (v0.2.0) ──────────────────────────────────────────────

def get_chunks_by_tier(
    conn: sqlite3.Connection,
    language_tier: str,
    min_semantic_depth: int = 0,
    max_semantic_depth: Optional[int] = None,
    chunk_type: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """
    Query chunks filtered by language tier and optional depth/type constraints.

    Useful for:
      - "show all deeply nested code" → tier='deep_semantic', min_depth=2
      - "show all config sections" → tier='structural'
      - "show all HTML sections" → tier='hybrid', chunk_type='html_section'
    """
    conditions = ["cm.language_tier = ?"]
    params: list = [language_tier]

    if min_semantic_depth > 0:
        conditions.append("cm.semantic_depth >= ?")
        params.append(min_semantic_depth)

    if max_semantic_depth is not None:
        conditions.append("cm.semantic_depth <= ?")
        params.append(max_semantic_depth)

    if chunk_type:
        conditions.append("cm.chunk_type = ?")
        params.append(chunk_type)

    params.append(limit)
    where_clause = " AND ".join(conditions)

    rows = conn.execute(f"""
        SELECT
            cm.chunk_id,
            cm.chunk_type,
            cm.context_prefix,
            cm.token_count,
            cm.semantic_depth,
            cm.structural_depth,
            cm.language_tier,
            tn.line_start,
            tn.line_end
        FROM chunk_manifest cm
        JOIN tree_nodes tn ON cm.node_id = tn.node_id
        WHERE {where_clause}
        ORDER BY cm.context_prefix
        LIMIT ?
    """, params).fetchall()

    return [
        {
            "chunk_id": r[0],
            "chunk_type": r[1],
            "context_prefix": r[2],
            "token_count": r[3],
            "semantic_depth": r[4],
            "structural_depth": r[5],
            "language_tier": r[6],
            "line_start": r[7],
            "line_end": r[8],
        }
        for r in rows
    ]


def get_tier_summary(conn: sqlite3.Connection) -> dict:
    """
    Get a summary of chunk counts grouped by language tier.
    Useful for the explorer view's sidebar statistics.
    """
    rows = conn.execute("""
        SELECT
            language_tier,
            COUNT(*) as chunk_count,
            COUNT(DISTINCT node_id) as node_count
        FROM chunk_manifest
        GROUP BY language_tier
        ORDER BY chunk_count DESC
    """).fetchall()

    return {
        r[0]: {"chunk_count": r[1], "node_count": r[2]}
        for r in rows
    }


def get_file_tree(conn: sqlite3.Connection) -> list[dict]:
    """
    Get the logical tree structure for the explorer view.
    Returns file nodes and their child chunk nodes with tier info.
    """
    rows = conn.execute("""
        SELECT
            node_id,
            node_type,
            name,
            parent_id,
            path,
            depth,
            file_cid,
            line_start,
            line_end,
            language_tier,
            chunk_id
        FROM tree_nodes
        ORDER BY path, depth, line_start
    """).fetchall()

    return [
        {
            "node_id": r[0],
            "node_type": r[1],
            "name": r[2],
            "parent_id": r[3],
            "path": r[4],
            "depth": r[5],
            "file_cid": r[6],
            "line_start": r[7],
            "line_end": r[8],
            "language_tier": r[9],
            "chunk_id": r[10],
        }
        for r in rows
    ]


# ── Graph Panel Queries ────────────────────────────────────────────────────────

def get_graph_neighbors(conn: sqlite3.Connection, graph_node_id: str) -> dict:
    """
    Get entities and related chunks for a given chunk's graph node.

    Returns:
        {
            "entities": [{node_id, label, entity_type, edge_type}, ...],
            "related_chunks": [{chunk_id, context_prefix, edge_type}, ...]
        }
    """
    if not graph_node_id:
        return {"entities": [], "related_chunks": []}

    # Find entities that this chunk mentions (MENTIONS edges)
    entity_rows = conn.execute("""
        SELECT DISTINCT
            gn.node_id,
            gn.label,
            gn.entity_type,
            ge.edge_type
        FROM graph_edges ge
        JOIN graph_nodes gn ON ge.dst_node_id = gn.node_id
        WHERE ge.src_node_id = ?
          AND gn.node_type = 'entity'
          AND ge.edge_type = 'MENTIONS'
        ORDER BY gn.salience DESC
    """, (graph_node_id,)).fetchall()

    entities = [
        {
            "node_id": r[0],
            "label": r[1],
            "entity_type": r[2],
            "edge_type": r[3],
        }
        for r in entity_rows
    ]

    # Find related chunks (PRECEDES, FOLLOWS, etc.)
    related_rows = conn.execute("""
        SELECT DISTINCT
            cm.chunk_id,
            cm.context_prefix,
            ge.edge_type
        FROM graph_edges ge
        JOIN graph_nodes gn ON (
            CASE
                WHEN ge.src_node_id = ? THEN ge.dst_node_id
                ELSE ge.src_node_id
            END
        ) = gn.node_id
        JOIN chunk_manifest cm ON gn.chunk_id = cm.chunk_id
        WHERE (ge.src_node_id = ? OR ge.dst_node_id = ?)
          AND gn.node_type = 'chunk'
          AND ge.edge_type IN ('PRECEDES', 'FOLLOWS', 'RELATES_TO')
        LIMIT 20
    """, (graph_node_id, graph_node_id, graph_node_id)).fetchall()

    related_chunks = [
        {
            "chunk_id": r[0],
            "context_prefix": r[1],
            "edge_type": r[2],
        }
        for r in related_rows
    ]

    return {
        "entities": entities,
        "related_chunks": related_chunks,
    }


# ── Search Panel Queries ───────────────────────────────────────────────────────

def fts_search(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict]:
    """Full-text search against fts_chunks."""
    try:
        rows = conn.execute("""
            SELECT
                chunk_id,
                context_prefix,
                snippet(fts_chunks, 1, '<mark>', '</mark>', '...', 32) as snippet,
                rank
            FROM fts_chunks
            WHERE fts_chunks MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()

        return [
            {
                "chunk_id": r[0],
                "context_prefix": r[1],
                "snippet": r[2],
                "score": abs(r[3]) if r[3] else 0.0,  # FTS rank is negative
                "search_type": "fts",
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        # FTS query syntax error - return empty results
        return []


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(vec_a, vec_b))
    mag_a = sum(x * x for x in vec_a) ** 0.5
    mag_b = sum(x * x for x in vec_b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def unpack_vector(blob: bytes) -> list[float]:
    """Unpack a float32 LE blob back to a list of floats."""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def semantic_search(
    conn: sqlite3.Connection,
    query: str,
    embedder,
    limit: int = 20
) -> list[dict]:
    """
    Semantic search using vector embeddings.

    Args:
        conn: Database connection
        query: Search query text
        embedder: Loaded embedder model (from models.manager.get_embedder)
        limit: Maximum results to return
    """
    # Embed the query
    try:
        result = embedder.embed(query)
        if result and isinstance(result[0], list):
            query_vec = result[0]
        else:
            query_vec = result
    except Exception as e:
        print(f"[search] Failed to embed query: {e}")
        return []

    # Fetch all embeddings and compute similarity
    rows = conn.execute("""
        SELECT e.chunk_id, e.vector, cm.context_prefix
        FROM embeddings e
        JOIN chunk_manifest cm ON e.chunk_id = cm.chunk_id
    """).fetchall()

    results = []
    for chunk_id, vector_blob, context_prefix in rows:
        chunk_vec = unpack_vector(vector_blob)
        score = cosine_similarity(query_vec, chunk_vec)
        results.append({
            "chunk_id": chunk_id,
            "context_prefix": context_prefix,
            "score": score,
            "search_type": "semantic",
        })

    # Sort by score descending and limit
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    embedder=None,
    limit: int = 20
) -> list[dict]:
    """
    Run both semantic and FTS search, merge results.
    Falls back to FTS-only if embedder is not available.
    """
    results_map = {}  # chunk_id -> result dict

    # Semantic search if embedder available
    if embedder is not None:
        try:
            semantic_results = semantic_search(conn, query, embedder, limit)
            for r in semantic_results:
                results_map[r["chunk_id"]] = r
        except Exception as e:
            print(f"[search] Semantic search failed: {e}")

    # FTS search
    fts_results = fts_search(conn, query, limit)
    for r in fts_results:
        chunk_id = r["chunk_id"]
        if chunk_id in results_map:
            # Merge: keep semantic score but add FTS snippet
            results_map[chunk_id]["snippet"] = r.get("snippet", "")
            results_map[chunk_id]["search_type"] = "hybrid"
        else:
            results_map[chunk_id] = r

    # Convert to list and sort
    results = list(results_map.values())
    results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    # Add text snippets for results that don't have them
    for r in results[:limit]:
        if "snippet" not in r or not r["snippet"]:
            # Get first 150 chars of chunk text
            text = reconstruct_chunk_text(conn, r["chunk_id"])
            r["snippet"] = text[:150] + "..." if len(text) > 150 else text

    return results[:limit]


# ── Graph Panel Queries (continued) ───────────────────────────────────────────

def list_entities(
    conn: sqlite3.Connection,
    entity_type_filter: Optional[str] = None
) -> list[dict]:
    """List all entities, optionally filtered by entity_type."""
    if entity_type_filter:
        rows = conn.execute("""
            SELECT node_id, label, entity_type, salience
            FROM graph_nodes
            WHERE node_type = 'entity' AND entity_type = ?
            ORDER BY salience DESC, label
        """, (entity_type_filter,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT node_id, label, entity_type, salience
            FROM graph_nodes
            WHERE node_type = 'entity'
            ORDER BY salience DESC, label
        """).fetchall()

    return [
        {
            "node_id": r[0],
            "label": r[1],
            "entity_type": r[2],
            "salience": r[3],
        }
        for r in rows
    ]


def get_entity_types(conn: sqlite3.Connection) -> list[str]:
    """Get all unique entity types in the database."""
    rows = conn.execute("""
        SELECT DISTINCT entity_type
        FROM graph_nodes
        WHERE node_type = 'entity' AND entity_type IS NOT NULL
        ORDER BY entity_type
    """).fetchall()
    return [r[0] for r in rows]


def get_chunks_mentioning_entity(
    conn: sqlite3.Connection,
    entity_node_id: str
) -> list[dict]:
    """Get all chunks that mention this entity."""
    rows = conn.execute("""
        SELECT DISTINCT
            cm.chunk_id,
            cm.context_prefix,
            cm.chunk_type
        FROM graph_edges ge
        JOIN graph_nodes gn ON ge.dst_node_id = gn.node_id
        JOIN chunk_manifest cm ON gn.chunk_id = cm.chunk_id
        WHERE ge.src_node_id = ?
          AND ge.edge_type = 'MENTIONS'
          AND gn.node_type = 'chunk'
        ORDER BY cm.context_prefix
    """, (entity_node_id,)).fetchall()

    return [
        {
            "chunk_id": r[0],
            "context_prefix": r[1],
            "chunk_type": r[2],
        }
        for r in rows
    ]


# ── Utility Functions ──────────────────────────────────────────────────────────

def get_db_stats(conn: sqlite3.Connection) -> dict:
    """Get database statistics for the status bar."""
    stats = {}

    # Count tables
    stats["files"] = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
    stats["chunks"] = conn.execute("SELECT COUNT(*) FROM chunk_manifest").fetchone()[0]
    stats["embeddings"] = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    stats["entities"] = conn.execute(
        "SELECT COUNT(*) FROM graph_nodes WHERE node_type = 'entity'"
    ).fetchone()[0]

    # Tier breakdown
    stats["tier_summary"] = get_tier_summary(conn)

    # Last ingest run
    row = conn.execute("""
        SELECT run_id, started_at, completed_at, files_processed, chunks_created, status
        FROM ingest_runs
        ORDER BY started_at DESC
        LIMIT 1
    """).fetchone()

    if row:
        stats["last_run"] = {
            "run_id": row[0],
            "started_at": row[1],
            "completed_at": row[2],
            "files_processed": row[3],
            "chunks_created": row[4],
            "status": row[5],
        }
    else:
        stats["last_run"] = None

    return stats
