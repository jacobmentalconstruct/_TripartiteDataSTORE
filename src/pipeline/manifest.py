"""
Pipeline Stage 9: Manifest Write

Writes the chunk_manifest record for each chunk — the central join record
that ties together the verbatim layer, semantic layer, and graph layer.

This is the last step of the pipeline for each file.  By the time this
runs, all other stages have completed and the chunk_id, node_id, and
graph references are all known.

v0.2.0 — Now writes semantic_depth, structural_depth, language_tier as
  proper SQL columns AND includes them in the hierarchy JSON blob for
  backward compatibility with older viewer code.
"""

from __future__ import annotations

import json
import sqlite3

from ..chunkers.base import Chunk
from ..config import PIPELINE_VERSION
from ..utils import build_context_prefix, chunk_cid


def write_manifest(
    conn: sqlite3.Connection,
    chunks: list[Chunk],
    chunk_ids: list[str],
    node_ids: list[str],
    chunker_name: str,
) -> None:
    """
    Write chunk_manifest records for all chunks in a file.

    chunk_ids and node_ids are parallel lists produced by earlier pipeline
    stages (verbatim.build_tree returns node_ids; chunk_ids come from
    _assign_chunk_ids).
    """
    # Build a local index so we can resolve prev/next chunk_ids from indices
    idx_to_chunk_id = {i: cid for i, cid in enumerate(chunk_ids)}

    for i, (chunk, chunk_id, node_id) in enumerate(
        zip(chunks, chunk_ids, node_ids)
    ):
        context_prefix = build_context_prefix(chunk.heading_path)

        # Hierarchy JSON — includes tier fields for backward compat
        parent_chunk_id = (
            idx_to_chunk_id.get(chunk.parent_chunk_idx)
            if chunk.parent_chunk_idx is not None
            else None
        )
        hierarchy = {
            "parent_chunk_id": parent_chunk_id,
            "heading_path": chunk.heading_path,
            "depth": chunk.depth,
            # v0.2.0: redundant in JSON for backward compat
            "semantic_depth": chunk.semantic_depth,
            "structural_depth": chunk.structural_depth,
            "language_tier": chunk.language_tier,
        }

        # Overlap JSON
        prev_chunk_id = (
            idx_to_chunk_id.get(chunk.prev_chunk_idx)
            if chunk.prev_chunk_idx is not None
            else None
        )
        next_chunk_id = (
            idx_to_chunk_id.get(chunk.next_chunk_idx)
            if chunk.next_chunk_idx is not None
            else None
        )
        overlap = {
            "prev_chunk_id": prev_chunk_id,
            "next_chunk_id": next_chunk_id,
            "prefix_lines": chunk.overlap_prefix_lines,
            "suffix_lines": chunk.overlap_suffix_lines,
        }

        # Spans JSON
        spans = [s.to_dict() for s in chunk.spans]

        # Token count estimate
        from ..utils import estimate_tokens
        token_count = estimate_tokens(chunk.text)

        conn.execute(
            """
            INSERT OR REPLACE INTO chunk_manifest
              (chunk_id, node_id, chunk_type, context_prefix, token_count,
               spans, hierarchy, overlap,
               semantic_depth, structural_depth, language_tier,
               chunker, pipeline_ver)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                node_id,
                chunk.chunk_type,
                context_prefix,
                token_count,
                json.dumps(spans),
                json.dumps(hierarchy),
                json.dumps(overlap),
                chunk.semantic_depth,
                chunk.structural_depth,
                chunk.language_tier,
                chunker_name,
                PIPELINE_VERSION,
            ),
        )

        # Update the tree node to point at its chunk
        conn.execute(
            "UPDATE tree_nodes SET chunk_id = ? WHERE node_id = ?",
            (chunk_id, node_id),
        )


def assign_chunk_ids(chunks: list[Chunk]) -> list[str]:
    """
    Compute the chunk_id for each chunk from the canonical text of its spans.
    This is stage 5 of the pipeline (CID chunk hash).
    Deduplication across sources is automatic — same content = same chunk_id.
    """
    return [chunk_cid(chunk.text) for chunk in chunks]
