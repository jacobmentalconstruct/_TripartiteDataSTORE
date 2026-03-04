"""
Shared utility functions used across all pipeline stages.
"""

import hashlib
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Optional


# ── Content addressing ─────────────────────────────────────────────────────────

def cid(content: str) -> str:
    """
    Return a stable content identifier for a string.
    CID = 'sha256:' + hex digest of the UTF-8 encoded canonical form.
    Whitespace is normalized before hashing so that lines that differ only
    in trailing spaces or CRLF vs LF share a CID.
    """
    normalized = _normalize_line(content)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def file_cid(path: Path) -> str:
    """
    Return a CID for an entire file (used as source_cid in span references).
    Hashes the raw bytes — format-agnostic.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def chunk_cid(span_text: str) -> str:
    """
    Return a CID for a chunk, derived from the canonical reconstructed text
    of its spans.  Used as the chunk_id in the manifest.
    """
    normalized = unicodedata.normalize("NFC", span_text.strip())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"cid:sha256:{digest}"


def stable_uuid() -> str:
    """Return a new random UUID as a plain hex string."""
    return str(uuid.uuid4())


# ── Text normalization ─────────────────────────────────────────────────────

def _normalize_line(line: str) -> str:
    """Strip trailing whitespace and normalize line endings."""
    return line.rstrip("\r\n").rstrip()


def normalize_text(text: str) -> str:
    """
    Full normalization pass for content before embedding:
    - NFC unicode normalization
    - Collapse runs of blank lines to a single blank line
    - Strip BOM if present
    """
    text = text.lstrip("\ufeff")                      # strip BOM
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\n{3,}", "\n\n", text)            # collapse blank lines
    return text.strip()


def split_lines(text: str) -> list[str]:
    """
    Split text into lines, normalizing line endings.
    Returns a list of lines WITHOUT trailing newlines.
    Empty files return an empty list.
    """
    if not text:
        return []
    return [_normalize_line(l) for l in text.splitlines()]


# ── Token estimation ───────────────────────────────────────────────────────

# Rough heuristic: 1 token ≈ 4 characters of English text.
# Good enough for chunking budget decisions without loading a tokenizer.
_CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string using the 4-char heuristic."""
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


def tokens_for_lines(lines: list[str]) -> int:
    """Estimate token count for a list of lines."""
    return estimate_tokens("\n".join(lines))


# ── Source type helpers ────────────────────────────────────────────────────

def is_text_file(path: Path, sample_bytes: int = 8192) -> bool:
    """
    Heuristic check: is this file safe to read as UTF-8 text?
    Reads the first sample_bytes and checks for null bytes (binary indicator).
    """
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_bytes)
        if b"\x00" in chunk:
            return False
        chunk.decode("utf-8")
        return True
    except (UnicodeDecodeError, OSError):
        return False


def read_text(path: Path) -> Optional[str]:
    """
    Read a file as UTF-8 text.  Falls back to latin-1 if UTF-8 fails.
    Returns None if the file cannot be read as text at all.
    """
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError):
            continue
    return None


# ── Context prefix ─────────────────────────────────────────────────────────

def build_context_prefix(heading_path: list[str]) -> str:
    """
    Build the context_prefix string from a heading path list.
    Example: ['src', 'app.py', 'class Config', 'load()']
    Returns: 'src > app.py > class Config > load()'
    """
    return " > ".join(str(p) for p in heading_path if p)


__all__ = [
    "cid",
    "file_cid",
    "chunk_cid",
    "stable_uuid",
    "normalize_text",
    "split_lines",
    "estimate_tokens",
    "tokens_for_lines",
    "is_text_file",
    "read_text",
    "build_context_prefix",
]
