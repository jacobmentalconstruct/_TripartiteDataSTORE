"""Tripartite package."""
from .base import BaseChunker, Chunk, SpanRef
from .code import PythonChunker
from .prose import ProseChunker
from .treesitter import TreeSitterChunker, get_treesitter_chunker  # ← ADD THIS

__all__ = [
    "BaseChunker",
    "Chunk", 
    "SpanRef",
    "PythonChunker",
    "ProseChunker",
    "TreeSitterChunker",      # ← ADD THIS
    "get_treesitter_chunker",  # ← ADD THIS
]