"""
src/components/viewer.py

ViewerPanel and ViewerStack — the central content viewer for the
Tripartite DataSTORE GUI. Displays node content with version scrubbing,
diff mode, and file reconstruction capabilities.

Extracted from the monolithic datastore.py (hunks 03 + 04).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Optional

from ..gui_constants import (
    BG, BG2, FG, FG_DIM, ACCENT, FONT_MONO, FONT_XS, FONT_MONO,
    NODE_ICONS, SUCCESS, ERROR,
)
from ..models.tree_item import TreeItem
from ..db.query import reconstruct_file_from_db, reconstruct_lines


class ViewerPanel(tk.Frame):
    """
    Content viewer for a single node at any granularity.

    Header: [icon] name | type | v3 [< >] | [Diff] [->Patch] [Split] [x]
    Body:   Read-only Text widget (diff-colored in diff mode).
    """

    def __init__(self, parent, stack: "ViewerStack", **kw):
        super().__init__(parent, bg=BG, **kw)
        self.stack = stack
        self._node: Optional[TreeItem] = None
        self._content: str = ""
        self._version: Optional[int] = None
        self._diff_mode: bool = False

        self._build()

    def _build(self):
        # ── Header bar ────────────────────────────────────────────────
        header = tk.Frame(self, bg=BG2)
        header.pack(fill="x")

        self._icon_label = tk.Label(header, text="", bg=BG2, fg=FG,
                                     font=FONT_MONO)
        self._icon_label.pack(side="left", padx=(6, 2))
        self._name_label = tk.Label(header, text="(empty)", bg=BG2, fg=FG,
                                     font=("Segoe UI Semibold", 9), anchor="w")
        self._name_label.pack(side="left", padx=2)
        self._type_label = tk.Label(header, text="", bg=BG2, fg=FG_DIM,
                                     font=FONT_XS, anchor="w")
        self._type_label.pack(side="left", padx=4)

        # Version scrub
        self._ver_label = tk.Label(header, text="", bg=BG2, fg=ACCENT,
                                    font=FONT_XS, anchor="w")
        self._ver_label.pack(side="left", padx=4)
        tk.Button(header, text="\u25c0", command=self._prev_version,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  width=2, cursor="hand2").pack(side="left")
        tk.Button(header, text="\u25b6", command=self._next_version,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  width=2, cursor="hand2").pack(side="left")

        # Right-side buttons
        tk.Button(header, text="\u2715", command=self._request_close,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  width=2, cursor="hand2").pack(side="right", padx=2)
        tk.Button(header, text="\u2193Split", command=self._request_split,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  cursor="hand2", padx=4).pack(side="right", padx=2)
        tk.Button(header, text="\u2192Patch", command=self._send_to_patch,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  cursor="hand2", padx=4).pack(side="right", padx=2)
        tk.Button(header, text="Diff", command=self._toggle_diff_mode,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_XS,
                  cursor="hand2", padx=4).pack(side="right", padx=2)

        # ── Content area ──────────────────────────────────────────────
        text_frame = tk.Frame(self, bg=BG)
        text_frame.pack(fill="both", expand=True)

        self._text = tk.Text(text_frame, bg=BG, fg=FG, font=FONT_MONO,
                              borderwidth=0, wrap="none", state="disabled",
                              insertbackground=FG)
        ysb = ttk.Scrollbar(text_frame, orient="vertical",
                             command=self._text.yview)
        xsb = ttk.Scrollbar(text_frame, orient="horizontal",
                             command=self._text.xview)
        self._text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        self._text.pack(side="left", fill="both", expand=True)

        # Diff highlighting tags
        self._text.tag_configure("added", background="#2d4a2d")
        self._text.tag_configure("removed", background="#4a2d2d")
        self._text.tag_configure("changed", background="#4a4a2d")
        self._text.tag_configure("hunk_header", foreground=ACCENT)

        # Show placeholder on initial load
        self._show_empty_placeholder()

    # ── Public API ────────────────────────────────────────────────────

    def load_node(self, item: TreeItem):
        """Determine content type from node_type and load accordingly."""
        self._node = item
        icon = NODE_ICONS.get(item.node_type, "\u25aa")
        self._icon_label.configure(text=icon)
        self._name_label.configure(text=item.name)
        self._type_label.configure(text=item.node_type)
        self._diff_mode = False

        if item.node_type == "directory":
            self._load_directory_listing(item)
        elif item.node_type in ("file", "virtual_file"):
            self._load_file_content(item)
        else:
            self._load_chunk_content(item)

    def clear(self):
        """Reset to empty state with visible placeholder."""
        self._node = None
        self._content = ""
        self._version = None
        self._icon_label.configure(text="")
        self._name_label.configure(text="(empty)")
        self._type_label.configure(text="")
        self._ver_label.configure(text="")
        self._show_empty_placeholder()

    def _show_empty_placeholder(self):
        """Show a centered placeholder when no content is loaded."""
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        placeholder = (
            "\n\n\n"
            "              Select a node in the Explorer\n"
            "              to view its content here.\n\n"
            "              Or right-click a node and choose\n"
            "              'View' or 'View in New Panel'."
        )
        self._text.insert("1.0", placeholder)
        self._text.tag_add("placeholder", "1.0", "end")
        self._text.tag_configure("placeholder", foreground=FG_DIM,
                                  font=("Segoe UI", 10, "italic"),
                                  justify="center")
        self._text.configure(state="disabled")

    # ── Content loaders ───────────────────────────────────────────────

    def _load_file_content(self, item: TreeItem):
        """Load file content from DiffEngine HEAD, DB, or disk."""
        app = self.stack.app
        content = None

        # Try DiffEngine HEAD first
        if app.diff_engine and item.path:
            head = app.diff_engine.get_head(item.path)
            if head:
                content = head.content
                self._version = head.version
                self._ver_label.configure(text=f"v{head.version}")

        # Fall back to reconstructing from verbatim DB
        if content is None and app.conn and item.file_cid:
            content = reconstruct_file_from_db(app.conn, item.file_cid)

        # Fall back to disk
        if content is None and item.path:
            try:
                fp = Path(item.path)
                if fp.exists():
                    content = fp.read_text(encoding="utf-8")
            except Exception as e:
                app._log("Viewer", f"File read failed: {e}", "error")

        if content is None:
            content = "(content not available)"

        # Large file guard (HITL)
        line_count = content.count('\n')
        if line_count > 5000:
            if not app.hitl.confirm(
                    "Large File",
                    f"This file is {line_count:,} lines. Loading may be slow.",
                    details="Load first 1000 lines with pagination instead?"):
                content = "\n".join(content.split("\n")[:1000])
                content += f"\n\n... [{line_count - 1000} more lines] ..."

        self._content = content
        self._display_content(content)

    def _load_chunk_content(self, item: TreeItem):
        """Load single chunk content from chunk_manifest."""
        app = self.stack.app
        content = None

        if app.conn and item.chunk_id:
            try:
                row = app.conn.execute(
                    "SELECT context_prefix, cm.chunk_type, "
                    "GROUP_CONCAT(vl.content, char(10)) as text "
                    "FROM chunk_manifest cm "
                    "JOIN json_each(cm.spans) je "
                    "JOIN verbatim_lines vl ON vl.line_cid = json_extract(je.value, '$.line_cid') "
                    "WHERE cm.chunk_id = ? "
                    "ORDER BY CAST(json_extract(je.value, '$.line_num') AS INTEGER)",
                    (item.chunk_id,)
                ).fetchone()
                if row and row[2]:
                    content = row[2]
            except Exception as e:
                app._log("Viewer", f"Chunk load failed: {e}", "error")

        # Fallback: try line range from source file
        if content is None and app.conn and item.file_cid and item.line_start is not None:
            content = reconstruct_lines(
                app.conn, item.file_cid, item.line_start, item.line_end)

        self._version = None
        self._ver_label.configure(text="")
        self._content = content or "(no content)"
        self._display_content(self._content)

    def _load_directory_listing(self, item: TreeItem):
        """List children of a directory node."""
        app = self.stack.app
        if not app.conn:
            self._display_content("(no database connected)")
            return

        rows = []
        try:
            rows = app.conn.execute(
                "SELECT node_type, name, language_tier "
                "FROM tree_nodes WHERE parent_id = ? ORDER BY name",
                (item.node_id,)
            ).fetchall()
            lines = [f"{NODE_ICONS.get(r[0], '\u25aa')} {r[1]}  [{r[2]}]" for r in rows]
            content = f"Directory: {item.name}\n{'\u2500' * 40}\n" + "\n".join(lines)
        except Exception as e:
            app._log("Viewer", f"Directory listing failed: {e}", "error")
            content = "(could not list directory)"

        self._content = content
        self._version = None
        self._ver_label.configure(text=f"{len(rows)} items")
        self._display_content(content)

    # ── Version scrubbing ─────────────────────────────────────────────

    def _prev_version(self):
        app = self.stack.app
        if not app.diff_engine or not self._node or self._version is None:
            return
        if self._version <= 1:
            return
        target = self._version - 1
        content = app.diff_engine.reconstruct_at_version(
            self._node.path, target)
        if content is not None:
            self._version = target
            self._content = content
            self._ver_label.configure(text=f"v{target}")
            self._display_content(content)

    def _next_version(self):
        app = self.stack.app
        if not app.diff_engine or not self._node or self._version is None:
            return
        head = app.diff_engine.get_head(self._node.path)
        if not head or self._version >= head.version:
            return
        target = self._version + 1
        content = app.diff_engine.reconstruct_at_version(
            self._node.path, target)
        if content is not None:
            self._version = target
            self._content = content
            self._ver_label.configure(text=f"v{target}")
            self._display_content(content)

    # ── Diff mode ─────────────────────────────────────────────────────

    def _toggle_diff_mode(self):
        app = self.stack.app
        if not app.diff_engine or not self._node or self._version is None:
            return
        self._diff_mode = not self._diff_mode
        if self._diff_mode and self._version > 1:
            diff = app.diff_engine.get_diff_between(
                self._node.path, self._version - 1, self._version)
            if diff:
                self._display_diff(diff)
                return
        self._diff_mode = False
        self._display_content(self._content)

    def _display_diff(self, diff_text: str):
        """Render a unified diff with colored tags."""
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        for line in diff_text.splitlines(keepends=True):
            if line.startswith("@@"):
                self._text.insert("end", line, "hunk_header")
            elif line.startswith("+"):
                self._text.insert("end", line, "added")
            elif line.startswith("-"):
                self._text.insert("end", line, "removed")
            else:
                self._text.insert("end", line)
        self._text.configure(state="disabled")

    # ── Actions ───────────────────────────────────────────────────────

    def _send_to_patch(self):
        """Copy current content to the Patch tab's source editor."""
        if not self._content:
            return
        app = self.stack.app
        app._patch_source.delete("1.0", "end")
        app._patch_source.insert("1.0", self._content)
        app._patch_current_path = self._node.path if self._node else None
        app._patch_file_label.configure(
            text=self._node.name if self._node else "from viewer")
        # Switch to Patch tab
        app.work_tabs.select(4)
        app._log("Viewer", f"Sent to Patch: {self._node.name if self._node else 'content'}", "dim")

    def _request_split(self):
        self.stack.add_panel()

    def _request_close(self):
        self.stack.remove_panel(self)

    # ── Display helper ────────────────────────────────────────────────

    def _display_content(self, text: str):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("1.0", text)
        self._text.configure(state="disabled")


class ViewerStack(tk.Frame):
    """Vertical stack of ViewerPanels. Splittable, closeable."""

    def __init__(self, parent, app, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.app = app
        self.panels: list[ViewerPanel] = []

        from ..gui_constants import BORDER
        self._paned = tk.PanedWindow(self, orient=tk.VERTICAL,
                                      bg=BORDER, sashwidth=2)
        self._paned.pack(fill="both", expand=True)

        # Start with one empty panel
        self.add_panel()

    def add_panel(self) -> ViewerPanel:
        panel = ViewerPanel(self._paned, stack=self)
        self._paned.add(panel, minsize=100)
        self.panels.append(panel)
        return panel

    def remove_panel(self, panel: ViewerPanel):
        if len(self.panels) <= 1:
            panel.clear()
            return
        self._paned.forget(panel)
        self.panels.remove(panel)
        panel.destroy()

    def open_node(self, item: TreeItem, new_panel: bool = False):
        if new_panel or not self.panels:
            panel = self.add_panel()
        else:
            panel = self.panels[0]
        panel.load_node(item)
