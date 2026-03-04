"""
src/db/search.py

Standalone search functions for the Query Builder.
Extracted from the monolithic datastore.py (hunk 07, lines 1127-1189).

These take ``conn`` as a first argument so the GUI does not
contain SQL strings or embedding logic.
"""

from __future__ import annotations

import sqlite3
from typing import Callable, Optional


def query_semantic_layer(
    conn: sqlite3.Connection,
    query: str,
    top_k: int,
    log_fn: Optional[Callable] = None,
) -> list[tuple]:
    """Search semantic embeddings via cosine similarity.

    Returns list of (score, chunk_type, name, preview) tuples.
    Falls back to verbatim search if embedding fails.
    """
    results: list[tuple] = []

    def _log(tag, msg, level="dim"):
        if log_fn:
            log_fn(tag, msg, level)

    try:
        from ..models.manager import ModelManager
        mm = ModelManager()
        q_vec = mm.embed(query)

        if q_vec is not None:
            import numpy as np

            rows = conn.execute("""
                SELECT cm.chunk_id, cm.chunk_type, tn.name,
                       e.vector
                FROM chunk_manifest cm
                JOIN embeddings e ON e.chunk_id = cm.chunk_id
                LEFT JOIN tree_nodes tn ON tn.chunk_id = cm.chunk_id
                WHERE cm.embed_status = 'done'
            """).fetchall()

            for chunk_id, chunk_type, name, emb_blob in rows:
                emb = np.frombuffer(emb_blob, dtype=np.float32)
                score = float(np.dot(q_vec, emb) / (
                    np.linalg.norm(q_vec) * np.linalg.norm(emb) + 1e-10))
                preview = (name or chunk_type or "")[:200]
                results.append((score, chunk_type, name or "", preview))

            results.sort(key=lambda r: r[0], reverse=True)
            return results[:top_k]

    except ImportError:
        _log("Query", "ModelManager not available \u2014 using text fallback", "warning")
    except Exception as e:
        _log("Query", f"Semantic search error: {e}", "warning")

    # Fallback: verbatim search
    return query_verbatim_layer(conn, query, top_k)


def query_verbatim_layer(
    conn: sqlite3.Connection,
    query: str,
    top_k: int,
) -> list[tuple]:
    """Search verbatim layer using LIKE matching.

    Returns list of (score, chunk_type, name, preview) tuples.
    """
    results: list[tuple] = []
    try:
        rows = conn.execute("""
            SELECT cm.chunk_id, cm.chunk_type, tn.name, cm.context_prefix
            FROM chunk_manifest cm
            LEFT JOIN tree_nodes tn ON tn.chunk_id = cm.chunk_id
            WHERE cm.context_prefix LIKE ?
               OR tn.name LIKE ?
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", top_k)).fetchall()

        for chunk_id, chunk_type, name, ctx_prefix in rows:
            content_lower = (ctx_prefix or "").lower()
            query_lower = query.lower()
            count = content_lower.count(query_lower)
            score = min(count * 0.2, 1.0) if count else 0.1
            preview = (ctx_prefix or name or "")[:200]
            results.append((score, chunk_type, name, preview))
    except Exception:
        pass

    return results
