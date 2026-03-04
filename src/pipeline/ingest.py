"""
Ingest pipeline orchestrator.

Runs the full 9-stage pipeline for a source root (file or directory)
and writes all output to the target SQLite database.

Stages (per the coherent ingestion architecture spec):
  1. Detect & normalize
  2. Structural parse → chunk selection
  3. Chunk
  4. Verbatim write
  5. CID chunk hash (assign_chunk_ids)
  6. Context prefix generation
  7. Embed
  8. Entity extraction → graph write
  9. Manifest write

v0.2.0 — Updated _get_chunker to route structured (JSON, YAML, TOML) and
  markup (HTML, CSS) files through tree-sitter for tier-aware chunking,
  not just code files.

v0.3.0 — Added CompoundDocumentChunker integration. Files detected as
  compound documents (multi-file dumps) are routed through the compound
  chunker before falling through to prose.  Detection runs in _get_chunker()
  to keep detect.py fast and extension-based.
"""

from __future__ import annotations

import sqlite3
import time
import traceback
from pathlib import Path
from typing import Optional

from ..chunkers.base import Chunk
from ..chunkers.code import PythonChunker
from ..chunkers.prose import ProseChunker
from ..config import PIPELINE_VERSION
from ..db.schema import open_db
from ..pipeline.detect import SourceFile, detect, walk_source
from ..pipeline.embed import embed_chunks
from ..pipeline.extract import write_graph
from ..pipeline.manifest import assign_chunk_ids, write_manifest
from ..pipeline.verbatim import build_tree, write_source_file, write_verbatim
from ..utils import stable_uuid


# ── Extensions that tree-sitter can handle beyond "code" ──────────────────────
# These are classified as "structured" or "generic" by detect.py but
# tree-sitter has grammars for them and our tier system knows how to chunk them.
_TREESITTER_EXTRA_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".toml",         # structural tier
    ".html", ".htm", ".css", ".xml",           # hybrid tier
}


# ── Chunker registry ───────────────────────────────────────────────────────────

def _get_chunker(source: SourceFile):
    """
    Return the appropriate chunker for a source file.

    Priority:
    1. TreeSitterChunker for supported code languages (20+ languages)
    2. TreeSitterChunker for structural/markup files (JSON, YAML, HTML, CSS, etc.)
    3. PythonChunker for .py files (fallback if tree-sitter unavailable)
    4. CompoundDocumentChunker for multi-file dumps / concatenated sources
    5. ProseChunker for markdown, text, and generic files
    """
    from ..chunkers.treesitter import get_treesitter_chunker

    ext = source.path.suffix.lower()

    # Try tree-sitter for code files
    if source.source_type == "code":
        ts_chunker = get_treesitter_chunker(source)
        if ts_chunker is not None:
            lang = source.language or ext.lstrip(".")
            return ts_chunker, f"treesitter_{lang}_v2"

        # Fallback to Python AST chunker for .py files if tree-sitter unavailable
        if source.language == "python":
            return PythonChunker(), "ast_python_v1"

    # Try tree-sitter for structured and markup files
    if ext in _TREESITTER_EXTRA_EXTENSIONS:
        ts_chunker = get_treesitter_chunker(source)
        if ts_chunker is not None:
            lang = source.language or ext.lstrip(".")
            return ts_chunker, f"treesitter_{lang}_v2"

    # ── v0.3.0: Compound document detection ──────────────────────────────
    # Check if this is a multi-file dump before falling through to prose.
    # This runs on prose, generic, and structured files that weren't handled
    # by tree-sitter above.  The check is lightweight (line scanning, no ML).
    #
    # OPTIMIZATION: Skip compound detection for file types that will never be
    # compound documents. This avoids O(n) line scanning for shell scripts,
    # batch files, config files, etc.
    SKIP_COMPOUND_EXTENSIONS = {
        '.bat', '.cmd', '.ps1', '.sh', '.bash',     # Shell scripts (binary-adjacent)
        '.exe', '.dll', '.so', '.dylib',             # Binaries
        '.env', '.cfg', '.conf', '.ini',             # Config files
        '.gitignore', '.dockerignore',               # Special config files
    }

    if ext not in SKIP_COMPOUND_EXTENSIONS:
        try:
            from ..chunkers.compound import CompoundDocumentChunker, is_compound_document
            if is_compound_document(source):
                return CompoundDocumentChunker(), "compound_v1"
        except ImportError:
            pass  # compound.py not yet installed — skip gracefully

    # Default: prose chunker for markdown, text, generic, and unsupported code
    return ProseChunker(), "prose_v1"


# ── Per-file pipeline ──────────────────────────────────────────────────────────

def _ingest_file(
    conn: sqlite3.Connection,
    source: SourceFile,
    lazy: bool = False,
    verbose: bool = False,
    on_chunk=None,
    on_progress=None,
) -> tuple[int, int]:
    """
    Run the full pipeline for a single SourceFile.
    Returns (chunks_created, chunks_embedded).

    on_chunk:    optional callable(source, chunk, chunk_id, index, total)
    on_progress: optional callable(event: dict) for status bar updates
    """
    if verbose:
        print(f"  [{source.source_type}] {source.path.name}", flush=True)

    def _progress(event: dict):
        if on_progress:
            try:
                on_progress(event)
            except Exception:
                pass

    # ── Stage 2+3: Structural parse + chunk ──────────────────────────────
    chunker, chunker_name = _get_chunker(source)
    chunks = chunker.chunk(source)

    if not chunks:
        if verbose:
            print(f"    → 0 chunks (skipped)", flush=True)
        return 0, 0

    _progress({"type": "chunk_progress", "chunk_idx": 0, "chunk_total": len(chunks),
               "filename": source.path.name})

    # ── Stage 4: Verbatim write ──────────────────────────────────────────
    line_cids = write_verbatim(conn, source)
    write_source_file(conn, source, line_cids)

    # ── Stage 4b: Build logical tree ─────────────────────────────────────
    _, node_ids = build_tree(conn, source, chunks)

    # ── Stage 5: CID chunk hash ───────────────────────────────────────────
    chunk_ids = assign_chunk_ids(chunks)

    # ── Fire chunk callback ───────────────────────────────────────────────
    if on_chunk is not None:
        for i, (chunk, chunk_id) in enumerate(zip(chunks, chunk_ids)):
            try:
                on_chunk(source, chunk, chunk_id, i, len(chunks))
            except Exception:
                pass

    # ── Stage 9: Manifest write ───────────────────────────────────────────
    write_manifest(conn, chunks, chunk_ids, node_ids, chunker_name)

    # ── Stage 7: Embed ────────────────────────────────────────────────────
    embed_chunks(conn, chunks, chunk_ids, node_ids, lazy=lazy, on_progress=on_progress)

    # ── Stage 8: Entity extraction + graph ───────────────────────────────
    # v0.3.1: Pass on_progress so extraction fires progress events and
    # the GUI can check the stop flag between chunks.
    write_graph(conn, chunks, chunk_ids, node_ids, lazy=lazy, on_progress=on_progress)

    embedded = sum(1 for c in chunks) if lazy else _count_embedded(conn, chunk_ids)

    if verbose:
        print(f"    → {len(chunks)} chunks, {embedded} embedded", flush=True)

    return len(chunks), embedded


def _count_embedded(conn: sqlite3.Connection, chunk_ids: list[str]) -> int:
    if not chunk_ids:
        return 0
    placeholders = ",".join("?" * len(chunk_ids))
    row = conn.execute(
        f"SELECT COUNT(*) FROM chunk_manifest WHERE embed_status='done' AND chunk_id IN ({placeholders})",
        chunk_ids,
    ).fetchone()
    return row[0] if row else 0


# ── Top-level ingest ───────────────────────────────────────────────────────────

def ingest(
    source_root: Path,
    db_path: Path,
    lazy: bool = False,
    verbose: bool = True,
    on_chunk=None,
    on_progress=None,
) -> dict:
    """
    Ingest all eligible files under *source_root* into the database at *db_path*.

    on_progress: optional callable(event: dict) fired at key pipeline moments.
      Event types:
        {"type": "file_start",  "file_idx": int, "file_total": int, "filename": str}
        {"type": "file_done",   "file_idx": int, "file_total": int}
        {"type": "chunk_progress", "chunk_idx": int, "chunk_total": int, "filename": str}
        {"type": "embedding_progress", "chunk_idx": int, "chunk_total": int}
    """
    conn = open_db(db_path)
    run_id = stable_uuid()
    started = time.time()

    # Get embedding model and dimensions for this ingest run
    try:
        from ..models.manager import get_active_embedder_spec
        embedder_spec = get_active_embedder_spec()
        embed_model = embedder_spec.get("filename", "unknown") if embedder_spec else "unknown"
        embed_dims = embedder_spec.get("dims", 768) if embedder_spec else 768
    except Exception:
        embed_model = "unknown"
        embed_dims = 768

    # Register ingest run with configuration snapshot
    conn.execute(
        """
        INSERT INTO ingest_runs (
            run_id, source_root, pipeline_ver, embed_model, embed_dims,
            files_discovered, status
        ) VALUES (?, ?, ?, ?, ?, 0, 'running')
        """,
        (run_id, str(source_root), PIPELINE_VERSION, embed_model, embed_dims),
    )
    conn.commit()

    files_processed = 0
    files_discovered = 0
    files_skipped = 0
    chunks_created = 0
    chunks_embedded = 0
    errors: list[str] = []
    callback_errors: list[str] = []
    current_dir = None

    candidate_paths = list(walk_source(source_root))
    total = len(candidate_paths)
    files_discovered = total

    if verbose:
        mode = "lazy (no embedding)" if lazy else "full"
        print(f"\n[ingest] {total} file(s) found — mode: {mode}")
        print(f"[ingest] Output: {db_path}\n")

    # Update ingest_runs with discovered file count
    conn.execute(
        "UPDATE ingest_runs SET files_discovered = ? WHERE run_id = ?",
        (files_discovered, run_id),
    )
    conn.commit()

    def _progress(event):
        """Fire progress callback with error reporting instead of silent swallowing."""
        if on_progress:
            try:
                on_progress(event)
            except Exception as e:
                # Log callback error instead of silently suppressing
                err_msg = f"Progress callback error: {type(e).__name__}: {e}"
                callback_errors.append(err_msg)
                if verbose:
                    print(f"[ingest] {err_msg}")
                # Continue execution — don't re-raise

    for idx, path in enumerate(candidate_paths, 1):
        # Show subdirectory changes for visibility into traversal
        path_dir = path.parent
        if path_dir != current_dir and verbose:
            try:
                rel_dir = path_dir.relative_to(source_root)
            except ValueError:
                rel_dir = path_dir
            print(f"\n[ingest] Crawling: {rel_dir}/", flush=True)
            current_dir = path_dir

        if verbose and total > 1:
            print(f"[{idx}/{total}] {path.name}", flush=True)

        _progress({"type": "file_start", "file_idx": idx,
                   "file_total": total, "filename": path.name, "filepath": str(path)})

        source = detect(path)
        if source is None:
            if verbose:
                print(f"  → skipped (binary or unreadable)")
            files_skipped += 1
            _progress({"type": "file_done", "file_idx": idx, "file_total": total})
            continue

        try:
            with conn:
                fc, fe = _ingest_file(
                    conn, source, lazy=lazy, verbose=verbose,
                    on_chunk=on_chunk, on_progress=on_progress,
                )
                files_processed += 1
                chunks_created += fc
                chunks_embedded += fe
        except Exception as e:
            err = f"{path}: {e}"
            errors.append(err)
            if verbose:
                print(f"  ✗ ERROR: {err}")
                traceback.print_exc()

        _progress({"type": "file_done", "file_idx": idx, "file_total": total})

    elapsed = time.time() - started

    # Get final counts from database for cartridge_manifest
    tree_node_count = conn.execute("SELECT COUNT(*) FROM tree_nodes").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunk_manifest").fetchone()[0]
    embedding_count = conn.execute(
        "SELECT COUNT(*) FROM embeddings"
    ).fetchone()[0]
    graph_node_count = conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
    graph_edge_count = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]

    # Determine deployment readiness based on completion status
    final_status = "success" if not errors else "partial"
    all_embedded = chunk_count == embedding_count and chunk_count > 0
    graph_complete = graph_edge_count > 0 or chunk_count == 0
    is_deployable = all_embedded and graph_complete and not errors

    # Update ingest_runs record with full details
    conn.execute(
        """
        UPDATE ingest_runs
        SET completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
            files_processed = ?,
            files_skipped = ?,
            chunks_created = ?,
            chunks_embedded = ?,
            graph_nodes_created = ?,
            graph_edges_created = ?,
            status = ?,
            error_count = ?,
            duration_seconds = ?,
            stage_detect_complete = 1,
            stage_structural_complete = 1,
            stage_verbatim_complete = 1,
            stage_embed_complete = 1,
            stage_graph_complete = 1,
            stage_manifest_complete = 1
        WHERE run_id = ?
        """,
        (
            files_processed,
            files_skipped,
            chunks_created,
            chunks_embedded,
            graph_node_count,
            graph_edge_count,
            final_status,
            len(errors),
            round(elapsed, 2),
            run_id,
        ),
    )

    # Update cartridge_manifest with final state
    conn.execute(
        """
        UPDATE cartridge_manifest
        SET source_root = ?,
            pipeline_ver = ?,
            embed_model = ?,
            embed_dims = ?,
            structural_complete = 1,
            semantic_complete = ?,
            graph_complete = ?,
            search_index_complete = 1,
            is_deployable = ?,
            file_count = ?,
            tree_node_count = ?,
            chunk_count = ?,
            embedding_count = ?,
            graph_node_count = ?,
            graph_edge_count = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        (
            str(source_root),
            PIPELINE_VERSION,
            embed_model,
            embed_dims,
            1 if all_embedded else 0,
            1 if graph_complete else 0,
            is_deployable,
            files_processed,
            tree_node_count,
            chunk_count,
            embedding_count,
            graph_node_count,
            graph_edge_count,
        ),
    )

    conn.commit()
    conn.close()

    summary = {
        "run_id": run_id,
        "source_root": str(source_root),
        "db_path": str(db_path),
        "files_discovered": files_discovered,
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "chunks_created": chunks_created,
        "chunks_embedded": chunks_embedded,
        "graph_nodes": graph_node_count,
        "graph_edges": graph_edge_count,
        "status": final_status,
        "is_deployable": is_deployable,
        "errors": errors,
        "callback_errors": callback_errors,
        "elapsed_seconds": round(elapsed, 2),
    }

    if verbose:
        _print_summary(summary)

    return summary


def _print_summary(s: dict) -> None:
    print("\n" + "─" * 52)
    print("  Ingest complete")
    print("─" * 52)
    print(f"  Files discovered: {s['files_discovered']}")
    print(f"  Files processed : {s['files_processed']}")
    print(f"  Files skipped   : {s['files_skipped']}")
    print(f"  Chunks created  : {s['chunks_created']}")
    print(f"  Chunks embedded : {s['chunks_embedded']}")
    print(f"  Graph nodes     : {s['graph_nodes']}")
    print(f"  Graph edges     : {s['graph_edges']}")
    print(f"  Status          : {s['status']}")
    deployable_str = "DEPLOYABLE" if s['is_deployable'] else "NOT DEPLOYABLE"
    print(f"  Deployment      : {deployable_str}")
    print(f"  Time            : {s['elapsed_seconds']}s")
    print(f"  Output          : {s['db_path']}")
    if s["errors"]:
        print(f"\n  ⚠ {len(s['errors'])} ingestion error(s):")
        for e in s["errors"]:
            print(f"    · {e}")
    if s.get("callback_errors"):
        print(f"\n  ⚠ {len(s['callback_errors'])} callback error(s):")
        for e in s["callback_errors"]:
            print(f"    · {e}")
    print("─" * 52 + "\n")
