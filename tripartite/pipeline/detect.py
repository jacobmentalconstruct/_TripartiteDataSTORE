"""
Pipeline Stage 1: Detect and Normalize

Identifies source type, language, and encoding for each candidate file.
Returns a SourceFile dataclass that subsequent stages operate on.
Filters out binary files, hidden files, and skip-listed directories.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from ..config import (
    CODE_EXTENSIONS,
    PROSE_EXTENSIONS,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
    STRUCTURED_EXTENSIONS,
)
from ..utils import file_cid, is_text_file, read_text, split_lines


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class SourceFile:
    """All information about an ingested source file, ready for the next stage."""
    path: Path
    file_cid: str
    source_type: str              # 'code' | 'prose' | 'structured' | 'generic'
    language: Optional[str]       # 'python' | 'markdown' | None | …
    encoding: str
    text: str                     # decoded full content
    lines: list[str]              # split_lines(text)
    byte_size: int


# ── Language detection ─────────────────────────────────────────────────────────

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript", ".java": "java",
    ".go": "go", ".rs": "rust", ".c": "c", ".cpp": "cpp",
    ".h": "c", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby",
    ".php": "php", ".swift": "swift", ".kt": "kotlin",
    ".scala": "scala", ".r": "r", ".sh": "bash", ".bash": "bash",
    ".zsh": "bash", ".md": "markdown", ".markdown": "markdown",
    ".rst": "rst", ".txt": "text", ".json": "json", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml", ".xml": "xml", ".csv": "csv",
    ".tsv": "tsv", ".html": "html", ".htm": "html",
}


def _detect_language(path: Path) -> Optional[str]:
    return _EXT_TO_LANGUAGE.get(path.suffix.lower())


def _detect_source_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in CODE_EXTENSIONS:
        return "code"
    if ext in PROSE_EXTENSIONS:
        return "prose"
    if ext in STRUCTURED_EXTENSIONS:
        return "structured"
    return "generic"


# ── File eligibility ───────────────────────────────────────────────────────────

def _should_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.startswith(".")


def _should_skip_file(path: Path) -> bool:
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return True
    if path.name.startswith("."):
        return True
    if path.stat().st_size == 0:
        return True
    return False


# ── Public API ─────────────────────────────────────────────────────────────────

def walk_source(root: Path) -> Iterator[Path]:
    """
    Recursively walk *root* (file or directory), yielding candidate paths.
    Skips hidden directories, skip-listed dirs, binary files, and empty files.
    """
    if root.is_file():
        if not _should_skip_file(root) and is_text_file(root):
            yield root
        return

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in sorted(dirnames) if not _should_skip_dir(d)]

        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            try:
                if not _should_skip_file(fpath) and is_text_file(fpath):
                    yield fpath
            except OSError:
                continue


def detect(path: Path) -> Optional[SourceFile]:
    """
    Detect and normalize a single file.
    Returns None if the file should not be ingested (binary, unreadable, empty).
    """
    try:
        stat = path.stat()
    except OSError:
        return None

    if not is_text_file(path):
        return None

    text = read_text(path)
    if text is None or not text.strip():
        return None

    # Detect encoding used for successful read
    encoding = "utf-8"
    for enc in ("utf-8-sig", "utf-8"):
        try:
            path.read_text(encoding=enc)
            encoding = "utf-8"
            break
        except UnicodeDecodeError:
            encoding = "latin-1"

    lines = split_lines(text)
    if not lines:
        return None

    return SourceFile(
        path=path.resolve(),
        file_cid=file_cid(path),
        source_type=_detect_source_type(path),
        language=_detect_language(path),
        encoding=encoding,
        text=text,
        lines=lines,
        byte_size=stat.st_size,
    )
