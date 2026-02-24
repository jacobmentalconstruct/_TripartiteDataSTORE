"""
Pipeline Stages 3 & 4: Verbatim Write + Logical Tree Construction

Stage 3 — Verbatim write:
  Hash each line → deduplicate → insert new line_cid records.
  Insert source_file record with ordered line_cids JSON array.

Stage 4 — Logical tree:
  Create tree_node records for the source file and each chunk.
  Assign stable UUIDs. Wire parent/child relationships.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..chunkers.base import Chunk
from ..config import PIPELINE_VERSION
from ..pipeline.detect import SourceFile
from ..utils import cid as line_cid, stable_uuid


# ── Verbatim layer ─────────────────────────────────────────────────────────────

def write_verbatim(conn: sqlite3.Connection, source: SourceFile) -> list[str]:
    """
    Write all lines of *source* to the verbatim layer.

    Returns the ordered list of line CIDs (one per line), which is stored
    in source_files.line_cids as a JSON array.

    Lines that already exist in verbatim_lines are not re-inserted (CID
    deduplication is automatic via INSERT OR IGNORE).
    """
    line_cids: list[str] = []
    new_lines: list[tuple[str, str, int]] = []  # (cid, content, byte_len)

    for line in source.lines:
        lcid = line_cid(line)
        line_cids.append(lcid)
        new_lines.append((lcid, line, len(line.encode("utf-8"))))

    # Bulk insert — OR IGNORE silently skips existing CIDs
    conn.executemany(
        "INSERT OR IGNORE INTO verbatim_lines (line_cid, content, byte_len) VALUES (?, ?, ?)",
        new_lines,
    )

    # Bulk insert into FTS for lines that are actually new
    # We check which ones were actually inserted to avoid FTS duplication
    # (SQLite FTS5 has no IGNORE equivalent — we guard with a subquery)
    conn.executemany(
        """
        INSERT INTO fts_lines (content, line_cid)
        SELECT ?, ?
        WHERE NOT EXISTS (SELECT 1 FROM fts_lines WHERE line_cid = ?)
        """,
        [(line, lcid, lcid) for line, lcid in
         zip(source.lines, line_cids)],
    )

    return line_cids


def write_source_file(
    conn: sqlite3.Connection,
    source: SourceFile,
    line_cids: list[str],
) -> None:
    """
    Insert the source_file record.
    Uses INSERT OR REPLACE so re-ingesting the same file is idempotent.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO source_files
          (file_cid, path, name, source_type, language, encoding,
           line_count, byte_size, line_cids, pipeline_ver)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source.file_cid,
            str(source.path),
            source.path.name,
            source.source_type,
            source.language,
            source.encoding,
            len(source.lines),
            source.byte_size,
            json.dumps(line_cids),
            PIPELINE_VERSION,
        ),
    )


# ── Logical tree ───────────────────────────────────────────────────────────────

def build_tree(
    conn: sqlite3.Connection,
    source: SourceFile,
    chunks: list[Chunk],
    root_node_id: Optional[str] = None,
) -> tuple[str, list[str]]:
    """
    Create tree_node records for a source file and all its chunks.

    Returns:
        (file_node_id, [chunk_node_id, ...])
        where the list is parallel to *chunks*.
    """
    # File-level node
    file_node_id = stable_uuid()
    file_path = str(source.path)

    # Determine parent: root node of the DB (or provided root)
    parent_id = root_node_id  # None = top-level

    conn.execute(
        """
        INSERT OR REPLACE INTO tree_nodes
          (node_id, node_type, name, parent_id, path, depth,
           file_cid, line_start, line_end)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_node_id,
            "file",
            source.path.name,
            parent_id,
            file_path,
            0,
            source.file_cid,
            0,
            len(source.lines) - 1,
        ),
    )

    # Chunk nodes
    chunk_node_ids: list[str] = []
    for chunk in chunks:
        node_id = stable_uuid()
        chunk_node_ids.append(node_id)

        # Build path string: file_path + heading path
        path_parts = [file_path] + chunk.heading_path[1:]  # skip duplicate file name
        node_path = " > ".join(path_parts)

        conn.execute(
            """
            INSERT OR REPLACE INTO tree_nodes
              (node_id, node_type, name, parent_id, path, depth,
               file_cid, line_start, line_end)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id,
                chunk.chunk_type,
                chunk.name,
                file_node_id,
                node_path,
                chunk.depth + 1,
                source.file_cid,
                chunk.line_start,
                chunk.line_end,
            ),
        )

    return file_node_id, chunk_node_ids
