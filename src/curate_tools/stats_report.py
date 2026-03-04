"""
src/curate_tools/stats_report.py — Example drop-in curation tool.

Generates a detailed statistics report about the database contents.
Demonstrates the BaseCurationTool contract for third-party tool authors.
"""

from __future__ import annotations

import json
import sqlite3
import tkinter as tk
from pathlib import Path

# Import from the data_store module where BaseCurationTool lives
from ..data_store import BaseCurationTool, BG, BG2, FG, FONT_SM


class StatsReportTool(BaseCurationTool):
    """Generate a detailed statistics report about the knowledge store."""

    @property
    def name(self) -> str:
        return "Stats Report"

    @property
    def description(self) -> str:
        return "Generate a detailed breakdown of DB contents by type, language, and tier"

    @property
    def icon(self) -> str:
        return "📊"

    @property
    def priority(self) -> int:
        return 5  # Show near the top

    def build_config_ui(self, parent: tk.Frame) -> tk.Frame:
        frame = tk.Frame(parent, bg=BG)
        self._show_chunks_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            frame, text="Include chunk type breakdown",
            variable=self._show_chunks_var, bg=BG, fg=FG,
            selectcolor=BG2, activebackground=BG, activeforeground=FG,
            font=FONT_SM
        ).pack(anchor="w")

        self._show_tiers_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            frame, text="Include language tier breakdown",
            variable=self._show_tiers_var, bg=BG, fg=FG,
            selectcolor=BG2, activebackground=BG, activeforeground=FG,
            font=FONT_SM
        ).pack(anchor="w")
        return frame

    def run(self, conn: sqlite3.Connection, selection, on_progress=None, on_log=None) -> dict:
        log = on_log or (lambda m, t="info": None)

        # Basic counts
        files = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
        lines = conn.execute("SELECT COUNT(*) FROM verbatim_lines").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunk_manifest").fetchone()[0]
        embedded = conn.execute(
            "SELECT COUNT(*) FROM chunk_manifest WHERE embed_status='done'"
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM chunk_manifest WHERE embed_status='pending'"
        ).fetchone()[0]
        errors = conn.execute(
            "SELECT COUNT(*) FROM chunk_manifest WHERE embed_status='error'"
        ).fetchone()[0]
        nodes = conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        edges = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]

        log("═══ Database Overview ═══", "accent")
        log(f"  Source files  : {files}")
        log(f"  Verbatim lines: {lines}")
        log(f"  Total chunks  : {chunks}")
        log(f"  Embedded      : {embedded}")
        log(f"  Pending       : {pending}")
        if errors:
            log(f"  Errors        : {errors}", "warning")
        log(f"  Graph nodes   : {nodes}")
        log(f"  Graph edges   : {edges}")

        # Source type breakdown
        log("\n═══ Source Types ═══", "accent")
        rows = conn.execute(
            "SELECT source_type, COUNT(*) as n FROM source_files "
            "GROUP BY source_type ORDER BY n DESC"
        ).fetchall()
        for stype, count in rows:
            log(f"  {stype:<16} {count} file(s)")

        # Language breakdown
        log("\n═══ Languages ═══", "accent")
        rows = conn.execute(
            "SELECT language, COUNT(*) as n FROM source_files "
            "WHERE language IS NOT NULL "
            "GROUP BY language ORDER BY n DESC"
        ).fetchall()
        if rows:
            for lang, count in rows:
                log(f"  {lang:<16} {count} file(s)")
        else:
            log("  (no language data)", "dim")

        # Chunk type breakdown
        if self._show_chunks_var.get():
            log("\n═══ Chunk Types ═══", "accent")
            rows = conn.execute(
                "SELECT chunk_type, COUNT(*) as n FROM chunk_manifest "
                "GROUP BY chunk_type ORDER BY n DESC"
            ).fetchall()
            for ctype, count in rows:
                log(f"  {ctype:<24} {count}")

        # Language tier breakdown
        if self._show_tiers_var.get():
            log("\n═══ Language Tiers ═══", "accent")
            rows = conn.execute(
                "SELECT language_tier, COUNT(*) as n FROM chunk_manifest "
                "WHERE language_tier IS NOT NULL "
                "GROUP BY language_tier ORDER BY n DESC"
            ).fetchall()
            if rows:
                for tier, count in rows:
                    log(f"  {tier:<20} {count} chunk(s)")
            else:
                log("  (no tier data — older pipeline version?)", "dim")

        # Embedding model summary
        log("\n═══ Embedding Models ═══", "accent")
        rows = conn.execute(
            "SELECT embed_model, embed_dims, COUNT(*) as n FROM chunk_manifest "
            "WHERE embed_model IS NOT NULL "
            "GROUP BY embed_model, embed_dims ORDER BY n DESC"
        ).fetchall()
        if rows:
            for model, dims, count in rows:
                log(f"  {model}  (dims={dims})  — {count} chunk(s)")
        else:
            log("  (no embeddings yet)", "dim")

        return {
            "files": files,
            "chunks": chunks,
            "embedded": embedded,
            "pending": pending,
            "nodes": nodes,
            "edges": edges,
        }
