"""
tripartite/chunk_viewer.py

A Toplevel window that displays chunks as they are produced by the pipeline,
building a scrolling monolithic dump in real time.

Each chunk is rendered as a labeled block:

  ━━ function_def ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    sample_app/app.py > class Calculator > compute()
    lines 34–51  │  108 tokens  │  chunk 3 of 7
  ──────────────────────────────────────────────────────────
  def compute(self, op, a, b):
      \"\"\"Perform an operation.\"\"\"
      if op == 'add':
      ...
  ══════════════════════════════════════════════════════════

The window can be opened before or during an ingest run.
Call .feed(source, chunk, chunk_id, index, total) from the pipeline callback
(always safe to call from any thread — uses a queue internally).

A "Save Log" button writes the full text to a .txt file.
"""

import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, scrolledtext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pipeline.detect import SourceFile
    from .chunkers.base import Chunk


# ── Colour palette (matches gui.py) ───────────────────────────────────────────
BG        = "#13131f"
BG2       = "#1e1e2e"
BG3       = "#2a2a3e"
FG        = "#cdd6f4"
FG_DIM    = "#6e6c8e"
ACCENT    = "#7c6af7"
ACCENT2   = "#5de4c7"
SUCCESS   = "#a6e3a1"
WARNING   = "#f9e2af"
ERROR     = "#f38ba8"
PINK      = "#f5c2e7"
YELLOW    = "#f9e2af"
BLUE      = "#89dceb"

# Chunk type → colour mapping
_TYPE_COLOURS = {
    "function_def":     ACCENT2,
    "method_def":       ACCENT2,
    "class_def":        ACCENT,
    "module_summary":   SUCCESS,
    "import_block":     FG_DIM,
    "document_summary": SUCCESS,
    "document":         SUCCESS,
    "section":          BLUE,
    "subsection":       BLUE,
    "paragraph":        FG,
    "generic":          FG_DIM,
}

_PREVIEW_LINES = 12    # max source lines shown per chunk before truncation
_DIVIDER_W    = 62     # character width of dividers


def _type_colour(chunk_type: str) -> str:
    return _TYPE_COLOURS.get(chunk_type, FG)


def _thick_divider(chunk_type: str) -> str:
    label = f" {chunk_type} "
    pad = "━" * max(2, (_DIVIDER_W - len(label)) // 2)
    return f"{pad}{label}{pad}"


def _thin_divider() -> str:
    return "─" * _DIVIDER_W


def _bottom_divider() -> str:
    return "═" * _DIVIDER_W


class ChunkViewerWindow(tk.Toplevel):
    """
    Floating window that streams chunk blocks as they arrive.

    Usage from the GUI:
        viewer = ChunkViewerWindow(parent)
        # pass viewer.feed as on_chunk to ingest()
        ingest(..., on_chunk=viewer.feed)
    """

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("Chunk Stream Viewer")
        self.configure(bg=BG2)
        self.minsize(700, 500)

        self._queue: queue.Queue = queue.Queue()
        self._chunk_count = 0
        self._log_lines: list[str] = []   # plain text for save-to-file

        self._build_ui()
        self._poll()

        # Position to the right of the parent window
        self.update_idletasks()
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            self.geometry(f"740x620+{px + pw + 12}+{py}")
        except Exception:
            self.geometry("740x620")

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG3, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  Chunk Stream", bg=BG3, fg=ACCENT,
                 font=("Segoe UI Semibold", 12)).pack(side="left", padx=14)
        self._counter_var = tk.StringVar(value="0 chunks")
        tk.Label(hdr, textvariable=self._counter_var,
                 bg=BG3, fg=FG_DIM,
                 font=("Consolas", 9)).pack(side="left", padx=8)

        # Save button
        tk.Button(hdr, text="💾  Save Log",
                  command=self._save_log,
                  bg=BG3, fg=FG_DIM, relief="flat",
                  font=("Segoe UI", 9), cursor="hand2",
                  activebackground=BG2,
                  ).pack(side="right", padx=10)

        tk.Button(hdr, text="🗑  Clear",
                  command=self._clear,
                  bg=BG3, fg=FG_DIM, relief="flat",
                  font=("Segoe UI", 9), cursor="hand2",
                  activebackground=BG2,
                  ).pack(side="right", padx=4)

        # Text widget
        self._text = scrolledtext.ScrolledText(
            self, bg=BG, fg=FG,
            font=("Consolas", 9),
            relief="flat", wrap="none",
            state="disabled",
        )
        self._text.pack(fill="both", expand=True, padx=6, pady=(4, 6))

        # Configure tags
        t = self._text
        t.tag_config("divider_top", foreground=FG_DIM)
        t.tag_config("location",    foreground=ACCENT,  font=("Consolas", 9, "bold"))
        t.tag_config("meta",        foreground=FG_DIM)
        t.tag_config("separator",   foreground=BG3)
        t.tag_config("code",        foreground=FG)
        t.tag_config("truncated",   foreground=FG_DIM,  font=("Consolas", 9, "italic"))
        t.tag_config("divider_bot", foreground=BG3)
        t.tag_config("spacer",      foreground=BG)

        # Type-specific header colours
        for ctype, colour in _TYPE_COLOURS.items():
            t.tag_config(f"type_{ctype}", foreground=colour,
                         font=("Consolas", 9, "bold"))

    # ── Public API ────────────────────────────────────────────────────────────

    def feed(self, source, chunk, chunk_id: str, index: int, total: int):
        """
        Thread-safe entry point.  Call this as the on_chunk callback from ingest().
        source: SourceFile, chunk: Chunk — same objects the pipeline uses.
        """
        self._queue.put((source, chunk, chunk_id, index, total))

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                source, chunk, chunk_id, index, total = self._queue.get_nowait()
                self._render_chunk(source, chunk, chunk_id, index, total)
        except queue.Empty:
            pass
        self.after(40, self._poll)

    def _render_chunk(self, source, chunk, chunk_id: str, index: int, total: int):
        self._chunk_count += 1
        self._counter_var.set(f"{self._chunk_count} chunk{'s' if self._chunk_count != 1 else ''}")

        t = self._text
        t.configure(state="normal")

        ctype = chunk.chunk_type
        colour_tag = f"type_{ctype}" if ctype in _TYPE_COLOURS else "code"

        # ── Header line ───────────────────────────────────────────────────
        top = _thick_divider(ctype)
        self._write(t, top + "\n", colour_tag)

        # ── Location breadcrumb ───────────────────────────────────────────
        prefix = chunk.context_prefix if hasattr(chunk, "context_prefix") else ""
        if not prefix:
            # Build it from heading_path if context_prefix not set yet
            from .utils import build_context_prefix
            prefix = build_context_prefix(chunk.heading_path)
        if prefix:
            self._write(t, f"  {prefix}\n", "location")

        # ── Meta line ─────────────────────────────────────────────────────
        line_start = chunk.line_start + 1   # 1-indexed for display
        line_end   = chunk.line_end + 1
        from .utils import estimate_tokens
        tokens = estimate_tokens(chunk.text)
        meta = f"  lines {line_start}–{line_end}  │  {tokens} tokens  │  chunk {index + 1} of {total}"
        self._write(t, meta + "\n", "meta")

        # ── Thin divider then source text ─────────────────────────────────
        self._write(t, _thin_divider() + "\n", "separator")

        lines = chunk.text.splitlines()
        if len(lines) <= _PREVIEW_LINES:
            self._write(t, chunk.text + "\n", "code")
        else:
            preview = "\n".join(lines[:_PREVIEW_LINES])
            self._write(t, preview + "\n", "code")
            remaining = len(lines) - _PREVIEW_LINES
            self._write(t, f"  … {remaining} more line{'s' if remaining != 1 else ''} (scroll log to see full text)\n", "truncated")

        # ── Bottom divider + blank line ───────────────────────────────────
        self._write(t, _bottom_divider() + "\n", "divider_bot")
        self._write(t, "\n", "spacer")

        t.see("end")
        t.configure(state="disabled")

        # Accumulate plain text for save-to-file
        self._log_lines.append(top)
        if prefix:
            self._log_lines.append(f"  {prefix}")
        self._log_lines.append(meta)
        self._log_lines.append(_thin_divider())
        self._log_lines.append(chunk.text)
        self._log_lines.append(_bottom_divider())
        self._log_lines.append("")

    def _write(self, widget, text: str, tag: str):
        widget.insert("end", text, tag)

    # ── Controls ──────────────────────────────────────────────────────────────

    def _clear(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
        self._log_lines.clear()
        self._chunk_count = 0
        self._counter_var.set("0 chunks")

    def _save_log(self):
        if not self._log_lines:
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save chunk log as…",
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
            initialfile="chunk_stream.txt",
        )
        if not path:
            return
        try:
            Path(path).write_text("\n".join(self._log_lines), encoding="utf-8")
        except Exception as e:
            tk.messagebox.showerror("Save failed", str(e), parent=self)
