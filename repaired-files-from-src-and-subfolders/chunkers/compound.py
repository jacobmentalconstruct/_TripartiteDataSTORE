"""
Compound document chunker for multi-file dumps and concatenated sources.

Detects compound documents (multiple files concatenated into one) using
two layers of analysis drawn from the Tripartite architecture:

  Layer 1 (Deterministic) — Exact delimiter pattern matching:
    Scans for repeating separator lines (dashes, equals, etc.) followed
    by FILE: headers.  Works for all structured file dump formats.

  Layer 1.5 (CID Repetition) — Verbatim-layer structure discovery:
    When no known delimiter pattern matches, falls back to detecting
    lines that repeat at roughly regular intervals.  High-frequency
    identical lines are structural delimiters.  This is a pure Layer 1
    technique — no vectors, no ML, just content-addressed deduplication
    revealing document structure.

Once sections are identified, each is routed through the appropriate
sub-chunker based on the detected language of the virtual file:
  - Code files → TreeSitterChunker (if available) → fallback to ProseChunker
  - Prose/text → ProseChunker
  - Structured  → TreeSitterChunker (JSON/YAML/TOML/XML) → fallback to ProseChunker

All sub-chunk spans are remapped to reference the original compound
document's line numbers and file_cid, so the verbatim layer stays correct.

v0.3.0 — Initial implementation.
v0.3.1 — P2 hardening:
  - _get_sub_chunker() now uses explicit chunker registry instead of fragile
    dynamic importlib scanning.
  - _detect_repetition_sections() handles overlapping delimiters, very short
    sections (< 2 content lines), and sections with no content between delimiters.
  - _remap_chunks() clamps all span coordinates to valid compound doc range.
  - is_compound_document() adds a file-size floor (< 10 lines → not compound).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import MAX_CHUNK_TOKENS, OVERLAP_LINES
from ..pipeline.detect import SourceFile
from ..utils import estimate_tokens
from .base import BaseChunker, Chunk, SpanRef


# ── Delimiter detection patterns ──────────────────────────────────────────────

# Separator lines: 40+ repeated characters (dashes, equals, hash, etc.)
_SEPARATOR_RE = re.compile(r'^[-=~#*_]{40,}$')

# Header lines that name a file
_FILE_HEADER_PATTERNS = [
    re.compile(r'^FILE:\s*(.+)$', re.IGNORECASE),
    re.compile(r'^FILENAME:\s*(.+)$', re.IGNORECASE),
    re.compile(r'^PATH:\s*(.+)$', re.IGNORECASE),
    re.compile(r'^---\s+(.+\.\w+)\s+---$'),
    re.compile(r'^===\s+(.+\.\w+)\s+===$'),
    re.compile(r'^//\s*FILE:\s*(.+)$', re.IGNORECASE),
    re.compile(r'^#\s*FILE:\s*(.+)$', re.IGNORECASE),
]

# Language detection from file extension (mirrors detect.py)
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript", ".java": "java",
    ".go": "go", ".rs": "rust", ".c": "c", ".cpp": "cpp",
    ".h": "c", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby",
    ".php": "php", ".swift": "swift", ".kt": "kotlin",
    ".scala": "scala", ".r": "r", ".sh": "bash", ".bash": "bash",
    ".md": "markdown", ".markdown": "markdown", ".rst": "rst",
    ".txt": "text", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".xml": "xml", ".html": "html", ".htm": "html",
    ".css": "css", ".sql": "sql", ".dockerfile": "dockerfile",
}

_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".r", ".sh", ".bash", ".zsh", ".sql",
}

_STRUCTURED_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".toml", ".xml", ".csv", ".tsv",
}

# ── Minimum content lines for a valid section ────────────────────────────────
_MIN_SECTION_CONTENT_LINES = 2


# ── Section data type ─────────────────────────────────────────────────────────

@dataclass
class VirtualFile:
    """A section of a compound document representing one embedded file."""
    name: str                    # filename from the header
    language: Optional[str]      # detected language
    source_type: str             # code | prose | structured
    line_start: int              # inclusive, in compound doc
    line_end: int                # inclusive, in compound doc
    content_start: int           # first content line (after header/delimiter)
    header_lines: list[int] = field(default_factory=list)  # delimiter + header line indices


# ── Public API ────────────────────────────────────────────────────────────────

def is_compound_document(source: SourceFile, min_sections: int = 2) -> bool:
    """
    Quick check: does this source look like a compound document?

    Uses fast heuristic checks without full parsing.  Call this from
    the ingest pipeline's chunker routing to decide whether to use
    CompoundDocumentChunker.
    """
    lines = source.lines
    if len(lines) < 10:
        return False

    # Check 1: Look for FILE: headers near separator lines
    sep_count = 0
    header_count = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _SEPARATOR_RE.match(stripped):
            sep_count += 1
            # Check next non-empty line for a file header
            for j in range(i + 1, min(i + 3, len(lines))):
                for pat in _FILE_HEADER_PATTERNS:
                    if pat.match(lines[j].strip()):
                        header_count += 1
                        break

    if header_count >= min_sections:
        return True

    # Check 2: CID repetition — separator lines appearing frequently
    if sep_count >= min_sections * 2:
        return True

    # Check 3: Fuzzy — look for repeating lines as potential delimiters
    line_freq: dict[str, list[int]] = defaultdict(list)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if len(stripped) > 5:  # skip short/empty lines
            line_freq[stripped].append(i)

    for text, positions in line_freq.items():
        if len(positions) >= min_sections:
            # Check if positions are roughly evenly spaced
            if _is_roughly_periodic(positions, tolerance=0.5):
                return True

    return False


class CompoundDocumentChunker(BaseChunker):
    """
    Chunker for compound documents containing multiple embedded files.

    Detection strategy:
      1. Try exact delimiter pattern matching (fast, precise)
      2. Fall back to CID repetition analysis (fuzzy, general)

    Each detected section is routed through the appropriate sub-chunker,
    with all spans remapped to the compound document's coordinate space.

    Parameters
    ----------
    chunker_registry : dict, optional
        Mapping of (source_type, language) → BaseChunker instance.
        If not provided, uses default resolution via _build_default_registry().
        Pass an explicit registry for testing or to override chunker selection.
    """

    def __init__(self, chunker_registry: Optional[dict] = None):
        self._registry = chunker_registry

    def chunk(self, source: SourceFile) -> list[Chunk]:
        lines = source.lines
        file_name = source.path.name

        # Detect sections
        sections = self._detect_sections(source)

        if not sections:
            # Not actually compound — fall back to prose
            from .prose import ProseChunker
            return ProseChunker().chunk(source)

        all_chunks: list[Chunk] = []

        # Compound document summary chunk
        summary = self._make_compound_summary(source, file_name, sections)
        if summary:
            all_chunks.append(summary)

        # Process each virtual file section
        for section in sections:
            # Virtual file marker chunk
            vf_chunk = self._make_virtual_file_chunk(source, file_name, section)
            all_chunks.append(vf_chunk)

            # Sub-chunk the section content
            sub_chunks = self._chunk_section(source, file_name, section)
            all_chunks.extend(sub_chunks)

        if not all_chunks:
            # Absolute fallback
            all_chunks.append(Chunk(
                chunk_type="document",
                name=file_name,
                spans=[SpanRef(source.file_cid, 0, len(lines) - 1)],
                source=source,
                heading_path=[file_name],
                depth=0,
                language_tier="unknown",
            ))

        self._link_siblings(all_chunks, OVERLAP_LINES)
        return all_chunks

    # ── Section detection ─────────────────────────────────────────────────

    def _detect_sections(self, source: SourceFile) -> list[VirtualFile]:
        """
        Detect embedded file sections in the compound document.

        Strategy:
          1. Pattern-based: look for separator + FILE: header pairs
          2. Repetition-based: find high-frequency lines as delimiters
        """
        # Try pattern-based detection first
        sections = self._detect_pattern_sections(source)
        if sections:
            return sections

        # Fall back to repetition-based detection
        sections = self._detect_repetition_sections(source)
        return sections

    def _detect_pattern_sections(self, source: SourceFile) -> list[VirtualFile]:
        """
        Detect sections using known delimiter patterns.

        Looks for: separator line → FILE: header → (optional separator) → content
        """
        lines = source.lines
        sections: list[VirtualFile] = []
        i = 0

        while i < len(lines):
            stripped = lines[i].strip()

            # Look for a separator line
            if _SEPARATOR_RE.match(stripped):
                header_lines = [i]
                # Check next lines for a file header
                j = i + 1
                while j < min(i + 4, len(lines)):
                    for pat in _FILE_HEADER_PATTERNS:
                        m = pat.match(lines[j].strip())
                        if m:
                            filename = m.group(1).strip()
                            header_lines.append(j)

                            # Check for closing separator
                            content_start = j + 1
                            if content_start < len(lines):
                                if _SEPARATOR_RE.match(lines[content_start].strip()):
                                    header_lines.append(content_start)
                                    content_start += 1

                            # Close previous section if exists
                            if sections:
                                sections[-1].line_end = i - 1

                            # Create new section
                            ext = Path(filename).suffix.lower()
                            sections.append(VirtualFile(
                                name=filename,
                                language=_EXT_TO_LANGUAGE.get(ext),
                                source_type=_classify_extension(ext),
                                line_start=i,
                                line_end=len(lines) - 1,  # will be adjusted
                                content_start=content_start,
                                header_lines=header_lines,
                            ))
                            i = content_start
                            break
                    else:
                        j += 1
                        continue
                    break
                else:
                    i += 1
            else:
                i += 1

        # Fix up: if we have sections, close the last one
        if sections:
            sections[-1].line_end = len(lines) - 1

            # Trim trailing empty lines from each section
            for sec in sections:
                while sec.line_end > sec.content_start:
                    if not lines[sec.line_end].strip():
                        sec.line_end -= 1
                    else:
                        break

        return sections

    def _detect_repetition_sections(self, source: SourceFile) -> list[VirtualFile]:
        """
        Detect sections using CID repetition analysis.

        Finds lines that repeat frequently at roughly regular intervals
        and uses them as section delimiters.  The line immediately after
        each delimiter is treated as the section title.

        v0.3.1 hardening:
          - Filters out overlapping delimiter candidates (same positions ±2 lines)
          - Drops sections with fewer than _MIN_SECTION_CONTENT_LINES content lines
          - Handles adjacent delimiters with no content between them
        """
        lines = source.lines
        if len(lines) < 20:
            return []

        # Find repeating lines
        line_positions: dict[str, list[int]] = defaultdict(list)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if len(stripped) > 3:  # skip very short lines
                line_positions[stripped].append(i)

        # Find the best delimiter candidate:
        # - Appears 3+ times
        # - Looks like a separator (long, repetitive chars) OR appears periodically
        # - Has the highest frequency among candidates
        candidates = []
        for text, positions in line_positions.items():
            if len(positions) < 3:
                continue

            score = len(positions)

            # Bonus for separator-like appearance
            if _SEPARATOR_RE.match(text):
                score *= 3

            # Bonus for roughly periodic spacing
            if _is_roughly_periodic(positions, tolerance=0.5):
                score *= 2

            candidates.append((text, positions, score))

        if not candidates:
            return []

        # Pick the best delimiter
        candidates.sort(key=lambda c: c[2], reverse=True)
        delim_text, delim_positions, _ = candidates[0]

        # ── v0.3.1: Deduplicate near-adjacent delimiter hits ─────────────
        # If two delimiter positions are within 2 lines of each other,
        # keep only the first — they're part of the same header block.
        deduped_positions: list[int] = []
        for pos in sorted(delim_positions):
            if deduped_positions and (pos - deduped_positions[-1]) <= 2:
                continue
            deduped_positions.append(pos)
        delim_positions = deduped_positions

        # Build sections from delimiter positions
        sections: list[VirtualFile] = []
        for idx, pos in enumerate(delim_positions):
            # Find section title: first non-empty, non-delimiter line after pos
            title_line = None
            content_start = pos + 1
            header_lines = [pos]

            for j in range(pos + 1, min(pos + 5, len(lines))):
                stripped = lines[j].strip()
                if not stripped or _SEPARATOR_RE.match(stripped):
                    header_lines.append(j)
                    content_start = j + 1
                    continue

                # Check if this looks like a file header
                for pat in _FILE_HEADER_PATTERNS:
                    m = pat.match(stripped)
                    if m:
                        title_line = m.group(1).strip()
                        header_lines.append(j)
                        content_start = j + 1
                        break
                else:
                    # Use the line itself as the title
                    title_line = stripped
                    header_lines.append(j)
                    content_start = j + 1
                break

            if title_line is None:
                title_line = f"Section {idx + 1}"

            # Clamp content_start to file bounds
            content_start = min(content_start, len(lines) - 1)

            # Determine end: just before the next delimiter, or end of file
            if idx + 1 < len(delim_positions):
                line_end = delim_positions[idx + 1] - 1
            else:
                line_end = len(lines) - 1

            # Close previous section
            if sections:
                sections[-1].line_end = pos - 1

            # ── v0.3.1: Skip sections with no real content ───────────────
            content_line_count = line_end - content_start + 1
            if content_line_count < _MIN_SECTION_CONTENT_LINES:
                continue

            ext = Path(title_line).suffix.lower() if "." in title_line else ""
            sections.append(VirtualFile(
                name=title_line,
                language=_EXT_TO_LANGUAGE.get(ext),
                source_type=_classify_extension(ext) if ext else "prose",
                line_start=pos,
                line_end=line_end,
                content_start=content_start,
                header_lines=header_lines,
            ))

        return sections if len(sections) >= 2 else []

    # ── Sub-chunking ──────────────────────────────────────────────────────

    def _chunk_section(
        self, source: SourceFile, compound_name: str, section: VirtualFile
    ) -> list[Chunk]:
        """
        Route a virtual file section through the appropriate sub-chunker,
        then remap all spans to compound document coordinates.
        """
        lines = source.lines
        section_lines = lines[section.content_start: section.line_end + 1]

        if not section_lines or not any(l.strip() for l in section_lines):
            return []

        # Create a synthetic SourceFile for the sub-chunker
        synthetic = SourceFile(
            path=Path(section.name),
            file_cid=source.file_cid,  # reference the real compound doc
            source_type=section.source_type,
            language=section.language,
            encoding=source.encoding,
            text="\n".join(section_lines),
            lines=section_lines,
            byte_size=sum(len(l.encode("utf-8")) for l in section_lines),
        )

        # Get the appropriate sub-chunker
        sub_chunker = self._get_sub_chunker(section.language, section.source_type)

        try:
            sub_chunks = sub_chunker.chunk(synthetic)
        except Exception as e:
            print(f"[compound] Sub-chunker failed for {section.name}: {e}")
            # Fallback: one chunk for the whole section
            return [Chunk(
                chunk_type="section",
                name=section.name,
                spans=[SpanRef(source.file_cid, section.content_start, section.line_end)],
                source=source,
                heading_path=[compound_name, section.name],
                depth=1,
                language_tier="unknown",
            )]

        # Remap all chunks: offset line numbers, update heading paths, adjust depth
        return self._remap_chunks(
            sub_chunks, source, compound_name, section.name,
            offset=section.content_start,
            max_line=len(lines) - 1,
        )

    def _remap_chunks(
        self,
        sub_chunks: list[Chunk],
        source: SourceFile,
        compound_name: str,
        section_name: str,
        offset: int,
        max_line: int,
    ) -> list[Chunk]:
        """
        Remap sub-chunker output to compound document coordinate space.

        v0.3.1: All span coordinates are clamped to [0, max_line] to prevent
        any out-of-bounds references in the verbatim layer.
        """
        remapped: list[Chunk] = []

        for chunk in sub_chunks:
            # Remap span line numbers with clamping
            new_spans = []
            for span in chunk.spans:
                new_start = max(0, min(span.line_start + offset, max_line))
                new_end = max(0, min(span.line_end + offset, max_line))
                # Ensure start <= end
                if new_start > new_end:
                    new_start, new_end = new_end, new_start
                new_spans.append(SpanRef(
                    source_cid=source.file_cid,
                    line_start=new_start,
                    line_end=new_end,
                    char_start=span.char_start,
                    char_end=span.char_end,
                ))

            # Skip chunks whose spans collapsed to nothing
            if not new_spans:
                continue

            # Build heading path: [compound_name, virtual_file, ...sub_path]
            sub_path = chunk.heading_path
            # Remove the synthetic filename from sub-chunker's heading_path
            # (it would be the filename of the virtual file, already covered)
            if sub_path and sub_path[0] == section_name:
                sub_path = sub_path[1:]

            heading_path = [compound_name, section_name] + sub_path

            remapped.append(Chunk(
                chunk_type=chunk.chunk_type,
                name=chunk.name,
                spans=new_spans,
                source=source,  # point to the real compound doc
                heading_path=heading_path,
                depth=chunk.depth + 1,  # +1 for virtual file level
                parent_chunk_idx=chunk.parent_chunk_idx,
                semantic_depth=chunk.semantic_depth,
                structural_depth=chunk.structural_depth,
                language_tier=chunk.language_tier,
            ))

        return remapped

    def _get_sub_chunker(self, language: Optional[str], source_type: str) -> BaseChunker:
        """
        Get the appropriate chunker for a virtual file section.

        v0.3.1: Uses an explicit registry dict instead of fragile importlib
        scanning.  The registry is built lazily on first call (or injected
        via __init__ for testing).

        Resolution order:
          1. Check registry for exact (source_type, language) key
          2. Check registry for (source_type, None) wildcard key
          3. Fall back to ProseChunker
        """
        registry = self._get_registry()

        # Exact match: (source_type, language)
        key = (source_type, language)
        if key in registry:
            return registry[key]

        # Wildcard match: (source_type, None)
        wildcard = (source_type, None)
        if wildcard in registry:
            return registry[wildcard]

        # Ultimate fallback
        from .prose import ProseChunker
        return ProseChunker()

    def _get_registry(self) -> dict:
        """
        Return the chunker registry, building the default lazily if needed.
        """
        if self._registry is not None:
            return self._registry
        self._registry = self._build_default_registry()
        return self._registry

    @staticmethod
    def _build_default_registry() -> dict:
        """
        Build the default sub-chunker registry.

        Maps (source_type, language) → BaseChunker instance.
        Uses tree-sitter where available, with ProseChunker as fallback.

        The registry uses None as a language wildcard:
          ("code", "python") → TreeSitterChunker("python")    # specific
          ("code", None)     → ProseChunker()                  # fallback for unknown code langs
          ("prose", None)    → ProseChunker()                  # all prose
          ("structured", None) → ProseChunker()                # fallback if no tree-sitter
        """
        from .prose import ProseChunker

        registry: dict = {
            # Fallbacks for each source_type
            ("code", None): ProseChunker(),
            ("prose", None): ProseChunker(),
            ("structured", None): ProseChunker(),
            ("generic", None): ProseChunker(),
        }

        # Try to register tree-sitter chunkers for code languages
        try:
            from .treesitter import get_treesitter_chunker
            _ts_available = True
        except ImportError:
            _ts_available = False

        if _ts_available:
            # Register tree-sitter for all known code languages
            for ext, lang in _EXT_TO_LANGUAGE.items():
                if ext in _CODE_EXTENSIONS:
                    # Create a minimal SourceFile-like probe to check availability
                    # We just need to know if tree-sitter has a grammar for this lang
                    registry[("code", lang)] = _TreeSitterProxy(lang)

                # Structured files that tree-sitter handles
                if ext in _STRUCTURED_EXTENSIONS:
                    registry[("structured", lang)] = _TreeSitterProxy(lang)

            # HTML/CSS/XML — hybrid tier, tree-sitter capable
            for lang in ("html", "css", "xml"):
                registry[("structured", lang)] = _TreeSitterProxy(lang)

        return registry

    # ── Summary / marker chunks ───────────────────────────────────────────

    def _make_compound_summary(
        self, source: SourceFile, file_name: str, sections: list[VirtualFile]
    ) -> Optional[Chunk]:
        """Create a summary chunk listing all embedded files."""
        file_list = ", ".join(s.name for s in sections[:20])
        summary_text = f"Compound document: {file_name} containing {len(sections)} files: {file_list}"

        # Use the first few content lines as the summary span
        lines = source.lines
        end = min(40, len(lines) - 1)
        tokens = 0
        for i, line in enumerate(lines[:end + 1]):
            tokens += estimate_tokens(line)
            if tokens > 256:
                end = i
                break

        return Chunk(
            chunk_type="compound_summary",
            name=f"{file_name} ({len(sections)} files)",
            spans=[SpanRef(source.file_cid, 0, end)],
            source=source,
            heading_path=[file_name, "(summary)"],
            depth=0,
            language_tier="unknown",
        )

    def _make_virtual_file_chunk(
        self, source: SourceFile, compound_name: str, section: VirtualFile
    ) -> Chunk:
        """Create a marker chunk for a virtual file boundary."""
        # Span covers just the header + first few content lines
        content_preview_end = min(section.content_start + 5, section.line_end)

        return Chunk(
            chunk_type="virtual_file",
            name=section.name,
            spans=[SpanRef(source.file_cid, section.line_start, content_preview_end)],
            source=source,
            heading_path=[compound_name, section.name],
            depth=0,
            language_tier=_tier_for_type(section.source_type, section.language),
        )


class _TreeSitterProxy(BaseChunker):
    """
    Lazy proxy that resolves to a TreeSitterChunker at chunk-time.

    This avoids instantiating tree-sitter grammars eagerly during registry
    construction.  If tree-sitter can't handle this language at chunk-time,
    falls back to ProseChunker.
    """

    def __init__(self, language: str):
        self._language = language

    def chunk(self, source: SourceFile) -> list[Chunk]:
        try:
            from .treesitter import get_treesitter_chunker
            ts = get_treesitter_chunker(source)
            if ts is not None:
                return ts.chunk(source)
        except Exception:
            pass
        # Fallback
        from .prose import ProseChunker
        return ProseChunker().chunk(source)


# ── CID repetition analysis utilities (Layer 1 pure) ─────────────────────────

def find_structural_delimiters(
    line_cids: list[str],
    lines: list[str],
    min_freq: int = 3,
) -> list[dict]:
    """
    Identify structural delimiters using content-addressed repetition.

    This is a pure Layer 1 (verbatim) technique: identical lines share
    the same CID.  Lines whose CIDs appear frequently at regular intervals
    are structural delimiters — document section boundaries that emerge
    from the data without any format-specific parsing.

    Returns a list of delimiter candidates sorted by likelihood:
        [{"cid": str, "text": str, "positions": [int], "score": float}, ...]

    Can be used as a curation tool for post-hoc analysis of already-ingested
    documents, or called during chunking for real-time detection.
    """
    cid_positions: dict[str, list[int]] = defaultdict(list)
    cid_text: dict[str, str] = {}

    for i, (cid, line) in enumerate(zip(line_cids, lines)):
        stripped = line.strip()
        if len(stripped) > 3:
            cid_positions[cid].append(i)
            if cid not in cid_text:
                cid_text[cid] = stripped

    candidates = []
    for cid, positions in cid_positions.items():
        if len(positions) < min_freq:
            continue

        text = cid_text.get(cid, "")
        score = float(len(positions))

        # Separator-like lines get a strong bonus
        if _SEPARATOR_RE.match(text):
            score *= 3.0

        # Periodic spacing bonus
        if _is_roughly_periodic(positions, tolerance=0.5):
            score *= 2.0

        # Short lines that aren't separators are less likely to be delimiters
        if len(text) < 10 and not _SEPARATOR_RE.match(text):
            score *= 0.3

        candidates.append({
            "cid": cid,
            "text": text,
            "positions": positions,
            "score": score,
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_roughly_periodic(positions: list[int], tolerance: float = 0.5) -> bool:
    """
    Check if a list of positions are roughly evenly spaced.

    tolerance: max allowed deviation from mean gap as a fraction of mean.
    E.g., tolerance=0.5 means gaps can vary by ±50% of the average gap.
    """
    if len(positions) < 3:
        return False

    gaps = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    mean_gap = sum(gaps) / len(gaps)
    if mean_gap == 0:
        return False

    deviations = [abs(g - mean_gap) / mean_gap for g in gaps]
    return all(d <= tolerance for d in deviations)


def _classify_extension(ext: str) -> str:
    """Classify a file extension as code/prose/structured."""
    if ext in _CODE_EXTENSIONS:
        return "code"
    if ext in _STRUCTURED_EXTENSIONS:
        return "structured"
    return "prose"


def _tier_for_type(source_type: str, language: Optional[str]) -> str:
    """Map source type to a default language tier."""
    if source_type == "code":
        # Deep semantic languages (tree-sitter gives us rich hierarchy)
        deep = {"python", "javascript", "typescript", "java", "go", "rust",
                "cpp", "csharp", "kotlin", "scala", "swift"}
        shallow = {"bash", "ruby", "php", "c", "r", "sql"}
        if language in deep:
            return "deep_semantic"
        if language in shallow:
            return "shallow_semantic"
        return "deep_semantic"  # default for code
    if source_type == "structured":
        return "structural"
    if source_type in ("prose", "markdown", "text"):
        return "unknown"  # prose doesn't have a formal tier yet
    return "unknown"
