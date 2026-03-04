"""
src/utils/shell.py

Cross-platform shell actions — open files, reveal in explorer, launch terminals.
Extracted from the monolithic datastore.py (hunk 07).
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def open_file(path) -> None:
    """Open a file with the system default application."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if platform.system() == "Windows":
        os.startfile(str(p))
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def open_file_at_line(path, line) -> None:
    """Open a file at a specific line in VS Code, with fallback."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    la = f":{line}" if line else ""
    try:
        subprocess.Popen(
            ["code", "--goto", f"{p}{la}"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return
    except FileNotFoundError:
        pass
    open_file(path)


def open_in_explorer(path) -> None:
    """Reveal a file/folder in the system file manager."""
    p = Path(path)
    if not p.exists():
        p = p.parent
    if platform.system() == "Windows":
        subprocess.Popen(["explorer", str(p)])
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def open_terminal(path) -> None:
    """Open a terminal at the given directory."""
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


def open_powershell(path) -> None:
    """Open PowerShell at the given directory (Windows)."""
    p = Path(path)
    if not p.is_dir():
        p = p.parent
    subprocess.Popen(
        ["powershell", "-NoExit", "-Command", f"Set-Location '{p}'"],
        creationflags=subprocess.CREATE_NEW_CONSOLE)
