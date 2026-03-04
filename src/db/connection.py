"""
src/db/connection.py

Database lifecycle helpers — open, close, WAL checkpoint, DiffEngine init.
Extracted from the monolithic datastore.py to support the Controller-View pattern.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..diff_engine import DiffEngine


def open_db(path: str, check_same_thread: bool = False) -> sqlite3.Connection:
    """Open an SQLite connection to a Tripartite database.

    Ensures foreign key enforcement and other pragmas are active.
    Note: For new database creation, use schema.py::open_db() instead.
    """
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)

    # Ensure foreign key enforcement is enabled
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def init_diff_engine(db_path: str) -> Optional["DiffEngine"]:
    """Instantiate DiffEngine for the versioning layer.

    Tries the package import first, then falls back to loading
    diff_engine.py from the src/ directory via importlib.
    """
    diff_db = Path(db_path).parent / "diffs.db"

    try:
        from ..diff_engine import DiffEngine as DE
        return DE(db_path=diff_db)
    except ImportError:
        pass

    # Fallback: load from file
    try:
        import importlib.util as ilu
        ep = Path(__file__).parent.parent / "diff_engine.py"
        if ep.exists():
            sp = ilu.spec_from_file_location("diff_engine", ep)
            if sp and sp.loader:
                m = ilu.module_from_spec(sp)
                sp.loader.exec_module(m)
                return m.DiffEngine(db_path=diff_db)
    except Exception:
        pass

    return None


def close_db(
    conn: Optional[sqlite3.Connection],
    diff_engine: Optional["DiffEngine"] = None,
) -> None:
    """Clean shutdown: WAL checkpoint + close connections."""
    if conn:
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            print(f"[exit] WAL checkpoint failed: {e}")
        try:
            conn.close()
        except Exception:
            pass

    if diff_engine:
        try:
            if hasattr(diff_engine, "conn") and diff_engine.conn:
                diff_engine.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                diff_engine.conn.close()
        except Exception as e:
            print(f"[exit] DiffEngine cleanup failed: {e}")
