"""
tripartite/settings_dialog.py

Settings Toplevel window.

Sections:
  • Embedder model   — dropdown of all KNOWN_MODELS where role=='embedder'
  • Extractor model  — dropdown of all KNOWN_MODELS where role=='extractor'
  • Diagnostics      — lazy mode toggle

Each model row shows:
  • Display name + description
  • Cache status badge: ✓ Cached (green) | ✗ Not downloaded (dim)
  • File size on disk (if cached)
  • "Download" button — opens inline log and streams download progress

Footer buttons:
  • Apply   — save settings to disk, stay open (shows confirmation flash)
  • Cancel  — discard any changes and close
  • X close — same as Cancel (prompts if unsaved changes)

Model mismatch detection:
  Call settings_dialog.warn_if_mismatch(db_path, parent) before an ingest run
  to alert the user if the selected embedder differs from what the DB was built with.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Optional

from .config import KNOWN_MODELS, MODELS_DIR
from .settings_store import Settings

# ── Palette (matches gui.py) ──────────────────────────────────────────────────
BG      = "#1e1e2e"
BG2     = "#2a2a3e"
BG3     = "#13131f"
ACCENT  = "#7c6af7"
ACCENT2 = "#5de4c7"
FG      = "#cdd6f4"
FG_DIM  = "#6e6c8e"
SUCCESS = "#a6e3a1"
WARNING = "#f9e2af"
ERROR   = "#f38ba8"
FONT_UI = ("Segoe UI", 10)
FONT_SM = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 9)


def warn_if_mismatch(db_path: Path, parent: tk.Misc) -> bool:
    """
    Check if the DB was embedded with a different model than currently selected.
    Returns True if safe to proceed, False if user chose to cancel.
    Call this before starting a full (non-lazy) ingest on an existing DB.
    """
    import sqlite3
    settings = Settings.load()
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT embed_model FROM chunk_manifest WHERE embed_model IS NOT NULL LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return True  # DB is new or lazy — no conflict
        db_model = row[0]
        selected = settings.embedder_filename
        if db_model != selected:
            answer = messagebox.askyesno(
                "Model mismatch",
                f"This .db was embedded with:\n  {db_model}\n\n"
                f"Your currently selected embedder is:\n  {selected}\n\n"
                "Mixing models produces incompatible vectors — semantic search "
                "will return wrong results.\n\n"
                "Proceed anyway? (Choose No to cancel and fix in Settings)",
                icon="warning",
                parent=parent,
            )
            return answer
    except Exception:
        pass
    return True


class SettingsDialog(tk.Toplevel):
    """Modal settings window with Apply / Cancel buttons."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("Settings")
        self.configure(bg=BG)
        self.grab_set()  # modal

        # Allow vertical resize so the user can grow the window if needed
        self.resizable(False, True)
        self.minsize(620, 660)

        self._settings = Settings.load()
        self._log_queue: queue.Queue = queue.Queue()
        self._downloading = False
        self._dirty = False  # tracks unsaved changes

        # Snapshot the original values so Cancel can truly discard
        self._original_embedder = self._settings.embedder_filename
        self._original_extractor = self._settings.extractor_filename
        self._original_lazy = self._settings.lazy_mode

        self._build_ui()
        self._refresh_cache_status()
        self._poll_log()

        # Handle the X close button — same as Cancel (with prompt if dirty)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Centre over parent
        self.update_idletasks()
        w, h = 620, 680
        px = parent.winfo_rootx() + (parent.winfo_width()  - w) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{px}+{py}")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ══════════════════════════════════════════════════════════════════════
        # PACK ORDER MATTERS.  In tkinter's pack manager, widgets packed first
        # claim space first.  We pack in this order:
        #   1. Header   (top, fixed height)
        #   2. Footer   (bottom, fixed height) ← MUST come before body
        #   3. Body     (fill remaining space, expand=True)
        # This guarantees the Apply/Cancel buttons are always visible even if
        # the body content is tall.
        # ══════════════════════════════════════════════════════════════════════

        # ── 1. Header (top) ───────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG2, pady=10)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text="⚙  Settings", bg=BG2, fg=ACCENT,
                 font=("Segoe UI Semibold", 13)).pack(side="left", padx=16)

        # ── 2. Footer with buttons (bottom, packed BEFORE body) ───────────────
        foot = tk.Frame(self, bg=BG2, pady=8)
        foot.pack(fill="x", side="bottom")

        # Thin separator line at top of footer
        tk.Frame(foot, bg="#3a3a5e", height=1).pack(fill="x", side="top")

        # Button row
        btn_row = tk.Frame(foot, bg=BG2)
        btn_row.pack(fill="x", padx=12, pady=(6, 2))

        # Status feedback label (shows "Settings applied ✓" flash) — left side
        self._status_msg = tk.StringVar(value="")
        self._status_label = tk.Label(
            btn_row, textvariable=self._status_msg,
            bg=BG2, fg=SUCCESS, font=FONT_SM,
        )
        self._status_label.pack(side="left")

        # Cancel — right side
        tk.Button(btn_row, text="Cancel",
                  command=self._on_cancel,
                  bg=BG2, fg=FG_DIM, relief="flat",
                  font=FONT_UI, cursor="hand2", padx=12, pady=5,
                  activebackground=BG,
                  ).pack(side="right", padx=(4, 0))

        # Apply — right side, next to Cancel
        self._apply_btn = tk.Button(
            btn_row, text="✓  Apply",
            command=self._on_apply,
            bg=ACCENT2, fg=BG, relief="flat",
            font=("Segoe UI Semibold", 10),
            cursor="hand2", padx=16, pady=5,
            activebackground="#4dcfb3",
        )
        self._apply_btn.pack(side="right", padx=(0, 4))

        # ── 3. Body (fills remaining space between header and footer) ─────────
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=12)

        # ── Embedder section ──────────────────────────────────────────────────
        self._model_section(
            body,
            role="embedder",
            label="Embedder Model",
            subtitle="Used to generate vector embeddings for semantic search.",
            attr="embedder_filename",
        )

        tk.Frame(body, bg=BG2, height=1).pack(fill="x", pady=10)

        # ── Extractor section ─────────────────────────────────────────────────
        self._model_section(
            body,
            role="extractor",
            label="Extractor Model",
            subtitle="Used for entity and relationship extraction (graph layer).",
            attr="extractor_filename",
        )

        tk.Frame(body, bg=BG2, height=1).pack(fill="x", pady=10)

        # ── Diagnostics section ───────────────────────────────────────────────
        diag_section = tk.Frame(body, bg=BG)
        diag_section.pack(fill="x", pady=(0, 4))

        tk.Label(diag_section, text="Diagnostics", bg=BG, fg=FG,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w")
        tk.Label(diag_section, text="Testing and development options.", bg=BG, fg=FG_DIM,
                 font=FONT_SM).pack(anchor="w", pady=(0, 6))

        self.lazy_var = tk.BooleanVar(value=self._settings.lazy_mode)
        self.lazy_var.trace_add("write", lambda *_: self._mark_dirty())
        tk.Checkbutton(
            diag_section,
            text="Lazy mode  (structural pass only — skips embedding and entity extraction)",
            variable=self.lazy_var,
            bg=BG, fg=FG, selectcolor=BG2,
            activebackground=BG, activeforeground=FG,
            font=FONT_UI
        ).pack(anchor="w")

        tk.Label(diag_section,
                 text="Useful for testing the chunking pipeline without loading models.",
                 bg=BG, fg=FG_DIM, font=FONT_SM, wraplength=560, justify="left"
                 ).pack(anchor="w", pady=(2, 0))

        tk.Frame(body, bg=BG2, height=1).pack(fill="x", pady=10)

        # ── Download log ──────────────────────────────────────────────────────
        tk.Label(body, text="Download log", bg=BG, fg=FG_DIM,
                 font=FONT_SM).pack(anchor="w")
        self._log_widget = scrolledtext.ScrolledText(
            body, bg=BG3, fg=FG, font=FONT_MONO,
            height=6, relief="flat", state="disabled", wrap="word",
        )
        self._log_widget.pack(fill="both", expand=True, pady=(4, 0))
        self._log_widget.tag_config("ok",   foreground=SUCCESS)
        self._log_widget.tag_config("warn", foreground=WARNING)
        self._log_widget.tag_config("err",  foreground=ERROR)
        self._log_widget.tag_config("dim",  foreground=FG_DIM)

    def _model_section(self, parent, role: str, label: str, subtitle: str, attr: str):
        """Build one model-selection section (embedder or extractor)."""
        models = [m for m in KNOWN_MODELS if m["role"] == role]

        section = tk.Frame(parent, bg=BG)
        section.pack(fill="x", pady=(0, 4))

        tk.Label(section, text=label, bg=BG, fg=FG,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w")
        tk.Label(section, text=subtitle, bg=BG, fg=FG_DIM,
                 font=FONT_SM).pack(anchor="w", pady=(0, 6))

        display_names = [m["display_name"] for m in models]
        current_filename = getattr(self._settings, attr)
        current_idx = next(
            (i for i, m in enumerate(models) if m["filename"] == current_filename), 0
        )

        combo_var = tk.StringVar(value=display_names[current_idx])
        combo = ttk.Combobox(section, textvariable=combo_var,
                             values=display_names, state="readonly", width=52)
        combo.pack(anchor="w")

        # Description label under combo
        desc_var = tk.StringVar(value=models[current_idx]["description"])
        tk.Label(section, textvariable=desc_var, bg=BG, fg=FG_DIM,
                 font=FONT_SM).pack(anchor="w", pady=(2, 4))

        # Status + download row
        status_row = tk.Frame(section, bg=BG)
        status_row.pack(fill="x")

        status_var = tk.StringVar()
        status_lbl = tk.Label(status_row, textvariable=status_var,
                              bg=BG, font=FONT_SM)
        status_lbl.pack(side="left")

        dl_btn = tk.Button(status_row, text="⬇  Download",
                           bg=BG2, fg=FG, relief="flat",
                           font=FONT_SM, cursor="hand2", padx=10, pady=3,
                           activebackground="#3a3a5e")
        dl_btn.pack(side="left", padx=(12, 0))

        # Wire combo change → update description + status + mark dirty
        def on_combo_change(*_):
            name = combo_var.get()
            spec = next(m for m in models if m["display_name"] == name)
            desc_var.set(spec["description"])
            setattr(self._settings, attr, spec["filename"])
            self._update_status(spec, status_var, status_lbl, dl_btn)
            self._mark_dirty()

        combo.bind("<<ComboboxSelected>>", on_combo_change)

        # Wire download button
        def on_download():
            name = combo_var.get()
            spec = next(m for m in models if m["display_name"] == name)
            self._start_download(spec, status_var, status_lbl, dl_btn)

        dl_btn.configure(command=on_download)

        # Store refs so _refresh_cache_status can update them
        if not hasattr(self, "_status_refs"):
            self._status_refs = {}
        self._status_refs[attr] = (models, combo_var, status_var, status_lbl, dl_btn, attr)

        # Initial status
        self._update_status(models[current_idx], status_var, status_lbl, dl_btn)

    # ── Dirty tracking ────────────────────────────────────────────────────────

    def _mark_dirty(self):
        """Flag that the user has made changes that haven't been applied yet."""
        self._dirty = True
        # Clear any "applied" feedback since something changed again
        self._status_msg.set("")

    # ── Cache status ──────────────────────────────────────────────────────────

    def _refresh_cache_status(self):
        """Re-check which models are cached and update all status labels."""
        if not hasattr(self, "_status_refs"):
            return
        for attr, (models, combo_var, status_var, status_lbl, dl_btn, _) in self._status_refs.items():
            name = combo_var.get()
            spec = next((m for m in models if m["display_name"] == name), models[0])
            self._update_status(spec, status_var, status_lbl, dl_btn)

    def _update_status(self, spec: dict, status_var: tk.StringVar,
                       status_lbl: tk.Label, dl_btn: tk.Button):
        path = MODELS_DIR / spec["filename"]
        if path.exists() and path.stat().st_size >= spec.get("min_size_bytes", 0):
            size_mb = path.stat().st_size / 1_048_576
            status_var.set(f"✓  Cached  ({size_mb:.0f} MB)")
            status_lbl.configure(fg=SUCCESS)
            dl_btn.configure(text="⬇  Re-download", fg=FG_DIM)
        else:
            status_var.set("✗  Not downloaded")
            status_lbl.configure(fg=FG_DIM)
            dl_btn.configure(text="⬇  Download", fg=ACCENT2)

    # ── Download ──────────────────────────────────────────────────────────────

    def _start_download(self, spec: dict, status_var: tk.StringVar,
                        status_lbl: tk.Label, dl_btn: tk.Button):
        if self._downloading:
            self._log("⚠ A download is already in progress.", "warn")
            return

        self._downloading = True
        dl_btn.configure(state="disabled")
        self._log(f"Starting download: {spec['display_name']}", "dim")
        self._log(f"  URL: {spec['url']}", "dim")

        def run():
            try:
                import urllib.request
                MODELS_DIR.mkdir(parents=True, exist_ok=True)
                dest = MODELS_DIR / spec["filename"]
                tmp  = dest.with_suffix(".tmp")

                def reporthook(count, block_size, total_size):
                    if total_size > 0:
                        pct = min(100, count * block_size * 100 // total_size)
                        done_mb  = count * block_size / 1_048_576
                        total_mb = total_size / 1_048_576
                        self._log_queue.put(
                            (f"\r  {pct:3d}%  {done_mb:.1f} / {total_mb:.1f} MB", "dim", True)
                        )

                urllib.request.urlretrieve(spec["url"], tmp, reporthook)
                tmp.rename(dest)

                actual = dest.stat().st_size
                min_sz = spec.get("min_size_bytes", 0)
                if actual < min_sz:
                    dest.unlink()
                    self._log_queue.put((
                        f"✗  Download too small ({actual / 1e6:.1f} MB) — likely interrupted.",
                        "err", False
                    ))
                else:
                    self._log_queue.put((
                        f"✓  Download complete — {actual / 1_048_576:.0f} MB saved to cache.",
                        "ok", False
                    ))
                    # Refresh status badges on main thread
                    self.after(100, self._refresh_cache_status)

            except Exception as e:
                self._log_queue.put((f"✗  Download failed: {e}", "err", False))
            finally:
                self._downloading = False
                self.after(100, lambda: dl_btn.configure(state="normal"))

        threading.Thread(target=run, daemon=True).start()

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log(self, text: str, tag: str = "dim"):
        self._log_queue.put((text, tag, False))

    def _poll_log(self):
        try:
            while True:
                item = self._log_queue.get_nowait()
                text, tag, overwrite_last = item
                w = self._log_widget
                w.configure(state="normal")
                if overwrite_last:
                    # Overwrite the last line (for progress %)
                    w.delete("end-2l", "end-1c")
                    w.insert("end", "\n" + text.lstrip("\r"), tag)
                else:
                    w.insert("end", text + "\n", tag)
                w.see("end")
                w.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(60, self._poll_log)

    # ── Apply / Cancel / Close ────────────────────────────────────────────────

    def _on_apply(self):
        """Save all current settings to disk and show confirmation."""
        self._settings.lazy_mode = self.lazy_var.get()
        self._settings.save()
        self._dirty = False

        # Update snapshots so Cancel after Apply doesn't revert the applied state
        self._original_embedder = self._settings.embedder_filename
        self._original_extractor = self._settings.extractor_filename
        self._original_lazy = self._settings.lazy_mode

        # Visual confirmation flash
        self._status_msg.set("✓  Settings applied")
        self._status_label.configure(fg=SUCCESS)
        # Fade the message after 3 seconds
        self.after(3000, lambda: self._status_msg.set(""))

        self._log("Settings saved.", "ok")

    def _on_cancel(self):
        """Discard unsaved changes and close."""
        if self._dirty:
            answer = messagebox.askyesno(
                "Unsaved changes",
                "You have unsaved changes.\n\n"
                "Discard changes and close?",
                icon="question",
                parent=self,
            )
            if not answer:
                return

        # Revert in-memory settings to the original values
        # (in case something else reads self._settings before gui.py reloads)
        self._settings.embedder_filename = self._original_embedder
        self._settings.extractor_filename = self._original_extractor
        self._settings.lazy_mode = self._original_lazy

        self.destroy()