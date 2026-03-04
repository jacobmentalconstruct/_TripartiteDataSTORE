"""
src/models/tree_item.py

Unified node representation for the explorer tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TreeItem:
    """Unified node representation for the explorer tree."""
    node_id: str
    node_type: str
    name: str
    parent_id: Optional[str]
    path: str
    depth: int
    file_cid: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]
    language_tier: str
    chunk_id: Optional[str]
    token_count: int = 0
    embed_status: str = ""
    semantic_depth: int = 0
    structural_depth: int = 0
    context_prefix: str = ""
    children: list["TreeItem"] = field(default_factory=list)
