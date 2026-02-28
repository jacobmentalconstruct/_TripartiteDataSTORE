"""
tripartite/explorer.py — Hierarchy Explorer Panel

Auto-detecting tree explorer for the Tripartite structural layer.
Reads tree_nodes + chunk_manifest to reconstruct the full hierarchy
and presents it as a navigable tree with right-click context menus.

Display modes (auto-detected from source_type distribution):
  - Project  : directory → files → functions/classes/sections
  - Document : document → sections/headings → paragraphs
  - Outline  : single file → AST / heading structure

Context menu actions adapt by node type.

v0.3.1 — Fixed JOIN bug (cm.node_id, not tn.chunk_id), removed empty flat
  mode, added virtual_file and compound_summary node types, always shows
  chunk-level structure even for single files.
"""

from __future__ import annotations

import json, os, platform, sqlite3, subprocess, sys, threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import tkinter as tk
from tkinter import ttk

try:
    from .studio import (
        BG, BG2, BG3, SIDEBAR, ACCENT, ACCENT2, ACCENT3,
        FG, FG_DIM, SUCCESS, WARNING, ERROR,
        FONT_UI, FONT_SM, FONT_H, FONT_MONO, FONT_TINY,
    )
except ImportError:
    BG = "#1e1e2e"; BG2 = "#2a2a3e"; BG3 = "#13131f"
    SIDEBAR = "#16162a"; ACCENT = "#7c6af7"; ACCENT2 = "#5de4c7"
    ACCENT3 = "#f5c542"; FG = "#cdd6f4"; FG_DIM = "#6e6c8e"
    SUCCESS = "#a6e3a1"; WARNING = "#f9e2af"; ERROR = "#f38ba8"
    FONT_UI = ("Segoe UI", 10); FONT_SM = ("Segoe UI", 9)
    FONT_H = ("Segoe UI Semibold", 11); FONT_MONO = ("Consolas", 9)
    FONT_TINY = ("Consolas", 8)

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


@dataclass
class TreeItem:
    node_id: str; node_type: str; name: str; parent_id: Optional[str]
    path: str; depth: int; file_cid: Optional[str]
    line_start: Optional[int]; line_end: Optional[int]
    language_tier: str; chunk_id: Optional[str]
    token_count: int = 0; embed_status: str = ""
    semantic_depth: int = 0; structural_depth: int = 0
    context_prefix: str = ""
    children: list["TreeItem"] = field(default_factory=list)


class HierarchyExplorer(tk.Frame):
    """
    Self-contained hierarchy explorer widget.
    on_select(node_id, chunk_id, file_cid) fires on click.
    on_tool_request(TreeItem) fires from right-click → Run Tool.
    """

    def __init__(self, parent, conn, source_root=None,
                 on_select=None, on_tool_request=None, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.conn = conn
        self.source_root = source_root
        self.on_select = on_select
        self.on_tool_request = on_tool_request
        self.mode = self._detect_mode()
        self._build_ui()
        self._setup_styles()
        self._load_tree()

    # ── Mode detection ────────────────────────────────────────────────────

    def _detect_mode(self) -> str:
        rows = self.conn.execute(
            "SELECT source_type, COUNT(*) as n FROM source_files "
            "GROUP BY source_type ORDER BY n DESC"
        ).fetchall()
        if not rows:
            return "outline"

        type_counts = {r[0]: r[1] for r in rows}
        total = sum(type_counts.values())

        vf_count = self.conn.execute(
            "SELECT COUNT(*) FROM tree_nodes WHERE node_type = 'virtual_file'"
        ).fetchone()[0]
        if vf_count > 0:
            return "project"
        if total > 1:
            return "project"

        dominant = rows[0][0]
        if dominant in ("prose", "markdown", "text"):
            return "document"
        return "outline"

    # ── UI ────────────────────────────────────────────────────────────────

    def _setup_styles(self):
        style = ttk.Style()
        style.configure("Explorer.Treeview", background=BG2, foreground=FG,
                         fieldbackground=BG2, borderwidth=0, font=FONT_SM,
                         rowheight=22)
        style.map("Explorer.Treeview",
                   background=[("selected", ACCENT)],
                   foreground=[("selected", "white")])
        style.configure("Explorer.Treeview.Heading", background=BG3,
                         foreground=FG_DIM, font=FONT_TINY)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        tk.Label(header, text=f"Explorer  ·  {self.mode.title()} mode",
                 bg=BG, fg=FG_DIM, font=FONT_TINY).pack(side="left")
        tk.Button(header, text="▶ Expand All", command=self._expand_all,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_TINY,
                  cursor="hand2", padx=6, pady=1).pack(side="right", padx=2)
        tk.Button(header, text="◀ Collapse", command=self._collapse_all,
                  bg=BG2, fg=FG_DIM, relief="flat", font=FONT_TINY,
                  cursor="hand2", padx=6, pady=1).pack(side="right", padx=2)

        tree_frame = tk.Frame(self, bg=BG)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            tree_frame, show="tree headings",
            columns=("type", "lines", "tokens", "status"),
            selectmode="browse", style="Explorer.Treeview")
        self.tree.heading("#0", text="Name", anchor="w")
        self.tree.heading("type", text="Type", anchor="w")
        self.tree.heading("lines", text="Lines", anchor="e")
        self.tree.heading("tokens", text="Tokens", anchor="e")
        self.tree.heading("status", text="Embed", anchor="center")
        self.tree.column("#0", width=320, minwidth=200)
        self.tree.column("type", width=100, minwidth=60)
        self.tree.column("lines", width=70, minwidth=50, anchor="e")
        self.tree.column("tokens", width=60, minwidth=40, anchor="e")
        self.tree.column("status", width=50, minwidth=40, anchor="center")

        ysb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Button-2>", self._on_right_click)

        self._status_var = tk.StringVar(value="Loading…")
        tk.Label(self, textvariable=self._status_var, bg=BG, fg=FG_DIM,
                 font=FONT_TINY, anchor="w"
                 ).grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 4))

        self._node_data: dict[str, TreeItem] = {}

    # ── Tree loading ──────────────────────────────────────────────────────

    def _load_tree(self):
        # ── CRITICAL JOIN FIX ─────────────────────────────────────────
        # JOIN on chunk_manifest.node_id = tree_nodes.node_id
        # (NOT tn.chunk_id which is often NULL)
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

        if not rows:
            self._status_var.set("No data — ingest something first")
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

        roots = []
        for item in items.values():
            if item.parent_id and item.parent_id in items:
                items[item.parent_id].children.append(item)
            else:
                roots.append(item)

        if self.mode == "project" and roots:
            roots = self._build_directory_tree(roots, items)

        self._sort_children(items, roots)

        for root in roots:
            self._insert_node(root, parent_iid="")

        self._auto_expand()

        file_count = sum(1 for i in items.values()
                         if i.node_type in ("file", "virtual_file"))
        chunk_count = sum(1 for i in items.values() if i.embed_status)
        embedded = sum(1 for i in items.values() if i.embed_status == "done")
        self._status_var.set(
            f"{file_count} files  ·  {chunk_count} chunks  ·  "
            f"{embedded} embedded  ·  {self.mode} mode")

    def _sort_children(self, items, roots):
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

    def _auto_expand(self):
        top = self.tree.get_children("")
        if self.mode == "outline":
            self._expand_all()
        elif self.mode == "document":
            for iid in top:
                self.tree.item(iid, open=True)
                for child in self.tree.get_children(iid):
                    self.tree.item(child, open=True)
        else:
            for iid in top:
                self.tree.item(iid, open=True)
                for child in self.tree.get_children(iid):
                    item = self._node_data.get(child)
                    if item and item.node_type in ("directory", "virtual_file"):
                        self.tree.item(child, open=True)

    def _build_directory_tree(self, file_nodes, all_items):
        file_map = {}; other_roots = []
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

        dir_nodes = {}; new_roots = []
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

    def _insert_node(self, item, parent_iid):
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
            self.tree.insert(
                parent_iid, "end", iid=item.node_id, text=display_name,
                values=(type_str, lines_str, tokens_str, status_str), open=False)
        except tk.TclError:
            return

        for child in item.children:
            self._insert_node(child, parent_iid=item.node_id)

    # ── Selection ─────────────────────────────────────────────────────────

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        item = self._node_data.get(sel[0])
        if item and self.on_select:
            self.on_select(item.node_id, item.chunk_id, item.file_cid)

    # ── Right-click context menu ──────────────────────────────────────────

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid: return
        self.tree.selection_set(iid)
        item = self._node_data.get(iid)
        if not item: return

        menu = tk.Menu(self, tearoff=0, bg=BG2, fg=FG, font=FONT_SM,
                       activebackground=ACCENT, activeforeground="white",
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
        if item.context_prefix:
            menu.add_command(label="📋  Copy Context Prefix",
                             command=lambda: self._copy_to_clipboard(item.context_prefix))

        if self.on_tool_request:
            menu.add_separator()
            menu.add_command(label="🔧  Run Tool on This…",
                             command=lambda: self.on_tool_request(item))

        menu.tk_popup(event.x_root, event.y_root)

    def _add_directory_menu(self, menu, item):
        d = item.path
        menu.add_command(label="📂  Open in File Explorer",
                         command=lambda: self._open_in_explorer(d))
        menu.add_command(label="💻  Open Terminal Here",
                         command=lambda: self._open_terminal(d))
        menu.add_command(label="🐍  Open Terminal + venv",
                         command=lambda: self._open_terminal_venv(d))
        menu.add_command(label="⚡  Open PowerShell Here",
                         command=lambda: self._open_powershell(d))

    def _add_file_menu(self, menu, item):
        fp = item.path; is_virtual = item.node_type == "virtual_file"
        if not is_virtual:
            menu.add_command(label="📝  Open in Default Editor",
                             command=lambda: self._open_file(fp))
            menu.add_command(label="📂  Open Containing Folder",
                             command=lambda: self._open_in_explorer(str(Path(fp).parent)))
            menu.add_command(label="💻  Open Terminal in Folder",
                             command=lambda: self._open_terminal(str(Path(fp).parent)))
            menu.add_command(label="🐍  Terminal + venv",
                             command=lambda: self._open_terminal_venv(str(Path(fp).parent)))
            menu.add_command(label="⚡  PowerShell in Folder",
                             command=lambda: self._open_powershell(str(Path(fp).parent)))
        if item.chunk_id:
            menu.add_separator()
            menu.add_command(label="📋  Copy Chunk Text",
                             command=lambda: self._copy_chunk_text(item.chunk_id))

    def _add_chunk_menu(self, menu, item):
        fp = self._resolve_file_path(item)
        if fp:
            menu.add_command(label=f"📝  Open File (L{item.line_start or '?'})",
                             command=lambda: self._open_file_at_line(fp, item.line_start))
        if item.chunk_id:
            menu.add_command(label="📋  Copy Chunk Text",
                             command=lambda: self._copy_chunk_text(item.chunk_id))
        if item.embed_status == "done":
            menu.add_command(label="🎯  Find Similar Chunks",
                             command=lambda: self._find_similar(item.chunk_id))

    # ── Shell actions ─────────────────────────────────────────────────────

    def _open_file(self, path):
        try:
            p = Path(path)
            if not p.exists():
                self._status_var.set(f"File not found: {path}"); return
            if platform.system() == "Windows": os.startfile(str(p))
            elif platform.system() == "Darwin": subprocess.Popen(["open", str(p)])
            else: subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            self._status_var.set(f"Could not open: {e}")

    def _open_file_at_line(self, path, line):
        try:
            p = Path(path)
            if not p.exists():
                self._status_var.set(f"File not found: {path}"); return
            la = f":{line}" if line else ""
            try:
                subprocess.Popen(["code", "--goto", f"{p}{la}"],
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                return
            except FileNotFoundError: pass
            self._open_file(path)
        except Exception as e:
            self._status_var.set(f"Could not open: {e}")

    def _open_in_explorer(self, path):
        try:
            p = Path(path)
            if not p.exists(): p = p.parent
            if platform.system() == "Windows": subprocess.Popen(["explorer", str(p)])
            elif platform.system() == "Darwin": subprocess.Popen(["open", str(p)])
            else: subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            self._status_var.set(f"Could not open explorer: {e}")

    def _open_terminal(self, path):
        try:
            p = Path(path)
            if not p.is_dir(): p = p.parent
            if platform.system() == "Windows":
                subprocess.Popen(["cmd", "/K", f"cd /d {p}"],
                    creationflags=subprocess.CREATE_NEW_CONSOLE)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", "Terminal", str(p)])
            else:
                subprocess.Popen(["x-terminal-emulator", f"--working-directory={p}"])
        except Exception as e:
            self._status_var.set(f"Could not open terminal: {e}")

    def _open_terminal_venv(self, path):
        try:
            p = Path(path)
            if not p.is_dir(): p = p.parent
            venv = self._find_venv(p)
            if platform.system() == "Windows":
                if venv:
                    act = venv / "Scripts" / "Activate.bat"
                    cmd = f'cd /d {p} && "{act}"'
                else:
                    cmd = f'cd /d {p} && echo No .venv found'
                subprocess.Popen(["cmd", "/K", cmd],
                    creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                if venv:
                    act = venv / "bin" / "activate"
                    cmd = f'cd "{p}" && source "{act}"'
                else:
                    cmd = f'cd "{p}" && echo "No .venv found"'
                subprocess.Popen(["bash", "-c",
                    f'exec bash --init-file <(echo "{cmd}")'])
        except Exception as e:
            self._status_var.set(f"Could not open terminal: {e}")

    def _open_powershell(self, path):
        try:
            p = Path(path)
            if not p.is_dir(): p = p.parent
            if platform.system() == "Windows":
                subprocess.Popen(["powershell", "-NoExit", "-Command",
                    f"Set-Location '{p}'"],
                    creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen(["pwsh", "-NoExit", "-Command",
                    f"Set-Location '{p}'"])
        except Exception as e:
            self._status_var.set(f"Could not open PowerShell: {e}")

    def _find_venv(self, start):
        current = start
        for _ in range(10):
            candidate = current / ".venv"
            if candidate.is_dir(): return candidate
            parent = current.parent
            if parent == current: break
            current = parent
        return None

    # ── Clipboard ─────────────────────────────────────────────────────────

    def _copy_to_clipboard(self, text):
        self.clipboard_clear(); self.clipboard_append(text)
        d = f"{text[:60]}…" if len(text) > 60 else text
        self._status_var.set(f"Copied: {d}")

    def _copy_chunk_text(self, chunk_id):
        try:
            from .db.query import reconstruct_chunk_text
            text = reconstruct_chunk_text(self.conn, chunk_id)
            if text: self._copy_to_clipboard(text)
            else: self._status_var.set("No text found for this chunk")
        except Exception as e:
            self._status_var.set(f"Error: {e}")

    def _find_similar(self, chunk_id):
        self._status_var.set(f"Find similar: {chunk_id[:20]}… (wire to Search panel)")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _resolve_file_path(self, item):
        if item.node_type in ("file", "virtual_file"): return item.path
        if item.parent_id and item.parent_id in self._node_data:
            return self._resolve_file_path(self._node_data[item.parent_id])
        if item.file_cid:
            row = self.conn.execute(
                "SELECT path FROM source_files WHERE file_cid = ?",
                (item.file_cid,)).fetchone()
            if row: return row[0]
        return None

    def _expand_all(self):
        def _ex(iid):
            self.tree.item(iid, open=True)
            for c in self.tree.get_children(iid): _ex(c)
        for r in self.tree.get_children(""): _ex(r)

    def _collapse_all(self):
        def _col(iid):
            for c in self.tree.get_children(iid): _col(c)
            self.tree.item(iid, open=False)
        for r in self.tree.get_children(""):
            _col(r); self.tree.item(r, open=True)

    def refresh(self):
        for item in self.tree.get_children(""): self.tree.delete(item)
        self._node_data.clear()
        self.mode = self._detect_mode()
        self._load_tree()
