"""
Python AST chunker.

Uses Python's built-in `ast` module to derive chunk boundaries at the
function, method, and class level.  Falls back to a line-window chunker
if the file cannot be parsed (syntax errors, encoding issues).

Chunk hierarchy produced:
  module  (one per file — summary chunk)
  └── class_def
      └── method_def
  └── function_def
  └── import_block  (one chunk for all imports)
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from ..config import MAX_CHUNK_TOKENS, OVERLAP_LINES
from ..pipeline.detect import SourceFile
from ..utils import build_context_prefix, estimate_tokens
from .base import BaseChunker, Chunk, SpanRef


class PythonChunker(BaseChunker):
    """AST-based chunker for Python source files."""

    def chunk(self, source: SourceFile) -> list[Chunk]:
        try:
            tree = ast.parse(source.text)
        except SyntaxError:
            return _fallback_chunker(source)

        chunks: list[Chunk] = []
        file_stem = source.path.stem
        base_path = [source.path.name]

        # Collect import lines first
        import_lines = _collect_import_lines(tree)
        if import_lines:
            lo, hi = import_lines[0], import_lines[-1]
            chunks.append(Chunk(
                chunk_type="import_block",
                name="imports",
                spans=[SpanRef(source.file_cid, lo, hi)],
                source=source,
                heading_path=base_path + ["imports"],
                depth=1,
            ))

        # Walk top-level nodes
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                c = _function_chunk(node, source, base_path, depth=1)
                if c:
                    chunks.append(c)

            elif isinstance(node, ast.ClassDef):
                class_chunks = _class_chunks(node, source, base_path)
                chunks.extend(class_chunks)

        # Module-level summary chunk (docstring + signature overview)
        summary = _module_summary_chunk(tree, source, base_path, chunks)
        if summary:
            chunks.insert(0, summary)

        # If AST yielded nothing useful, fall back to line windows
        if not chunks:
            return _fallback_chunker(source)

        self._link_siblings(chunks, OVERLAP_LINES)
        return chunks


# ── AST helpers ────────────────────────────────────────────────────────────────

def _node_line_range(node: ast.AST) -> tuple[int, int]:
    """Return 0-indexed (start, end) line range for an AST node."""
    return node.lineno - 1, node.end_lineno - 1  # type: ignore[attr-defined]


def _collect_import_lines(tree: ast.Module) -> list[int]:
    """Return sorted 0-indexed line numbers occupied by import statements."""
    lines: set[int] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            lo, hi = _node_line_range(node)
            lines.update(range(lo, hi + 1))
    return sorted(lines)


def _function_chunk(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source: SourceFile,
    parent_path: list[str],
    depth: int,
    parent_chunk: Optional[Chunk] = None,
) -> Optional[Chunk]:
    lo, hi = _node_line_range(node)
    name = node.name
    heading = parent_path + [f"{name}()"]
    return Chunk(
        chunk_type="function_def",
        name=name,
        spans=[SpanRef(source.file_cid, lo, hi)],
        source=source,
        heading_path=heading,
        depth=depth,
    )


def _class_chunks(
    node: ast.ClassDef,
    source: SourceFile,
    parent_path: list[str],
) -> list[Chunk]:
    chunks: list[Chunk] = []
    class_lo, class_hi = _node_line_range(node)
    class_path = parent_path + [f"class {node.name}"]

    # Class header chunk (signature + class docstring only, not methods)
    body_start = class_lo
    # Find where the first method starts so we can trim the class header
    first_method_lo = class_hi
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            first_method_lo = min(first_method_lo, child.lineno - 1)

    header_end = max(body_start, first_method_lo - 1)
    chunks.append(Chunk(
        chunk_type="class_def",
        name=node.name,
        spans=[SpanRef(source.file_cid, class_lo, header_end)],
        source=source,
        heading_path=class_path,
        depth=1,
    ))

    # Method chunks
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            c = _function_chunk(child, source, class_path, depth=2)
            if c:
                chunks.append(c)

    return chunks


def _module_summary_chunk(
    tree: ast.Module,
    source: SourceFile,
    base_path: list[str],
    existing_chunks: list[Chunk],
) -> Optional[Chunk]:
    """
    Build a module-level summary chunk from the module docstring (if present).
    This is the high-recall entry point for the module in vector search.
    """
    docstring = ast.get_docstring(tree)
    if not docstring:
        return None

    # The docstring is the first expression statement in the module body
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            lo, hi = _node_line_range(node)
            return Chunk(
                chunk_type="module_summary",
                name=f"{source.path.stem} (module)",
                spans=[SpanRef(source.file_cid, lo, hi)],
                source=source,
                heading_path=base_path + ["(module docstring)"],
                depth=0,
            )
    return None


# ── Fallback: line-window chunker ──────────────────────────────────────────────

def _fallback_chunker(source: SourceFile) -> list[Chunk]:
    """
    Simple sliding-window chunker for files where AST parsing fails.
    Splits on MAX_CHUNK_TOKENS budget.
    """
    from .prose import ProseChunker
    return ProseChunker().chunk(source)
