"""
tripartite/gui.py — Tkinter ingest launcher

Run with:
    python -m tripartite.gui

Presents a simple window with:
  • Folder / file picker
  • Output .db path (auto-filled, editable)
  • Chunk stream checkbox
  • ⚙ Settings button (model selection, download)
  • Run / Stop / Exit buttons
  • Live scrolling log of ingest progress
  • Status bar with progress bar, current action, elapsed timer
  • DB stats bar after a successful run
"""

import queue
import sqlite3
import sys
import time
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .settings_store import Settings


# ── Colour palette ────────────────────────────────────────────────────────────
BG       = "#1e1e2e"
BG2      = "#2a2a3e"
ACCENT   = "#7c6af7"
ACCENT2  = "#5de4c7"
FG       = "#cdd6f4"
FG_DIM   = "#6e6c8e"
SUCCESS  = "#a6e3a1"
WARNING  = "#f9e2af"
ERROR    = "#f38ba8"
FONT_UI  = ("Segoe UI", 10)
FONT_LOG = ("Consolas", 9)
FONT_H   = ("Segoe UI Semibold", 11)


class TripartiteApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tripartite Ingest")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(680, 560)

        self._log_queue: queue.Queue = queue.Queue()
        self._progress_queue: queue.Queue = queue.Queue()
        self._running = False
        self._timer_id = None
        self._start_time = 0.0
        self._progress_total = 1
        self._progress_current = 0

        from .settings_store import Settings
        self._settings = Settings.load()

        # Progress tracking
        self._progress_total = 0
        self._progress_current = 0
        self._start_time = 0.0
        self._timer_id = None

        self._build_ui()
        self._poll_log()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Centre on screen
        self.update_idletasks()
        w, h = 800, 640
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 18, "pady": 6}

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG2, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  Tripartite Knowledge Store",
                 bg=BG2, fg=ACCENT,
                 font=("Segoe UI Semibold", 14)).pack(side="left", padx=16)
        tk.Button(hdr, text="⚙  Settings",
                  command=self._open_settings,
                  bg=BG2, fg=FG_DIM, relief="flat",
                  font=FONT_UI, cursor="hand2", padx=10,
                  activebackground="#3a3a5e",
                  ).pack(side="right", padx=12)
        tk.Label(hdr,
                 text="Ingest files into a portable verbatim · semantic · graph artifact",
                 bg=BG2, fg=FG_DIM, font=FONT_UI).pack(side="left")

        # ── Source picker ─────────────────────────────────────────────────────
        src_frame = tk.LabelFrame(self, text=" Source ", bg=BG, fg=FG_DIM,
                                  font=FONT_UI, bd=1, relief="flat")
        src_frame.pack(fill="x", **pad)

        self.source_var = tk.StringVar()
        tk.Entry(src_frame, textvariable=self.source_var,
                 bg=BG2, fg=FG, insertbackground=FG,
                 relief="flat", font=FONT_UI
                 ).pack(side="left", fill="x", expand=True, padx=(8, 4), pady=8)

        tk.Button(src_frame, text="📁  Pick Folder",
                  command=self._pick_folder,
                  bg=ACCENT, fg="white", relief="flat",
                  font=FONT_UI, cursor="hand2",
                  activebackground="#6a5ae0",
                  ).pack(side="left", padx=4, pady=8)

        tk.Button(src_frame, text="📄  Pick File",
                  command=self._pick_file,
                  bg=BG2, fg=FG, relief="flat",
                  font=FONT_UI, cursor="hand2",
                  activebackground="#3a3a5e",
                  ).pack(side="left", padx=(0, 8), pady=8)

        # ── Output picker ─────────────────────────────────────────────────────
        out_frame = tk.LabelFrame(self, text=" Output .db ", bg=BG, fg=FG_DIM,
                                  font=FONT_UI, bd=1, relief="flat")
        out_frame.pack(fill="x", **pad)

        self.output_var = tk.StringVar()
        tk.Entry(out_frame, textvariable=self.output_var,
                 bg=BG2, fg=FG, insertbackground=FG,
                 relief="flat", font=FONT_UI
                 ).pack(side="left", fill="x", expand=True, padx=(8, 4), pady=8)

        tk.Button(out_frame, text="…",
                  command=self._pick_output,
                  bg=BG2, fg=FG, relief="flat",
                  font=FONT_UI, cursor="hand2", width=3,
                  ).pack(side="left", padx=(0, 8), pady=8)

        # ── Options ───────────────────────────────────────────────────────────
        opt_frame = tk.Frame(self, bg=BG)
        opt_frame.pack(fill="x", padx=18, pady=4)

        self.show_chunks_var = tk.BooleanVar(value=False)
        tk.Checkbutton(opt_frame, text="Show chunk stream",
                       variable=self.show_chunks_var,
                       bg=BG, fg=FG, selectcolor=BG2,
                       activebackground=BG, activeforeground=FG,
                       font=FONT_UI).pack(side="left", padx=(20, 0))

        # ── Run / Stop / Exit buttons ─────────────────────────────────────────
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(fill="x", padx=18, pady=8)

        self.run_btn = tk.Button(btn_frame, text="▶  Run Ingest",
                                 command=self._start_ingest,
                                 bg=ACCENT2, fg=BG, relief="flat",
                                 font=("Segoe UI Semibold", 10),
                                 cursor="hand2", padx=18, pady=6,
                                 activebackground="#4dcfb3")
        self.run_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = tk.Button(btn_frame, text="■  Stop",
                                  command=self._stop_ingest,
                                  bg=BG2, fg=FG_DIM, relief="flat",
                                  font=FONT_UI, cursor="hand2",
                                  padx=12, pady=6, state="disabled")
        self.stop_btn.pack(side="left")

        tk.Button(btn_frame, text="✕  Exit",
                  command=self._on_close,
                  bg=BG2, fg=FG_DIM, relief="flat",
                  font=FONT_UI, cursor="hand2",
                  padx=12, pady=6,
                  activebackground="#3a3a5e",
                  ).pack(side="right")

        # ── Log ───────────────────────────────────────────────────────────────
        log_frame = tk.LabelFrame(self, text=" Progress ", bg=BG, fg=FG_DIM,
                                  font=FONT_UI, bd=1, relief="flat")
        log_frame.pack(fill="both", expand=True, padx=18, pady=(0, 4))

        self.log = scrolledtext.ScrolledText(
            log_frame, bg="#13131f", fg=FG, font=FONT_LOG,
            relief="flat", state="disabled", wrap="word",
            insertbackground=FG,
        )
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

        for tag, colour in [("info", FG), ("success", SUCCESS), ("warning", WARNING),
                             ("error", ERROR), ("dim", FG_DIM), ("accent", ACCENT2)]:
            self.log.tag_config(tag, foreground=colour)

        # ── Status bar (bottom, packed last so it stays at the very bottom) ──
        self._build_status_bar()

    def _build_status_bar(self):
        """
        Three-row status bar pinned to the bottom:
          Row 1: File progress bar  + "File N of M (X%)"  + elapsed clock
          Row 2: Chunk/embed bar    + action label
          Row 3: DB stats after a completed run
        """
        bar = tk.Frame(self, bg=BG2)
        bar.pack(fill="x", side="bottom")

        tk.Frame(bar, bg="#3a3a5e", height=1).pack(fill="x")  # separator line

        # ── Row 1: file-level progress ────────────────────────────────────────
        r1 = tk.Frame(bar, bg=BG2)
        r1.pack(fill="x", padx=10, pady=(5, 1))

        tk.Label(r1, text="Files:", bg=BG2, fg=FG_DIM,
                 font=("Consolas", 9)).pack(side="left", padx=(0, 4))

        self._file_bar = ttk.Progressbar(r1, mode="determinate",
                                         maximum=1, length=180)
        self._file_bar.pack(side="left", padx=(0, 8))

        self._file_label = tk.StringVar(value="—")
        tk.Label(r1, textvariable=self._file_label,
                 bg=BG2, fg=FG_DIM, font=("Consolas", 9),
                 anchor="w").pack(side="left", fill="x", expand=True)

        self._elapsed_var = tk.StringVar(value="")
        tk.Label(r1, textvariable=self._elapsed_var,
                 bg=BG2, fg=FG_DIM, font=("Consolas", 9)).pack(side="right")

        # ── Row 2: chunk/embedding sub-progress ───────────────────────────────
        r2 = tk.Frame(bar, bg=BG2)
        r2.pack(fill="x", padx=10, pady=(1, 4))

        tk.Label(r2, text="Chunks:", bg=BG2, fg=FG_DIM,
                 font=("Consolas", 9)).pack(side="left", padx=(0, 4))

        self._chunk_bar = ttk.Progressbar(r2, mode="determinate",
                                          maximum=1, length=180)
        self._chunk_bar.pack(side="left", padx=(0, 8))

        self._action_var = tk.StringVar(value="Idle")
        tk.Label(r2, textvariable=self._action_var,
                 bg=BG2, fg=FG_DIM, font=("Consolas", 9),
                 anchor="w").pack(side="left", fill="x", expand=True)

        # ── Row 3: DB stats after run ──────────────────────────────────────────
        self.stats_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.stats_var,
                 bg=BG2, fg=FG_DIM, font=("Consolas", 8),
                 anchor="w", padx=10).pack(fill="x", pady=(0, 4))

    # ── Settings ──────────────────────────────────────────────────────────────

    def _open_settings(self):
            from .settings_dialog import SettingsDialog
            dlg = SettingsDialog(self)
            self.wait_window(dlg)
            self._settings = Settings.load()
            
            # 1. Correct import
            from .models import manager
            
            # 2. Use 'manager' directly (remove 'models.' prefix)
            manager._embedder_instance  = None
            manager._extractor_instance = None
            manager._embedder_failed    = False
            manager._extractor_failed   = False
            self._set_action("Settings saved — models will reload on next run.")

    def _prompt_download(self, role: str) -> bool:
        """Ask user if they want to open Settings to download the missing model."""
        spec = self._settings.spec_for(role)
        answer = messagebox.askyesno(
            "Model not downloaded",
            f"The selected {role} model is not in the cache:\n"
            f"  {spec['display_name']}\n\n"
            f"  {spec.get('description', '')}\n\n"
            "Open Settings to download it now?",
            icon="question",
            parent=self,
        )
        if not answer:
            return False
        self._open_settings()
        return self._settings.model_is_cached(role)

    # ── Pickers ───────────────────────────────────────────────────────────────

    def _pick_folder(self):
        path = filedialog.askdirectory(title="Select folder to ingest")
        if path:
            self.source_var.set(path)
            self._auto_output(Path(path))

    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="Select file to ingest",
            filetypes=[("Text files", "*.py *.md *.txt *.rst *.json *.yaml *.toml"),
                       ("All files", "*.*")],
        )
        if path:
            self.source_var.set(path)
            self._auto_output(Path(path))

    def _pick_output(self):
        path = filedialog.asksaveasfilename(
            title="Save .db artifact as…",
            defaultextension=".db",
            filetypes=[("SQLite database", "*.db")],
        )
        if path:
            self.output_var.set(path)

    def _auto_output(self, source: Path):
        stem = source.stem if source.is_file() else source.name
        self.output_var.set(str(source.parent / f"{stem}.tripartite.db"))

    # ── Ingest control ────────────────────────────────────────────────────────

    def _start_ingest(self):
        source_str = self.source_var.get().strip()
        output_str = self.output_var.get().strip()

        if not source_str:
            messagebox.showwarning("No source", "Please select a folder or file to ingest.")
            return
        source = Path(source_str)
        if not source.exists():
            messagebox.showerror("Not found", f"Path does not exist:\n{source}")
            return
        if not output_str:
            messagebox.showwarning("No output", "Please specify an output .db path.")
            return

        db_path = Path(output_str)

        if db_path.exists() and not self._settings.lazy_mode:
            if self._check_model_mismatch(db_path) == "cancel":
                return

        if not self._settings.lazy_mode:
            if not self._settings.model_is_cached("embedder"):
                if not self._prompt_download("embedder"):
                    return

        lazy = self._settings.lazy_mode
        self._clear_log()
        self._set_running(True)
        self._log(f"Source  : {source}", "accent")
        self._log(f"Output  : {db_path}", "accent")
        self._log(f"Mode    : {'lazy (no embedding)' if lazy else 'full'}", "dim")
        self._log(f"Embedder: {self._settings.embedder_model}\n", "dim")

        from .pipeline.detect import walk_source
        candidate_paths = list(walk_source(source))
        self._progress_total   = len(candidate_paths)
        self._file_bar.configure(maximum=max(self._progress_total, 1))
        self._file_bar["value"]  = 0
        self._chunk_bar["value"] = 0
        self._chunk_bar["maximum"] = 1

        on_chunk = None
        if self.show_chunks_var.get():
            if not hasattr(self, "_chunk_viewer") or not self._chunk_viewer.winfo_exists():
                from .chunk_viewer import ChunkViewerWindow
                self._chunk_viewer = ChunkViewerWindow(self)
            else:
                self._chunk_viewer._clear()
                self._chunk_viewer.lift()
            on_chunk = self._chunk_viewer.feed

        self._stop_flag = threading.Event()
        threading.Thread(
            target=self._run_ingest,
            args=(source, db_path, lazy, on_chunk),
            daemon=True,
        ).start()

    def _check_model_mismatch(self, db_path: Path) -> str:
        try:
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                "SELECT DISTINCT embed_model FROM chunk_manifest WHERE embed_model IS NOT NULL"
            ).fetchall()
            conn.close()
        except Exception:
            return "ok"
        db_models = {r[0] for r in rows if r[0]}
        selected  = self._settings.embedder_model
        if not db_models or selected in db_models:
            return "ok"
        answer = messagebox.askyesnocancel(
            "Model mismatch",
            f"This .db was embedded with:\n  {', '.join(db_models)}\n\n"
            f"Your current embedder is:\n  {selected}\n\n"
            "Mixing models makes semantic search unreliable.\n\n"
            "Continue anyway?  (No = cancel)",
            icon="warning", parent=self,
        )
        return "ok" if answer else "cancel"

    def _stop_ingest(self):
        if hasattr(self, "_stop_flag"):
            self._stop_flag.set()
        self._log("\n⚠ Stop requested — will halt after current file.", "warning")
        self._set_action("Stopping…")

    def _run_ingest(self, source: Path, db_path: Path, lazy: bool, on_chunk=None):
        """Runs in a background thread."""
        try:
            from .pipeline.ingest import ingest
            import io

            class QueueWriter(io.TextIOBase):
                def __init__(self, q):
                    self.q = q
                def write(self, s):
                    s = s.rstrip()
                    if s:
                        self.q.put(("log", s, "info"))
                    return len(s) + 1

            old_stdout = sys.stdout
            sys.stdout = QueueWriter(self._log_queue)

            def on_progress(event):
                self._log_queue.put(("progress", event))

            result = ingest(
                source_root=source,
                db_path=db_path,
                lazy=lazy,
                verbose=True,
                on_chunk=on_chunk,
                on_progress=on_progress,
            )

            sys.stdout = old_stdout
            self._log_queue.put(("log", "", "info"))
            if result["errors"]:
                self._log_queue.put(("log", f"✗ Completed with {len(result['errors'])} error(s)", "error"))
            else:
                self._log_queue.put(("log", "✓ Ingest complete!", "success"))
            self.after(100, lambda: self._show_stats(db_path, result))

        except Exception as e:
            import traceback
            self._log_queue.put(("log", f"\n✗ Fatal error: {e}", "error"))
            self._log_queue.put(("log", traceback.format_exc(), "error"))
        finally:
            sys.stdout = sys.__stdout__
            self.after(100, lambda: self._set_running(False))

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log(self, text: str, tag: str = "info"):
        self._log_queue.put(("log", text, tag))

    def _poll_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                if msg[0] == "log":
                    self._append_log(msg[1], msg[2])
                elif msg[0] == "progress":
                    self._handle_progress(msg[1])
        except queue.Empty:
            pass
        self.after(50, self._poll_log)

    def _handle_progress(self, event: dict):
        etype = event.get("type")

        if etype == "file_start":
            idx   = event["file_idx"]
            total = event["file_total"]
            name  = event.get("filename", "")
            pct   = int(idx / total * 100) if total else 0
            self._file_bar["maximum"] = total
            self._file_bar["value"]   = idx - 1
            self._file_label.set(f"File {idx} of {total}  ({pct}%)  —  {name}")
            self._set_action(f"Processing {name}…")
            # Reset chunk bar for new file
            self._chunk_bar["value"]   = 0
            self._chunk_bar["maximum"] = 1

        elif etype == "file_done":
            self._file_bar["value"] = event["file_idx"]

        elif etype == "chunk_progress":
            total = event.get("chunk_total", 1)
            self._chunk_bar["maximum"] = total
            self._chunk_bar["value"]   = 0
            self._set_action(f"Chunking {event.get('filename', '')}…")

        elif etype == "embedding_progress":
            idx   = event.get("chunk_idx", 0)
            total = event.get("chunk_total", 1)
            pct   = int((idx + 1) / total * 100) if total else 0
            self._chunk_bar["maximum"] = total
            self._chunk_bar["value"]   = idx + 1
            self._set_action(f"Embedding chunk {idx + 1} of {total}  ({pct}%)")

    def _append_log(self, text: str, tag: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ── Status bar helpers ────────────────────────────────────────────────────

    def _set_action(self, text: str):
        self._action_var.set(text)

    def _start_timer(self):
        self._start_time = time.time()
        self._tick_timer()

    def _tick_timer(self):
        if not self._running:
            return
        elapsed = time.time() - self._start_time
        mins, secs = divmod(int(elapsed), 60)
        self._elapsed_var.set(f"{mins:02d}:{secs:02d}")
        self._timer_id = self.after(1000, self._tick_timer)

    def _stop_timer(self):
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None

    # ── Graceful close ────────────────────────────────────────────────────────

    def _on_close(self):
        if self._running:
            answer = messagebox.askyesno(
                "Ingest in progress",
                "An ingest is currently running.\n\n"
                "Stopping now may leave the .db file in an incomplete state "
                "(already-processed files are safe — only the current file "
                "may be affected).\n\n"
                "Stop and exit anyway?",
                icon="warning", parent=self,
            )
            if not answer:
                return
            if hasattr(self, "_stop_flag"):
                self._stop_flag.set()
        for child in self.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        self.quit()
        self.destroy()

    # ── State helpers ─────────────────────────────────────────────────────────

    def _set_running(self, running: bool):
        self._running = running
        if running:
            self.run_btn.configure(state="disabled", bg="#555570")
            self.stop_btn.configure(state="normal")
            self._file_bar["value"]  = 0
            self._chunk_bar["value"] = 0
            self._set_action("Starting…")
            self._file_label.set("—")
            self._start_timer()
        else:
            self.run_btn.configure(state="normal", bg=ACCENT2)
            self.stop_btn.configure(state="disabled")
            self._stop_timer()
            self._file_bar["value"] = self._file_bar["maximum"]

    def _show_stats(self, db_path: Path, result: dict):
        try:
            conn = sqlite3.connect(str(db_path))
            def q(sql): return conn.execute(sql).fetchone()[0]
            chunks   = q("SELECT COUNT(*) FROM chunk_manifest")
            embedded = q("SELECT COUNT(*) FROM chunk_manifest WHERE embed_status='done'")
            nodes    = q("SELECT COUNT(*) FROM graph_nodes")
            edges    = q("SELECT COUNT(*) FROM graph_edges")
            conn.close()
            size_mb = db_path.stat().st_size / 1_048_576

            self.stats_var.set(
                f"DB: {size_mb:.1f} MB  │  "
                f"Files: {result['files_processed']}  │  "
                f"Chunks: {chunks}  │  "
                f"Embedded: {embedded}  │  "
                f"Graph nodes: {nodes}  │  "
                f"Edges: {edges}  │  "
                f"Time: {result['elapsed_seconds']}s"
            )
            self._set_action("✓ Done")
            self._elapsed_var.set("")
        except Exception:
            pass


def main():
    app = TripartiteApp()
    app.mainloop()


if __name__ == "__main__":
    main()

