"""
Tripartite DataSTORE — Desktop GUI

Full-featured knowledge store interface with VS Code Dark theme.
Panels: Explorer, DB List, Graph | Query Builder, Ingest, Curate, Export, Patch

All tabs are live except Patch (placeholder for future integration).
Requires: tripartite package with pipeline, chunkers, layers, models.

Drop-in replacement for studio.py.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import pkgutil
import platform
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


# ══════════════════════════════════════════════════════════════════════════════
#  THEME
# ══════════════════════════════════════════════════════════════════════════════

# VS Code Dark — all colour constants
BG       = "#1e1e1e"       # main background
BG2      = "#252526"       # panels, toolbars
BG3      = "#2d2d2d"       # elevated surfaces
BORDER   = "#3c3c3c"       # borders/separators
ACCENT   = "#007acc"       # primary accent (selection, active tab)
ACCENT2  = "#0e639c"       # buttons
ACCENT3  = "#1177bb"       # hover states
FG       = "#d4d4d4"       # primary text
FG_DIM   = "#858585"       # secondary text
FG_MUTED = "#6a6a6a"       # disabled/hint text
SUCCESS  = "#6a9955"       # green
WARNING  = "#dcdcaa"       # yellow
ERROR    = "#f44747"       # red
INFO     = "#9cdcfe"       # light blue (info text)

FONT_UI   = ("Segoe UI", 10)
FONT_SM   = ("Segoe UI", 9)
FONT_XS   = ("Segoe UI", 8)
FONT_H    = ("Segoe UI Semibold", 11)
FONT_MONO = ("Consolas", 10)
FONT_MONO_SM = ("Consolas", 9)
FONT_MONO_XS = ("Consolas", 8)

PAD = 8


# ══════════════════════════════════════════════════════════════════════════════
#  NODE ICONS (used in explorer + results)
# ══════════════════════════════════════════════════════════════════════════════

NODE_ICONS = {
    "root": "🗄", "directory": "📁", "file": "📄", "virtual_file": "📎",
    "compound_summary": "📋", "module": "📦", "class_def": "🔷",
    "function_def": "⚡", "method_def": "⚡", "async_function": "⚡",
    "decorator": "🏷", "import": "📎", "document": "📄",
    "document_summary": "📋", "section": "§", "subsection": "§",
    "heading": "§", "paragraph": "¶", "list_item": "•",
    "object": "{ }", "array": "[ ]", "key_value": "→", "table": "▦",
    "html_element": "◇", "html_section": "◈", "css_rule": "🎨",
    "xml_element": "◇", "chunk": "▪",
}


# ══════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TreeItem:
    """Unified node representation for the explorer tree."""
    node_id: str
    node_type: str
    name: str
    parent_id: Optional[str]
    path: str
    depth: int
    file_cid: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]
    language_tier: str
    chunk_id: Optional[str]
    token_count: int = 0
    embed_status: str = ""
    semantic_depth: int = 0
    structural_depth: int = 0
    context_prefix: str = ""
    children: list["TreeItem"] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
#  CURATION TOOL BASE CLASS
# ══════════════════════════════════════════════════════════════════════════════

class BaseCurationTool(ABC):
    """Interface for drop-in curation tools."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    def icon(self) -> str:
        return "🔧"

    @property
    def priority(self) -> int:
        return 50

    @abstractmethod
    def build_config_ui(self, parent: tk.Frame) -> tk.Frame: ...

    @abstractmethod
    def run(self, conn: sqlite3.Connection, selection: Any,
            on_progress: Optional[Callable] = None,
            on_log: Optional[Callable] = None) -> dict: ...


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL DISCOVERY
# ══════════════════════════════════════════════════════════════════════════════

def discover_tools(extra_dirs: list[Path] | None = None) -> list[type]:
    """
    Find all BaseCurationTool subclasses in curate_tools/ + extra directories.
    Returns classes sorted by priority (lowest first).
    """
    tools: list[type] = []
    seen_names: set[str] = set()

    search_dirs: list[tuple[str, Path]] = []

    # Built-in curate_tools/ package
    builtin_dir = Path(__file__).parent / "curate_tools"
    if builtin_dir.is_dir():
        search_dirs.append(("tripartite.curate_tools", builtin_dir))

    for extra in (extra_dirs or []):
        if isinstance(extra, str):
            extra = Path(extra)
        if extra.is_dir():
            search_dirs.append((f"_tripartite_tools_{extra.stem}", extra))

    for package_name, dir_path in search_dirs:
        try:
            for _finder, mod_name, _is_pkg in pkgutil.iter_modules([str(dir_path)]):
                if mod_name.startswith("_"):
                    continue
                module = _safe_import(package_name, mod_name, dir_path)
                if module is None:
                    continue
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BaseCurationTool)
                            and obj is not BaseCurationTool
                            and obj.__name__ not in seen_names):
                        tools.append(obj)
                        seen_names.add(obj.__name__)
        except Exception as e:
            print(f"[tools] Warning scanning {dir_path}: {e}")

    def _priority(cls):
        try:
            return cls().priority
        except Exception:
            return 50

    tools.sort(key=_priority)
    return tools


def _safe_import(package_name: str, mod_name: str, dir_path: Path):
    """Import a module from a directory with fallback for external dirs."""
    try:
        return importlib.import_module(f".{mod_name}", package=package_name)
    except (ImportError, ModuleNotFoundError):
        pass

    mod_file = dir_path / f"{mod_name}.py"
    if not mod_file.exists():
        return None

    full_name = f"{package_name}.{mod_name}"
    try:
        spec = importlib.util.spec_from_file_location(full_name, mod_file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[full_name] = module
            spec.loader.exec_module(module)
            return module
    except Exception as e:
        print(f"[tools] Failed to load {mod_file}: {e}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ══════════════════════════════════════════════════════════════════════════════

class TripartiteDataStore:
    """Main application window."""

    def __init__(self, root: tk.Tk, db_path: Optional[str] = None):
        self.root = root
        self.root.title("Tripartite DataSTORE")
        self.root.geometry("1400x950")
        self.root.configure(bg=BG)
        self.root.minsize(900, 600)

        # State
        self.db_path: Optional[str] = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._selected_item: Optional[TreeItem] = None
        self._tool_instances: dict[str, BaseCurationTool] = {}
        self._ingest_thread: Optional[threading.Thread] = None

        self._setup_styles()
        self._build_ui()
        self._update_status("READY")

        # Auto-connect if db given
        if self.db_path:
            self._connect_db(self.db_path)

    # ── Styles ────────────────────────────────────────────────────────────

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background=BG)
        style.configure("TPanedwindow", background=BORDER)

        # Notebook
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab",
                        background=BG2, foreground=FG_DIM,
                        font=FONT_SM, padding=[12, 4], borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", BG)],
                  foreground=[("selected", ACCENT)])

        # Treeview
        style.configure("Treeview",
                        background=BG, foreground=FG,
                        fieldbackground=BG, font=FONT_MONO_SM,
                        borderwidth=0, rowheight=22)
        style.configure("Treeview.Heading",
                        background=BG2, foreground=FG_DIM,
                        font=FONT_XS, borderwidth=1)
        style.map("Treeview",
                  background=[("selected", "#37373d")],
                  foreground=[("selected", "#ffffff")])

        # Scrollbar
        style.configure("Vertical.TScrollbar",
                        background=BG2, troughcolor=BG,
                        borderwidth=0, arrowsize=0)
        style.configure("Horizontal.TScrollbar",
                        background=BG2, troughcolor=BG,
                        borderwidth=0, arrowsize=0)

        # Progressbar
        style.configure("Accent.Horizontal.TProgressbar",
                        background=ACCENT, troughcolor=BG2)

    # ── Main Layout ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Top-level paned: sidebar | workspace
        self.main_paned = tk.PanedWindow(
            self.root, orient=tk.HORIZONTAL,
            bg=BORDER, sashwidth=2, sashrelief="flat")
        self.main_paned.pack(fill="both", expand=True)

        # Left sidebar
        self.sidebar = tk.Frame(self.main_paned, bg=BG)
        self.main_paned.add(self.sidebar, width=350, minsize=250)
        self._build_sidebar()

        # Right: workspace + log
        self.right_paned = tk.PanedWindow(
            self.main_paned, orient=tk.VERTICAL,
            bg=BORDER, sashwidth=2, sashrelief="flat")
        self.main_paned.add(self.right_paned, minsize=600)
        self._build_workspace()

        # Status bar
        self._status_frame = tk.Frame(self.root, bg=ACCENT, height=24)
        self._status_frame.pack(side="bottom", fill="x")
        self._status_label = tk.Label(
            self._status_frame, text="", bg=ACCENT, fg="#ffffff",
            font=FONT_SM, anchor="w", padx=8, pady=2)
        self._status_label.pack(side="left", fill="x", expand=True)
        self._db_label = tk.Label(
            self._status_frame, text="DB: none", bg=ACCENT, fg="#ffffff",
            font=FONT_SM, anchor="e", padx=8, pady=2)
        self._db_label.pack(side="right")

    # ── Sidebar ───────────────────────────────────────────────────────────

    def _build_sidebar(self):
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.rowconfigure(1, weight=1)

        # Selection info panel
        self._info_frame = tk.Frame(self.sidebar, bg=BG2)
        self._info_frame.grid(row=0, column=0, sticky="ew", pady=(0, 1))
        tk.Label(self._info_frame, text="SELECTION INFO",
                 bg=BG2, fg=ACCENT, font=(FONT_XS[0], FONT_XS[1], "bold"),
                 anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        self._info_label = tk.Label(
            self._info_frame, text="Select a node to inspect",
            bg=BG2, fg=FG_DIM, font=FONT_MONO_XS, anchor="w",
            justify="left")
        self._info_label.pack(fill="x", padx=8, pady=(2, 6))

        # Sidebar tabs: Explorer / DB List / Graph
        self.sidebar_tabs = ttk.Notebook(self.sidebar)
        self.sidebar_tabs.grid(row=1, column=0, sticky="nsew")

        # == Explorer tab ==
        self._explorer_frame = tk.Frame(self.sidebar_tabs, bg=BG)
        self.sidebar_tabs.add(self._explorer_frame, text="  Explorer  ")
        self._build_explorer_tab()

        # == DB List tab ==
        self._dblist_frame = tk.Frame(self.sidebar_tabs, bg=BG)
        self.sidebar_tabs.add(self._dblist_frame, text="  DB List  ")
        self._build_dblist_tab()

        # == Graph tab ==
        self._graph_frame = tk.Frame(self.sidebar_tabs, bg=BG)
        self.sidebar_tabs.add(self._graph_frame, text="  Graph  ")
        self._build_graph_tab()

        # Bottom controls
        ctrl_frame = tk.Frame(self.sidebar, bg=BG2)
        ctrl_frame.grid(row=2, column=0, sticky="ew")
        tk.Button(ctrl_frame, text="📂 Open DB", command=self._open_db_dialog,
                  bg=BG2, fg=FG, relief="flat", font=FONT_SM,
                  activebackground=BG3, activeforeground=FG,
                  cursor="hand2").pack(side="left", expand=True, fill="x", pady=4, padx=2)
        tk.Button(ctrl_frame, text="⚙ Settings", command=self._open_settings,
                  bg=BG2, fg=FG, relief="flat", font=FONT_SM,
                  activebackground=BG3, activeforeground=FG,
                  cursor="hand2").pack(side="left", expand=True, fill="x", pady=4, padx=2)
        tk.Button(ctrl_frame, text="Exit", command=self.root.quit,
                  bg=BG2, fg=ERROR, relief="flat", font=FONT_SM,
                  activebackground=BG3, activeforeground=ERROR,
                  cursor="hand2").pack(side="left", expand=True, fill="x", pady=4, padx=2)

    # ── Explorer Tab ──────────────────────────────────────────────────────

    def _build_explorer_tab(self):
        self._explorer_frame.columnconfigure(0, weight=1)
        self._explorer_frame.rowconfigure(1, weight=1)

        # Toolbar
        toolbar = tk.Frame(self._explorer_frame, bg=BG)
        toolbar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        self._explorer_mode_label = tk.Label(
            toolbar, text="Explorer", bg=BG, fg=FG_DIM, font=FONT_XS)
        self._explorer_mode_label.pack(side="left")
        tk.Button(toolbar, text="▶ Expand", command=self._explorer_expand_all,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  cursor="hand2", padx=4).pack(side="right", padx=1)
        tk.Button(toolbar, text="◀ Collapse", command=self._explorer_collapse_all,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  cursor="hand2", padx=4).pack(side="right", padx=1)
        tk.Button(toolbar, text="↻ Refresh", command=self._explorer_refresh,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  cursor="hand2", padx=4).pack(side="right", padx=1)

        # Treeview
        tree_frame = tk.Frame(self._explorer_frame, bg=BG)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.explorer_tree = ttk.Treeview(
            tree_frame, show="tree headings",
            columns=("type", "lines", "tokens", "status"),
            selectmode="browse")
        self.explorer_tree.heading("#0", text="Name", anchor="w")
        self.explorer_tree.heading("type", text="Type", anchor="w")
        self.explorer_tree.heading("lines", text="Lines", anchor="e")
        self.explorer_tree.heading("tokens", text="Tok", anchor="e")
        self.explorer_tree.heading("status", text="Emb", anchor="center")
        self.explorer_tree.column("#0", width=240, minwidth=150)
        self.explorer_tree.column("type", width=80, minwidth=50)
        self.explorer_tree.column("lines", width=65, minwidth=40, anchor="e")
        self.explorer_tree.column("tokens", width=45, minwidth=30, anchor="e")
        self.explorer_tree.column("status", width=35, minwidth=30, anchor="center")

        ysb = ttk.Scrollbar(tree_frame, orient="vertical",
                            command=self.explorer_tree.yview)
        self.explorer_tree.configure(yscrollcommand=ysb.set)
        self.explorer_tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")

        self.explorer_tree.bind("<<TreeviewSelect>>", self._on_explorer_select)
        self.explorer_tree.bind("<Button-3>", self._on_explorer_right_click)
        self.explorer_tree.bind("<Button-2>", self._on_explorer_right_click)

        # Explorer status
        self._explorer_status = tk.Label(
            self._explorer_frame, text="No database loaded",
            bg=BG, fg=FG_DIM, font=FONT_XS, anchor="w")
        self._explorer_status.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 4))

        self._node_data: dict[str, TreeItem] = {}

    # ── DB List Tab ───────────────────────────────────────────────────────

    def _build_dblist_tab(self):
        self._dblist_frame.columnconfigure(0, weight=1)
        self._dblist_frame.rowconfigure(0, weight=1)

        self._dblist_tree = ttk.Treeview(
            self._dblist_frame, show="headings",
            columns=("name", "size", "files", "chunks"))
        self._dblist_tree.heading("name", text="Database", anchor="w")
        self._dblist_tree.heading("size", text="Size", anchor="e")
        self._dblist_tree.heading("files", text="Files", anchor="e")
        self._dblist_tree.heading("chunks", text="Chunks", anchor="e")
        self._dblist_tree.column("name", width=180)
        self._dblist_tree.column("size", width=60, anchor="e")
        self._dblist_tree.column("files", width=50, anchor="e")
        self._dblist_tree.column("chunks", width=60, anchor="e")

        ysb = ttk.Scrollbar(self._dblist_frame, orient="vertical",
                            command=self._dblist_tree.yview)
        self._dblist_tree.configure(yscrollcommand=ysb.set)
        self._dblist_tree.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        ysb.grid(row=0, column=1, sticky="ns", pady=4)

        self._dblist_tree.bind("<<TreeviewSelect>>", self._on_dblist_select)

    # ── Graph Tab ─────────────────────────────────────────────────────────

    def _build_graph_tab(self):
        self._graph_frame.columnconfigure(0, weight=1)
        self._graph_frame.rowconfigure(1, weight=1)

        toolbar = tk.Frame(self._graph_frame, bg=BG)
        toolbar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        tk.Label(toolbar, text="Graph Edges", bg=BG, fg=FG_DIM,
                 font=FONT_XS).pack(side="left")
        tk.Button(toolbar, text="↻ Refresh", command=self._refresh_graph,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  cursor="hand2", padx=4).pack(side="right")

        self._graph_tree = ttk.Treeview(
            self._graph_frame, show="headings",
            columns=("source", "rel", "target", "weight"))
        self._graph_tree.heading("source", text="Source", anchor="w")
        self._graph_tree.heading("rel", text="Relation", anchor="w")
        self._graph_tree.heading("target", text="Target", anchor="w")
        self._graph_tree.heading("weight", text="Wt", anchor="e")
        self._graph_tree.column("source", width=100)
        self._graph_tree.column("rel", width=80)
        self._graph_tree.column("target", width=100)
        self._graph_tree.column("weight", width=40, anchor="e")

        ysb = ttk.Scrollbar(self._graph_frame, orient="vertical",
                            command=self._graph_tree.yview)
        self._graph_tree.configure(yscrollcommand=ysb.set)
        self._graph_tree.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        ysb.grid(row=1, column=1, sticky="ns", pady=4)

    # ── Workspace (right column) ──────────────────────────────────────────

    def _build_workspace(self):
        # Workspace tabs
        self.work_tabs = ttk.Notebook(self.right_paned)
        self.right_paned.add(self.work_tabs, minsize=400)

        # Query Builder
        qb_frame = tk.Frame(self.work_tabs, bg=BG)
        self.work_tabs.add(qb_frame, text="  Query Builder  ")
        self._build_query_tab(qb_frame)

        # Ingest
        ingest_frame = tk.Frame(self.work_tabs, bg=BG)
        self.work_tabs.add(ingest_frame, text="  Ingest  ")
        self._build_ingest_tab(ingest_frame)

        # Curate
        curate_frame = tk.Frame(self.work_tabs, bg=BG)
        self.work_tabs.add(curate_frame, text="  Curate  ")
        self._build_curate_tab(curate_frame)

        # Export
        export_frame = tk.Frame(self.work_tabs, bg=BG)
        self.work_tabs.add(export_frame, text="  Export  ")
        self._build_export_tab(export_frame)

        # Patch (placeholder)
        patch_frame = tk.Frame(self.work_tabs, bg=BG)
        self.work_tabs.add(patch_frame, text="  Patch  ")
        self._build_patch_placeholder(patch_frame)

        # Output log (bottom)
        log_frame = tk.Frame(self.right_paned, bg=BG2)
        self.right_paned.add(log_frame, minsize=140)
        self._build_output_log(log_frame)

    # ── Query Builder Tab ─────────────────────────────────────────────────

    def _build_query_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        # Query input row
        query_row = tk.Frame(parent, bg=BG)
        query_row.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 4))
        query_row.columnconfigure(1, weight=1)

        tk.Label(query_row, text="Query:", bg=BG, fg=FG,
                 font=FONT_UI).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._query_entry = tk.Entry(
            query_row, bg=BG2, fg=FG, insertbackground=FG,
            font=FONT_MONO, borderwidth=0, relief="flat")
        self._query_entry.grid(row=0, column=1, sticky="ew", ipady=5)
        self._query_entry.bind("<Return>", lambda e: self._execute_query())

        tk.Button(query_row, text="Execute", bg=ACCENT2, fg="#ffffff",
                  relief="flat", font=FONT_SM, cursor="hand2",
                  activebackground=ACCENT3, activeforeground="#ffffff",
                  command=self._execute_query,
                  padx=16).grid(row=0, column=2, padx=(8, 0))

        # Layer selection
        layer_row = tk.Frame(parent, bg=BG2)
        layer_row.grid(row=1, column=0, sticky="ew", padx=PAD, pady=4)

        self._query_semantic = tk.BooleanVar(value=True)
        self._query_verbatim = tk.BooleanVar(value=False)
        self._query_graph = tk.BooleanVar(value=False)

        for var, label in [
            (self._query_semantic, "Semantic Layer"),
            (self._query_verbatim, "Verbatim DB"),
            (self._query_graph, "Knowledge Graph"),
        ]:
            tk.Checkbutton(
                layer_row, text=label, variable=var,
                bg=BG2, fg=FG, selectcolor=BG, font=FONT_SM,
                activebackground=BG2, activeforeground=FG,
            ).pack(side="left", padx=12, pady=6)

        # Top-K slider
        tk.Label(layer_row, text="Top-K:", bg=BG2, fg=FG_DIM,
                 font=FONT_SM).pack(side="left", padx=(24, 4))
        self._topk_var = tk.IntVar(value=10)
        tk.Spinbox(layer_row, from_=1, to=100, textvariable=self._topk_var,
                   width=4, bg=BG, fg=FG, font=FONT_MONO_SM,
                   buttonbackground=BG2, borderwidth=0).pack(side="left")

        # Results
        results_frame = tk.Frame(parent, bg=BG)
        results_frame.grid(row=2, column=0, sticky="nsew", padx=PAD, pady=(4, PAD))
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

        self._results_tree = ttk.Treeview(
            results_frame,
            columns=("score", "type", "source", "content"),
            show="headings")
        self._results_tree.heading("score", text="Score", anchor="center")
        self._results_tree.heading("type", text="Type", anchor="w")
        self._results_tree.heading("source", text="Source", anchor="w")
        self._results_tree.heading("content", text="Preview", anchor="w")
        self._results_tree.column("score", width=70, anchor="center")
        self._results_tree.column("type", width=100)
        self._results_tree.column("source", width=180)
        self._results_tree.column("content", width=400)

        ysb = ttk.Scrollbar(results_frame, orient="vertical",
                            command=self._results_tree.yview)
        self._results_tree.configure(yscrollcommand=ysb.set)
        self._results_tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")

        self._results_tree.bind("<<TreeviewSelect>>", self._on_result_select)

    # ── Ingest Tab ────────────────────────────────────────────────────────

    def _build_ingest_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        # Source selection
        src_frame = tk.Frame(parent, bg=BG)
        src_frame.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 4))
        src_frame.columnconfigure(1, weight=1)

        tk.Label(src_frame, text="Source:", bg=BG, fg=FG,
                 font=FONT_UI).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._ingest_path_var = tk.StringVar()
        tk.Entry(src_frame, textvariable=self._ingest_path_var,
                 bg=BG2, fg=FG, insertbackground=FG,
                 font=FONT_MONO_SM, borderwidth=0).grid(row=0, column=1, sticky="ew", ipady=4)
        tk.Button(src_frame, text="📁 Browse…", command=self._browse_ingest_source,
                  bg=BG2, fg=FG, relief="flat", font=FONT_SM,
                  cursor="hand2").grid(row=0, column=2, padx=(4, 0))

        # Options
        opts_frame = tk.Frame(parent, bg=BG2)
        opts_frame.grid(row=1, column=0, sticky="ew", padx=PAD, pady=4)

        self._ingest_embed = tk.BooleanVar(value=True)
        self._ingest_graph = tk.BooleanVar(value=True)
        self._ingest_compound = tk.BooleanVar(value=True)

        tk.Checkbutton(opts_frame, text="Embed after ingest",
                       variable=self._ingest_embed, bg=BG2, fg=FG,
                       selectcolor=BG, font=FONT_SM,
                       activebackground=BG2).pack(side="left", padx=10, pady=6)
        tk.Checkbutton(opts_frame, text="Build graph edges",
                       variable=self._ingest_graph, bg=BG2, fg=FG,
                       selectcolor=BG, font=FONT_SM,
                       activebackground=BG2).pack(side="left", padx=10, pady=6)
        tk.Checkbutton(opts_frame, text="Detect compound docs",
                       variable=self._ingest_compound, bg=BG2, fg=FG,
                       selectcolor=BG, font=FONT_SM,
                       activebackground=BG2).pack(side="left", padx=10, pady=6)

        # Action buttons
        btn_frame = tk.Frame(parent, bg=BG)
        btn_frame.grid(row=2, column=0, sticky="ew", padx=PAD, pady=4)

        tk.Button(btn_frame, text="▶  Start Ingest", command=self._start_ingest,
                  bg=ACCENT2, fg="#ffffff", relief="flat", font=FONT_SM,
                  cursor="hand2", padx=16,
                  activebackground=ACCENT3).pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="⏹  Stop", command=self._stop_ingest,
                  bg=BG2, fg=ERROR, relief="flat", font=FONT_SM,
                  cursor="hand2", padx=12).pack(side="left", padx=(0, 8))

        self._ingest_progress = ttk.Progressbar(
            btn_frame, mode="determinate", style="Accent.Horizontal.TProgressbar")
        self._ingest_progress.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self._ingest_progress_label = tk.Label(
            btn_frame, text="", bg=BG, fg=FG_DIM, font=FONT_XS)
        self._ingest_progress_label.pack(side="right", padx=(8, 0))

        # Ingest log
        log_frame = tk.Frame(parent, bg=BG)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=PAD, pady=(4, PAD))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self._ingest_log = tk.Text(
            log_frame, bg=BG2, fg=FG, font=FONT_MONO_XS,
            borderwidth=0, wrap="word", state="disabled",
            insertbackground=FG)
        ysb = ttk.Scrollbar(log_frame, orient="vertical",
                            command=self._ingest_log.yview)
        self._ingest_log.configure(yscrollcommand=ysb.set)
        self._ingest_log.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")

        # Configure log tags
        self._ingest_log.tag_configure("info", foreground=FG)
        self._ingest_log.tag_configure("dim", foreground=FG_DIM)
        self._ingest_log.tag_configure("accent", foreground=ACCENT)
        self._ingest_log.tag_configure("success", foreground=SUCCESS)
        self._ingest_log.tag_configure("warning", foreground=WARNING)
        self._ingest_log.tag_configure("error", foreground=ERROR)

    # ── Curate Tab ────────────────────────────────────────────────────────

    def _build_curate_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        # Tool selector + config
        top_paned = tk.PanedWindow(parent, orient=tk.HORIZONTAL,
                                   bg=BORDER, sashwidth=2)
        top_paned.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 4))

        # Tool list
        tool_list_frame = tk.Frame(top_paned, bg=BG2)
        top_paned.add(tool_list_frame, width=220, minsize=150)

        tk.Label(tool_list_frame, text="TOOLS", bg=BG2, fg=ACCENT,
                 font=(FONT_XS[0], FONT_XS[1], "bold"),
                 anchor="w").pack(fill="x", padx=6, pady=(4, 0))
        self._curate_tool_list = tk.Listbox(
            tool_list_frame, bg=BG2, fg=FG, font=FONT_SM,
            borderwidth=0, selectbackground=ACCENT,
            selectforeground="#ffffff", activestyle="none",
            relief="flat")
        self._curate_tool_list.pack(fill="both", expand=True, padx=4, pady=4)
        self._curate_tool_list.bind("<<ListboxSelect>>", self._on_tool_select)

        # Tool config area
        self._curate_config_frame = tk.Frame(top_paned, bg=BG)
        top_paned.add(self._curate_config_frame, minsize=300)

        self._curate_config_label = tk.Label(
            self._curate_config_frame, text="Select a tool to configure",
            bg=BG, fg=FG_DIM, font=FONT_SM)
        self._curate_config_label.pack(fill="x", padx=PAD, pady=PAD)

        # Run button
        self._curate_run_btn = tk.Button(
            self._curate_config_frame, text="▶  Run Tool",
            command=self._run_curate_tool,
            bg=ACCENT2, fg="#ffffff", relief="flat", font=FONT_SM,
            cursor="hand2", padx=16, state="disabled",
            activebackground=ACCENT3)
        self._curate_run_btn.pack(anchor="w", padx=PAD, pady=(0, PAD))

        # Curate log
        curate_log_frame = tk.Frame(parent, bg=BG)
        curate_log_frame.grid(row=1, column=0, sticky="nsew", padx=PAD, pady=(4, PAD))
        curate_log_frame.columnconfigure(0, weight=1)
        curate_log_frame.rowconfigure(0, weight=1)

        self._curate_log_text = tk.Text(
            curate_log_frame, bg=BG2, fg=FG, font=FONT_MONO_XS,
            borderwidth=0, wrap="word", state="disabled")
        ysb = ttk.Scrollbar(curate_log_frame, orient="vertical",
                            command=self._curate_log_text.yview)
        self._curate_log_text.configure(yscrollcommand=ysb.set)
        self._curate_log_text.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")

        self._curate_log_text.tag_configure("info", foreground=FG)
        self._curate_log_text.tag_configure("dim", foreground=FG_DIM)
        self._curate_log_text.tag_configure("accent", foreground=ACCENT)
        self._curate_log_text.tag_configure("success", foreground=SUCCESS)
        self._curate_log_text.tag_configure("warning", foreground=WARNING)
        self._curate_log_text.tag_configure("error", foreground=ERROR)

        # Discover tools on next idle
        self.root.after_idle(self._discover_tools)

    # ── Export Tab ────────────────────────────────────────────────────────

    def _build_export_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        # Format selection
        fmt_frame = tk.Frame(parent, bg=BG2)
        fmt_frame.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 4))

        tk.Label(fmt_frame, text="Export Format:", bg=BG2, fg=FG,
                 font=FONT_SM).pack(side="left", padx=(10, 8), pady=6)
        self._export_format = tk.StringVar(value="json")
        for val, label in [("json", "JSON"), ("csv", "CSV"),
                           ("markdown", "Markdown"), ("sqlite", "SQLite Copy")]:
            tk.Radiobutton(
                fmt_frame, text=label, variable=self._export_format,
                value=val, bg=BG2, fg=FG, selectcolor=BG,
                font=FONT_SM, activebackground=BG2, activeforeground=FG,
            ).pack(side="left", padx=8, pady=6)

        # Options
        opts_frame = tk.Frame(parent, bg=BG)
        opts_frame.grid(row=1, column=0, sticky="ew", padx=PAD, pady=4)

        self._export_chunks = tk.BooleanVar(value=True)
        self._export_embeddings = tk.BooleanVar(value=False)
        self._export_graph = tk.BooleanVar(value=True)

        tk.Checkbutton(opts_frame, text="Include chunks", variable=self._export_chunks,
                       bg=BG, fg=FG, selectcolor=BG2, font=FONT_SM,
                       activebackground=BG).pack(side="left", padx=10, pady=4)
        tk.Checkbutton(opts_frame, text="Include embeddings", variable=self._export_embeddings,
                       bg=BG, fg=FG, selectcolor=BG2, font=FONT_SM,
                       activebackground=BG).pack(side="left", padx=10, pady=4)
        tk.Checkbutton(opts_frame, text="Include graph", variable=self._export_graph,
                       bg=BG, fg=FG, selectcolor=BG2, font=FONT_SM,
                       activebackground=BG).pack(side="left", padx=10, pady=4)

        tk.Button(opts_frame, text="📦  Export…", command=self._do_export,
                  bg=ACCENT2, fg="#ffffff", relief="flat", font=FONT_SM,
                  cursor="hand2", padx=16,
                  activebackground=ACCENT3).pack(side="right", padx=10, pady=4)

        # Export preview
        preview_frame = tk.Frame(parent, bg=BG)
        preview_frame.grid(row=2, column=0, sticky="nsew", padx=PAD, pady=(4, PAD))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self._export_preview = tk.Text(
            preview_frame, bg=BG2, fg=FG, font=FONT_MONO_XS,
            borderwidth=0, wrap="word", state="disabled")
        ysb = ttk.Scrollbar(preview_frame, orient="vertical",
                            command=self._export_preview.yview)
        self._export_preview.configure(yscrollcommand=ysb.set)
        self._export_preview.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")

    # ── Patch Tab (placeholder) ───────────────────────────────────────────

    def _build_patch_placeholder(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        tk.Label(parent, text="⚡ Patch Interface\n\nComing soon — dual-editor with "
                 "source preview + patch JSON validation & application.",
                 bg=BG, fg=FG_DIM, font=FONT_UI, justify="center"
                 ).grid(row=0, column=0, sticky="nsew")

    # ── Output Log (bottom panel) ─────────────────────────────────────────

    def _build_output_log(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        header = tk.Frame(parent, bg=BG2)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="OUTPUT", bg=BG2, fg=FG_DIM,
                 font=(FONT_XS[0], FONT_XS[1], "bold"),
                 anchor="w").pack(fill="x", padx=8, pady=(4, 0))
        tk.Button(header, text="Clear", command=self._clear_output_log,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  cursor="hand2", padx=4).pack(side="right", padx=4)

        self._output_log = tk.Text(
            parent, bg=BG2, fg=FG, font=FONT_MONO_XS,
            borderwidth=0, wrap="word", state="disabled",
            height=6)
        ysb = ttk.Scrollbar(parent, orient="vertical",
                            command=self._output_log.yview)
        self._output_log.configure(yscrollcommand=ysb.set)
        self._output_log.grid(row=1, column=0, sticky="nsew")
        ysb.grid(row=1, column=1, sticky="ns")

        self._output_log.tag_configure("info", foreground=FG)
        self._output_log.tag_configure("dim", foreground=FG_DIM)
        self._output_log.tag_configure("accent", foreground=ACCENT)
        self._output_log.tag_configure("success", foreground=SUCCESS)
        self._output_log.tag_configure("warning", foreground=WARNING)
        self._output_log.tag_configure("error", foreground=ERROR)
        self._output_log.tag_configure("system", foreground=INFO)

        self._log("System", "Tripartite DataSTORE initialized", "system")

    # ══════════════════════════════════════════════════════════════════════
    #  LOGGING HELPERS
    # ══════════════════════════════════════════════════════════════════════

    def _log(self, source: str, msg: str, tag: str = "info"):
        """Append to the main output log (thread-safe)."""
        def _write():
            self._output_log.configure(state="normal")
            ts = time.strftime("%H:%M:%S")
            self._output_log.insert("end", f"[{ts}] [{source}] {msg}\n", tag)
            self._output_log.see("end")
            self._output_log.configure(state="disabled")
        self.root.after(0, _write)

    def _ingest_log_append(self, msg: str, tag: str = "info"):
        """Append to the ingest tab log (thread-safe)."""
        def _write():
            self._ingest_log.configure(state="normal")
            self._ingest_log.insert("end", f"{msg}\n", tag)
            self._ingest_log.see("end")
            self._ingest_log.configure(state="disabled")
        self.root.after(0, _write)

    def _curate_log_append(self, msg: str, tag: str = "info"):
        """Append to the curate tab log (thread-safe)."""
        def _write():
            self._curate_log_text.configure(state="normal")
            self._curate_log_text.insert("end", f"{msg}\n", tag)
            self._curate_log_text.see("end")
            self._curate_log_text.configure(state="disabled")
        self.root.after(0, _write)

    def _clear_output_log(self):
        self._output_log.configure(state="normal")
        self._output_log.delete("1.0", "end")
        self._output_log.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════
    #  STATUS BAR
    # ══════════════════════════════════════════════════════════════════════

    def _update_status(self, status: str, mode: str = "LOCAL"):
        self._status_label.configure(
            text=f" STATUS: {status}  |  MODE: {mode}")
        db_name = Path(self.db_path).name if self.db_path else "none"
        self._db_label.configure(text=f"DB: {db_name}")

    # ══════════════════════════════════════════════════════════════════════
    #  DATABASE CONNECTION
    # ══════════════════════════════════════════════════════════════════════

    def _open_db_dialog(self):
        path = filedialog.askopenfilename(
            title="Open Tripartite Database",
            filetypes=[("SQLite DB", "*.db *.sqlite"), ("All files", "*.*")])
        if path:
            self._connect_db(path)

    def _connect_db(self, path: str):
        """Connect to a Tripartite database and populate all panels."""
        try:
            if self.conn:
                self.conn.close()
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.db_path = path
            self._update_status("CONNECTED")
            self._log("DB", f"Connected to {Path(path).name}", "success")

            # Populate panels
            self._load_explorer()
            self._load_dblist()
            self._refresh_graph()

        except Exception as e:
            self._log("DB", f"Connection failed: {e}", "error")
            messagebox.showerror("Database Error", str(e))

    # ══════════════════════════════════════════════════════════════════════
    #  EXPLORER — Full tree loading with directory reconstruction
    # ══════════════════════════════════════════════════════════════════════

    def _load_explorer(self):
        """Load the full hierarchy tree from the database."""
        if not self.conn:
            return

        # Clear existing
        for item in self.explorer_tree.get_children(""):
            self.explorer_tree.delete(item)
        self._node_data.clear()

        # Detect mode
        mode = self._detect_explorer_mode()
        self._explorer_mode_label.configure(text=f"Explorer  ·  {mode.title()} mode")

        # Query tree_nodes + chunk_manifest
        try:
            rows = self.conn.execute("""
                SELECT
                    tn.node_id, tn.node_type, tn.name, tn.parent_id,
                    tn.path, tn.depth, tn.file_cid,
                    tn.line_start, tn.line_end, tn.language_tier,
                    tn.chunk_id,
                    cm.token_count, cm.embed_status,
                    cm.semantic_depth, cm.structural_depth,
                    cm.context_prefix
                FROM tree_nodes tn
                LEFT JOIN chunk_manifest cm ON cm.node_id = tn.node_id
                ORDER BY tn.path, tn.depth, tn.line_start
            """).fetchall()
        except sqlite3.OperationalError as e:
            self._explorer_status.configure(text=f"Schema error: {e}")
            self._log("Explorer", f"Query error: {e}", "warning")
            return

        if not rows:
            self._explorer_status.configure(text="No data — ingest something first")
            return

        items: dict[str, TreeItem] = {}
        for r in rows:
            item = TreeItem(
                node_id=r[0], node_type=r[1], name=r[2],
                parent_id=r[3], path=r[4] or "", depth=r[5],
                file_cid=r[6], line_start=r[7], line_end=r[8],
                language_tier=r[9] or "unknown", chunk_id=r[10],
                token_count=r[11] or 0, embed_status=r[12] or "",
                semantic_depth=r[13] or 0, structural_depth=r[14] or 0,
                context_prefix=r[15] or "",
            )
            items[item.node_id] = item
            self._node_data[item.node_id] = item

        # Build parent-child relationships
        roots = []
        for item in items.values():
            if item.parent_id and item.parent_id in items:
                items[item.parent_id].children.append(item)
            else:
                roots.append(item)

        # In project mode, reconstruct directory structure
        if mode == "project" and roots:
            roots = self._build_directory_tree(roots, items)

        # Sort children at each level
        self._sort_tree_children(items, roots)

        # Insert into treeview
        for root_item in roots:
            self._insert_tree_node(root_item, parent_iid="")

        # Auto-expand based on mode
        self._auto_expand_tree(mode)

        # Stats
        file_count = sum(1 for i in items.values()
                         if i.node_type in ("file", "virtual_file"))
        chunk_count = sum(1 for i in items.values() if i.embed_status)
        embedded = sum(1 for i in items.values() if i.embed_status == "done")
        self._explorer_status.configure(
            text=f"{file_count} files  ·  {chunk_count} chunks  ·  "
                 f"{embedded} embedded  ·  {mode} mode")

    def _detect_explorer_mode(self) -> str:
        rows = self.conn.execute(
            "SELECT source_type, COUNT(*) as n FROM source_files "
            "GROUP BY source_type ORDER BY n DESC"
        ).fetchall()
        if not rows:
            return "outline"

        type_counts = {r[0]: r[1] for r in rows}
        total = sum(type_counts.values())

        # Check for compound/virtual files
        try:
            vf_count = self.conn.execute(
                "SELECT COUNT(*) FROM tree_nodes WHERE node_type = 'virtual_file'"
            ).fetchone()[0]
            if vf_count > 0:
                return "project"
        except sqlite3.OperationalError:
            pass

        if total > 1:
            return "project"

        dominant = rows[0][0]
        if dominant in ("prose", "markdown", "text"):
            return "document"
        return "outline"

    def _build_directory_tree(self, file_nodes: list[TreeItem],
                              all_items: dict[str, TreeItem]) -> list[TreeItem]:
        """Reconstruct directory hierarchy from flat file paths."""
        file_map = {}
        other_roots = []
        for node in file_nodes:
            if node.node_type == "file" and node.path:
                file_map[node.path] = node
            else:
                other_roots.append(node)

        if not file_map:
            return file_nodes

        file_paths = list(file_map.keys())
        try:
            parts_list = [Path(p).parts for p in file_paths]
            if len(parts_list) > 1:
                common = []
                for level_parts in zip(*parts_list):
                    if len(set(level_parts)) == 1:
                        common.append(level_parts[0])
                    else:
                        break
                common_root = Path(*common) if common else Path(parts_list[0][0])
            else:
                common_root = Path(file_paths[0]).parent
        except (ValueError, IndexError):
            common_root = Path(".")

        dir_nodes = {}
        new_roots = []
        root_id = f"__dir__{common_root}"
        root_item = TreeItem(
            node_id=root_id, node_type="directory",
            name=common_root.name or str(common_root),
            parent_id=None, path=str(common_root), depth=0,
            file_cid=None, line_start=None, line_end=None,
            language_tier="unknown", chunk_id=None)
        dir_nodes[str(common_root)] = root_item
        self._node_data[root_id] = root_item
        new_roots.append(root_item)

        for fpath_str, file_item in file_map.items():
            fpath = Path(fpath_str)
            try:
                rel = fpath.relative_to(common_root)
            except ValueError:
                root_item.children.append(file_item)
                continue

            current_parent = root_item
            for i, part in enumerate(rel.parts[:-1]):
                dir_path = common_root / Path(*rel.parts[:i + 1])
                dir_key = str(dir_path)
                if dir_key not in dir_nodes:
                    dir_id = f"__dir__{dir_key}"
                    dir_item = TreeItem(
                        node_id=dir_id, node_type="directory", name=part,
                        parent_id=current_parent.node_id, path=dir_key,
                        depth=i + 1, file_cid=None, line_start=None,
                        line_end=None, language_tier="unknown", chunk_id=None)
                    dir_nodes[dir_key] = dir_item
                    self._node_data[dir_id] = dir_item
                    current_parent.children.append(dir_item)
                current_parent = dir_nodes[dir_key]
            current_parent.children.append(file_item)

        new_roots.extend(other_roots)
        return new_roots

    def _sort_tree_children(self, items, roots):
        for item in items.values():
            item.children.sort(key=lambda c: (
                c.node_type != "directory",
                c.node_type != "virtual_file",
                c.node_type != "file",
                c.line_start if c.line_start is not None else 999999,
                c.name.lower()))
        roots.sort(key=lambda c: (
            c.node_type != "directory",
            c.node_type != "virtual_file",
            c.node_type != "file",
            c.name.lower()))

    def _insert_tree_node(self, item: TreeItem, parent_iid: str):
        icon = NODE_ICONS.get(item.node_type, "▪")
        display_name = f"{icon}  {item.name}"

        lines_str = (f"L{item.line_start}–{item.line_end}"
                     if item.line_start is not None and item.line_end is not None
                     else "")
        tokens_str = str(item.token_count) if item.token_count else ""
        status_map = {"done": "✓", "pending": "○", "error": "✗",
                      "skipped": "—", "stale": "◐"}
        status_str = status_map.get(item.embed_status, "")
        type_str = item.node_type.replace("_", " ")

        try:
            self.explorer_tree.insert(
                parent_iid, "end", iid=item.node_id, text=display_name,
                values=(type_str, lines_str, tokens_str, status_str), open=False)
        except tk.TclError:
            return

        for child in item.children:
            self._insert_tree_node(child, parent_iid=item.node_id)

    def _auto_expand_tree(self, mode: str):
        top = self.explorer_tree.get_children("")
        if mode == "outline":
            self._explorer_expand_all()
        elif mode == "document":
            for iid in top:
                self.explorer_tree.item(iid, open=True)
                for child in self.explorer_tree.get_children(iid):
                    self.explorer_tree.item(child, open=True)
        else:
            for iid in top:
                self.explorer_tree.item(iid, open=True)
                for child in self.explorer_tree.get_children(iid):
                    item = self._node_data.get(child)
                    if item and item.node_type in ("directory", "virtual_file"):
                        self.explorer_tree.item(child, open=True)

    def _explorer_expand_all(self):
        def _ex(iid):
            self.explorer_tree.item(iid, open=True)
            for c in self.explorer_tree.get_children(iid):
                _ex(c)
        for r in self.explorer_tree.get_children(""):
            _ex(r)

    def _explorer_collapse_all(self):
        def _col(iid):
            for c in self.explorer_tree.get_children(iid):
                _col(c)
            self.explorer_tree.item(iid, open=False)
        for r in self.explorer_tree.get_children(""):
            _col(r)
            self.explorer_tree.item(r, open=True)

    def _explorer_refresh(self):
        self._load_explorer()

    # ── Explorer selection & context menu ─────────────────────────────────

    def _on_explorer_select(self, event):
        sel = self.explorer_tree.selection()
        if not sel:
            return
        item = self._node_data.get(sel[0])
        if not item:
            return

        self._selected_item = item

        # Update info panel
        info_parts = [
            f"ID: {item.node_id[:24]}…" if len(item.node_id) > 24 else f"ID: {item.node_id}",
            f"Type: {item.node_type}",
            f"Tier: {item.language_tier}",
        ]
        if item.line_start is not None:
            info_parts.append(f"Lines: {item.line_start}–{item.line_end}")
        if item.token_count:
            info_parts.append(f"Tokens: {item.token_count}")
        if item.embed_status:
            info_parts.append(f"Embed: {item.embed_status}")
        if item.file_cid:
            info_parts.append(f"CID: {item.file_cid[:16]}…")
        self._info_label.configure(text="\n".join(info_parts))

    def _on_explorer_right_click(self, event):
        iid = self.explorer_tree.identify_row(event.y)
        if not iid:
            return
        self.explorer_tree.selection_set(iid)
        item = self._node_data.get(iid)
        if not item:
            return

        menu = tk.Menu(self.root, tearoff=0, bg=BG2, fg=FG, font=FONT_SM,
                       activebackground=ACCENT, activeforeground="#ffffff",
                       relief="flat", bd=1)

        if item.node_type == "directory":
            self._add_directory_menu(menu, item)
        elif item.node_type in ("file", "virtual_file"):
            self._add_file_menu(menu, item)
        else:
            self._add_chunk_menu(menu, item)

        menu.add_separator()
        menu.add_command(label="📋  Copy Path",
                         command=lambda: self._copy_to_clipboard(item.path))
        if item.chunk_id:
            menu.add_command(label="📋  Copy Chunk ID",
                             command=lambda: self._copy_to_clipboard(item.chunk_id))

        menu.tk_popup(event.x_root, event.y_root)

    def _add_directory_menu(self, menu, item):
        d = item.path
        menu.add_command(label="📂  Open in File Explorer",
                         command=lambda: self._open_in_explorer(d))
        menu.add_command(label="💻  Open Terminal Here",
                         command=lambda: self._open_terminal(d))
        if platform.system() == "Windows":
            menu.add_command(label="⚡  Open PowerShell Here",
                             command=lambda: self._open_powershell(d))

    def _add_file_menu(self, menu, item):
        fp = item.path
        is_virtual = item.node_type == "virtual_file"
        if not is_virtual:
            menu.add_command(label="📝  Open in Default Editor",
                             command=lambda: self._open_file(fp))
            menu.add_command(label="📂  Open Containing Folder",
                             command=lambda: self._open_in_explorer(
                                 str(Path(fp).parent)))
        if item.chunk_id:
            menu.add_separator()
            menu.add_command(label="📋  Copy Chunk Text",
                             command=lambda: self._copy_chunk_text(item.chunk_id))

    def _add_chunk_menu(self, menu, item):
        fp = self._resolve_file_path(item)
        if fp:
            menu.add_command(
                label=f"📝  Open File (L{item.line_start or '?'})",
                command=lambda: self._open_file_at_line(fp, item.line_start))
        if item.chunk_id:
            menu.add_command(label="📋  Copy Chunk Text",
                             command=lambda: self._copy_chunk_text(item.chunk_id))
        if item.embed_status == "done":
            menu.add_command(label="🎯  Find Similar",
                             command=lambda: self._find_similar(item.chunk_id))

    # ── Shell actions ─────────────────────────────────────────────────────

    def _open_file(self, path):
        try:
            p = Path(path)
            if not p.exists():
                self._log("Explorer", f"File not found: {path}", "warning")
                return
            if platform.system() == "Windows":
                os.startfile(str(p))
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            self._log("Explorer", f"Open failed: {e}", "error")

    def _open_file_at_line(self, path, line):
        try:
            p = Path(path)
            if not p.exists():
                self._log("Explorer", f"File not found: {path}", "warning")
                return
            la = f":{line}" if line else ""
            try:
                subprocess.Popen(
                    ["code", "--goto", f"{p}{la}"],
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                return
            except FileNotFoundError:
                pass
            self._open_file(path)
        except Exception as e:
            self._log("Explorer", f"Open failed: {e}", "error")

    def _open_in_explorer(self, path):
        try:
            p = Path(path)
            if not p.exists():
                p = p.parent
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", str(p)])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            self._log("Explorer", f"Could not open explorer: {e}", "error")

    def _open_terminal(self, path):
        try:
            p = Path(path)
            if not p.is_dir():
                p = p.parent
            if platform.system() == "Windows":
                subprocess.Popen(
                    ["cmd", "/K", f"cd /d {p}"],
                    creationflags=subprocess.CREATE_NEW_CONSOLE)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", "Terminal", str(p)])
            else:
                subprocess.Popen(
                    ["x-terminal-emulator", f"--working-directory={p}"])
        except Exception as e:
            self._log("Explorer", f"Could not open terminal: {e}", "error")

    def _open_powershell(self, path):
        try:
            p = Path(path)
            if not p.is_dir():
                p = p.parent
            subprocess.Popen(
                ["powershell", "-NoExit", "-Command", f"Set-Location '{p}'"],
                creationflags=subprocess.CREATE_NEW_CONSOLE)
        except Exception as e:
            self._log("Explorer", f"Could not open PowerShell: {e}", "error")

    def _copy_to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        display = f"{text[:50]}…" if len(text) > 50 else text
        self._log("Clipboard", display, "dim")

    def _copy_chunk_text(self, chunk_id):
        if not self.conn:
            return
        try:
            row = self.conn.execute(
                "SELECT content FROM chunk_manifest WHERE chunk_id = ?",
                (chunk_id,)).fetchone()
            if row and row[0]:
                self._copy_to_clipboard(row[0])
            else:
                self._log("Explorer", "No text found for this chunk", "warning")
        except Exception as e:
            self._log("Explorer", f"Error: {e}", "error")

    def _find_similar(self, chunk_id):
        """Populate query builder with a similarity search for this chunk."""
        self._query_entry.delete(0, "end")
        self._query_entry.insert(0, f"similar:{chunk_id}")
        self._query_semantic.set(True)
        self.work_tabs.select(0)  # Switch to Query Builder tab
        self._log("Explorer", f"Ready to search similar to {chunk_id[:20]}…", "accent")

    def _resolve_file_path(self, item: TreeItem) -> Optional[str]:
        if item.node_type in ("file", "virtual_file"):
            return item.path
        if item.parent_id and item.parent_id in self._node_data:
            return self._resolve_file_path(self._node_data[item.parent_id])
        if item.file_cid and self.conn:
            row = self.conn.execute(
                "SELECT path FROM source_files WHERE file_cid = ?",
                (item.file_cid,)).fetchone()
            if row:
                return row[0]
        return None

    # ══════════════════════════════════════════════════════════════════════
    #  DB LIST
    # ══════════════════════════════════════════════════════════════════════

    def _load_dblist(self):
        """Populate DB list with all .db files in the database directory."""
        for item in self._dblist_tree.get_children(""):
            self._dblist_tree.delete(item)

        if not self.db_path:
            return

        db_dir = Path(self.db_path).parent
        for db_file in sorted(db_dir.glob("*.db")):
            try:
                size = db_file.stat().st_size
                size_str = (f"{size / 1024 / 1024:.1f} MB" if size > 1024 * 1024
                            else f"{size / 1024:.0f} KB")

                # Quick stats
                files_count = chunks_count = "?"
                try:
                    tmp_conn = sqlite3.connect(str(db_file))
                    try:
                        files_count = str(tmp_conn.execute(
                            "SELECT COUNT(*) FROM source_files").fetchone()[0])
                    except Exception:
                        pass
                    try:
                        chunks_count = str(tmp_conn.execute(
                            "SELECT COUNT(*) FROM chunk_manifest").fetchone()[0])
                    except Exception:
                        pass
                    tmp_conn.close()
                except Exception:
                    pass

                is_current = str(db_file) == str(self.db_path)
                name = f"● {db_file.name}" if is_current else db_file.name

                self._dblist_tree.insert(
                    "", "end", iid=str(db_file),
                    values=(name, size_str, files_count, chunks_count))
            except Exception:
                continue

    def _on_dblist_select(self, event):
        sel = self._dblist_tree.selection()
        if not sel:
            return
        db_path = sel[0]
        if db_path != str(self.db_path):
            self._connect_db(db_path)

    # ══════════════════════════════════════════════════════════════════════
    #  GRAPH
    # ══════════════════════════════════════════════════════════════════════

    def _refresh_graph(self):
        for item in self._graph_tree.get_children(""):
            self._graph_tree.delete(item)

        if not self.conn:
            return

        try:
            rows = self.conn.execute("""
                SELECT
                    ge.source_id, ge.relation, ge.target_id,
                    ge.weight
                FROM graph_edges ge
                ORDER BY ge.weight DESC
                LIMIT 500
            """).fetchall()

            for r in rows:
                source = r[0][:20] + "…" if len(r[0]) > 20 else r[0]
                target = r[2][:20] + "…" if len(r[2]) > 20 else r[2]
                weight = f"{r[3]:.2f}" if r[3] else ""
                self._graph_tree.insert(
                    "", "end", values=(source, r[1], target, weight))

            self._log("Graph", f"Loaded {len(rows)} edges", "dim")
        except sqlite3.OperationalError as e:
            self._log("Graph", f"Query error: {e}", "warning")

    # ══════════════════════════════════════════════════════════════════════
    #  QUERY BUILDER
    # ══════════════════════════════════════════════════════════════════════

    def _execute_query(self):
        query = self._query_entry.get().strip()
        if not query:
            return
        if not self.conn:
            self._log("Query", "No database connected", "warning")
            return

        # Clear previous results
        for item in self._results_tree.get_children(""):
            self._results_tree.delete(item)

        self._log("Query", f"Executing: {query}", "accent")

        # Run in thread to avoid blocking UI
        threading.Thread(
            target=self._run_query, args=(query,), daemon=True).start()

    def _run_query(self, query: str):
        try:
            results = []
            top_k = self._topk_var.get()

            # Semantic search
            if self._query_semantic.get():
                results.extend(self._query_semantic_layer(query, top_k))

            # Verbatim search
            if self._query_verbatim.get():
                results.extend(self._query_verbatim_layer(query, top_k))

            # Graph search
            if self._query_graph.get():
                results.extend(self._query_graph_layer(query, top_k))

            # Sort by score descending
            results.sort(key=lambda r: r[0], reverse=True)

            # Insert results
            def _populate():
                for score, chunk_type, source, preview in results[:top_k]:
                    self._results_tree.insert(
                        "", "end",
                        values=(f"{score:.3f}", chunk_type, source,
                                preview[:200]))
                self._log("Query", f"Found {len(results)} results", "success")

            self.root.after(0, _populate)

        except Exception as e:
            self._log("Query", f"Error: {e}", "error")

    def _query_semantic_layer(self, query: str, top_k: int) -> list[tuple]:
        """Search semantic embeddings via cosine similarity."""
        results = []
        try:
            # Try to use the model manager for embedding the query
            from .models.manager import ModelManager
            mm = ModelManager()
            q_vec = mm.embed(query)

            if q_vec is not None:
                rows = self.conn.execute("""
                    SELECT cm.chunk_id, cm.chunk_type, cm.name,
                           cm.content, cm.embedding
                    FROM chunk_manifest cm
                    WHERE cm.embed_status = 'done' AND cm.embedding IS NOT NULL
                """).fetchall()

                import numpy as np
                for chunk_id, chunk_type, name, content, emb_blob in rows:
                    emb = np.frombuffer(emb_blob, dtype=np.float32)
                    score = float(np.dot(q_vec, emb) / (
                        np.linalg.norm(q_vec) * np.linalg.norm(emb) + 1e-10))
                    preview = (content or name or "")[:200]
                    results.append((score, chunk_type, name, preview))

                results.sort(key=lambda r: r[0], reverse=True)
                return results[:top_k]
        except ImportError:
            self._log("Query", "ModelManager not available — using text fallback", "warning")
        except Exception as e:
            self._log("Query", f"Semantic search error: {e}", "warning")

        # Fallback: text LIKE search on chunk content
        return self._query_verbatim_layer(query, top_k)

    def _query_verbatim_layer(self, query: str, top_k: int) -> list[tuple]:
        """Search verbatim layer using LIKE matching."""
        results = []
        try:
            rows = self.conn.execute("""
                SELECT cm.chunk_id, cm.chunk_type, cm.name, cm.content
                FROM chunk_manifest cm
                WHERE cm.content LIKE ?
                LIMIT ?
            """, (f"%{query}%", top_k)).fetchall()

            for chunk_id, chunk_type, name, content in rows:
                # Simple relevance score based on match density
                content_lower = (content or "").lower()
                query_lower = query.lower()
                count = content_lower.count(query_lower)
                score = min(count * 0.2, 1.0) if count else 0.1
                preview = (content or "")[:200]
                results.append((score, chunk_type, name, preview))
        except Exception as e:
            self._log("Query", f"Verbatim search error: {e}", "warning")

        return results

    def _query_graph_layer(self, query: str, top_k: int) -> list[tuple]:
        """Search graph layer for matching node names or edge labels."""
        results = []
        try:
            rows = self.conn.execute("""
                SELECT gn.node_id, gn.node_type, gn.name, gn.properties
                FROM graph_nodes gn
                WHERE gn.name LIKE ?
                LIMIT ?
            """, (f"%{query}%", top_k)).fetchall()

            for node_id, node_type, name, props in rows:
                score = 0.5
                preview = props[:200] if props else name
                results.append((score, node_type, name, preview))
        except Exception as e:
            self._log("Query", f"Graph search error: {e}", "warning")

        return results

    def _on_result_select(self, event):
        """When a result is selected, highlight it in the explorer if possible."""
        sel = self._results_tree.selection()
        if not sel:
            return
        values = self._results_tree.item(sel[0], "values")
        if values and len(values) >= 3:
            source_name = values[2]
            self._log("Query", f"Selected: {source_name}", "dim")

    # ══════════════════════════════════════════════════════════════════════
    #  INGEST
    # ══════════════════════════════════════════════════════════════════════

    def _browse_ingest_source(self):
        choice = filedialog.askdirectory(title="Select folder to ingest")
        if not choice:
            choice = filedialog.askopenfilename(
                title="Select file to ingest",
                filetypes=[("All files", "*.*")])
        if choice:
            self._ingest_path_var.set(choice)

    def _start_ingest(self):
        source = self._ingest_path_var.get().strip()
        if not source:
            self._log("Ingest", "No source selected", "warning")
            return
        if not self.conn:
            self._log("Ingest", "No database connected", "warning")
            return
        if self._ingest_thread and self._ingest_thread.is_alive():
            self._log("Ingest", "Ingest already running", "warning")
            return

        self._ingest_cancel = False
        self._ingest_thread = threading.Thread(
            target=self._run_ingest, args=(source,), daemon=True)
        self._ingest_thread.start()
        self._update_status("INGESTING")
        self._log("Ingest", f"Started: {source}", "accent")

    def _stop_ingest(self):
        self._ingest_cancel = True
        self._log("Ingest", "Stop requested", "warning")

    def _run_ingest(self, source_path: str):
        """Run the full ingest pipeline in a background thread."""
        try:
            path = Path(source_path)
            if not path.exists():
                self._ingest_log_append(f"Path not found: {source_path}", "error")
                return

            # Try to import the pipeline
            try:
                from .pipeline.detect import walk_source, detect
                from .pipeline.detect import SourceFile
            except ImportError:
                self._ingest_log_append(
                    "Pipeline not available — ensure tripartite package is installed",
                    "error")
                return

            # Discover files
            self._ingest_log_append("Scanning source…", "accent")
            candidates = list(walk_source(path))
            total = len(candidates)
            self._ingest_log_append(f"Found {total} candidate files", "info")

            if total == 0:
                self._ingest_log_append("No files to ingest", "warning")
                return

            # Process each file
            processed = 0
            errors = 0
            for i, fpath in enumerate(candidates):
                if self._ingest_cancel:
                    self._ingest_log_append("Ingest cancelled by user", "warning")
                    break

                # Update progress
                pct = ((i + 1) / total) * 100
                self.root.after(0, lambda p=pct: self._ingest_progress.configure(value=p))
                self.root.after(0, lambda n=i+1, t=total:
                    self._ingest_progress_label.configure(text=f"{n}/{t}"))

                try:
                    sf = detect(fpath)
                    if sf is None:
                        continue

                    # Check for compound document
                    if self._ingest_compound.get():
                        try:
                            from .chunkers.compound import is_compound_document
                            if is_compound_document(sf):
                                sf_type = "compound"
                                self._ingest_log_append(
                                    f"  📎 Compound: {fpath.name}", "accent")
                        except ImportError:
                            pass

                    # Get appropriate chunker
                    chunker = self._get_chunker(sf)
                    chunks = chunker.chunk(sf)

                    # Store chunks
                    self._store_chunks(sf, chunks)

                    processed += 1
                    self._ingest_log_append(
                        f"  ✓ {fpath.name} ({len(chunks)} chunks)", "success")

                except Exception as e:
                    errors += 1
                    self._ingest_log_append(
                        f"  ✗ {fpath.name}: {e}", "error")

            # Embedding pass
            if self._ingest_embed.get() and processed > 0:
                self._ingest_log_append("\nStarting embedding pass…", "accent")
                self._run_embedding_pass()

            # Summary
            self._ingest_log_append(
                f"\nDone: {processed} files, {errors} errors", "success")
            self._log("Ingest", f"Complete: {processed} files", "success")

            # Refresh explorer
            self.root.after(0, self._load_explorer)
            self.root.after(0, lambda: self._update_status("READY"))

        except Exception as e:
            self._ingest_log_append(f"\nFatal error: {e}", "error")
            self._ingest_log_append(traceback.format_exc(), "error")
            self.root.after(0, lambda: self._update_status("ERROR"))

    def _get_chunker(self, sf):
        """Select the right chunker based on source type."""
        # Try compound first
        if self._ingest_compound.get():
            try:
                from .chunkers.compound import is_compound_document, CompoundDocumentChunker
                if is_compound_document(sf):
                    return CompoundDocumentChunker()
            except ImportError:
                pass

        # Try tree-sitter for code
        if sf.source_type == "code":
            try:
                from .chunkers.treesitter import TreeSitterChunker
                return TreeSitterChunker()
            except ImportError:
                pass

        # Default: prose
        try:
            from .chunkers.prose import ProseChunker
            return ProseChunker()
        except ImportError:
            pass

        # Absolute fallback
        from .chunkers.base import BaseChunker
        return BaseChunker()

    def _store_chunks(self, sf, chunks):
        """Store source file and chunks into the database."""
        if not self.conn:
            return

        # Store source file
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO source_files
                (file_cid, path, source_type, language, encoding, byte_size)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (sf.file_cid, str(sf.path), sf.source_type,
                  sf.language, sf.encoding, sf.byte_size))
        except Exception:
            pass

        # Store chunks
        for chunk in chunks:
            try:
                chunk_id = f"{sf.file_cid}:{chunk.name}:{chunk.spans[0].start if chunk.spans else 0}"
                self.conn.execute("""
                    INSERT OR REPLACE INTO chunk_manifest
                    (chunk_id, node_id, chunk_type, name, content,
                     file_cid, line_start, line_end, token_count,
                     embed_status, language_tier, heading_path,
                     semantic_depth, structural_depth, context_prefix)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chunk_id, chunk_id, chunk.chunk_type, chunk.name,
                    "\n".join(sf.lines[s.start:s.end + 1]
                             for s in chunk.spans) if chunk.spans else "",
                    sf.file_cid,
                    chunk.spans[0].start if chunk.spans else None,
                    chunk.spans[-1].end if chunk.spans else None,
                    getattr(chunk, 'token_count', 0),
                    "pending",
                    getattr(chunk, 'language_tier', 'unknown'),
                    json.dumps(chunk.heading_path) if chunk.heading_path else "[]",
                    getattr(chunk, 'semantic_depth', 0),
                    getattr(chunk, 'structural_depth', 0),
                    getattr(chunk, 'context_prefix', ''),
                ))

                # Tree node
                self.conn.execute("""
                    INSERT OR REPLACE INTO tree_nodes
                    (node_id, node_type, name, parent_id, path, depth,
                     file_cid, line_start, line_end, language_tier, chunk_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chunk_id, chunk.chunk_type, chunk.name,
                    None,  # parent_id handled by hierarchy logic
                    str(sf.path), chunk.depth,
                    sf.file_cid,
                    chunk.spans[0].start if chunk.spans else None,
                    chunk.spans[-1].end if chunk.spans else None,
                    getattr(chunk, 'language_tier', 'unknown'),
                    chunk_id,
                ))
            except Exception as e:
                self._ingest_log_append(f"    Store error: {e}", "warning")

        self.conn.commit()

    def _run_embedding_pass(self):
        """Embed all pending chunks."""
        try:
            from .models.manager import ModelManager
            mm = ModelManager()

            pending = self.conn.execute(
                "SELECT chunk_id, content FROM chunk_manifest "
                "WHERE embed_status = 'pending' AND content IS NOT NULL"
            ).fetchall()

            total = len(pending)
            self._ingest_log_append(f"Embedding {total} chunks…", "info")

            for i, (chunk_id, content) in enumerate(pending):
                if self._ingest_cancel:
                    break
                if not content or not content.strip():
                    self.conn.execute(
                        "UPDATE chunk_manifest SET embed_status='skipped' "
                        "WHERE chunk_id=?", (chunk_id,))
                    continue

                try:
                    vec = mm.embed(content)
                    if vec is not None:
                        import numpy as np
                        blob = np.array(vec, dtype=np.float32).tobytes()
                        self.conn.execute(
                            "UPDATE chunk_manifest SET embedding=?, "
                            "embed_status='done' WHERE chunk_id=?",
                            (blob, chunk_id))
                    else:
                        self.conn.execute(
                            "UPDATE chunk_manifest SET embed_status='error' "
                            "WHERE chunk_id=?", (chunk_id,))
                except Exception:
                    self.conn.execute(
                        "UPDATE chunk_manifest SET embed_status='error' "
                        "WHERE chunk_id=?", (chunk_id,))

                if (i + 1) % 50 == 0:
                    self.conn.commit()
                    self._ingest_log_append(f"  Embedded {i + 1}/{total}", "dim")

            self.conn.commit()
            done = self.conn.execute(
                "SELECT COUNT(*) FROM chunk_manifest WHERE embed_status='done'"
            ).fetchone()[0]
            self._ingest_log_append(f"Embedding complete: {done} chunks", "success")

        except ImportError:
            self._ingest_log_append(
                "ModelManager not available — skipping embedding", "warning")
        except Exception as e:
            self._ingest_log_append(f"Embedding error: {e}", "error")

    # ══════════════════════════════════════════════════════════════════════
    #  CURATE
    # ══════════════════════════════════════════════════════════════════════

    def _discover_tools(self):
        """Discover and populate the curate tool list."""
        self._tool_instances.clear()
        self._curate_tool_list.delete(0, "end")

        try:
            discovered = discover_tools()
            for cls in discovered:
                try:
                    inst = cls()
                    self._tool_instances[inst.name] = inst
                    self._curate_tool_list.insert(
                        tk.END, f"{inst.icon}  {inst.name}")
                except Exception as e:
                    self._curate_log_append(
                        f"Failed to load {cls.__name__}: {e}", "warning")

            count = len(self._tool_instances)
            self._curate_log_append(
                f"Discovered {count} curation tool(s)", "dim")
            self._log("Curate", f"{count} tools available", "dim")
        except Exception as e:
            self._curate_log_append(f"Tool discovery error: {e}", "warning")

    def _on_tool_select(self, event):
        sel = self._curate_tool_list.curselection()
        if not sel:
            return

        # Get tool name (strip icon prefix)
        raw = self._curate_tool_list.get(sel[0])
        tool_name = raw.split("  ", 1)[-1] if "  " in raw else raw

        tool = self._tool_instances.get(tool_name)
        if not tool:
            return

        # Clear config area
        for widget in self._curate_config_frame.winfo_children():
            if widget != self._curate_run_btn:
                widget.destroy()

        # Show tool description
        tk.Label(self._curate_config_frame, text=tool.name, bg=BG, fg=FG,
                 font=FONT_H).pack(anchor="w", padx=PAD, pady=(PAD, 2))
        tk.Label(self._curate_config_frame, text=tool.description, bg=BG,
                 fg=FG_DIM, font=FONT_SM, wraplength=400,
                 justify="left").pack(anchor="w", padx=PAD, pady=(0, PAD))

        # Build tool config UI
        try:
            config_widget = tool.build_config_ui(self._curate_config_frame)
            if config_widget:
                config_widget.pack(fill="x", padx=PAD, pady=(0, PAD))
        except Exception as e:
            tk.Label(self._curate_config_frame, text=f"Config error: {e}",
                     bg=BG, fg=ERROR, font=FONT_SM).pack(padx=PAD)

        # Enable run button
        self._curate_run_btn.configure(state="normal")
        self._curate_run_btn.pack(anchor="w", padx=PAD, pady=(0, PAD))

    def _run_curate_tool(self):
        sel = self._curate_tool_list.curselection()
        if not sel:
            return
        if not self.conn:
            self._curate_log_append("No database connected", "warning")
            return

        raw = self._curate_tool_list.get(sel[0])
        tool_name = raw.split("  ", 1)[-1] if "  " in raw else raw
        tool = self._tool_instances.get(tool_name)
        if not tool:
            return

        self._curate_log_append(f"\n{'═' * 40}", "accent")
        self._curate_log_append(f"Running: {tool.name}", "accent")
        self._curate_log_append(f"{'═' * 40}", "accent")

        # Run in thread
        threading.Thread(
            target=self._run_curate_tool_thread,
            args=(tool,), daemon=True).start()

    def _run_curate_tool_thread(self, tool: BaseCurationTool):
        try:
            result = tool.run(
                conn=self.conn,
                selection=self._selected_item,
                on_progress=None,
                on_log=self._curate_log_append)

            if result:
                self._curate_log_append(
                    f"\nResult: {json.dumps(result, indent=2, default=str)[:500]}",
                    "dim")

            self._log("Curate", f"{tool.name} complete", "success")
        except Exception as e:
            self._curate_log_append(f"\nError: {e}", "error")
            self._curate_log_append(traceback.format_exc(), "error")

    # ══════════════════════════════════════════════════════════════════════
    #  EXPORT
    # ══════════════════════════════════════════════════════════════════════

    def _do_export(self):
        if not self.conn:
            self._log("Export", "No database connected", "warning")
            return

        fmt = self._export_format.get()
        ext_map = {"json": ".json", "csv": ".csv",
                   "markdown": ".md", "sqlite": ".db"}
        ext = ext_map.get(fmt, ".json")

        path = filedialog.asksaveasfilename(
            title="Export Database",
            defaultextension=ext,
            filetypes=[(f"{fmt.upper()} files", f"*{ext}"), ("All files", "*.*")])
        if not path:
            return

        self._log("Export", f"Exporting to {path}", "accent")

        threading.Thread(
            target=self._run_export,
            args=(path, fmt), daemon=True).start()

    def _run_export(self, path: str, fmt: str):
        try:
            data = {}

            # Source files
            rows = self.conn.execute(
                "SELECT file_cid, path, source_type, language, byte_size "
                "FROM source_files").fetchall()
            data["source_files"] = [
                {"file_cid": r[0], "path": r[1], "source_type": r[2],
                 "language": r[3], "byte_size": r[4]}
                for r in rows
            ]

            # Chunks
            if self._export_chunks.get():
                rows = self.conn.execute(
                    "SELECT chunk_id, chunk_type, name, content, file_cid, "
                    "line_start, line_end, token_count, embed_status, language_tier "
                    "FROM chunk_manifest").fetchall()
                data["chunks"] = [
                    {"chunk_id": r[0], "chunk_type": r[1], "name": r[2],
                     "content": r[3], "file_cid": r[4],
                     "line_start": r[5], "line_end": r[6],
                     "token_count": r[7], "embed_status": r[8],
                     "language_tier": r[9]}
                    for r in rows
                ]

            # Graph
            if self._export_graph.get():
                try:
                    edges = self.conn.execute(
                        "SELECT source_id, relation, target_id, weight "
                        "FROM graph_edges").fetchall()
                    data["graph_edges"] = [
                        {"source_id": r[0], "relation": r[1],
                         "target_id": r[2], "weight": r[3]}
                        for r in edges
                    ]
                except Exception:
                    pass

            # Write output
            if fmt == "json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

            elif fmt == "csv":
                import csv
                for table_name, rows_data in data.items():
                    if not rows_data:
                        continue
                    csv_path = path.replace(".csv", f"_{table_name}.csv")
                    with open(csv_path, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=rows_data[0].keys())
                        writer.writeheader()
                        writer.writerows(rows_data)

            elif fmt == "markdown":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"# Tripartite Export\n\n")
                    f.write(f"**Source files:** {len(data.get('source_files', []))}\n")
                    f.write(f"**Chunks:** {len(data.get('chunks', []))}\n")
                    f.write(f"**Graph edges:** {len(data.get('graph_edges', []))}\n\n")
                    for sf in data.get("source_files", []):
                        f.write(f"## {sf['path']}\n")
                        f.write(f"Type: {sf['source_type']} | "
                                f"Language: {sf.get('language', 'N/A')}\n\n")

            elif fmt == "sqlite":
                import shutil
                shutil.copy2(self.db_path, path)

            self._log("Export", f"Export complete: {path}", "success")

            # Show preview
            preview = json.dumps(data, indent=2, default=str)[:2000]
            def _show():
                self._export_preview.configure(state="normal")
                self._export_preview.delete("1.0", "end")
                self._export_preview.insert("1.0", preview)
                self._export_preview.configure(state="disabled")
            self.root.after(0, _show)

        except Exception as e:
            self._log("Export", f"Error: {e}", "error")

    # ══════════════════════════════════════════════════════════════════════
    #  SETTINGS
    # ══════════════════════════════════════════════════════════════════════

    def _open_settings(self):
        """Open a settings dialog."""
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.geometry("500x400")
        win.configure(bg=BG)
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text="⚙ Settings", bg=BG, fg=FG,
                 font=FONT_H).pack(anchor="w", padx=16, pady=(16, 8))

        # DB path
        db_frame = tk.Frame(win, bg=BG)
        db_frame.pack(fill="x", padx=16, pady=4)
        tk.Label(db_frame, text="Database:", bg=BG, fg=FG,
                 font=FONT_SM).pack(side="left")
        db_entry = tk.Entry(db_frame, bg=BG2, fg=FG, font=FONT_MONO_SM,
                            borderwidth=0)
        db_entry.pack(side="left", fill="x", expand=True, padx=8, ipady=3)
        if self.db_path:
            db_entry.insert(0, self.db_path)

        # Tool dirs
        tk.Label(win, text="Extra Tool Directories:", bg=BG, fg=FG,
                 font=FONT_SM).pack(anchor="w", padx=16, pady=(16, 4))
        tool_text = tk.Text(win, bg=BG2, fg=FG, font=FONT_MONO_SM,
                            height=4, borderwidth=0)
        tool_text.pack(fill="x", padx=16, pady=4)

        # Close
        tk.Button(win, text="Close", command=win.destroy,
                  bg=ACCENT2, fg="#ffffff", relief="flat", font=FONT_SM,
                  padx=20).pack(anchor="e", padx=16, pady=16)


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    root = tk.Tk()

    # Parse args
    db_path = None
    if len(sys.argv) > 1:
        db_path = sys.argv[1]

    app = TripartiteDataStore(root, db_path=db_path)
    root.mainloop()


if __name__ == "__main__":
    main()