"""
Prose chunker for Markdown and plain text files.

Two-pass strategy (per the architecture spec):
  Pass 1 — split on structural signals (ATX headings for Markdown, blank-line
            paragraph breaks for plain text).
  Pass 2 — apply a sliding token window within sections that exceed
            MAX_CHUNK_TOKENS, preserving OVERLAP_LINES of context.

A document-level summary chunk is always generated as the first item.
"""

from __future__ import annotations

import re
from typing import Optional

from ..config import MAX_CHUNK_TOKENS, OVERLAP_LINES
from ..pipeline.detect import SourceFile
from ..utils import build_context_prefix, estimate_tokens
from .base import BaseChunker, Chunk, SpanRef


# ATX heading pattern: # / ## / ### …
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


class ProseChunker(BaseChunker):
    """Heading-aware chunker for Markdown and plain text."""

    def chunk(self, source: SourceFile) -> list[Chunk]:
        lines = source.lines
        is_markdown = source.language in ("markdown",) or source.path.suffix.lower() in (".md", ".markdown")

        if is_markdown:
            sections = _split_on_headings(lines)
        else:
            sections = _split_on_paragraphs(lines)

        chunks: list[Chunk] = []
        file_name = source.path.name

        # Document summary chunk — first non-empty lines up to 256 tokens
        summary = _make_summary_chunk(source, file_name)
        if summary:
            chunks.append(summary)

        for section in sections:
            lo, hi, heading_path = section
            section_lines = lines[lo: hi + 1]
            token_count = estimate_tokens("\n".join(section_lines))

            if token_count <= MAX_CHUNK_TOKENS:
                chunk_type = _heading_depth_to_type(len(heading_path))
                chunks.append(Chunk(
                    chunk_type=chunk_type,
                    name=heading_path[-1] if heading_path else file_name,
                    spans=[SpanRef(source.file_cid, lo, hi)],
                    source=source,
                    heading_path=[file_name] + heading_path,
                    depth=len(heading_path),
                ))
            else:
                # Section too large — apply sliding window
                sub_chunks = _sliding_window(
                    source=source,
                    lo=lo,
                    hi=hi,
                    heading_path=[file_name] + heading_path,
                )
                chunks.extend(sub_chunks)

        if not chunks:
            # Absolute fallback: whole file as one chunk
            chunks.append(Chunk(
                chunk_type="document",
                name=source.path.name,
                spans=[SpanRef(source.file_cid, 0, len(lines) - 1)],
                source=source,
                heading_path=[source.path.name],
                depth=0,
            ))

        self._link_siblings(chunks, OVERLAP_LINES)
        return chunks


# ── Heading / paragraph splitters ─────────────────────────────────────────────

def _split_on_headings(
    lines: list[str],
) -> list[tuple[int, int, list[str]]]:
    """
    Split lines on ATX headings.
    Returns list of (line_start, line_end, heading_path) tuples.
    heading_path is the breadcrumb from root to current heading.
    """
    sections: list[tuple[int, int, list[str]]] = []
    heading_stack: list[tuple[int, str]] = []  # (level, text)
    current_start: Optional[int] = None
    current_path: list[str] = []

    def flush(end: int):
        if current_start is not None and end >= current_start:
            sections.append((current_start, end, list(current_path)))

    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()

            flush(i - 1)

            # Trim heading stack to current level
            heading_stack = [(l, t) for l, t in heading_stack if l < level]
            heading_stack.append((level, text))
            current_path = [t for _, t in heading_stack]
            current_start = i

    # Last section
    flush(len(lines) - 1)
    return sections


def _split_on_paragraphs(
    lines: list[str],
) -> list[tuple[int, int, list[str]]]:
    """
    Split plain text on blank-line paragraph boundaries.
    Returns (start, end, []) — no heading path for plain text.
    """
    sections: list[tuple[int, int, list[str]]] = []
    start: Optional[int] = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped:
            if start is None:
                start = i
        else:
            if start is not None:
                sections.append((start, i - 1, []))
                start = None

    if start is not None:
        sections.append((start, len(lines) - 1, []))

    return sections


# ── Sliding window ─────────────────────────────────────────────────────────────

def _sliding_window(
    source: SourceFile,
    lo: int,
    hi: int,
    heading_path: list[str],
) -> list[Chunk]:
    """
    Break a large section into overlapping token-budget chunks.
    """
    lines = source.lines
    chunks: list[Chunk] = []
    cursor = lo
    window_idx = 0

    while cursor <= hi:
        # Accumulate lines until we hit the token budget
        end = cursor
        tokens = 0
        while end <= hi:
            tokens += estimate_tokens(lines[end])
            if tokens > MAX_CHUNK_TOKENS and end > cursor:
                break
            end += 1

        chunk_end = min(end - 1, hi)
        label = heading_path[-1] if heading_path else source.path.name
        chunks.append(Chunk(
            chunk_type="paragraph",
            name=f"{label} (part {window_idx + 1})",
            spans=[SpanRef(source.file_cid, cursor, chunk_end)],
            source=source,
            heading_path=heading_path,
            depth=len(heading_path) - 1,
        ))

        # Advance cursor with overlap
        next_cursor = chunk_end + 1 - OVERLAP_LINES
        if next_cursor <= cursor:
            next_cursor = cursor + 1   # always make forward progress
        cursor = next_cursor
        window_idx += 1

    return chunks


# ── Summary chunk ──────────────────────────────────────────────────────────────

def _make_summary_chunk(source: SourceFile, file_name: str) -> Optional[Chunk]:
    """
    Generate a document-level summary chunk from the first N tokens of the file.
    This is the high-recall entry point in vector search.
    """
    lines = source.lines
    tokens = 0
    end = 0
    target = 256  # tokens for summary

    for i, line in enumerate(lines):
        tokens += estimate_tokens(line)
        if tokens > target:
            break
        end = i

    if end == 0 and len(lines) == 0:
        return None

    return Chunk(
        chunk_type="document_summary",
        name=f"{file_name} (summary)",
        spans=[SpanRef(source.file_cid, 0, end)],
        source=source,
        heading_path=[file_name, "(summary)"],
        depth=0,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _heading_depth_to_type(depth: int) -> str:
    mapping = {0: "document", 1: "section", 2: "subsection", 3: "paragraph"}
    return mapping.get(depth, "paragraph")
