"""
src/viewer.py

Tkinter viewer/query app for exploring a Tripartite knowledge store.

Three panels:
  - Browse: File tree → Chunks → Detail
  - Search: Text query → Hybrid search results → Detail
  - Graph: Entity list → Chunks mentioning entity → Detail

Usage:
    python -m src.viewer
    python -m src.viewer --db path/to/store.db
"""

import argparse
import sqlite3
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

from .db import query

# ── Color Palette (matches gui.py) ────────────────────────────────────────────
BG       = "#1e1e2e"
BG2      = "#2a2a3e"
BG3      = "#13131f"
ACCENT   = "#7c6af7"
ACCENT2  = "#5de4c7"
FG       = "#cdd6f4"
FG_DIM   = "#6e6c8e"
SUCCESS  = "#a6e3a1"
ERROR    = "#f38ba8"
FONT_UI  = ("Segoe UI", 10)
FONT_SM  = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 9)
FONT_H   = ("Segoe UI Semibold", 11)


class TripartiteViewer(tk.Tk):
    """Main viewer window."""
    
    def __init__(self, db_path: Path):
        super().__init__()
        self.title(f"Tripartite Viewer — {db_path.name}")
        self.configure(bg=BG)
        self.minsize(1000, 700)
        
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._embedder = None
        self._embedder_failed = False
        
        # Connect to database
        try:
            self.conn = sqlite3.connect(str(db_path))
            self.stats = query.get_db_stats(self.conn)
        except Exception as e:
            messagebox.showerror("Database Error", f"Could not open database:\n{e}")
            sys.exit(1)
        
        self._build_ui()
        self._load_initial_data()
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Center on screen
        self.update_idletasks()
        w, h = 1200, 800
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
    
    # ── UI Construction ───────────────────────────────────────────────────────
    
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG2, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  Tripartite Viewer",
                 bg=BG2, fg=ACCENT, font=("Segoe UI Semibold", 14)
                 ).pack(side="left", padx=16)
        tk.Label(hdr, text=f"{self.db_path.name}",
                 bg=BG2, fg=FG_DIM, font=FONT_UI
                 ).pack(side="left")
        
        # Export button
        tk.Button(hdr, text="📤 Export",
                 command=self._show_export_dialog,
                 bg=BG2, fg=FG, relief="flat", font=FONT_UI,
                 cursor="hand2", padx=12, pady=4,
                 activebackground="#3a3a5e"
                 ).pack(side="right", padx=(0, 8))
        
        # Exit button
        tk.Button(hdr, text="✕ Exit",
                 command=self._on_close,
                 bg=BG2, fg=FG_DIM, relief="flat", font=FONT_UI,
                 cursor="hand2", padx=12, pady=4,
                 activebackground="#3a3a5e"
                 ).pack(side="right", padx=12)
        
        # Main content: three-panel layout (top) + detail panel (bottom)
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=8, pady=8)
        
        # Top: three panels side by side
        top_pane = tk.Frame(main, bg=BG)
        top_pane.pack(fill="both", expand=True, pady=(0, 8))
        
        # Browse Panel (left)
        browse_frame = tk.LabelFrame(top_pane, text=" Browse ", bg=BG, fg=FG_DIM,
                                     font=FONT_UI, bd=1, relief="flat")
        browse_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self._build_browse_panel(browse_frame)
        
        # Search Panel (middle)
        search_frame = tk.LabelFrame(top_pane, text=" Search ", bg=BG, fg=FG_DIM,
                                     font=FONT_UI, bd=1, relief="flat")
        search_frame.pack(side="left", fill="both", expand=True, padx=4)
        self._build_search_panel(search_frame)
        
        # Graph Panel (right)
        graph_frame = tk.LabelFrame(top_pane, text=" Graph ", bg=BG, fg=FG_DIM,
                                    font=FONT_UI, bd=1, relief="flat")
        graph_frame.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self._build_graph_panel(graph_frame)
        
        # Bottom: Chunk Detail Panel
        detail_frame = tk.LabelFrame(main, text=" Chunk Detail ", bg=BG, fg=FG_DIM,
                                     font=FONT_UI, bd=1, relief="flat")
        detail_frame.pack(fill="both", expand=True)
        self._build_detail_panel(detail_frame)
        
        # Status bar
        status = tk.Frame(self, bg=BG2, pady=4)
        status.pack(fill="x", side="bottom")
        
        stats_text = (
            f"Files: {self.stats['files']}  │  "
            f"Chunks: {self.stats['chunks']}  │  "
            f"Embeddings: {self.stats['embeddings']}  │  "
            f"Entities: {self.stats['entities']}"
        )
        tk.Label(status, text=stats_text, bg=BG2, fg=FG_DIM, font=FONT_SM
                 ).pack(side="left", padx=12)
    
    def _build_browse_panel(self, parent):
        """File tree → Chunks list."""
        # Files treeview
        tk.Label(parent, text="Files", bg=BG, fg=FG, font=FONT_SM
                 ).pack(anchor="w", padx=8, pady=(4, 2))
        
        files_frame = tk.Frame(parent, bg=BG)
        files_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        
        scrollbar = tk.Scrollbar(files_frame, bg=BG2)
        scrollbar.pack(side="right", fill="y")
        
        self.files_tree = ttk.Treeview(files_frame, show="tree", 
                                       yscrollcommand=scrollbar.set, height=8)
        self.files_tree.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.files_tree.yview)
        
        self.files_tree.bind("<<TreeviewSelect>>", self._on_file_select)
        
        # Chunks listbox
        tk.Label(parent, text="Chunks", bg=BG, fg=FG, font=FONT_SM
                 ).pack(anchor="w", padx=8, pady=(8, 2))
        
        chunks_frame = tk.Frame(parent, bg=BG)
        chunks_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        
        scrollbar2 = tk.Scrollbar(chunks_frame, bg=BG2)
        scrollbar2.pack(side="right", fill="y")
        
        self.chunks_list = tk.Listbox(chunks_frame, bg=BG2, fg=FG,
                                      selectbackground=ACCENT, selectforeground="white",
                                      font=FONT_SM, relief="flat",
                                      yscrollcommand=scrollbar2.set)
        self.chunks_list.pack(side="left", fill="both", expand=True)
        scrollbar2.config(command=self.chunks_list.yview)
        
        self.chunks_list.bind("<<ListboxSelect>>", self._on_chunk_select)
        
        # Store chunk_id for each listbox item
        self.chunks_data = []
    
    def _build_search_panel(self, parent):
        """Search box → Results list."""
        # Search input
        search_input_frame = tk.Frame(parent, bg=BG)
        search_input_frame.pack(fill="x", padx=8, pady=8)
        
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(search_input_frame, textvariable=self.search_var,
                               bg=BG2, fg=FG, insertbackground=FG, relief="flat",
                               font=FONT_UI)
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        search_entry.bind("<Return>", lambda e: self._run_search())
        
        tk.Button(search_input_frame, text="🔍 Search",
                 command=self._run_search,
                 bg=ACCENT, fg="white", relief="flat", font=FONT_SM,
                 cursor="hand2", padx=12, pady=4,
                 activebackground="#6a5ae0"
                 ).pack(side="right")
        
        # Search status
        self.search_status = tk.Label(parent, text="Enter query and press Search",
                                      bg=BG, fg=FG_DIM, font=FONT_SM)
        self.search_status.pack(anchor="w", padx=8, pady=(0, 4))
        
        # Results listbox
        results_frame = tk.Frame(parent, bg=BG)
        results_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        
        scrollbar = tk.Scrollbar(results_frame, bg=BG2)
        scrollbar.pack(side="right", fill="y")
        
        self.search_results = tk.Listbox(results_frame, bg=BG2, fg=FG,
                                        selectbackground=ACCENT, selectforeground="white",
                                        font=FONT_SM, relief="flat",
                                        yscrollcommand=scrollbar.set)
        self.search_results.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.search_results.yview)
        
        self.search_results.bind("<<ListboxSelect>>", self._on_search_result_select)
        
        # Store search result data
        self.search_data = []
    
    def _build_graph_panel(self, parent):
        """Entity filter → Entity list → Chunks."""
        # Entity type filter
        filter_frame = tk.Frame(parent, bg=BG)
        filter_frame.pack(fill="x", padx=8, pady=8)
        
        tk.Label(filter_frame, text="Type:", bg=BG, fg=FG_DIM, font=FONT_SM
                 ).pack(side="left", padx=(0, 4))
        
        # Get entity types
        entity_types = ["All"] + query.get_entity_types(self.conn)
        
        self.entity_type_var = tk.StringVar(value="All")
        entity_combo = ttk.Combobox(filter_frame, textvariable=self.entity_type_var,
                                   values=entity_types, state="readonly", width=12,
                                   font=FONT_SM)
        entity_combo.pack(side="left", fill="x", expand=True)
        entity_combo.bind("<<ComboboxSelected>>", lambda e: self._load_entities())
        
        # Entity list
        tk.Label(parent, text="Entities", bg=BG, fg=FG, font=FONT_SM
                 ).pack(anchor="w", padx=8, pady=(4, 2))
        
        entities_frame = tk.Frame(parent, bg=BG)
        entities_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        
        scrollbar = tk.Scrollbar(entities_frame, bg=BG2)
        scrollbar.pack(side="right", fill="y")
        
        self.entities_list = tk.Listbox(entities_frame, bg=BG2, fg=FG,
                                       selectbackground=ACCENT, selectforeground="white",
                                       font=FONT_SM, relief="flat",
                                       yscrollcommand=scrollbar.set)
        self.entities_list.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.entities_list.yview)
        
        self.entities_list.bind("<<ListboxSelect>>", self._on_entity_select)
        
        # Store entity data
        self.entities_data = []
    
    def _build_detail_panel(self, parent):
        """Shared chunk detail view."""
        # Toolbar
        toolbar = tk.Frame(parent, bg=BG)
        toolbar.pack(fill="x", padx=8, pady=4)
        
        self.detail_label = tk.Label(toolbar, text="Select a chunk to view details",
                                     bg=BG, fg=FG_DIM, font=FONT_SM)
        self.detail_label.pack(side="left")
        
        tk.Button(toolbar, text="📋 Copy Text",
                 command=self._copy_chunk_text,
                 bg=BG2, fg=FG, relief="flat", font=FONT_SM,
                 cursor="hand2", padx=8, pady=2,
                 activebackground="#3a3a5e"
                 ).pack(side="right")
        
        # Text widget
        text_frame = tk.Frame(parent, bg=BG)
        text_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        
        scrollbar = tk.Scrollbar(text_frame, bg=BG2)
        scrollbar.pack(side="right", fill="y")
        
        self.detail_text = scrolledtext.ScrolledText(
            text_frame, bg=BG3, fg=FG, font=FONT_MONO,
            relief="flat", wrap="word", state="disabled",
            yscrollcommand=scrollbar.set
        )
        self.detail_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.detail_text.yview)
        
        # Text tags for formatting
        self.detail_text.tag_config("heading", foreground=ACCENT, font=("Segoe UI Semibold", 10))
        self.detail_text.tag_config("dim", foreground=FG_DIM)
        self.detail_text.tag_config("accent", foreground=ACCENT2)
        self.detail_text.tag_config("error", foreground=ERROR)
        
        self.current_chunk_text = ""  # For copy function
    
    # ── Data Loading ──────────────────────────────────────────────────────────
    
    def _load_initial_data(self):
        """Load files tree and entities on startup."""
        self._load_files()
        self._load_entities()
    
    def _load_files(self):
        """Populate files treeview."""
        files = query.list_source_files(self.conn)
        
        # Clear tree
        for item in self.files_tree.get_children():
            self.files_tree.delete(item)
        
        # Add files
        for f in files:
            display = f"{f['name']}  ({f['line_count']} lines, {f['source_type']})"
            self.files_tree.insert("", "end", text=display, values=(f["file_cid"],))
    
    def _load_entities(self):
        """Populate entities list based on current filter."""
        entity_type = self.entity_type_var.get()
        filter_val = None if entity_type == "All" else entity_type
        
        entities = query.list_entities(self.conn, filter_val)
        
        # Clear list
        self.entities_list.delete(0, tk.END)
        self.entities_data = []
        
        # Add entities
        for e in entities:
            salience = e.get("salience", 0.0) or 0.0
            display = f"{e['label']}  ({e['entity_type']}, {salience:.2f})"
            self.entities_list.insert(tk.END, display)
            self.entities_data.append(e)
    
    # ── Event Handlers ────────────────────────────────────────────────────────
    
    def _on_file_select(self, event):
        """File selected → load chunks for that file."""
        selection = self.files_tree.selection()
        if not selection:
            return
        
        file_cid = self.files_tree.item(selection[0])["values"][0]
        chunks = query.get_chunks_for_file(self.conn, file_cid)
        
        # Clear chunks list
        self.chunks_list.delete(0, tk.END)
        self.chunks_data = []
        
        # Populate chunks
        for c in chunks:
            prefix = c.get("context_prefix", "")
            lines = f"L{c['line_start']}-{c['line_end']}"
            status = c.get("embed_status", "pending")
            status_icon = "✓" if status == "done" else "○"
            
            display = f"{status_icon} {prefix or '(no context)'}  [{lines}, {c['token_count']}t]"
            self.chunks_list.insert(tk.END, display)
            self.chunks_data.append(c)
    
    def _on_chunk_select(self, event):
        """Chunk selected from browse panel → show detail."""
        selection = self.chunks_list.curselection()
        if not selection:
            return
        
        idx = selection[0]
        chunk = self.chunks_data[idx]
        self._show_chunk_detail(chunk["chunk_id"])
    
    def _on_search_result_select(self, event):
        """Search result selected → show detail."""
        selection = self.search_results.curselection()
        if not selection:
            return
        
        idx = selection[0]
        result = self.search_data[idx]
        self._show_chunk_detail(result["chunk_id"])
    
    def _on_entity_select(self, event):
        """Entity selected → show chunks that mention it."""
        selection = self.entities_list.curselection()
        if not selection:
            return
        
        idx = selection[0]
        entity = self.entities_data[idx]
        
        # Get chunks mentioning this entity
        chunks = query.get_chunks_mentioning_entity(self.conn, entity["node_id"])
        
        # Show in detail panel
        self._show_entity_chunks(entity, chunks)
    
    def _run_search(self):
        """Execute hybrid search."""
        query_text = self.search_var.get().strip()
        if not query_text:
            return
        
        # Lazy load embedder if needed
        embedder = self._get_embedder()
        
        # Update status
        if embedder:
            self.search_status.config(text="Searching (semantic + FTS)...", fg=ACCENT2)
        else:
            self.search_status.config(text="Searching (FTS only, no embedder)...", fg=FG_DIM)
        
        self.update_idletasks()
        
        # Run search
        try:
            results = query.hybrid_search(self.conn, query_text, embedder, limit=20)
            
            # Clear results
            self.search_results.delete(0, tk.END)
            self.search_data = []
            
            # Populate results
            for r in results:
                score = r.get("score", 0.0)
                search_type = r.get("search_type", "")
                type_icon = "🔍" if search_type == "fts" else "🎯" if search_type == "semantic" else "⚡"
                
                prefix = r.get("context_prefix", "(no context)")
                display = f"{type_icon} {score:.3f}  {prefix[:60]}"
                
                self.search_results.insert(tk.END, display)
                self.search_data.append(r)
            
            # Update status
            status_text = f"Found {len(results)} results"
            if embedder:
                status_text += " (semantic + FTS)"
            else:
                status_text += " (FTS only)"
            self.search_status.config(text=status_text, fg=SUCCESS)
            
        except Exception as e:
            self.search_status.config(text=f"Search failed: {e}", fg=ERROR)
    
    # ── Detail Panel ──────────────────────────────────────────────────────────
    
    def _show_chunk_detail(self, chunk_id: str):
        """Display full chunk detail."""
        detail = query.get_chunk_detail(self.conn, chunk_id)
        if not detail:
            return
        
        # Update label
        self.detail_label.config(text=f"Chunk: {detail.get('context_prefix', chunk_id)}", fg=FG)
        
        # Build detail text
        text_parts = []
        
        # Metadata
        text_parts.append(("─── Metadata ───\n", "heading"))
        text_parts.append((f"Type: {detail.get('chunk_type', 'unknown')}\n", "dim"))
        text_parts.append((f"Tokens: {detail.get('token_count', 0)}\n", "dim"))
        
        if detail.get("line_start") is not None:
            text_parts.append((f"Lines: {detail['line_start']}-{detail['line_end']}\n", "dim"))
        
        embed_status = detail.get("embed_status", "pending")
        if embed_status == "done":
            text_parts.append((f"Embedding: ✓ {detail.get('embed_model', '')}\n", "accent"))
        elif embed_status == "error":
            text_parts.append((f"Embedding: ✗ {detail.get('embed_error', 'failed')}\n", "error"))
        else:
            text_parts.append((f"Embedding: ○ pending\n", "dim"))
        
        text_parts.append(("\n", None))
        
        # Context prefix
        if detail.get("context_prefix"):
            text_parts.append(("─── Context ───\n", "heading"))
            text_parts.append((f"{detail['context_prefix']}\n\n", "accent"))
        
        # Full text
        text_parts.append(("─── Content ───\n", "heading"))
        text_parts.append((detail.get("text", "(no text)") + "\n\n", None))
        
        # Graph neighbors
        neighbors = detail.get("neighbors", {})
        entities = neighbors.get("entities", [])
        related = neighbors.get("related_chunks", [])
        
        if entities:
            text_parts.append(("─── Entities Mentioned ───\n", "heading"))
            for e in entities[:10]:  # Limit to 10
                text_parts.append((f"  • {e['label']} ({e['entity_type']})\n", "dim"))
            text_parts.append(("\n", None))
        
        if related:
            text_parts.append(("─── Related Chunks ───\n", "heading"))
            for rc in related[:10]:  # Limit to 10
                text_parts.append((f"  • {rc['context_prefix']} ({rc['edge_type']})\n", "dim"))
            text_parts.append(("\n", None))
        
        # Render text
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", tk.END)
        
        for text, tag in text_parts:
            if tag:
                self.detail_text.insert(tk.END, text, tag)
            else:
                self.detail_text.insert(tk.END, text)
        
        self.detail_text.configure(state="disabled")
        
        # Store for copy function
        self.current_chunk_text = detail.get("text", "")
    
    def _show_entity_chunks(self, entity: dict, chunks: list):
        """Display entity and its chunks."""
        # Update label
        self.detail_label.config(text=f"Entity: {entity['label']}", fg=FG)
        
        # Build text
        text_parts = []
        
        text_parts.append(("─── Entity ───\n", "heading"))
        text_parts.append((f"{entity['label']}\n", "accent"))
        text_parts.append((f"Type: {entity['entity_type']}\n", "dim"))
        salience = entity.get("salience", 0.0) or 0.0
        text_parts.append((f"Salience: {salience:.3f}\n\n", "dim"))
        
        text_parts.append(("─── Mentioned In ───\n", "heading"))
        if chunks:
            for c in chunks:
                text_parts.append((f"  • {c['context_prefix']} ({c['chunk_type']})\n", "dim"))
        else:
            text_parts.append(("  (no chunks found)\n", "dim"))
        
        # Render
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", tk.END)
        
        for text, tag in text_parts:
            if tag:
                self.detail_text.insert(tk.END, text, tag)
            else:
                self.detail_text.insert(tk.END, text)
        
        self.detail_text.configure(state="disabled")
        
        self.current_chunk_text = ""
    
    def _copy_chunk_text(self):
        """Copy current chunk text to clipboard."""
        if self.current_chunk_text:
            self.clipboard_clear()
            self.clipboard_append(self.current_chunk_text)
            self.detail_label.config(text="✓ Copied to clipboard", fg=SUCCESS)
            self.after(2000, lambda: self.detail_label.config(fg=FG))
    
    # ── Embedder Loading ──────────────────────────────────────────────────────
    
    def _get_embedder(self):
        """Lazy load embedder for semantic search."""
        if self._embedder is not None:
            return self._embedder
        
        if self._embedder_failed:
            return None
        
        try:
            from .models.manager import get_embedder
            print("[viewer] Loading embedder for semantic search...")
            self._embedder = get_embedder()
            if self._embedder:
                print("[viewer] ✓ Embedder ready")
            return self._embedder
        except Exception as e:
            print(f"[viewer] Failed to load embedder: {e}")
            print("[viewer] Semantic search disabled, using FTS only")
            self._embedder_failed = True
            return None
    
    # ── Cleanup ───────────────────────────────────────────────────────────────
    
    def _show_export_dialog(self):
        """Show export options dialog."""
        dialog = tk.Toplevel(self)
        dialog.title("Export Database")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.grab_set()
        
        # Graceful close handler
        def on_dialog_close():
            dialog.grab_release()
            dialog.destroy()
        
        dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)
        
        # Center over parent
        dialog.update_idletasks()
        w, h = 500, 420  # Increased height to show buttons
        px = self.winfo_rootx() + (self.winfo_width() - w) // 2
        py = self.winfo_rooty() + (self.winfo_height() - h) // 2
        dialog.geometry(f"{w}x{h}+{px}+{py}")
        
        # Header
        tk.Label(dialog, text="📤 Export Options", bg=BG, fg=ACCENT,
                font=("Segoe UI Semibold", 12)).pack(pady=12)
        
        # Stats
        from . import export as export_module
        stats = export_module.get_export_stats(self.conn)
        stats_text = (
            f"Files: {stats['file_count']}  •  "
            f"Lines: {stats['line_count']}  •  "
            f"Size: {stats['total_bytes'] / 1024:.1f} KB"
        )
        tk.Label(dialog, text=stats_text, bg=BG, fg=FG_DIM, font=FONT_SM
                ).pack(pady=(0, 12))
        
        # Export mode
        mode_frame = tk.LabelFrame(dialog, text=" Export Mode ", bg=BG, fg=FG_DIM,
                                   font=FONT_UI, bd=1, relief="flat")
        mode_frame.pack(fill="x", padx=20, pady=8)
        
        mode_var = tk.StringVar(value="dump")
        
        tk.Radiobutton(mode_frame, text="Hierarchy Dump  (folder tree + file dump)",
                      variable=mode_var, value="dump",
                      bg=BG, fg=FG, selectcolor=BG2,
                      activebackground=BG, activeforeground=FG,
                      font=FONT_SM).pack(anchor="w", padx=8, pady=4)
        
        tk.Radiobutton(mode_frame, text="Reconstruct Files  (write originals to disk)",
                      variable=mode_var, value="files",
                      bg=BG, fg=FG, selectcolor=BG2,
                      activebackground=BG, activeforeground=FG,
                      font=FONT_SM).pack(anchor="w", padx=8, pady=4)
        
        tk.Radiobutton(mode_frame, text="Both",
                      variable=mode_var, value="both",
                      bg=BG, fg=FG, selectcolor=BG2,
                      activebackground=BG, activeforeground=FG,
                      font=FONT_SM).pack(anchor="w", padx=8, pady=4)
        
        # Output directory
        dir_frame = tk.Frame(dialog, bg=BG)
        dir_frame.pack(fill="x", padx=20, pady=8)
        
        tk.Label(dir_frame, text="Output Directory:", bg=BG, fg=FG, font=FONT_SM
                ).pack(anchor="w", pady=(0, 4))
        
        dir_var = tk.StringVar(value=str(Path.home() / "tripartite_export"))
        
        dir_entry_frame = tk.Frame(dir_frame, bg=BG)
        dir_entry_frame.pack(fill="x")
        
        tk.Entry(dir_entry_frame, textvariable=dir_var, bg=BG2, fg=FG,
                insertbackground=FG, relief="flat", font=FONT_SM
                ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        
        tk.Button(dir_entry_frame, text="...",
                 command=lambda: self._pick_export_dir(dir_var),
                 bg=BG2, fg=FG, relief="flat", font=FONT_SM,
                 cursor="hand2", width=3
                 ).pack(side="right")
        
        # Status
        status_label = tk.Label(dialog, text="", bg=BG, fg=FG_DIM, font=FONT_SM)
        status_label.pack(pady=8)
        
        # Buttons
        btn_frame = tk.Frame(dialog, bg=BG)
        btn_frame.pack(fill="x", padx=20, pady=12)
        
        def do_export():
            output_dir = Path(dir_var.get())
            mode = mode_var.get()
            
            status_label.config(text="Exporting...", fg=ACCENT2)
            dialog.update_idletasks()
            
            try:
                result = export_module.export_all(
                    self.db_path, output_dir, mode=mode, verbose=False
                )
                
                # Show success
                msg = f"✓ Export complete!\n\nOutput: {output_dir}"
                if "dump" in result:
                    msg += f"\n\nTree: {result['dump']['tree_path'].name}"
                    msg += f"\nDump: {result['dump']['dump_path'].name}"
                if "files" in result:
                    msg += f"\n\nFiles: {result['files']['files_written']}"
                    msg += f"\nBytes: {result['files']['bytes_written']:,}"
                
                status_label.config(text="✓ Complete", fg=SUCCESS)
                messagebox.showinfo("Export Complete", msg, parent=dialog)
                on_dialog_close()
                
            except Exception as e:
                status_label.config(text=f"✗ Error: {e}", fg=ERROR)
                messagebox.showerror("Export Failed", str(e), parent=dialog)
        
        tk.Button(btn_frame, text="Export",
                 command=do_export,
                 bg=ACCENT2, fg=BG, relief="flat", font=FONT_UI,
                 cursor="hand2", padx=20, pady=6,
                 activebackground="#4dcfb3"
                 ).pack(side="right")
        
        tk.Button(btn_frame, text="Cancel",
                 command=on_dialog_close,
                 bg=BG2, fg=FG_DIM, relief="flat", font=FONT_UI,
                 cursor="hand2", padx=12, pady=6,
                 activebackground="#3a3a5e"
                 ).pack(side="right", padx=(0, 8))
    
    def _pick_export_dir(self, var: tk.StringVar):
        """Pick export directory."""
        from tkinter import filedialog
        dir_path = filedialog.askdirectory(
            title="Select Export Directory",
            initialdir=var.get()
        )
        if dir_path:
            var.set(dir_path)
    
    def _on_close(self):
        """Graceful shutdown."""
        if self.conn:
            self.conn.close()
        self.destroy()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tripartite knowledge store viewer")
    parser.add_argument("--db", type=str, help="Path to .db file")
    args = parser.parse_args()
    
    # Get DB path
    if args.db:
        db_path = Path(args.db)
        if not db_path.exists():
            print(f"Error: Database not found: {db_path}")
            sys.exit(1)
    else:
        # File picker
        root = tk.Tk()
        root.withdraw()
        db_path_str = filedialog.askopenfilename(
            title="Select Tripartite database",
            filetypes=[("Database files", "*.db"), ("All files", "*.*")]
        )
        root.destroy()
        
        if not db_path_str:
            print("No database selected. Exiting.")
            sys.exit(0)
        
        db_path = Path(db_path_str)
    
    # Launch viewer
    app = TripartiteViewer(db_path)
    app.mainloop()


if __name__ == "__main__":
    main()
