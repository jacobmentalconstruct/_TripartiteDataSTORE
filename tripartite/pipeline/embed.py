"""
Pipeline Stages 6 & 7: Context Prefix Generation + Embedding

Stage 6 — Context prefix:
  Synthesize the heading_path string for each chunk and store in the manifest.
  Prepended to chunk text before embedding.

Stage 7 — Embed:
  Load the GGUF embedder via llama-cpp-python.
  Embed (context_prefix + chunk_text) for each chunk.
  Store raw float32 vector blob in the embeddings table.
  Update chunk_manifest.embed_status.

v0.3.1 — CRITICAL FIX: The embed/write/manifest/FTS block was at the wrong
  indentation level — it sat outside the per-chunk for loop, so only the last
  chunk in each batch was actually embedded. Now correctly inside the loop.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from typing import Optional

from ..chunkers.base import Chunk
from ..config import EMBEDDING_BATCH
from ..utils import build_context_prefix


# ── Context prefix ─────────────────────────────────────────────────────────────

def make_context_prefix(chunk: Chunk) -> str:
    """Return the context prefix string for a chunk."""
    return build_context_prefix(chunk.heading_path)


# ── Embedding ──────────────────────────────────────────────────────────────────

def embed_chunks(
    conn: sqlite3.Connection,
    chunks: list[Chunk],
    chunk_ids: list[str],
    node_ids: list[str],
    lazy: bool = False,
    on_progress=None,
) -> None:
    """
    Embed all chunks and write results to the embeddings table.

    Reads dims and model_name dynamically from the selected embedder spec
    so switching models in Settings Just Works™.

    on_progress: optional callable(event: dict) — fired per chunk with:
        {"type": "embedding_progress", "chunk_idx": i, "chunk_total": n, "filename": str}
    """
    if lazy:
        _mark_all_pending(conn, chunk_ids)
        return

    try:
        from ..models.manager import get_embedder, safe_embed, get_active_embedder_spec
        embedder = get_embedder()
        if embedder is None:
            _mark_all_pending(conn, chunk_ids)
            return
    except Exception as e:
        print(f"[embed] Warning: could not load embedder — {e}")
        print("[embed] Marking all chunks as pending.")
        _mark_all_pending(conn, chunk_ids)
        return

    # Read dims and model_name from the active embedder spec (not hardcoded)
    spec = get_active_embedder_spec()
    model_name = spec["filename"]
    dims = spec["dims"]
    total = len(chunks)

    # Process in batches to keep memory manageable
    for batch_start in range(0, total, EMBEDDING_BATCH):
        batch_end = batch_start + EMBEDDING_BATCH
        batch_chunks = chunks[batch_start:batch_end]
        batch_ids = chunk_ids[batch_start:batch_end]

        for i, (chunk, chunk_id) in enumerate(zip(batch_chunks, batch_ids)):
            global_idx = batch_start + i

            if on_progress is not None:
                try:
                    on_progress({
                        "type": "embedding_progress",
                        "chunk_idx": global_idx,
                        "chunk_total": total,
                    })
                except Exception:
                    pass

            prefix = make_context_prefix(chunk)
            full_text = f"{prefix}: {chunk.text}" if prefix else chunk.text

            # ── v0.3.1 FIX: This block was at the wrong indent level ─────
            # Previously it was OUTSIDE the for loop (8-space indent instead
            # of 12-space), so only the last chunk per batch got embedded.
            # Now correctly inside the per-chunk loop.
            try:
                vector = safe_embed(embedder, full_text)

                # Pad or truncate to expected dims
                if len(vector) < dims:
                    vector = vector + [0.0] * (dims - len(vector))
                else:
                    vector = vector[:dims]

                # Pack as little-endian float32 blob
                blob = struct.pack(f"<{dims}f", *vector)

                # Write to embeddings table
                conn.execute(
                    """
                    INSERT OR REPLACE INTO embeddings (chunk_id, model, dims, vector)
                    VALUES (?, ?, ?, ?)
                    """,
                    (chunk_id, model_name, dims, blob),
                )

                # Update manifest status
                conn.execute(
                    """
                    UPDATE chunk_manifest
                    SET embed_status = 'done', embed_model = ?, embed_dims = ?
                    WHERE chunk_id = ?
                    """,
                    (model_name, dims, chunk_id),
                )

                # FTS insert for the chunk text
                conn.execute(
                    """
                    INSERT INTO fts_chunks (context_prefix, chunk_text, chunk_id)
                    VALUES (?, ?, ?)
                    """,
                    (prefix, chunk.text, chunk_id),
                )

            except Exception as e:
                # CRITICAL: Log failures so they don't go silent
                print(f"[embed] chunk {chunk_id} failed: {e}")
                conn.execute(
                    """
                    UPDATE chunk_manifest
                    SET embed_status = 'error', embed_error = ?
                    WHERE chunk_id = ?
                    """,
                    (str(e)[:512], chunk_id),
                )


def _mark_all_pending(conn: sqlite3.Connection, chunk_ids: list[str]) -> None:
    for cid in chunk_ids:
        conn.execute(
            "UPDATE chunk_manifest SET embed_status = 'pending' WHERE chunk_id = ?",
            (cid,),
        )


# ── Cosine similarity helper (for future near-duplicate linking) ───────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def unpack_vector(blob: bytes) -> list[float]:
    """Unpack a float32 LE blob back to a list of floats."""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))
