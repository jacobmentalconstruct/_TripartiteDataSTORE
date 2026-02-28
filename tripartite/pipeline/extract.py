"""
Pipeline Stage 8: Entity Extraction + Graph Layer

Uses the GGUF instruction-tuned model (Qwen2.5-0.5B) to extract:
  - Named entities with types and salience scores
  - Relationships between entities

Writes:
  - graph_nodes records (one per unique entity + one per chunk)
  - graph_edges records (MENTIONS, RELATES_TO, structural edges)

v0.3.1 — Added on_progress callback to write_graph() so the GUI can:
  1. Show extraction progress (not just "Extractor ready" then silence)
  2. Check the stop flag between chunks (previously unstoppable)
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Optional

from ..chunkers.base import Chunk
from ..config import ENTITY_EXTRACTION_PROMPT
from ..utils import stable_uuid


# ── Entity extraction ──────────────────────────────────────────────────────────

def extract_entities(text: str, extractor) -> dict:
    """
    Run the entity extraction prompt against the extractor model.
    Returns parsed JSON dict with 'entities' and 'relationships' keys.
    Falls back to empty structure on any failure.
    """
    prompt = ENTITY_EXTRACTION_PROMPT.format(chunk_text=text[:3000])

    try:
        response = extractor(
            prompt,
            max_tokens=512,
            temperature=0.0,
            echo=False,
        )
        raw = response["choices"][0]["text"].strip()

        # Strip markdown code fences if model wrapped output
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        return json.loads(raw)

    except (json.JSONDecodeError, KeyError, IndexError, Exception):
        return {"entities": [], "relationships": []}


# ── Graph writing ──────────────────────────────────────────────────────────────

def write_graph(
    conn: sqlite3.Connection,
    chunks: list[Chunk],
    chunk_ids: list[str],
    node_ids: list[str],
    lazy: bool = False,
    on_progress=None,
) -> None:
    """
    For each chunk: create a graph node, extract entities, write entity nodes
    and edges into the graph layer.

    Structural edges (PART_OF, PRECEDES) are wired from chunk ordering alone
    and don't require the extractor — always written even in lazy mode.

    Entity extraction requires the extractor model and is skipped in lazy mode.

    v0.3.1: Added on_progress parameter. Fires extraction_progress events so
    the GUI can update its progress bar and check the stop flag. Without this,
    the extraction loop was completely opaque — no progress, no stop, no skip.

    on_progress: optional callable(event: dict) — fired per chunk with:
        {"type": "extraction_progress", "chunk_idx": i, "chunk_total": n}
    """
    # Create chunk graph nodes first (no model needed)
    chunk_graph_node_ids: list[str] = []
    for chunk, chunk_id, tree_node_id in zip(chunks, chunk_ids, node_ids):
        gnode_id = stable_uuid()
        chunk_graph_node_ids.append(gnode_id)
        conn.execute(
            """
            INSERT OR REPLACE INTO graph_nodes
              (node_id, node_type, label, chunk_id)
            VALUES (?, ?, ?, ?)
            """,
            (gnode_id, "chunk", chunk.name, chunk_id),
        )
        # Update the tree node with its graph_node_id
        conn.execute(
            "UPDATE tree_nodes SET graph_node_id = ? WHERE node_id = ?",
            (gnode_id, tree_node_id),
        )
        # Update the manifest with graph node id
        conn.execute(
            "UPDATE chunk_manifest SET graph_status = 'structural' WHERE chunk_id = ?",
            (chunk_id,),
        )

    # Write structural edges: PART_OF and PRECEDES between adjacent chunks
    _write_structural_edges(conn, chunk_graph_node_ids, chunks)

    if lazy:
        return

    # Entity extraction (requires extractor model)
    try:
        from ..models.manager import get_extractor
        extractor = get_extractor()
        if extractor is None:
            return
    except Exception as e:
        print(f"[graph] Warning: could not load extractor — {e}")
        print("[graph] Skipping entity extraction. Graph has structural edges only.")
        return

    # Entity node cache to deduplicate within this ingest run
    entity_cache: dict[str, str] = {}  # label.lower() → graph_node_id

    # ── v0.3.1: Count extractable chunks for progress reporting ──────────
    extractable = [
        (chunk, chunk_id, gnode_id)
        for chunk, chunk_id, gnode_id
        in zip(chunks, chunk_ids, chunk_graph_node_ids)
        if len(chunk.text.strip()) >= 50
    ]
    total_extractable = len(extractable)

    for ext_idx, (chunk, chunk_id, gnode_id) in enumerate(extractable):
        # ── v0.3.1: Fire progress so GUI can update + check stop flag ────
        if on_progress is not None:
            try:
                on_progress({
                    "type": "extraction_progress",
                    "chunk_idx": ext_idx,
                    "chunk_total": total_extractable,
                })
            except Exception:
                # If on_progress raises (e.g. _StopIngest), let it propagate.
                # The bare `except Exception` won't catch BaseException subclasses
                # like _StopIngest, which is exactly what we want.
                pass

        result = extract_entities(chunk.text, extractor)

        # Write entity nodes and MENTIONS edges
        for entity in result.get("entities", []):
            label = entity.get("text", "").strip()
            etype = entity.get("type", "CONCEPT")
            salience = float(entity.get("salience", 0.5))

            if not label:
                continue

            cache_key = label.lower()
            if cache_key not in entity_cache:
                entity_node_id = stable_uuid()
                entity_cache[cache_key] = entity_node_id
                conn.execute(
                    """
                    INSERT OR IGNORE INTO graph_nodes
                      (node_id, node_type, label, entity_type, salience)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (entity_node_id, "entity", label, etype, salience),
                )
            else:
                entity_node_id = entity_cache[cache_key]

            # MENTIONS edge: chunk → entity
            conn.execute(
                """
                INSERT INTO graph_edges (edge_id, src_node_id, dst_node_id, edge_type, weight)
                VALUES (?, ?, ?, 'MENTIONS', ?)
                """,
                (stable_uuid(), gnode_id, entity_node_id, salience),
            )

        # Write relationship edges
        for rel in result.get("relationships", []):
            subj = rel.get("subject", "").strip().lower()
            obj = rel.get("object", "").strip().lower()
            pred = rel.get("predicate", "").strip()

            if subj in entity_cache and obj in entity_cache:
                conn.execute(
                    """
                    INSERT INTO graph_edges
                      (edge_id, src_node_id, dst_node_id, edge_type, predicate)
                    VALUES (?, ?, ?, 'RELATES_TO', ?)
                    """,
                    (stable_uuid(), entity_cache[subj], entity_cache[obj], pred),
                )

        # Mark as fully processed
        conn.execute(
            "UPDATE chunk_manifest SET graph_status = 'done' WHERE chunk_id = ?",
            (chunk_id,),
        )


def _write_structural_edges(
    conn: sqlite3.Connection,
    graph_node_ids: list[str],
    chunks: list[Chunk],
) -> None:
    """
    Write PRECEDES edges between sequential chunks.
    (PART_OF edges between child/parent chunks would go here too
     in a future pass once the full tree is built.)
    """
    for i in range(len(graph_node_ids) - 1):
        conn.execute(
            """
            INSERT INTO graph_edges
              (edge_id, src_node_id, dst_node_id, edge_type, weight)
            VALUES (?, ?, ?, 'PRECEDES', 1.0)
            """,
            (stable_uuid(), graph_node_ids[i], graph_node_ids[i + 1]),
        )
