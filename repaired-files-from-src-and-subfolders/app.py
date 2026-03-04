"""
app.py — Tripartite DataSTORE Orchestrator

The "Dumb Manager" that owns the database, DiffEngine, settings, and
lifecycle. Launches the GUI (TripartiteDataStore) with dependency injection
rather than letting the UI build the world itself.

Usage:
    python -m src.app [path/to/store.db]
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Optional

from .db.connection import open_db, init_diff_engine, close_db


class AppManager:
    """Application orchestrator — owns state, injects into GUI."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path: Optional[str] = db_path
        self.conn = None
        self.diff_engine = None
        self.db_lock = threading.Lock()

        # ── Tk root ──────────────────────────────────────────────────
        self.root = tk.Tk()

        # ── HITL gateway ─────────────────────────────────────────────
        from .hitl import HITLGateway
        self.hitl = HITLGateway(self.root, log_callback=self._log_stub)

        # ── Settings ─────────────────────────────────────────────────
        try:
            from .settings_store import Settings
            self.settings = Settings.load()
        except Exception:
            self.settings = None

        # ── Auto-connect if db_path given ────────────────────────────
        if self.db_path:
            self.connect_db(self.db_path)

    # ── DB lifecycle ─────────────────────────────────────────────────

    def connect_db(self, path: str) -> bool:
        """Open a Tripartite database and initialise the DiffEngine."""
        with self.db_lock:
            if self.conn:
                close_db(self.conn, self.diff_engine)
                self.conn = None
                self.diff_engine = None

            try:
                self.conn = open_db(path, check_same_thread=False)
                self.db_path = path
                self.diff_engine = init_diff_engine(path)
                return True
            except Exception as e:
                print(f"[app] connect_db failed: {e}")
                return False

    def shutdown(self) -> None:
        """Clean shutdown: checkpoint, close, destroy root."""
        with self.db_lock:
            close_db(self.conn, self.diff_engine)
            self.conn = None
            self.diff_engine = None
        self.root.destroy()

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _log_stub(tag: str, msg: str, level: str = "dim") -> None:
        """Fallback logger before the GUI is wired up."""
        print(f"[{tag}] {msg}")

    def set_log_callback(self, fn) -> None:
        """Replace the log stub with the real GUI log function."""
        self.hitl.log_callback = fn


def main():
    # Parse args
    db_path = None
    if len(sys.argv) > 1:
        db_path = sys.argv[1]

    mgr = AppManager(db_path=db_path)

    # Import GUI *after* manager is created (so constants are available)
    from .data_store import TripartiteDataStore

    app = TripartiteDataStore(
        root=mgr.root,
        conn=mgr.conn,
        diff_engine=mgr.diff_engine,
        hitl=mgr.hitl,
        settings=mgr.settings,
        db_lock=mgr.db_lock,
        manager=mgr,
    )

    # Wire the real GUI logger back into the manager
    if hasattr(app, "_log"):
        mgr.set_log_callback(app._log)

    mgr.root.mainloop()


if __name__ == "__main__":
    main()
