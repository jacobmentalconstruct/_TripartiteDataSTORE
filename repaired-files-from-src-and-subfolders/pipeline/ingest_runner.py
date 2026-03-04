"""
src/pipeline/ingest_runner.py

High-level ingest orchestrator — runs the full pipeline across a source
directory. Extracted from the monolithic datastore.py (hunk 08).

This module does NOT modify the per-file pipeline in ``src/pipeline/ingest.py``.
It only wraps the walk → detect → ingest loop that the GUI used to own.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable, Optional


def run_ingest(
    conn,
    source_path: str,
    lazy: bool = False,
    log_fn: Optional[Callable] = None,
    progress_fn: Optional[Callable] = None,
    cancel_check_fn: Optional[Callable] = None,
) -> dict:
    """Run the full ingest pipeline in the *calling* thread.

    Parameters
    ----------
    conn : sqlite3.Connection
        Active connection to the Tripartite database.
    source_path : str
        Path to the source directory or file.
    lazy : bool
        If True, skip embedding (lazy mode).
    log_fn : callable(msg, level)
        Append a line to the ingest log.
    progress_fn : callable(pct, current, total)
        Update progress bar (percentage, current index, total count).
    cancel_check_fn : callable() -> bool
        Return True if the user has requested cancellation.

    Returns
    -------
    dict with keys: processed, chunks, embedded, errors
    """

    def _log(msg, level="dim"):
        if log_fn:
            log_fn(msg, level)

    def _progress(pct, cur, total):
        if progress_fn:
            progress_fn(pct, cur, total)

    def _cancelled():
        return cancel_check_fn() if cancel_check_fn else False

    result = {"processed": 0, "chunks": 0, "embedded": 0, "errors": 0}

    try:
        path = Path(source_path)
        if not path.exists():
            _log(f"Path not found: {source_path}", "error")
            return result

        # Import pipeline
        try:
            from .detect import walk_source, detect
            from .ingest import _ingest_file
        except ImportError:
            _log("Pipeline not available \u2014 ensure tripartite package is installed", "error")
            return result

        # Discover files
        _log("Scanning source...", "accent")
        candidates = list(walk_source(path))
        total = len(candidates)
        _log(f"Found {total} candidate files", "info")
        if lazy:
            _log("Mode: lazy (no embedding)", "dim")

        if total == 0:
            _log("No files to ingest", "warning")
            return result

        for i, fpath in enumerate(candidates):
            if _cancelled():
                _log("Ingest cancelled by user", "warning")
                break

            pct = ((i + 1) / total) * 100
            _progress(pct, i + 1, total)

            try:
                sf = detect(fpath)
                if sf is None:
                    continue

                def _on_progress(event, _fname=fpath.name):
                    etype = event.get("type", "")
                    if etype == "chunk_progress":
                        ci = event.get("chunk_idx", 0)
                        ct = event.get("chunk_total", 0)
                        if ci == 0:
                            _log(f"  Chunking {_fname} ({ct} chunks)...", "dim")
                    elif etype == "embedding_progress":
                        ci = event.get("chunk_idx", 0)
                        ct = event.get("chunk_total", 0)
                        if (ci + 1) % 20 == 0:
                            _log(f"    Embedded {ci+1}/{ct}", "dim")

                with conn:
                    fc, fe = _ingest_file(
                        conn, sf,
                        lazy=lazy,
                        verbose=False,
                        on_progress=_on_progress,
                    )
                    result["chunks"] += fc
                    result["embedded"] += fe

                result["processed"] += 1
                _log(f"  \u2713 {fpath.name} ({fc} chunks)", "success")

            except Exception as e:
                result["errors"] += 1
                _log(f"  \u2717 {fpath.name}: {e}", "error")

        _log(
            f"\nDone: {result['processed']} files, {result['chunks']} chunks, "
            f"{result['embedded']} embedded, {result['errors']} errors",
            "success",
        )

    except Exception as e:
        _log(f"\nFatal error: {e}", "error")
        _log(traceback.format_exc(), "error")

    return result


def get_ingest_stats(conn, db_path: Optional[str] = None) -> dict:
    """Return post-ingest database statistics.

    Returns dict with keys: files, chunks, embedded, nodes, edges, size_mb
    """
    stats = {"files": 0, "chunks": 0, "embedded": 0, "nodes": 0, "edges": 0, "size_mb": 0.0}

    if not conn:
        return stats

    try:
        def q(sql):
            row = conn.execute(sql).fetchone()
            return row[0] if row else 0

        stats["files"] = q("SELECT COUNT(*) FROM source_files")
        stats["chunks"] = q("SELECT COUNT(*) FROM chunk_manifest")
        stats["embedded"] = q("SELECT COUNT(*) FROM chunk_manifest WHERE embed_status='done'")
        stats["nodes"] = q("SELECT COUNT(*) FROM graph_nodes")
        stats["edges"] = q("SELECT COUNT(*) FROM graph_edges")

        if db_path:
            stats["size_mb"] = Path(db_path).stat().st_size / 1_048_576
    except Exception:
        pass

    return stats
