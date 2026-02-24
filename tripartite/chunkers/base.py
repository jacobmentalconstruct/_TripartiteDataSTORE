"""
Base chunker interface and shared Chunk dataclass.

All chunkers receive a SourceFile and return a list of Chunk objects.
The pipeline then writes these to the logical tree and chunk manifest.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from ..pipeline.detect import SourceFile


@dataclass
class SpanRef:
    """Reference to a range of lines within a source file."""
    source_cid: str          # file_cid of the source file
    line_start: int          # 0-indexed, inclusive
    line_end: int            # 0-indexed, inclusive
    char_start: Optional[int] = None
    char_end: Optional[int] = None

    def to_dict(self) -> dict:
        d = {
            "source_cid": self.source_cid,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }
        if self.char_start is not None:
            d["char_start"] = self.char_start
            d["char_end"] = self.char_end
        return d


@dataclass
class Chunk:
    """
    A single logical unit of content, ready to be written to all three layers.
    Text is never stored here — it is always derived from the source file
    via the spans.  We carry it temporarily during the pipeline run only.
    """
    # Identity
    chunk_type: str              # function_def | class_def | section | paragraph | …
    name: str                    # short human label (function name, heading text, …)

    # Source location
    spans: list[SpanRef]
    source: SourceFile

    # Hierarchy (filled by the chunker or the parse stage)
    heading_path: list[str] = field(default_factory=list)
    parent_chunk_idx: Optional[int] = None   # index into sibling list, or None
    depth: int = 0

    # Overlap (filled by chunker after all siblings are known)
    prev_chunk_idx: Optional[int] = None
    next_chunk_idx: Optional[int] = None
    overlap_prefix_lines: int = 0
    overlap_suffix_lines: int = 0

    # Derived text — populated by the pipeline, not stored in DB
    _text: Optional[str] = field(default=None, repr=False)

    @property
    def text(self) -> str:
        """Return the chunk's text, reconstructed from its spans."""
        if self._text is not None:
            return self._text
        lines = self.source.lines
        parts = []
        for span in self.spans:
            start = max(0, span.line_start)
            end = min(len(lines), span.line_end + 1)
            parts.append("\n".join(lines[start:end]))
        self._text = "\n".join(parts)
        return self._text

    @property
    def line_start(self) -> int:
        return self.spans[0].line_start

    @property
    def line_end(self) -> int:
        return self.spans[-1].line_end


class BaseChunker(ABC):
    """Abstract base class for all source-type-specific chunkers."""

    @abstractmethod
    def chunk(self, source: SourceFile) -> list[Chunk]:
        """
        Split *source* into a list of Chunk objects.
        Implementors must populate: chunk_type, name, spans, heading_path, depth.
        Overlap fields are wired up by _link_siblings() after chunking.
        """
        ...

    def _link_siblings(self, chunks: list[Chunk], overlap_lines: int = 3) -> None:
        """
        Wire prev/next references and set overlap line counts between adjacent
        chunks in a flat list.  Call this at the end of chunk().
        """
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk.prev_chunk_idx = i - 1
                chunk.overlap_prefix_lines = min(
                    overlap_lines,
                    chunks[i - 1].line_end - chunks[i - 1].line_start + 1,
                )
            if i < len(chunks) - 1:
                chunk.next_chunk_idx = i + 1
                chunk.overlap_suffix_lines = min(
                    overlap_lines,
                    chunks[i + 1].line_end - chunks[i + 1].line_start + 1,
                )
