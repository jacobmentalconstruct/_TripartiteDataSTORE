"""
tripartite/studio.py — Unified Tripartite Studio

Single-app orchestrator merging ingest, viewer, and curation into one
sidebar-navigated interface. Lives alongside gui.py and viewer.py as a
prototype toward the full src/app.py architecture.

Run with:
    python -m tripartite.studio

Architecture:
    StudioApp (tk.Tk)
      ├── Sidebar: mode buttons, DB selector, settings, status
      └── Content Frame: swaps between panels
           ├── IngestPanel   — port of gui.py
           ├── ViewerPanel   — port of viewer.py (browse/search/graph tabs)
           └── CuratePanel   — NEW: drop-in tool discovery + pipeline builder
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import io
import json
import queue
import pkgutil
import sqlite3
import sys
import time
import threading
import tkinter as tk
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Optional


# ══════════════════════════════════════════════════════════════════════════════
# THEME — single source of truth
# ══════════════════════════════════════════════════════════════════════════════

BG        = "#1e1e2e"
BG2       = "#2a2a3e"
BG3       = "#13131f"
SIDEBAR   = "#16162a"
ACCENT    = "#7c6af7"
ACCENT2   = "#5de4c7"
ACCENT3   = "#f5c542"           # gold — curate mode
FG        = "#cdd6f4"
FG_DIM    = "#6e6c8e"
SUCCESS   = "#a6e3a1"
WARNING   = "#f9e2af"
ERROR     = "#f38ba8"

FONT_UI   = ("Segoe UI", 10)
FONT_SM   = ("Segoe UI", 9)
FONT_H    = ("Segoe UI Semibold", 11)
FONT_H2   = ("Segoe UI Semibold", 14)
FONT_LOG  = ("Consolas", 9)
FONT_MONO = ("Consolas", 9)
FONT_TINY = ("Consolas", 8)


# ══════════════════════════════════════════════════════════════════════════════
# STOP SIGNAL — BaseException subclass so it escapes `except Exception` in the
# pipeline's _progress wrapper, propagating up to kill the ingest cleanly.
# The per-file `with conn:` context manager rolls back the current transaction.
# ══════════════════════════════════════════════════════════════════════════════

class _StopIngest(BaseException):
    """Raised inside on_progress to halt the ingest pipeline immediately."""


# ══════════════════════════════════════════════════════════════════════════════
# BASE PANEL — every mode panel inherits this
# ══════════════════════════════════════════════════════════════════════════════

class BasePanel:
    """
    Mount/unmount pattern for swappable content panels.

    Subclasses implement _build(parent_frame) and optionally on_mount/on_unmount.
    The panel never owns the Tk root — it receives a parent frame.
    """

    def __init__(self, parent: tk.Frame, app: "StudioApp"):
        self.parent = parent
        self.app = app
        self.frame: Optional[tk.Frame] = None

    def mount(self):
        self.frame = tk.Frame(self.parent, bg=BG)
        self.frame.pack(fill="both", expand=True)
        self._build(self.frame)
        self.on_mount()

    def unmount(self):
        self.on_unmount()
        if self.frame:
            self.frame.destroy()
            self.frame = None

    def _build(self, parent: tk.Frame):
        raise NotImplementedError

    def on_mount(self):
        pass

    def on_unmount(self):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# CURATION TOOL BASE — the drop-in extensibility contract
# ══════════════════════════════════════════════════════════════════════════════

class BaseCurationTool(ABC):
    """
    Drop a subclass in tripartite/curate_tools/ and it auto-registers.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable tool name shown in the sidebar."""

    @property
    @abstractmethod
    def description(self) -> str:
        """One-liner shown as tooltip / subtitle."""

    @property
    def icon(self) -> str:
        return "🔧"

    @property
    def priority(self) -> int:
        return 50

    @abstractmethod
    def build_config_ui(self, parent: tk.Frame) -> tk.Frame:
        """Build and return a configuration frame."""

    @abstractmethod
    def run(self, conn: sqlite3.Connection, selection: "Selection",
            on_progress=None, on_log=None) -> dict:
        """Execute the curation operation. Return stats dict."""


@dataclass
class Selection:
    """Describes which subset of a tripartite DB to operate on."""
    db_path: Path
    conn: sqlite3.Connection
    mode: str = "all"
    filter_paths: list[str] = field(default_factory=list)
    filter_types: list[str] = field(default_factory=list)
    filter_query: str = ""

    def get_file_cids(self) -> list[str]:
        if self.mode == "all":
            rows = self.conn.execute("SELECT file_cid FROM source_files").fetchall()
        elif self.mode == "by_type":
            ph = ",".join("?" * len(self.filter_types))
            rows = self.conn.execute(
                f"SELECT file_cid FROM source_files WHERE source_type IN ({ph})",
                self.filter_types).fetchall()
        elif self.mode == "by_path":
            rows = []
            for pat in self.filter_paths:
                rows += self.conn.execute(
                    "SELECT file_cid FROM source_files WHERE path LIKE ?",
                    (f"%{pat}%",)).fetchall()
        else:
            rows = self.conn.execute("SELECT file_cid FROM source_files").fetchall()
        return [r[0] for r in rows]


# ── Tool auto-discovery ──────────────────────────────────────────────────────

def _safe_import(package_name: str, mod_name: str, dir_path: Path):
    """
    Import a module from a directory, trying package-relative import first,
    then falling back to spec_from_file_location for external directories.
    Registers in sys.modules with a unique key to prevent collisions.
    """
    # Try standard package import first (works for tripartite.curate_tools.*)
    try:
        return importlib.import_module(f".{mod_name}", package=package_name)
    except (ImportError, ModuleNotFoundError):
        pass

    # Fallback: load by file path (works for external tool directories)
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


def discover_tools(extra_dirs: list[Path] | None = None) -> list[type[BaseCurationTool]]:
    """
    Find all BaseCurationTool subclasses in curate_tools/ + extra directories.

    Search order:
      1. tripartite/curate_tools/  (built-in package)
      2. extra_dirs parameter      (passed programmatically)
      3. Settings.tool_dirs         (user-configured in Settings dialog)

    Returns a de-duplicated list of classes sorted by priority (lowest first).
    """
    tools: list[type[BaseCurationTool]] = []
    seen_names: set[str] = set()
    search_dirs: list[tuple[str, Path]] = []

    # 1. Built-in curate_tools/ package
    builtin_dir = Path(__file__).parent / "curate_tools"
    if builtin_dir.is_dir():
        search_dirs.append(("tripartite.curate_tools", builtin_dir))

    # 2. Programmatic extras
    for extra in (extra_dirs or []):
        if isinstance(extra, str):
            extra = Path(extra)
        if extra.is_dir():
            search_dirs.append((f"_tripartite_tools_{extra.stem}", extra))

    # 3. User-configured tool directories from Settings
    try:
        from .settings_store import Settings
        settings = Settings.load()
        for td in getattr(settings, "tool_dirs", []):
            td_path = Path(td)
            if td_path.is_dir() and td_path != builtin_dir:
                search_dirs.append((f"_tripartite_tools_{td_path.stem}", td_path))
    except Exception:
        pass

    # Scan each directory
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

    # Sort by priority (instantiate to read @property — cheap, no I/O)
    tools.sort(key=lambda cls: cls().priority)
    return tools


# ══════════════════════════════════════════════════════════════════════════════
# BUILT-IN CURATION TOOLS
# ══════════════════════════════════════════════════════════════════════════════

class ExportFilesTool(BaseCurationTool):
    @property
    def name(self): return "Export Files"
    @property
    def description(self): return "Reconstruct originals from DB to a folder on disk"
    @property
    def icon(self): return "📤"
    @property
    def priority(self): return 10

    def build_config_ui(self, parent):
        frame = tk.Frame(parent, bg=BG)
        tk.Label(frame, text="Output directory:", bg=BG, fg=FG, font=FONT_SM
                 ).pack(anchor="w", pady=(0, 4))
        self._dir_var = tk.StringVar(value=str(Path.home() / "tripartite_export"))
        row = tk.Frame(frame, bg=BG)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self._dir_var, bg=BG2, fg=FG,
                 insertbackground=FG, relief="flat", font=FONT_SM
                 ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(row, text="…", bg=BG2, fg=FG, relief="flat", font=FONT_SM,
                  cursor="hand2", width=3, command=self._pick).pack(side="right")
        return frame

    def _pick(self):
        d = filedialog.askdirectory(title="Export to…", initialdir=self._dir_var.get())
        if d: self._dir_var.set(d)

    def run(self, conn, selection, on_progress=None, on_log=None):
        from .export import export_to_files
        return export_to_files(conn, Path(self._dir_var.get()), on_progress=on_progress)


class ExportDumpTool(BaseCurationTool):
    @property
    def name(self): return "Export Dump"
    @property
    def description(self): return "Generate filedump .txt and folder-tree .txt"
    @property
    def icon(self): return "📝"
    @property
    def priority(self): return 11

    def build_config_ui(self, parent):
        frame = tk.Frame(parent, bg=BG)
        tk.Label(frame, text="Output directory:", bg=BG, fg=FG, font=FONT_SM
                 ).pack(anchor="w", pady=(0, 4))
        self._dir_var = tk.StringVar(value=str(Path.home() / "tripartite_export"))
        row = tk.Frame(frame, bg=BG)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self._dir_var, bg=BG2, fg=FG,
                 insertbackground=FG, relief="flat", font=FONT_SM
                 ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(row, text="…", bg=BG2, fg=FG, relief="flat", font=FONT_SM,
                  cursor="hand2", width=3, command=self._pick).pack(side="right")
        return frame

    def _pick(self):
        d = filedialog.askdirectory(title="Export to…", initialdir=self._dir_var.get())
        if d: self._dir_var.set(d)

    def run(self, conn, selection, on_progress=None, on_log=None):
        from .export import export_all
        return export_all(selection.db_path, Path(self._dir_var.get()),
                          mode="dump", verbose=False)


class DedupeTool(BaseCurationTool):
    @property
    def name(self): return "Deduplicate"
    @property
    def description(self): return "Find files with identical content (CID match)"
    @property
    def icon(self): return "🔍"
    @property
    def priority(self): return 20

    def build_config_ui(self, parent):
        frame = tk.Frame(parent, bg=BG)
        self._preview_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Preview only (don't delete)",
                       variable=self._preview_var, bg=BG, fg=FG, selectcolor=BG2,
                       activebackground=BG, activeforeground=FG,
                       font=FONT_SM).pack(anchor="w")
        return frame

    def run(self, conn, selection, on_progress=None, on_log=None):
        log = on_log or (lambda m, t="info": None)
        rows = conn.execute(
            "SELECT file_cid, name, path FROM source_files ORDER BY file_cid"
        ).fetchall()
        seen: dict[str, list] = {}
        for cid, name, path in rows:
            seen.setdefault(cid, []).append({"name": name, "path": path})
        dupes = {k: v for k, v in seen.items() if len(v) > 1}
        for cid, files in dupes.items():
            names = ", ".join(f["name"] for f in files)
            log(f"  Duplicate CID {cid[:12]}…: {names}", "warning")
        total_dupes = sum(len(v) for v in dupes.values())
        log(f"\nFound {len(dupes)} duplicate groups across {total_dupes} files", "info")
        return {"duplicate_groups": len(dupes), "preview": self._preview_var.get()}


class CleanTool(BaseCurationTool):
    @property
    def name(self): return "Clean"
    @property
    def description(self): return "Remove junk files (.DS_Store, Thumbs.db, __pycache__)"
    @property
    def icon(self): return "🧹"
    @property
    def priority(self): return 15

    def build_config_ui(self, parent):
        frame = tk.Frame(parent, bg=BG)
        self._preview_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Preview only (don't remove)",
                       variable=self._preview_var, bg=BG, fg=FG, selectcolor=BG2,
                       activebackground=BG, activeforeground=FG,
                       font=FONT_SM).pack(anchor="w")
        return frame

    def run(self, conn, selection, on_progress=None, on_log=None):
        log = on_log or (lambda m, t="info": None)
        junk = [".DS_Store", "Thumbs.db", "desktop.ini",
                "__pycache__", ".pyc", ".pyo"]
        rows = conn.execute("SELECT file_cid, name, path FROM source_files").fetchall()
        flagged = []
        for cid, name, path in rows:
            for pat in junk:
                if pat in name or pat in path:
                    flagged.append({"cid": cid, "name": name, "reason": pat})
                    log(f"  Junk: {path}/{name}  (matched {pat})", "warning")
                    break
        log(f"\nFlagged {len(flagged)} junk files out of {len(rows)} total", "info")
        return {"flagged": len(flagged), "total": len(rows),
                "preview": self._preview_var.get()}


_BUILTIN_TOOLS = [ExportFilesTool, ExportDumpTool, DedupeTool, CleanTool]


# ══════════════════════════════════════════════════════════════════════════════
# INGEST PANEL
# ══════════════════════════════════════════════════════════════════════════════

class IngestPanel(BasePanel):

    def _build(self, parent):
        self._log_queue: queue.Queue = queue.Queue()
        self._running = False
        self._timer_id = None
        self._start_time = 0.0
        self._stop_flag = threading.Event()
        self._skip_flag = threading.Event()
        # FIX BUG 1: Pre-built path→size mapping for file size display & auto-skip
        self._file_sizes: dict[str, int] = {}

        pad = {"padx": 14, "pady": 5}

        # ── Source picker ─────────────────────────────────────────────────
        src_frame = tk.LabelFrame(parent, text=" Source ", bg=BG, fg=FG_DIM,
                                  font=FONT_UI, bd=1, relief="flat")
        src_frame.pack(fill="x", **pad)

        self.source_var = tk.StringVar()
        tk.Entry(src_frame, textvariable=self.source_var,
                 bg=BG2, fg=FG, insertbackground=FG, relief="flat",
                 font=FONT_UI).pack(side="left", fill="x", expand=True,
                                     padx=(8, 4), pady=8)
        tk.Button(src_frame, text="📁 Folder", command=self._pick_folder,
                  bg=ACCENT, fg="white", relief="flat", font=FONT_UI,
                  cursor="hand2", activebackground="#6a5ae0",
                  ).pack(side="left", padx=4, pady=8)
        tk.Button(src_frame, text="📄 File", command=self._pick_file,
                  bg=BG2, fg=FG, relief="flat", font=FONT_UI,
                  cursor="hand2", activebackground="#3a3a5e",
                  ).pack(side="left", padx=(0, 8), pady=8)

        # ── Output picker ─────────────────────────────────────────────────
        out_frame = tk.LabelFrame(parent, text=" Output .db ", bg=BG, fg=FG_DIM,
                                  font=FONT_UI, bd=1, relief="flat")
        out_frame.pack(fill="x", **pad)

        self.output_var = tk.StringVar()
        tk.Entry(out_frame, textvariable=self.output_var,
                 bg=BG2, fg=FG, insertbackground=FG, relief="flat",
                 font=FONT_UI).pack(side="left", fill="x", expand=True,
                                     padx=(8, 4), pady=8)
        tk.Button(out_frame, text="…", command=self._pick_output,
                  bg=BG2, fg=FG, relief="flat", font=FONT_UI,
                  cursor="hand2", width=3).pack(side="left", padx=(0, 8), pady=8)

        # ── Options row 1: chunk stream + size threshold ──────────────────
        opt1 = tk.Frame(parent, bg=BG)
        opt1.pack(fill="x", padx=14, pady=2)

        self.show_chunks_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opt1, text="Show chunk stream",
                       variable=self.show_chunks_var, bg=BG, fg=FG,
                       selectcolor=BG2, activebackground=BG, activeforeground=FG,
                       font=FONT_UI).pack(side="left", padx=(16, 0))

        tk.Label(opt1, text="  │  Skip files >",
                 bg=BG, fg=FG_DIM, font=FONT_SM).pack(side="left", padx=(12, 4))
        self._size_threshold_var = tk.StringVar(value="0")
        tk.Spinbox(opt1, from_=0, to=9999, increment=1, width=5,
                   textvariable=self._size_threshold_var,
                   bg=BG2, fg=FG, insertbackground=FG, relief="flat",
                   font=FONT_SM, buttonbackground=BG2).pack(side="left")
        tk.Label(opt1, text="MB (0=off)",
                 bg=BG, fg=FG_DIM, font=FONT_SM).pack(side="left", padx=(4, 0))

        # ── Options row 2: model-aware chunk token limit ──────────────────
        opt2 = tk.Frame(parent, bg=BG)
        opt2.pack(fill="x", padx=14, pady=(0, 2))

        tk.Label(opt2, text="Max chunk tokens:",
                 bg=BG, fg=FG_DIM, font=FONT_SM).pack(side="left", padx=(16, 4))
        self._chunk_tokens_var = tk.StringVar(value="512")
        self._chunk_spin = tk.Spinbox(
            opt2, from_=64, to=8192, increment=64, width=6,
            textvariable=self._chunk_tokens_var,
            bg=BG2, fg=FG, insertbackground=FG, relief="flat",
            font=FONT_SM, buttonbackground=BG2)
        self._chunk_spin.pack(side="left")

        self._model_ctx_label = tk.Label(
            opt2, text="", bg=BG, fg=FG_DIM, font=FONT_TINY)
        self._model_ctx_label.pack(side="left", padx=(8, 0))

        # Populate model context info now
        self._sync_model_context()

        # ── Run / Stop ────────────────────────────────────────────────────
        btn_frame = tk.Frame(parent, bg=BG)
        btn_frame.pack(fill="x", padx=14, pady=6)

        self.run_btn = tk.Button(
            btn_frame, text="▶  Run Ingest", command=self._start_ingest,
            bg=ACCENT2, fg=BG, relief="flat",
            font=("Segoe UI Semibold", 10), cursor="hand2",
            padx=18, pady=6, activebackground="#4dcfb3")
        self.run_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = tk.Button(
            btn_frame, text="■  Stop", command=self._stop_ingest,
            bg=BG2, fg=FG_DIM, relief="flat", font=FONT_UI,
            cursor="hand2", padx=12, pady=6, state="disabled")
        self.stop_btn.pack(side="left")

        # ── Log area ──────────────────────────────────────────────────────
        log_frame = tk.LabelFrame(parent, text=" Progress ", bg=BG, fg=FG_DIM,
                                  font=FONT_UI, bd=1, relief="flat")
        log_frame.pack(fill="both", expand=True, padx=14, pady=(0, 4))

        self.log_widget = scrolledtext.ScrolledText(
            log_frame, bg=BG3, fg=FG, font=FONT_LOG,
            relief="flat", state="disabled", wrap="word",
            insertbackground=FG)
        self.log_widget.pack(fill="both", expand=True, padx=4, pady=4)

        for tag, colour in [("info", FG), ("success", SUCCESS),
                             ("warning", WARNING), ("error", ERROR),
                             ("dim", FG_DIM), ("accent", ACCENT2)]:
            self.log_widget.tag_config(tag, foreground=colour)

        # ── Status bar ────────────────────────────────────────────────────
        bar = tk.Frame(parent, bg=BG2)
        bar.pack(fill="x", side="bottom")
        tk.Frame(bar, bg="#3a3a5e", height=1).pack(fill="x")

        # Row 1: file progress
        r1 = tk.Frame(bar, bg=BG2)
        r1.pack(fill="x", padx=10, pady=(5, 1))
        tk.Label(r1, text="Files:", bg=BG2, fg=FG_DIM, font=FONT_TINY
                 ).pack(side="left", padx=(0, 4))
        self._file_bar = ttk.Progressbar(r1, mode="determinate", maximum=1, length=180)
        self._file_bar.pack(side="left", padx=(0, 8))
        self._file_label = tk.StringVar(value="—")
        tk.Label(r1, textvariable=self._file_label, bg=BG2, fg=FG_DIM,
                 font=FONT_TINY, anchor="w").pack(side="left", fill="x", expand=True)

        # FIX BUG 4: Build right-side widgets in correct right-to-left order
        #   so skip button appears between file label and elapsed timer
        self._elapsed_var = tk.StringVar(value="")
        tk.Label(r1, textvariable=self._elapsed_var, bg=BG2, fg=FG_DIM,
                 font=FONT_TINY).pack(side="right")

        self._file_size_var = tk.StringVar(value="")
        self._file_size_lbl = tk.Label(r1, textvariable=self._file_size_var,
                                       bg=BG2, fg=FG_DIM, font=FONT_TINY)
        self._file_size_lbl.pack(side="right", padx=(0, 6))

        self.skip_btn = tk.Button(
            r1, text="⏭ Skip", command=self._skip_current_file,
            bg=WARNING, fg=BG, relief="flat", font=FONT_TINY,
            cursor="hand2", padx=6, pady=1, activebackground="#e0c96e")
        # Hidden until ingest runs — DO NOT pack/pack_forget, just pack once and hide
        self.skip_btn.pack(side="right", padx=(0, 6))
        self.skip_btn.pack_forget()

        # Row 2: chunk/embed progress
        r2 = tk.Frame(bar, bg=BG2)
        r2.pack(fill="x", padx=10, pady=(1, 4))
        tk.Label(r2, text="Chunks:", bg=BG2, fg=FG_DIM, font=FONT_TINY
                 ).pack(side="left", padx=(0, 4))
        self._chunk_bar = ttk.Progressbar(r2, mode="determinate", maximum=1, length=180)
        self._chunk_bar.pack(side="left", padx=(0, 8))
        self._action_var = tk.StringVar(value="Idle")
        tk.Label(r2, textvariable=self._action_var, bg=BG2, fg=FG_DIM,
                 font=FONT_TINY, anchor="w").pack(side="left", fill="x", expand=True)

        # Row 3: stats after run
        self._stats_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._stats_var, bg=BG2, fg=FG_DIM,
                 font=FONT_TINY, anchor="w", padx=10).pack(fill="x", pady=(0, 4))

    # ── Model-aware chunk sizing ──────────────────────────────────────────

    def _sync_model_context(self):
        """Read selected embedder's context_length and set defaults."""
        try:
            from .settings_store import Settings
            from .config import KNOWN_MODELS
            settings = Settings.load()
            spec = settings.get_embedder_spec()
            ctx = spec.get("context_length", 512)
            dims = spec.get("dims", "?")
            name = spec.get("display_name", spec["filename"])
            # Default chunk tokens = model ctx minus headroom for context prefix
            safe_max = max(64, ctx - 64)
            self._chunk_tokens_var.set(str(min(512, safe_max)))
            self._chunk_spin.config(to=ctx)
            self._model_ctx_label.config(
                text=f"  (model: {name}  ctx={ctx}  dims={dims})")
        except Exception:
            self._model_ctx_label.config(text="  (could not read model info)")

    # ── Pickers ───────────────────────────────────────────────────────────

    def _pick_folder(self):
        path = filedialog.askdirectory(title="Select folder to ingest")
        if path:
            self.source_var.set(path)
            self._auto_output(Path(path))

    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="Select file to ingest",
            filetypes=[("Text files", "*.py *.md *.txt *.rst *.json *.yaml *.toml"),
                       ("All files", "*.*")])
        if path:
            self.source_var.set(path)
            self._auto_output(Path(path))

    def _pick_output(self):
        path = filedialog.asksaveasfilename(
            title="Save .db artifact as…", defaultextension=".db",
            filetypes=[("SQLite database", "*.db")])
        if path:
            self.output_var.set(path)

    def _auto_output(self, source: Path):
        stem = source.stem if source.is_file() else source.name
        self.output_var.set(str(source.parent / f"{stem}.tripartite.db"))
        self.app.db_path = Path(self.output_var.get())

    # ── Ingest control ────────────────────────────────────────────────────

    def _start_ingest(self):
        source_str = self.source_var.get().strip()
        output_str = self.output_var.get().strip()

        if not source_str:
            messagebox.showwarning("No source", "Pick a folder or file to ingest.")
            return
        source = Path(source_str)
        if not source.exists():
            messagebox.showerror("Not found", f"Path does not exist:\n{source}")
            return
        if not output_str:
            messagebox.showwarning("No output", "Specify an output .db path.")
            return

        db_path = Path(output_str)

        from .settings_store import Settings
        settings = Settings.load()

        if db_path.exists() and not settings.lazy_mode:
            if self._check_model_mismatch(db_path, settings) == "cancel":
                return
        if not settings.lazy_mode:
            if not settings.model_is_cached("embedder"):
                if not self._prompt_download(settings):
                    return

        # FIX BUG 3: Read all Tkinter vars on main thread BEFORE spawning
        lazy = settings.lazy_mode
        size_thresh_mb = int(self._size_threshold_var.get() or 0)
        chunk_tokens = int(self._chunk_tokens_var.get() or 512)
        show_chunks = self.show_chunks_var.get()

        # FIX BUG 8: Set MAX_CHUNK_TOKENS to model-aware value before ingest
        try:
            from . import config as tripartite_config
            tripartite_config.MAX_CHUNK_TOKENS = chunk_tokens
        except Exception:
            pass

        self._clear_log()
        self._set_running(True)
        self._log_msg(f"Source  : {source}", "accent")
        self._log_msg(f"Output  : {db_path}", "accent")
        self._log_msg(f"Mode    : {'lazy (no embedding)' if lazy else 'full'}", "dim")
        self._log_msg(f"Embedder: {settings.embedder_model}", "dim")
        self._log_msg(f"Chunks  : max {chunk_tokens} tokens", "dim")
        if size_thresh_mb > 0:
            self._log_msg(f"Skip    : files > {size_thresh_mb} MB", "dim")
        else:
            self._log_msg("Skip    : disabled (no size limit)", "dim")
        self._log_msg("", "info")

        # FIX BUG 1: Build filename→size map on main thread for lookup in on_progress
        from .pipeline.detect import walk_source
        candidate_paths = list(walk_source(source))
        self._file_sizes = {}
        for p in candidate_paths:
            try:
                self._file_sizes[p.name] = p.stat().st_size
            except OSError:
                self._file_sizes[p.name] = 0

        total = len(candidate_paths)
        self._file_bar.configure(maximum=max(total, 1))
        self._file_bar["value"] = 0
        self._chunk_bar["value"] = 0

        on_chunk = None
        if show_chunks:
            if not hasattr(self, "_chunk_viewer") or not self._chunk_viewer.winfo_exists():
                from .chunk_viewer import ChunkViewerWindow
                self._chunk_viewer = ChunkViewerWindow(self.app)
            else:
                self._chunk_viewer._clear()
                self._chunk_viewer.lift()
            on_chunk = self._chunk_viewer.feed

        self._stop_flag.clear()
        self._skip_flag.clear()
        threading.Thread(
            target=self._run_ingest,
            args=(source, db_path, lazy, on_chunk, size_thresh_mb),
            daemon=True).start()

    def _run_ingest(self, source, db_path, lazy, on_chunk, size_thresh_mb):
        size_thresh_bytes = size_thresh_mb * 1_048_576 if size_thresh_mb > 0 else 0
        skipped_files: list[str] = []

        try:
            from .pipeline.ingest import ingest

            class QueueWriter(io.TextIOBase):
                def __init__(self, q): self.q = q
                def write(self, s):
                    s = s.rstrip()
                    if s: self.q.put(("log", s, "info"))
                    return len(s) + 1

            old_stdout = sys.stdout
            sys.stdout = QueueWriter(self._log_queue)

            def on_progress(event):
                # FIX BUG 2: Check stop flag — raise BaseException to escape
                # the pipeline's `except Exception` wrappers. The current file's
                # `with conn:` transaction rolls back cleanly.
                if self._stop_flag.is_set():
                    raise _StopIngest("User requested stop")

                etype = event.get("type")

                if etype == "file_start":
                    self._skip_flag.clear()
                    fname = event.get("filename", "")

                    # FIX BUG 1: Inject file_size from pre-built map
                    fsize = self._file_sizes.get(fname, 0)
                    event = dict(event, file_size=fsize)  # copy to avoid mutating shared dict

                    # Auto-skip oversized files
                    if size_thresh_bytes > 0 and fsize > size_thresh_bytes:
                        mb = fsize / 1_048_576
                        self._log_queue.put((
                            "log",
                            f"⏭ Auto-skip: {fname} ({mb:.1f} MB > {size_thresh_mb} MB limit)",
                            "warning"))
                        skipped_files.append(fname)
                        self._skip_flag.set()

                self._log_queue.put(("progress", event))

            result = ingest(source_root=source, db_path=db_path,
                            lazy=lazy, verbose=True,
                            on_chunk=on_chunk, on_progress=on_progress)

            sys.stdout = old_stdout
            self._log_queue.put(("log", "", "info"))

            if skipped_files:
                self._log_queue.put((
                    "log",
                    f"⏭ Skipped {len(skipped_files)} oversized file(s)",
                    "warning"))
            if result["errors"]:
                self._log_queue.put(("log",
                    f"✗ Completed with {len(result['errors'])} error(s)", "error"))
            else:
                self._log_queue.put(("log", "✓ Ingest complete!", "success"))
            self.frame.after(100, lambda: self._show_stats(db_path, result))

        except _StopIngest:
            sys.stdout = sys.__stdout__
            self._log_queue.put(("log", "\n■ Ingest stopped by user.", "warning"))
            self._log_queue.put(("log",
                "  DB is safe — only fully-committed files were written.", "dim"))

        except Exception as e:
            import traceback
            self._log_queue.put(("log", f"\n✗ Fatal error: {e}", "error"))
            self._log_queue.put(("log", traceback.format_exc(), "error"))
        finally:
            sys.stdout = sys.__stdout__
            # FIX BUG 7: Set WAL + checkpoint AFTER ingest created the DB
            try:
                ckpt = sqlite3.connect(str(db_path))
                ckpt.execute("PRAGMA journal_mode=WAL")
                ckpt.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                ckpt.close()
            except Exception:
                pass
            if self.frame:
                self.frame.after(100, lambda: self._set_running(False))

    def _stop_ingest(self):
        self._stop_flag.set()
        self._log_msg("\n⚠ Stop requested — finishing current file…", "warning")
        self._action_var.set("Stopping safely…")
        self.skip_btn.pack_forget()

    def _skip_current_file(self):
        """Visual signal + flag. True skip requires pipeline contract (see TODO)."""
        self._skip_flag.set()
        self._log_msg("⏭ Skip requested for current file", "warning")
        self._action_var.set("Skipping…")
        # TODO: Pipeline's _progress wrapper swallows return values and exceptions.
        # To enable true per-file skip, pipeline/ingest.py needs:
        #   result = _progress({"type": "file_start", ...})
        #   if result and result.get("skip"): continue

    # ── Helpers ────────────────────────────────────────────────────────────

    def _check_model_mismatch(self, db_path, settings):
        try:
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                "SELECT DISTINCT embed_model FROM chunk_manifest "
                "WHERE embed_model IS NOT NULL").fetchall()
            conn.close()
        except Exception:
            return "ok"
        db_models = {r[0] for r in rows if r[0]}
        if not db_models or settings.embedder_model in db_models:
            return "ok"
        answer = messagebox.askyesnocancel(
            "Model mismatch",
            f"DB was embedded with: {', '.join(db_models)}\n"
            f"Current embedder: {settings.embedder_model}\n\n"
            "Mixing models hurts search quality. Continue?",
            icon="warning", parent=self.app)
        return "ok" if answer else "cancel"

    def _prompt_download(self, settings):
        spec = settings.spec_for("embedder")
        answer = messagebox.askyesno(
            "Model not downloaded",
            f"The embedder model is not cached:\n  {spec['display_name']}\n\n"
            "Open Settings to download it?",
            icon="question", parent=self.app)
        if answer:
            self.app._open_settings()
            self._sync_model_context()  # Refresh after settings change
            return settings.model_is_cached("embedder")
        return False

    def _log_msg(self, text, tag="info"):
        self._log_queue.put(("log", text, tag))

    def _clear_log(self):
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")

    def _set_running(self, running):
        self._running = running
        if running:
            self.run_btn.configure(state="disabled", bg="#555570")
            self.stop_btn.configure(state="normal")
            self.skip_btn.pack(side="right", padx=(0, 6))
            self._action_var.set("Starting…")
            self._file_label.set("—")
            self._file_size_var.set("")
            self._skip_flag.clear()
            self._stop_flag.clear()
            self._start_time = time.time()
            self._tick_timer()
        else:
            self.run_btn.configure(state="normal", bg=ACCENT2)
            self.stop_btn.configure(state="disabled")
            self.skip_btn.pack_forget()
            self._file_size_var.set("")
            self._file_bar["value"] = self._file_bar["maximum"]

    def _tick_timer(self):
        if not self._running or not self.frame:
            return
        elapsed = time.time() - self._start_time
        m, s = divmod(int(elapsed), 60)
        self._elapsed_var.set(f"{m:02d}:{s:02d}")
        self._timer_id = self.frame.after(1000, self._tick_timer)

    def _show_stats(self, db_path, result):
        try:
            conn = sqlite3.connect(str(db_path))
            q = lambda sql: conn.execute(sql).fetchone()[0]
            chunks = q("SELECT COUNT(*) FROM chunk_manifest")
            embedded = q("SELECT COUNT(*) FROM chunk_manifest WHERE embed_status='done'")
            nodes = q("SELECT COUNT(*) FROM graph_nodes")
            edges = q("SELECT COUNT(*) FROM graph_edges")
            size_mb = db_path.stat().st_size / 1_048_576
            self._stats_var.set(
                f"DB: {size_mb:.1f} MB  │  "
                f"Files: {result['files_processed']}  │  "
                f"Chunks: {chunks}  │  "
                f"Embedded: {embedded}  │  "
                f"Nodes: {nodes}  │  "
                f"Edges: {edges}  │  "
                f"Time: {result['elapsed_seconds']}s")
            conn.close()
            self._action_var.set("✓ Done")
            self.app.db_path = db_path
            self.app._update_db_display()
        except Exception:
            pass

    def on_mount(self):
        self._poll_log()

    def _poll_log(self):
        if not self.frame:
            return
        try:
            while True:
                msg = self._log_queue.get_nowait()
                if msg[0] == "log":
                    self._append_log(msg[1], msg[2])
                elif msg[0] == "progress":
                    self._handle_progress(msg[1])
        except queue.Empty:
            pass
        self.frame.after(50, self._poll_log)

    def _append_log(self, text, tag):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n", tag)
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _handle_progress(self, event):
        etype = event.get("type")
        if etype == "file_start":
            idx, total = event["file_idx"], event["file_total"]
            name = event.get("filename", "")
            pct = int(idx / total * 100) if total else 0
            self._file_bar["maximum"] = total
            self._file_bar["value"] = idx - 1
            self._file_label.set(f"File {idx}/{total} ({pct}%)  —  {name}")

            # FIX BUG 1: Show file size from injected field
            fsize = event.get("file_size", 0)
            if fsize >= 1_048_576:
                self._file_size_var.set(f"{fsize / 1_048_576:.1f} MB")
            elif fsize > 0:
                self._file_size_var.set(f"{fsize / 1024:.0f} KB")
            else:
                self._file_size_var.set("")

            if self._skip_flag.is_set():
                self._action_var.set(f"⏭ Skipping {name}…")
            else:
                self._action_var.set(f"Processing {name}…")
            self._chunk_bar["value"] = 0

        elif etype == "file_done":
            self._file_bar["value"] = event["file_idx"]
            self._file_size_var.set("")
            self._skip_flag.clear()
        elif etype == "chunk_progress":
            self._chunk_bar["maximum"] = event.get("chunk_total", 1)
            self._chunk_bar["value"] = 0
        elif etype == "embedding_progress":
            idx = event.get("chunk_idx", 0)
            total = event.get("chunk_total", 1)
            self._chunk_bar["maximum"] = total
            self._chunk_bar["value"] = idx + 1
            pct = int((idx + 1) / total * 100) if total else 0
            self._action_var.set(f"Embedding {idx+1}/{total} ({pct}%)")


# ══════════════════════════════════════════════════════════════════════════════
# VIEWER PANEL
# ══════════════════════════════════════════════════════════════════════════════

class ViewerPanel(BasePanel):

    def _build(self, parent):
        self.conn: Optional[sqlite3.Connection] = None
        self._embedder = None
        self._embedder_failed = False

        if not self.app.db_path or not self.app.db_path.exists():
            tk.Label(parent, text="No database loaded.\n\nIngest something first, "
                     "or select a .db file from the sidebar.",
                     bg=BG, fg=FG_DIM, font=FONT_UI, justify="center"
                     ).pack(expand=True)
            return

        try:
            self.conn = sqlite3.connect(str(self.app.db_path))
            self.conn.execute("PRAGMA journal_mode=WAL")  # safe concurrent reads
            from .db import query as qmod
            self.qmod = qmod
            self.stats = qmod.get_db_stats(self.conn)
        except Exception as e:
            tk.Label(parent, text=f"Could not open database:\n{e}",
                     bg=BG, fg=ERROR, font=FONT_UI).pack(expand=True)
            return

        # Notebook with Browse / Search / Graph tabs
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        browse_tab = tk.Frame(nb, bg=BG)
        nb.add(browse_tab, text="  Browse  ")
        self._build_browse(browse_tab)

        search_tab = tk.Frame(nb, bg=BG)
        nb.add(search_tab, text="  Search  ")
        self._build_search(search_tab)

        graph_tab = tk.Frame(nb, bg=BG)
        nb.add(graph_tab, text="  Graph  ")
        self._build_graph(graph_tab)

        # Detail panel below notebook
        detail_frame = tk.LabelFrame(parent, text=" Chunk Detail ", bg=BG,
                                     fg=FG_DIM, font=FONT_UI, bd=1, relief="flat")
        detail_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._build_detail(detail_frame)

        # Status bar
        status = tk.Frame(parent, bg=BG2, pady=4)
        status.pack(fill="x", side="bottom")
        tk.Label(status, bg=BG2, fg=FG_DIM, font=FONT_SM,
                 text=(f"Files: {self.stats['files']}  │  "
                       f"Chunks: {self.stats['chunks']}  │  "
                       f"Embeddings: {self.stats['embeddings']}  │  "
                       f"Entities: {self.stats['entities']}")
                 ).pack(side="left", padx=12)

    def _build_browse(self, parent):
        paned = tk.PanedWindow(parent, orient="horizontal", bg=BG,
                               sashwidth=4, sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        left = tk.Frame(paned, bg=BG)
        paned.add(left, width=350)
        tk.Label(left, text="Files", bg=BG, fg=FG, font=FONT_SM
                 ).pack(anchor="w", padx=8, pady=(4, 2))
        f_frame = tk.Frame(left, bg=BG)
        f_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        sb = tk.Scrollbar(f_frame, bg=BG2)
        sb.pack(side="right", fill="y")
        self.files_tree = ttk.Treeview(f_frame, show="tree",
                                       yscrollcommand=sb.set, height=12)
        self.files_tree.pack(side="left", fill="both", expand=True)
        sb.config(command=self.files_tree.yview)
        self.files_tree.bind("<<TreeviewSelect>>", self._on_file_select)

        right = tk.Frame(paned, bg=BG)
        paned.add(right, width=350)
        tk.Label(right, text="Chunks", bg=BG, fg=FG, font=FONT_SM
                 ).pack(anchor="w", padx=8, pady=(4, 2))
        c_frame = tk.Frame(right, bg=BG)
        c_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        sb2 = tk.Scrollbar(c_frame, bg=BG2)
        sb2.pack(side="right", fill="y")
        self.chunks_list = tk.Listbox(c_frame, bg=BG2, fg=FG,
                                      selectbackground=ACCENT, selectforeground="white",
                                      font=FONT_SM, relief="flat",
                                      yscrollcommand=sb2.set)
        self.chunks_list.pack(side="left", fill="both", expand=True)
        sb2.config(command=self.chunks_list.yview)
        self.chunks_list.bind("<<ListboxSelect>>", self._on_chunk_select)
        self.chunks_data = []

    def _build_search(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", padx=8, pady=8)
        self.search_var = tk.StringVar()
        entry = tk.Entry(bar, textvariable=self.search_var, bg=BG2, fg=FG,
                         insertbackground=FG, relief="flat", font=FONT_UI)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        entry.bind("<Return>", lambda e: self._run_search())
        tk.Button(bar, text="🔍 Search", command=self._run_search,
                  bg=ACCENT, fg="white", relief="flat", font=FONT_SM,
                  cursor="hand2", padx=12, pady=4,
                  activebackground="#6a5ae0").pack(side="right")

        self.search_status = tk.Label(parent, text="Enter query and press Search",
                                      bg=BG, fg=FG_DIM, font=FONT_SM)
        self.search_status.pack(anchor="w", padx=8, pady=(0, 4))

        res_frame = tk.Frame(parent, bg=BG)
        res_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        sb = tk.Scrollbar(res_frame, bg=BG2)
        sb.pack(side="right", fill="y")
        self.search_results = tk.Listbox(res_frame, bg=BG2, fg=FG,
                                         selectbackground=ACCENT,
                                         selectforeground="white",
                                         font=FONT_SM, relief="flat",
                                         yscrollcommand=sb.set)
        self.search_results.pack(side="left", fill="both", expand=True)
        sb.config(command=self.search_results.yview)
        self.search_results.bind("<<ListboxSelect>>", self._on_search_select)
        self.search_data = []

    def _build_graph(self, parent):
        filt = tk.Frame(parent, bg=BG)
        filt.pack(fill="x", padx=8, pady=8)
        tk.Label(filt, text="Type:", bg=BG, fg=FG_DIM, font=FONT_SM
                 ).pack(side="left", padx=(0, 4))
        entity_types = ["All"] + self.qmod.get_entity_types(self.conn)
        self.entity_type_var = tk.StringVar(value="All")
        combo = ttk.Combobox(filt, textvariable=self.entity_type_var,
                             values=entity_types, state="readonly", width=12,
                             font=FONT_SM)
        combo.pack(side="left", fill="x", expand=True)
        combo.bind("<<ComboboxSelected>>", lambda e: self._load_entities())

        tk.Label(parent, text="Entities", bg=BG, fg=FG, font=FONT_SM
                 ).pack(anchor="w", padx=8, pady=(4, 2))
        e_frame = tk.Frame(parent, bg=BG)
        e_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        sb = tk.Scrollbar(e_frame, bg=BG2)
        sb.pack(side="right", fill="y")
        self.entities_list = tk.Listbox(e_frame, bg=BG2, fg=FG,
                                        selectbackground=ACCENT,
                                        selectforeground="white",
                                        font=FONT_SM, relief="flat",
                                        yscrollcommand=sb.set)
        self.entities_list.pack(side="left", fill="both", expand=True)
        sb.config(command=self.entities_list.yview)
        self.entities_list.bind("<<ListboxSelect>>", self._on_entity_select)
        self.entities_data = []

    def _build_detail(self, parent):
        toolbar = tk.Frame(parent, bg=BG)
        toolbar.pack(fill="x", padx=8, pady=4)
        self.detail_label = tk.Label(toolbar, text="Select a chunk to view details",
                                     bg=BG, fg=FG_DIM, font=FONT_SM)
        self.detail_label.pack(side="left")
        tk.Button(toolbar, text="📋 Copy", command=self._copy_chunk,
                  bg=BG2, fg=FG, relief="flat", font=FONT_SM,
                  cursor="hand2", padx=8, pady=2,
                  activebackground="#3a3a5e").pack(side="right")

        t_frame = tk.Frame(parent, bg=BG)
        t_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.detail_text = scrolledtext.ScrolledText(
            t_frame, bg=BG3, fg=FG, font=FONT_MONO,
            relief="flat", wrap="word", state="disabled")
        self.detail_text.pack(fill="both", expand=True)
        self.detail_text.tag_config("heading", foreground=ACCENT,
                                    font=("Segoe UI Semibold", 10))
        self.detail_text.tag_config("dim", foreground=FG_DIM)
        self.detail_text.tag_config("accent", foreground=ACCENT2)
        self.detail_text.tag_config("error", foreground=ERROR)
        self.current_chunk_text = ""

    # ── Data loading ──────────────────────────────────────────────────────

    def on_mount(self):
        if self.conn:
            self._load_files()
            self._load_entities()

    def on_unmount(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def _load_files(self):
        files = self.qmod.list_source_files(self.conn)
        for item in self.files_tree.get_children():
            self.files_tree.delete(item)
        for f in files:
            display = f"{f['name']}  ({f['line_count']} lines, {f['source_type']})"
            self.files_tree.insert("", "end", text=display, values=(f["file_cid"],))

    def _load_entities(self):
        t = self.entity_type_var.get()
        filt = None if t == "All" else t
        entities = self.qmod.list_entities(self.conn, filt)
        self.entities_list.delete(0, tk.END)
        self.entities_data = []
        for e in entities:
            sal = e.get("salience", 0.0) or 0.0
            self.entities_list.insert(tk.END,
                                      f"{e['label']}  ({e['entity_type']}, {sal:.2f})")
            self.entities_data.append(e)

    # ── Event handlers ────────────────────────────────────────────────────

    def _on_file_select(self, event):
        sel = self.files_tree.selection()
        if not sel: return
        cid = self.files_tree.item(sel[0])["values"][0]
        chunks = self.qmod.get_chunks_for_file(self.conn, cid)
        self.chunks_list.delete(0, tk.END)
        self.chunks_data = []
        for c in chunks:
            prefix = c.get("context_prefix", "")
            lines = f"L{c['line_start']}-{c['line_end']}"
            icon = "✓" if c.get("embed_status") == "done" else "○"
            self.chunks_list.insert(tk.END,
                f"{icon} {prefix or '(no context)'}  [{lines}, {c['token_count']}t]")
            self.chunks_data.append(c)

    def _on_chunk_select(self, event):
        sel = self.chunks_list.curselection()
        if sel:
            self._show_chunk_detail(self.chunks_data[sel[0]]["chunk_id"])

    def _on_search_select(self, event):
        sel = self.search_results.curselection()
        if sel:
            self._show_chunk_detail(self.search_data[sel[0]]["chunk_id"])

    def _on_entity_select(self, event):
        sel = self.entities_list.curselection()
        if not sel: return
        entity = self.entities_data[sel[0]]
        chunks = self.qmod.get_chunks_mentioning_entity(self.conn, entity["node_id"])
        self._show_entity_chunks(entity, chunks)

    def _run_search(self):
        q_text = self.search_var.get().strip()
        if not q_text: return
        embedder = self._get_embedder()
        label = "semantic + FTS" if embedder else "FTS only"
        self.search_status.config(text=f"Searching ({label})…", fg=ACCENT2)
        self.frame.update_idletasks()
        try:
            results = self.qmod.hybrid_search(self.conn, q_text, embedder, limit=20)
            self.search_results.delete(0, tk.END)
            self.search_data = []
            for r in results:
                score = r.get("score", 0.0)
                st = r.get("search_type", "")
                icon = {"fts": "🔍", "semantic": "🎯"}.get(st, "⚡")
                prefix = r.get("context_prefix", "(no context)")
                self.search_results.insert(tk.END, f"{icon} {score:.3f}  {prefix[:60]}")
                self.search_data.append(r)
            self.search_status.config(
                text=f"Found {len(results)} results ({label})", fg=SUCCESS)
        except Exception as e:
            self.search_status.config(text=f"Search failed: {e}", fg=ERROR)

    # ── Detail rendering ──────────────────────────────────────────────────

    def _render_parts(self, parts: list[tuple[str, str | None]]):
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", tk.END)
        for text, tag in parts:
            if tag:
                self.detail_text.insert(tk.END, text, tag)
            else:
                self.detail_text.insert(tk.END, text)
        self.detail_text.configure(state="disabled")

    def _show_chunk_detail(self, chunk_id):
        detail = self.qmod.get_chunk_detail(self.conn, chunk_id)
        if not detail: return
        self.detail_label.config(
            text=f"Chunk: {detail.get('context_prefix', chunk_id)}", fg=FG)

        parts = [("─── Metadata ───\n", "heading"),
                 (f"Type: {detail.get('chunk_type', '?')}  │  "
                  f"Tokens: {detail.get('token_count', 0)}", "dim")]
        if detail.get("line_start") is not None:
            parts.append((f"  │  Lines: {detail['line_start']}-{detail['line_end']}", "dim"))
        es = detail.get("embed_status", "pending")
        if es == "done":
            parts.append((f"\nEmbedding: ✓ {detail.get('embed_model', '')}", "accent"))
        elif es == "error":
            parts.append((f"\nEmbedding: ✗ {detail.get('embed_error', '')}", "error"))
        else:
            parts.append(("\nEmbedding: ○ pending", "dim"))
        if detail.get("context_prefix"):
            parts += [("\n\n─── Context ───\n", "heading"),
                      (detail["context_prefix"], "accent")]
        parts += [("\n\n─── Content ───\n", "heading"),
                  (detail.get("text", "(no text)"), None)]
        neighbors = detail.get("neighbors", {})
        if neighbors.get("entities"):
            parts.append(("\n\n─── Entities ───\n", "heading"))
            for e in neighbors["entities"][:10]:
                parts.append((f"  • {e['label']} ({e['entity_type']})\n", "dim"))
        if neighbors.get("related_chunks"):
            parts.append(("\n─── Related ───\n", "heading"))
            for rc in neighbors["related_chunks"][:10]:
                parts.append((f"  • {rc['context_prefix']} ({rc['edge_type']})\n", "dim"))
        self._render_parts(parts)
        self.current_chunk_text = detail.get("text", "")

    def _show_entity_chunks(self, entity, chunks):
        self.detail_label.config(text=f"Entity: {entity['label']}", fg=FG)
        parts = [
            ("─── Entity ───\n", "heading"),
            (f"{entity['label']}\n", "accent"),
            (f"Type: {entity['entity_type']}  │  "
             f"Salience: {entity.get('salience', 0.0) or 0.0:.3f}\n\n", "dim"),
            ("─── Mentioned In ───\n", "heading")]
        for c in (chunks or []):
            parts.append((f"  • {c['context_prefix']} ({c['chunk_type']})\n", "dim"))
        if not chunks:
            parts.append(("  (none)\n", "dim"))
        self._render_parts(parts)
        self.current_chunk_text = ""

    def _copy_chunk(self):
        if self.current_chunk_text:
            self.app.clipboard_clear()
            self.app.clipboard_append(self.current_chunk_text)
            self.detail_label.config(text="✓ Copied", fg=SUCCESS)
            self.frame.after(2000, lambda: self.detail_label.config(fg=FG))

    def _get_embedder(self):
        if self._embedder is not None: return self._embedder
        if self._embedder_failed: return None
        try:
            from .models.manager import get_embedder
            self._embedder = get_embedder()
            return self._embedder
        except Exception:
            self._embedder_failed = True
            return None


# ══════════════════════════════════════════════════════════════════════════════
# CURATE PANEL
# ══════════════════════════════════════════════════════════════════════════════

class CuratePanel(BasePanel):

    def _build(self, parent):
        self._log_queue: queue.Queue = queue.Queue()
        self._tool_instances: dict[str, BaseCurationTool] = {}
        self._active_tool: Optional[BaseCurationTool] = None
        self._config_frame: Optional[tk.Frame] = None
        self._pipeline: list[tuple[str, BaseCurationTool]] = []
        self._curate_running = False

        if not self.app.db_path or not self.app.db_path.exists():
            tk.Label(parent, text="No database loaded.\n\nIngest something first, "
                     "or select a .db file from the sidebar.",
                     bg=BG, fg=FG_DIM, font=FONT_UI, justify="center"
                     ).pack(expand=True)
            return

        # Top pane: tool list (left) + config + pipeline (right)
        top = tk.PanedWindow(parent, orient="horizontal", bg=BG,
                             sashwidth=4, sashrelief="flat")
        top.pack(fill="both", expand=True, padx=8, pady=8)

        tool_frame = tk.LabelFrame(top, text=" Tools ", bg=BG, fg=FG_DIM,
                                   font=FONT_UI, bd=1, relief="flat")
        top.add(tool_frame, width=220)

        self.tool_listbox = tk.Listbox(tool_frame, bg=BG2, fg=FG,
                                       selectbackground=ACCENT3,
                                       selectforeground=BG,
                                       font=FONT_SM, relief="flat")
        self.tool_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.tool_listbox.bind("<<ListboxSelect>>", self._on_tool_select)

        right = tk.Frame(top, bg=BG)
        top.add(right, width=500)

        self._config_container = tk.LabelFrame(right, text=" Tool Settings ",
                                               bg=BG, fg=FG_DIM,
                                               font=FONT_UI, bd=1, relief="flat")
        self._config_container.pack(fill="x", padx=4, pady=(0, 4))

        self._config_placeholder = tk.Label(self._config_container,
                                            text="Select a tool from the list",
                                            bg=BG, fg=FG_DIM, font=FONT_SM)
        self._config_placeholder.pack(padx=10, pady=20)

        pipe_frame = tk.LabelFrame(right, text=" Pipeline ", bg=BG, fg=FG_DIM,
                                   font=FONT_UI, bd=1, relief="flat")
        pipe_frame.pack(fill="x", padx=4, pady=4)

        pipe_bar = tk.Frame(pipe_frame, bg=BG)
        pipe_bar.pack(fill="x", padx=8, pady=4)
        tk.Button(pipe_bar, text="+ Add to Pipeline",
                  command=self._add_to_pipeline,
                  bg=ACCENT3, fg=BG, relief="flat", font=FONT_SM,
                  cursor="hand2", padx=10, pady=3,
                  activebackground="#d4a832").pack(side="left")
        tk.Button(pipe_bar, text="Clear", command=self._clear_pipeline,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_SM,
                  cursor="hand2", padx=8, pady=3).pack(side="left", padx=4)

        self.pipeline_listbox = tk.Listbox(pipe_frame, bg=BG2, fg=FG,
                                           font=FONT_SM, relief="flat",
                                           height=4)
        self.pipeline_listbox.pack(fill="x", padx=8, pady=(0, 8))

        run_frame = tk.Frame(right, bg=BG)
        run_frame.pack(fill="x", padx=4, pady=4)

        self._run_single_btn = tk.Button(
            run_frame, text="▶ Run Selected Tool",
            command=self._run_single, bg=ACCENT2, fg=BG, relief="flat",
            font=("Segoe UI Semibold", 10), cursor="hand2",
            padx=14, pady=6, activebackground="#4dcfb3")
        self._run_single_btn.pack(side="left", padx=(0, 8))

        self._run_pipe_btn = tk.Button(
            run_frame, text="▶▶ Run Pipeline",
            command=self._run_pipeline, bg=ACCENT3, fg=BG, relief="flat",
            font=("Segoe UI Semibold", 10), cursor="hand2",
            padx=14, pady=6, activebackground="#d4a832")
        self._run_pipe_btn.pack(side="left")

        # Log area
        log_frame = tk.LabelFrame(parent, text=" Curation Log ", bg=BG, fg=FG_DIM,
                                  font=FONT_UI, bd=1, relief="flat")
        log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.log_widget = scrolledtext.ScrolledText(
            log_frame, bg=BG3, fg=FG, font=FONT_LOG,
            relief="flat", state="disabled", wrap="word", height=10)
        self.log_widget.pack(fill="both", expand=True, padx=4, pady=4)
        for tag, colour in [("info", FG), ("success", SUCCESS),
                             ("warning", WARNING), ("error", ERROR),
                             ("dim", FG_DIM), ("accent", ACCENT2)]:
            self.log_widget.tag_config(tag, foreground=colour)

        self._discover_and_populate()

    def _discover_and_populate(self):
        tool_classes = list(_BUILTIN_TOOLS)
        builtin_names = {t.__name__ for t in _BUILTIN_TOOLS}

        # Discover external tools from curate_tools/ and Settings.tool_dirs
        discovered = discover_tools()
        external_count = 0
        for t in discovered:
            if t.__name__ not in builtin_names:
                tool_classes.append(t)
                external_count += 1

        # Instantiate and populate the listbox
        for cls in tool_classes:
            try:
                inst = cls()
                self._tool_instances[inst.name] = inst
                self.tool_listbox.insert(tk.END, f"{inst.icon}  {inst.name}")
            except Exception as e:
                print(f"[tools] Failed to instantiate {cls.__name__}: {e}")

        # Log discovery summary to the curation log panel
        total = len(self._tool_instances)
        if external_count > 0:
            self._curate_log(
                f"Discovered {total} tools ({external_count} from external dirs)", "dim")
        else:
            self._curate_log(
                f"Loaded {total} built-in tools  "
                f"(drop .py files in curate_tools/ to add more)", "dim")

    def _on_tool_select(self, event):
        sel = self.tool_listbox.curselection()
        if not sel: return
        text = self.tool_listbox.get(sel[0])
        name = text.split("  ", 1)[-1] if "  " in text else text
        tool = self._tool_instances.get(name)
        if not tool: return
        self._active_tool = tool
        if self._config_frame:
            self._config_frame.destroy()
        self._config_placeholder.pack_forget()
        self._config_container.config(
            text=f" {tool.icon} {tool.name} — {tool.description} ")
        self._config_frame = tool.build_config_ui(self._config_container)
        self._config_frame.pack(fill="x", padx=8, pady=8)

    def _add_to_pipeline(self):
        if not self._active_tool: return
        self._pipeline.append((self._active_tool.name, self._active_tool))
        idx = len(self._pipeline)
        self.pipeline_listbox.insert(
            tk.END,
            f"  {idx}. {self._active_tool.icon}  {self._active_tool.name}")

    def _clear_pipeline(self):
        self._pipeline.clear()
        self.pipeline_listbox.delete(0, tk.END)

    def _run_single(self):
        if not self._active_tool:
            messagebox.showwarning("No tool", "Select a tool first.")
            return
        self._execute_tools_threaded([self._active_tool])

    def _run_pipeline(self):
        if not self._pipeline:
            messagebox.showwarning("Empty pipeline", "Add tools to the pipeline first.")
            return
        self._execute_tools_threaded([t for _, t in self._pipeline])

    # FIX BUG 6: Run curation tools in a background thread to keep UI responsive
    def _execute_tools_threaded(self, tools: list[BaseCurationTool]):
        if self._curate_running:
            messagebox.showinfo("Busy", "A curation operation is already running.")
            return
        self._curate_running = True
        self._run_single_btn.configure(state="disabled")
        self._run_pipe_btn.configure(state="disabled")
        self._clear_log()
        threading.Thread(target=self._execute_tools, args=(tools,), daemon=True).start()
        self._poll_curate_log()

    def _execute_tools(self, tools: list[BaseCurationTool]):
        conn = sqlite3.connect(str(self.app.db_path))
        selection = Selection(db_path=self.app.db_path, conn=conn)

        for i, tool in enumerate(tools, 1):
            self._log_queue.put(("log", f"{'═' * 40}", "dim"))
            self._log_queue.put(("log",
                f"  {tool.icon}  Running: {tool.name}  ({i}/{len(tools)})", "accent"))
            self._log_queue.put(("log", f"{'═' * 40}\n", "dim"))
            try:
                def threaded_log(msg, tag="info"):
                    self._log_queue.put(("log", msg, tag))
                result = tool.run(conn, selection, on_log=threaded_log)
                self._log_queue.put(("log",
                    f"\n✓ {tool.name}: {json.dumps(result, default=str)}", "success"))
            except Exception as e:
                import traceback
                self._log_queue.put(("log", f"\n✗ {tool.name} failed: {e}", "error"))
                self._log_queue.put(("log", traceback.format_exc(), "error"))
                break
            self._log_queue.put(("log", "", "info"))

        conn.close()
        self._log_queue.put(("log", "Pipeline finished.", "success"))
        self._log_queue.put(("done", None, None))

    def _poll_curate_log(self):
        if not self.frame:
            return
        try:
            while True:
                msg = self._log_queue.get_nowait()
                if msg[0] == "done":
                    self._curate_running = False
                    self._run_single_btn.configure(state="normal")
                    self._run_pipe_btn.configure(state="normal")
                    return  # Stop polling
                self._curate_log(msg[1], msg[2])
        except queue.Empty:
            pass
        self.frame.after(50, self._poll_curate_log)

    def _curate_log(self, text, tag="info"):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n", tag)
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _clear_log(self):
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")


# ══════════════════════════════════════════════════════════════════════════════
# STUDIO APP — the orchestrator
# ══════════════════════════════════════════════════════════════════════════════

class StudioApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Tripartite Studio")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(1000, 700)

        self.db_path: Optional[Path] = None

        from .settings_store import Settings
        self._settings = Settings.load()

        self._modes = {
            "ingest": ("⬡  Ingest",  ACCENT2,  IngestPanel),
            "view":   ("⬡  View",    ACCENT,   ViewerPanel),
            "curate": ("⬡  Curate",  ACCENT3,  CuratePanel),
        }
        self._active_mode: Optional[str] = None
        self._active_panel: Optional[BasePanel] = None
        self._mode_buttons: dict[str, tk.Button] = {}

        self._build_ui()
        self.switch_mode("ingest")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.update_idletasks()
        w, h = 1200, 800
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        # Sidebar
        self.sidebar = tk.Frame(self, bg=SIDEBAR, width=180)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        tk.Label(self.sidebar, text="Tripartite\nStudio",
                 bg=SIDEBAR, fg=ACCENT, font=("Segoe UI Semibold", 13),
                 justify="center").pack(pady=(20, 24))

        for key, (label, color, _) in self._modes.items():
            btn = tk.Button(
                self.sidebar, text=label, anchor="w",
                bg=SIDEBAR, fg=FG_DIM, relief="flat", font=FONT_UI,
                cursor="hand2", padx=16, pady=10,
                activebackground=BG2, activeforeground=FG,
                command=lambda k=key: self.switch_mode(k))
            btn.pack(fill="x", padx=8, pady=2)
            self._mode_buttons[key] = btn

        tk.Frame(self.sidebar, bg="#3a3a5e", height=1).pack(
            fill="x", padx=12, pady=16)

        tk.Label(self.sidebar, text="Database", bg=SIDEBAR, fg=FG_DIM,
                 font=FONT_SM).pack(anchor="w", padx=16)

        self._db_label = tk.Label(self.sidebar, text="(none)",
                                  bg=SIDEBAR, fg=FG, font=FONT_TINY,
                                  wraplength=150, justify="left")
        self._db_label.pack(anchor="w", padx=16, pady=(2, 4))

        tk.Button(self.sidebar, text="Open .db…", command=self._pick_db,
                  bg=BG2, fg=FG, relief="flat", font=FONT_SM,
                  cursor="hand2", padx=8, pady=4,
                  activebackground="#3a3a5e").pack(padx=16, anchor="w")

        bottom = tk.Frame(self.sidebar, bg=SIDEBAR)
        bottom.pack(side="bottom", fill="x", pady=12)

        tk.Button(bottom, text="⚙ Settings", command=self._open_settings,
                  bg=SIDEBAR, fg=FG_DIM, relief="flat", font=FONT_SM,
                  cursor="hand2", padx=8, pady=4,
                  activebackground=BG2).pack(fill="x", padx=12, pady=2)

        tk.Button(bottom, text="✕ Exit", command=self._on_close,
                  bg=SIDEBAR, fg=FG_DIM, relief="flat", font=FONT_SM,
                  cursor="hand2", padx=8, pady=4,
                  activebackground=BG2).pack(fill="x", padx=12, pady=2)

        # Content area
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side="right", fill="both", expand=True)

    def switch_mode(self, mode: str):
        if mode == self._active_mode:
            return
        if self._active_panel:
            self._active_panel.unmount()
            self._active_panel = None
        for key, btn in self._mode_buttons.items():
            if key == mode:
                _, color, _ = self._modes[key]
                btn.configure(bg=BG2, fg=color)
            else:
                btn.configure(bg=SIDEBAR, fg=FG_DIM)
        _, _, PanelClass = self._modes[mode]
        self._active_mode = mode
        self._active_panel = PanelClass(self.content, self)
        self._active_panel.mount()

    def _pick_db(self):
        path = filedialog.askopenfilename(
            title="Select Tripartite database",
            filetypes=[("Database files", "*.db"), ("All files", "*.*")])
        if path:
            self.db_path = Path(path)
            self._update_db_display()
            if self._active_mode:
                mode = self._active_mode
                self._active_mode = None
                self.switch_mode(mode)

    def _update_db_display(self):
        if self.db_path:
            self._db_label.config(text=self.db_path.name, fg=ACCENT2)
        else:
            self._db_label.config(text="(none)", fg=FG_DIM)

    def _open_settings(self):
        from .settings_dialog import SettingsDialog
        from .settings_store import Settings
        dlg = SettingsDialog(self)
        self.wait_window(dlg)
        self._settings = Settings.load()
        from .models import manager
        manager._embedder_instance = None
        manager._extractor_instance = None
        manager._embedder_failed = False
        manager._extractor_failed = False

    def _on_close(self):
        if (self._active_panel and isinstance(self._active_panel, IngestPanel)
                and getattr(self._active_panel, '_running', False)):
            answer = messagebox.askyesno(
                "Ingest in progress",
                "An ingest is running. Stop and exit?",
                icon="warning", parent=self)
            if not answer:
                return
            self._active_panel._stop_flag.set()
            time.sleep(0.3)  # Brief grace period for _StopIngest to propagate

        if self._active_panel:
            self._active_panel.unmount()
        self.quit()
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = StudioApp()
    app.mainloop()


if __name__ == "__main__":
    main()
