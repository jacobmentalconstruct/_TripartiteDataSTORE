"""
Tree-sitter based code chunker for multi-language support.

Provides AST-based chunking for 20+ programming languages using tree-sitter.
Falls back to prose chunker if parsing fails or language is unsupported.

v0.2.0 — Language-tier-aware hierarchy handling.
  Languages are classified into four tiers, each with a dedicated chunking
  strategy that produces correctly annotated semantic_depth, structural_depth,
  and language_tier metadata on every Chunk.

  Tiers:
    deep_semantic   — Python, JS, TS, Java, Go, Rust, C++, C#, etc.
                      Full class → method → nested function hierarchy.
    shallow_semantic — Bash, R, Ruby, PHP, C.
                      Functions only, max semantic depth = 1.
    structural      — JSON, YAML, TOML.
                      Key-value nesting with no code semantics.
    hybrid          — HTML, CSS, XML.
                      Structural markup, not executable code hierarchy.

Chunk hierarchy produced (tier-dependent):
  deep_semantic:
    module/file (summary)
    └── class_def
        └── method_def
    └── function_def
    └── import_block

  shallow_semantic:
    module/file (summary)
    └── function_def
    └── import_block

  structural:
    module/file (summary)
    └── config_section (top-level keys)

  hybrid:
    module/file (summary)
    └── html_section / css_ruleset
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import tree_sitter_language_pack
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

from ..config import MAX_CHUNK_TOKENS, OVERLAP_LINES
from ..pipeline.detect import SourceFile
from ..utils import build_context_prefix, estimate_tokens
from .base import BaseChunker, Chunk, SpanRef


# ── Language Tier Classification ──────────────────────────────────────────────

LANGUAGE_TIERS = {
    # Tier 1: Deep Semantic Hierarchies
    # Full class/method/function nesting with meaningful depth.
    "deep_semantic": {
        "languages": [
            "python", "javascript", "typescript", "java", "go",
            "rust", "cpp", "c_sharp", "kotlin", "scala", "swift",
        ],
        "max_depth": 4,          # module → class → method → nested function
        "chunk_strategy": "hierarchical",
        "meaningful_depth": True,
    },

    # Tier 2: Shallow Semantic Hierarchies
    # Functions and simple structures, limited nesting.
    "shallow_semantic": {
        "languages": ["bash", "r", "ruby", "php", "c"],
        "max_depth": 2,          # module → function
        "chunk_strategy": "flat",
        "meaningful_depth": True,
    },

    # Tier 3: Structural Only
    # Key-value nesting with no semantic hierarchy.
    "structural": {
        "languages": ["json", "yaml", "toml"],
        "max_depth": None,       # unlimited nesting but no semantic meaning
        "chunk_strategy": "structural",
        "meaningful_depth": False,
    },

    # Tier 4: Hybrid (Markup + Structure)
    # DOM trees or rule sets — not traditional code hierarchy.
    "hybrid": {
        "languages": ["html", "css", "xml"],
        "max_depth": 3,
        "chunk_strategy": "markup",
        "meaningful_depth": False,
    },
}


def get_language_tier(language: str) -> dict:
    """
    Get the tier configuration for a language.

    Returns a dict with keys: tier, languages, max_depth, chunk_strategy,
    meaningful_depth.
    """
    for tier_name, config in LANGUAGE_TIERS.items():
        if language in config["languages"]:
            return {**config, "tier": tier_name}

    # Default: treat unknown languages as shallow_semantic
    return {
        "tier": "shallow_semantic",
        "languages": [],
        "max_depth": 2,
        "chunk_strategy": "flat",
        "meaningful_depth": True,
    }


# ── Language → Grammar Mapping ─────────────────────────────────────────────────

# Maps file extensions to tree-sitter language names
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".cs": "c_sharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".r": "r",
    ".R": "r",
}


# ── Tree-sitter Query Patterns ─────────────────────────────────────────────────

# Generic patterns that work across C-style languages
# Each pattern is tried in order; first match wins for that node type

FUNCTION_QUERIES = {
    "python": """
        (function_definition
            name: (identifier) @name) @function
        (decorated_definition
            definition: (function_definition
                name: (identifier) @name)) @function
    """,
    "javascript": """
        (function_declaration
            name: (identifier) @name) @function
        (function
            name: (identifier) @name) @function
        (method_definition
            name: (property_identifier) @name) @method
        (arrow_function) @function
    """,
    "typescript": """
        (function_declaration
            name: (identifier) @name) @function
        (function_signature
            name: (identifier) @name) @function
        (method_definition
            name: (property_identifier) @name) @method
        (method_signature
            name: (property_identifier) @name) @method
        (arrow_function) @function
    """,
    "java": """
        (method_declaration
            name: (identifier) @name) @method
        (constructor_declaration
            name: (identifier) @name) @constructor
    """,
    "go": """
        (function_declaration
            name: (identifier) @name) @function
        (method_declaration
            name: (field_identifier) @name) @method
    """,
    "rust": """
        (function_item
            name: (identifier) @name) @function
        (function_signature_item
            name: (identifier) @name) @function
    """,
    "c": """
        (function_definition
            declarator: (function_declarator
                declarator: (identifier) @name)) @function
    """,
    "cpp": """
        (function_definition
            declarator: (function_declarator
                declarator: (identifier) @name)) @function
        (function_definition
            declarator: (function_declarator
                declarator: (qualified_identifier
                    name: (identifier) @name))) @function
    """,
    "c_sharp": """
        (method_declaration
            name: (identifier) @name) @method
        (constructor_declaration
            name: (identifier) @name) @constructor
    """,
    "ruby": """
        (method
            name: (identifier) @name) @method
        (singleton_method
            name: (identifier) @name) @method
    """,
    "php": """
        (function_definition
            name: (name) @name) @function
        (method_declaration
            name: (name) @name) @method
    """,
    "swift": """
        (function_declaration
            name: (simple_identifier) @name) @function
    """,
    "kotlin": """
        (function_declaration
            (simple_identifier) @name) @function
    """,
    "scala": """
        (function_definition
            name: (identifier) @name) @function
    """,
    "bash": """
        (function_definition
            name: (word) @name) @function
    """,
}


CLASS_QUERIES = {
    "python": """
        (class_definition
            name: (identifier) @name) @class
    """,
    "javascript": """
        (class_declaration
            name: (identifier) @name) @class
    """,
    "typescript": """
        (class_declaration
            name: (type_identifier) @name) @class
    """,
    "java": """
        (class_declaration
            name: (identifier) @name) @class
        (interface_declaration
            name: (identifier) @name) @interface
        (enum_declaration
            name: (identifier) @name) @enum
    """,
    "go": """
        (type_declaration
            (type_spec
                name: (type_identifier) @name)) @type
    """,
    "rust": """
        (struct_item
            name: (type_identifier) @name) @struct
        (enum_item
            name: (type_identifier) @name) @enum
        (trait_item
            name: (type_identifier) @name) @trait
        (impl_item) @impl
    """,
    "c": """
        (struct_specifier
            name: (type_identifier) @name) @struct
        (enum_specifier
            name: (type_identifier) @name) @enum
    """,
    "cpp": """
        (class_specifier
            name: (type_identifier) @name) @class
        (struct_specifier
            name: (type_identifier) @name) @struct
    """,
    "c_sharp": """
        (class_declaration
            name: (identifier) @name) @class
        (interface_declaration
            name: (identifier) @name) @interface
        (struct_declaration
            name: (identifier) @name) @struct
    """,
    "ruby": """
        (class
            name: (constant) @name) @class
        (module
            name: (constant) @name) @module
    """,
    "php": """
        (class_declaration
            name: (name) @name) @class
        (interface_declaration
            name: (name) @name) @interface
        (trait_declaration
            name: (name) @name) @trait
    """,
    "swift": """
        (class_declaration
            name: (type_identifier) @name) @class
        (struct_declaration
            name: (type_identifier) @name) @struct
        (enum_declaration
            name: (type_identifier) @name) @enum
        (protocol_declaration
            name: (type_identifier) @name) @protocol
    """,
    "kotlin": """
        (class_declaration
            (type_identifier) @name) @class
        (object_declaration
            (type_identifier) @name) @object
    """,
    "scala": """
        (class_definition
            name: (identifier) @name) @class
        (object_definition
            name: (identifier) @name) @object
        (trait_definition
            name: (identifier) @name) @trait
    """,
}


IMPORT_QUERIES = {
    "python": """
        (import_statement) @import
        (import_from_statement) @import
    """,
    "javascript": """
        (import_statement) @import
    """,
    "typescript": """
        (import_statement) @import
    """,
    "java": """
        (import_declaration) @import
    """,
    "go": """
        (import_declaration) @import
    """,
    "rust": """
        (use_declaration) @import
    """,
    "c": """
        (preproc_include) @import
    """,
    "cpp": """
        (preproc_include) @import
    """,
    "c_sharp": """
        (using_directive) @import
    """,
    "ruby": """
        (call
            method: (identifier) @method
            (#match? @method "^(require|require_relative|load|import)$")) @import
    """,
    "php": """
        (namespace_use_declaration) @import
    """,
    "swift": """
        (import_declaration) @import
    """,
    "kotlin": """
        (import_header) @import
    """,
    "scala": """
        (import_declaration) @import
    """,
}


# ── TreeSitterChunker ──────────────────────────────────────────────────────────

class TreeSitterChunker(BaseChunker):
    """
    Tree-sitter based chunker supporting 20+ programming languages.

    Uses tree-sitter AST parsing to identify code structure (functions, classes,
    methods, imports) and create semantically meaningful chunks.

    v0.2.0: Dispatches to tier-specific chunking strategies:
      - _chunk_hierarchical()  for deep_semantic  (Python, Java, TS, etc.)
      - _chunk_flat()          for shallow_semantic (Bash, R, C, etc.)
      - _chunk_structural()    for structural (JSON, YAML, TOML)
      - _chunk_markup()        for hybrid (HTML, CSS, XML)

    Falls back to line-window chunking if parsing fails.
    """

    def __init__(self, language: str):
        """
        Initialize chunker for a specific language.

        Args:
            language: Tree-sitter language name (e.g., 'python', 'javascript')
        """
        self.language = language
        self.tier_config = get_language_tier(language)
        self._parser = None
        self._tree = None

    def _get_parser(self):
        """Lazy-load the tree-sitter parser for this language."""
        if self._parser is not None:
            return self._parser

        if not TREE_SITTER_AVAILABLE:
            return None

        try:
            from tree_sitter import Parser
            from tree_sitter_language_pack import get_language

            parser = Parser()
            parser.set_language(get_language(self.language))
            self._parser = parser
            return parser
        except Exception:
            return None

    # ── Main dispatch ─────────────────────────────────────────────────────────

    def chunk(self, source: SourceFile) -> list[Chunk]:
        """
        Parse source file and extract chunks using tree-sitter AST.
        Dispatches to the tier-specific strategy based on language classification.
        Falls back to line-window chunker if parsing fails.
        """
        parser = self._get_parser()
        if parser is None:
            return _fallback_line_chunker(source)

        try:
            tree = parser.parse(bytes(source.text, "utf-8"))
            self._tree = tree
            root = tree.root_node

            if root.has_error:
                return _fallback_line_chunker(source)

        except Exception:
            return _fallback_line_chunker(source)

        # Dispatch to tier-specific strategy
        strategy = self.tier_config["chunk_strategy"]

        if strategy == "hierarchical":
            chunks = self._chunk_hierarchical(source)
        elif strategy == "flat":
            chunks = self._chunk_flat(source)
        elif strategy == "structural":
            chunks = self._chunk_structural(source)
        elif strategy == "markup":
            chunks = self._chunk_markup(source)
        else:
            chunks = _fallback_line_chunker(source)

        # Fallback if strategy produced nothing
        if not chunks:
            return _fallback_line_chunker(source)

        self._link_siblings(chunks, OVERLAP_LINES)
        return chunks

    # ── Strategy: Hierarchical (deep_semantic) ────────────────────────────────

    def _chunk_hierarchical(self, source: SourceFile) -> list[Chunk]:
        """
        Full hierarchical chunking for languages like Python, Java, C++, etc.
        Respects class → method → nested function hierarchy.
        semantic_depth matches structural_depth (all depth is meaningful).
        """
        chunks: list[Chunk] = []
        base_path = [source.path.name]
        tier = self.tier_config["tier"]

        # Extract imports
        import_chunks = self._extract_imports(source, base_path)
        chunks.extend(import_chunks)

        # Extract classes and their methods
        class_chunks = self._extract_classes(source, base_path)
        chunks.extend(class_chunks)

        # Extract top-level functions
        function_chunks = self._extract_functions(source, base_path, depth=1)
        chunks.extend(function_chunks)

        # Create module summary
        summary = self._create_summary_chunk(source, base_path, chunks)
        if summary:
            chunks.insert(0, summary)

        # Annotate all chunks with tier metadata
        for chunk in chunks:
            chunk.language_tier = tier
            chunk.semantic_depth = chunk.depth       # depth IS semantic for these
            chunk.structural_depth = chunk.depth

        return chunks

    # ── Strategy: Flat (shallow_semantic) ─────────────────────────────────────

    def _chunk_flat(self, source: SourceFile) -> list[Chunk]:
        """
        Flat chunking for languages like Bash, R, C.
        Just functions, no class hierarchy.  Max semantic depth = 1.
        """
        chunks: list[Chunk] = []
        base_path = [source.path.name]
        tier = self.tier_config["tier"]

        # Extract imports if present
        import_chunks = self._extract_imports(source, base_path)
        chunks.extend(import_chunks)

        # Extract all functions at top level (no class extraction)
        function_chunks = self._extract_functions(source, base_path, depth=1)
        chunks.extend(function_chunks)

        # Create module summary
        summary = self._create_summary_chunk(source, base_path, chunks)
        if summary:
            chunks.insert(0, summary)

        # Annotate — cap semantic depth at 1
        for chunk in chunks:
            chunk.language_tier = tier
            chunk.structural_depth = chunk.depth
            chunk.semantic_depth = min(chunk.depth, 1)

        return chunks

    # ── Strategy: Structural (JSON, YAML, TOML) ──────────────────────────────

    def _chunk_structural(self, source: SourceFile) -> list[Chunk]:
        """
        Structural chunking for data formats like JSON, YAML, TOML.
        Chunks by top-level keys/sections.  No semantic meaning — just structure.
        """
        chunks: list[Chunk] = []
        base_path = [source.path.name]
        tier = self.tier_config["tier"]

        if not self._tree:
            return []

        root = self._tree.root_node

        # Language-specific top-level key extraction
        if self.language == "json":
            chunks = self._extract_json_sections(source, root, base_path)
        elif self.language == "yaml":
            chunks = self._extract_yaml_sections(source, root, base_path)
        elif self.language == "toml":
            chunks = self._extract_toml_sections(source, root, base_path)
        else:
            return []

        # If no sections found, create a single chunk for the whole file
        if not chunks:
            chunks = [Chunk(
                chunk_type="config_file",
                name=source.path.stem,
                spans=[SpanRef(source.file_cid, 0, len(source.lines) - 1)],
                source=source,
                heading_path=base_path,
                depth=0,
            )]

        # Create summary for multi-section files
        if len(chunks) > 1:
            summary = self._create_summary_chunk(source, base_path, chunks)
            if summary:
                chunks.insert(0, summary)

        # Annotate — semantic depth is always 0 for data formats
        for chunk in chunks:
            chunk.language_tier = tier
            chunk.structural_depth = chunk.depth
            chunk.semantic_depth = 0

        return chunks

    def _extract_json_sections(
        self, source: SourceFile, root, base_path: list[str]
    ) -> list[Chunk]:
        """Extract top-level keys from a JSON object."""
        chunks: list[Chunk] = []

        # JSON root is typically a single object or array
        for child in root.children:
            if child.type == "object":
                # Extract each top-level key-value pair
                for pair in child.children:
                    if pair.type == "pair":
                        key_node = pair.child_by_field_name("key")
                        if key_node:
                            key_text = key_node.text.decode("utf-8").strip('"\'')
                            start_line = pair.start_point[0]
                            end_line = pair.end_point[0]
                            chunks.append(Chunk(
                                chunk_type="config_section",
                                name=key_text,
                                spans=[SpanRef(source.file_cid, start_line, end_line)],
                                source=source,
                                heading_path=base_path + [key_text],
                                depth=1,
                            ))
            elif child.type == "array":
                # Top-level array — chunk as one unit
                chunks.append(Chunk(
                    chunk_type="config_section",
                    name="root_array",
                    spans=[SpanRef(source.file_cid, child.start_point[0], child.end_point[0])],
                    source=source,
                    heading_path=base_path + ["root_array"],
                    depth=1,
                ))

        return chunks

    def _extract_yaml_sections(
        self, source: SourceFile, root, base_path: list[str]
    ) -> list[Chunk]:
        """Extract top-level keys from a YAML document."""
        chunks: list[Chunk] = []

        for child in root.children:
            # YAML top-level is typically a block_mapping or block_mapping_pair
            if child.type in ("block_mapping", "block_mapping_pair"):
                if child.type == "block_mapping":
                    # Iterate its pairs
                    for pair in child.children:
                        self._yaml_pair_to_chunk(pair, source, base_path, chunks)
                else:
                    self._yaml_pair_to_chunk(child, source, base_path, chunks)

        return chunks

    def _yaml_pair_to_chunk(
        self, pair, source: SourceFile, base_path: list[str], chunks: list[Chunk]
    ) -> None:
        """Convert a single YAML mapping pair to a chunk."""
        if pair.type != "block_mapping_pair":
            return

        key_node = pair.child_by_field_name("key")
        if key_node:
            key_text = key_node.text.decode("utf-8").strip()
            start_line = pair.start_point[0]
            end_line = pair.end_point[0]
            chunks.append(Chunk(
                chunk_type="config_section",
                name=key_text,
                spans=[SpanRef(source.file_cid, start_line, end_line)],
                source=source,
                heading_path=base_path + [key_text],
                depth=1,
            ))

    def _extract_toml_sections(
        self, source: SourceFile, root, base_path: list[str]
    ) -> list[Chunk]:
        """Extract tables/sections from a TOML document."""
        chunks: list[Chunk] = []

        for child in root.children:
            if child.type == "table":
                # [section_name]
                header = None
                for sub in child.children:
                    if sub.type in ("bare_key", "dotted_key", "quoted_key"):
                        header = sub.text.decode("utf-8")
                        break
                name = header or "table"
                start_line = child.start_point[0]
                end_line = child.end_point[0]
                chunks.append(Chunk(
                    chunk_type="config_section",
                    name=name,
                    spans=[SpanRef(source.file_cid, start_line, end_line)],
                    source=source,
                    heading_path=base_path + [name],
                    depth=1,
                ))
            elif child.type == "pair":
                # Top-level key = value (outside any table)
                key_node = child.child_by_field_name("key")
                if key_node:
                    key_text = key_node.text.decode("utf-8")
                    start_line = child.start_point[0]
                    end_line = child.end_point[0]
                    chunks.append(Chunk(
                        chunk_type="config_entry",
                        name=key_text,
                        spans=[SpanRef(source.file_cid, start_line, end_line)],
                        source=source,
                        heading_path=base_path + [key_text],
                        depth=1,
                    ))

        return chunks

    # ── Strategy: Markup (HTML, CSS, XML) ─────────────────────────────────────

    def _chunk_markup(self, source: SourceFile) -> list[Chunk]:
        """
        Markup chunking for HTML, CSS, XML.
        HTML: chunks by semantic HTML5 elements.
        CSS:  chunks by rule sets.
        XML:  chunks by top-level elements.
        """
        chunks: list[Chunk] = []
        base_path = [source.path.name]
        tier = self.tier_config["tier"]

        if not self._tree:
            return []

        if self.language == "html":
            chunks = self._chunk_html(source, base_path)
        elif self.language == "css":
            chunks = self._chunk_css(source, base_path)
        elif self.language == "xml":
            chunks = self._chunk_xml(source, base_path)

        # Fallback: whole file as one chunk
        if not chunks:
            chunks = [Chunk(
                chunk_type="markup_file",
                name=source.path.stem,
                spans=[SpanRef(source.file_cid, 0, len(source.lines) - 1)],
                source=source,
                heading_path=base_path,
                depth=0,
            )]

        # Create summary for multi-section files
        if len(chunks) > 1:
            summary = self._create_summary_chunk(source, base_path, chunks)
            if summary:
                chunks.insert(0, summary)

        # Annotate — depth exists but isn't semantic
        for chunk in chunks:
            chunk.language_tier = tier
            chunk.structural_depth = chunk.depth
            chunk.semantic_depth = 0

        return chunks

    def _chunk_html(self, source: SourceFile, base_path: list[str]) -> list[Chunk]:
        """HTML-specific chunking: group by semantic HTML5 elements."""
        chunks: list[Chunk] = []

        # Semantic HTML5 container elements worth chunking
        semantic_tags = {
            "head", "header", "nav", "main", "section",
            "article", "aside", "footer", "form",
        }

        # Walk the tree looking for elements with semantic tag names
        self._find_html_elements(
            self._tree.root_node, source, base_path, semantic_tags, chunks
        )

        return chunks

    def _find_html_elements(
        self, node, source: SourceFile, base_path: list[str],
        semantic_tags: set, chunks: list[Chunk], depth: int = 0,
    ) -> None:
        """Recursively find semantic HTML elements and create chunks."""
        if node.type == "element":
            # Check the tag name
            tag_name = self._get_html_tag_name(node)
            if tag_name and tag_name.lower() in semantic_tags:
                start_line = node.start_point[0]
                end_line = node.end_point[0]
                label = f"<{tag_name.lower()}>"

                chunks.append(Chunk(
                    chunk_type="html_section",
                    name=label,
                    spans=[SpanRef(source.file_cid, start_line, end_line)],
                    source=source,
                    heading_path=base_path + [label],
                    depth=1,
                ))
                return  # Don't recurse into children of matched elements

        # Recurse into children
        for child in node.children:
            self._find_html_elements(
                child, source, base_path, semantic_tags, chunks, depth + 1
            )

    def _get_html_tag_name(self, element_node) -> Optional[str]:
        """Extract the tag name from an HTML element node."""
        for child in element_node.children:
            if child.type == "start_tag":
                for tag_child in child.children:
                    if tag_child.type == "tag_name":
                        return tag_child.text.decode("utf-8")
            elif child.type == "self_closing_tag":
                for tag_child in child.children:
                    if tag_child.type == "tag_name":
                        return tag_child.text.decode("utf-8")
        return None

    def _chunk_css(self, source: SourceFile, base_path: list[str]) -> list[Chunk]:
        """CSS-specific chunking: group by rule sets and @-rules."""
        chunks: list[Chunk] = []
        root = self._tree.root_node

        for child in root.children:
            if child.type == "rule_set":
                # .class { ... } or #id { ... }
                selectors_node = child.child_by_field_name("selectors")
                if not selectors_node:
                    # Fallback: take first child text as selector
                    for sub in child.children:
                        if sub.type != "block":
                            selectors_node = sub
                            break

                selector_text = "rule"
                if selectors_node:
                    selector_text = selectors_node.text.decode("utf-8").strip()
                    # Truncate long selectors
                    if len(selector_text) > 60:
                        selector_text = selector_text[:57] + "..."

                chunks.append(Chunk(
                    chunk_type="css_ruleset",
                    name=selector_text,
                    spans=[SpanRef(source.file_cid, child.start_point[0], child.end_point[0])],
                    source=source,
                    heading_path=base_path + [selector_text],
                    depth=1,
                ))

            elif child.type in ("at_rule", "media_statement", "import_statement",
                                "charset_statement", "keyframes_statement"):
                # @media, @import, @charset, @keyframes, etc.
                rule_text = child.text.decode("utf-8").split("{")[0].strip()
                if len(rule_text) > 60:
                    rule_text = rule_text[:57] + "..."

                chunks.append(Chunk(
                    chunk_type="css_at_rule",
                    name=rule_text,
                    spans=[SpanRef(source.file_cid, child.start_point[0], child.end_point[0])],
                    source=source,
                    heading_path=base_path + [rule_text],
                    depth=1,
                ))

        return chunks

    def _chunk_xml(self, source: SourceFile, base_path: list[str]) -> list[Chunk]:
        """XML-specific chunking: group by top-level child elements."""
        chunks: list[Chunk] = []
        root = self._tree.root_node

        for child in root.children:
            if child.type == "element":
                tag_name = self._get_html_tag_name(child)
                if tag_name:
                    label = f"<{tag_name}>"
                    chunks.append(Chunk(
                        chunk_type="xml_element",
                        name=label,
                        spans=[SpanRef(source.file_cid, child.start_point[0], child.end_point[0])],
                        source=source,
                        heading_path=base_path + [label],
                        depth=1,
                    ))

        return chunks

    # ── Shared extraction helpers (used by hierarchical & flat strategies) ─────

    def _extract_imports(self, source: SourceFile, base_path: list[str]) -> list[Chunk]:
        """Extract import/include statements and consolidate into one chunk."""
        query_str = IMPORT_QUERIES.get(self.language)
        if not query_str or not self._tree:
            return []

        try:
            from tree_sitter_language_pack import get_language
            language = get_language(self.language)
            query = language.query(query_str)
            captures = query.captures(self._tree.root_node)

            if not captures:
                return []

            # Collect all line numbers covered by imports
            import_lines: set[int] = set()
            for node, _ in captures:
                start_line = node.start_point[0]
                end_line = node.end_point[0]
                import_lines.update(range(start_line, end_line + 1))

            if not import_lines:
                return []

            sorted_lines = sorted(import_lines)
            lo, hi = sorted_lines[0], sorted_lines[-1]

            return [Chunk(
                chunk_type="import_block",
                name="imports",
                spans=[SpanRef(source.file_cid, lo, hi)],
                source=source,
                heading_path=base_path + ["imports"],
                depth=1,
            )]

        except Exception:
            return []

    def _extract_classes(self, source: SourceFile, base_path: list[str]) -> list[Chunk]:
        """Extract class definitions and their methods."""
        query_str = CLASS_QUERIES.get(self.language)
        if not query_str or not self._tree:
            return []

        chunks: list[Chunk] = []

        try:
            from tree_sitter_language_pack import get_language
            language = get_language(self.language)
            query = language.query(query_str)
            captures = query.captures(self._tree.root_node)

            # Group captures by class node
            class_nodes = {}
            for node, capture_name in captures:
                if capture_name == "name":
                    continue
                class_nodes[node.id] = (node, capture_name)

            for node, chunk_type in class_nodes.values():
                name = self._get_node_name(node)
                if not name:
                    continue

                start_line = node.start_point[0]
                end_line = node.end_point[0]

                class_path = base_path + [f"class {name}"]

                # Create class header chunk (signature + docstring, not methods)
                class_chunk = Chunk(
                    chunk_type=chunk_type,
                    name=name,
                    spans=[SpanRef(source.file_cid, start_line, min(start_line + 10, end_line))],
                    source=source,
                    heading_path=class_path,
                    depth=1,
                )
                chunks.append(class_chunk)

                # Extract methods within this class
                method_chunks = self._extract_methods(source, node, class_path, depth=2)
                chunks.extend(method_chunks)

        except Exception:
            pass

        return chunks

    def _extract_methods(
        self,
        source: SourceFile,
        class_node,
        parent_path: list[str],
        depth: int
    ) -> list[Chunk]:
        """Extract method definitions from within a class node."""
        query_str = FUNCTION_QUERIES.get(self.language)
        if not query_str:
            return []

        chunks: list[Chunk] = []

        try:
            from tree_sitter_language_pack import get_language
            language = get_language(self.language)
            query = language.query(query_str)

            # Only query within the class body
            captures = query.captures(class_node)

            method_nodes = {}
            for node, capture_name in captures:
                if capture_name == "name":
                    continue
                # Ensure this is a direct child method, not nested
                if node.parent and node.parent.id == class_node.id:
                    method_nodes[node.id] = node

            for node in method_nodes.values():
                name = self._get_node_name(node)
                if not name:
                    continue

                start_line = node.start_point[0]
                end_line = node.end_point[0]

                chunks.append(Chunk(
                    chunk_type="method_def",
                    name=name,
                    spans=[SpanRef(source.file_cid, start_line, end_line)],
                    source=source,
                    heading_path=parent_path + [f"{name}()"],
                    depth=depth,
                ))

        except Exception:
            pass

        return chunks

    def _extract_functions(
        self,
        source: SourceFile,
        base_path: list[str],
        depth: int = 1
    ) -> list[Chunk]:
        """Extract top-level function definitions."""
        query_str = FUNCTION_QUERIES.get(self.language)
        if not query_str or not self._tree:
            return []

        chunks: list[Chunk] = []

        try:
            from tree_sitter_language_pack import get_language
            language = get_language(self.language)
            query = language.query(query_str)
            captures = query.captures(self._tree.root_node)

            # Filter to top-level functions only (not within classes)
            function_nodes = {}
            for node, capture_name in captures:
                if capture_name == "name":
                    continue

                # Check if this is a top-level function
                parent = node.parent
                while parent:
                    if parent.type in ("class_definition", "class_declaration",
                                      "class_specifier", "struct_specifier"):
                        break
                    parent = parent.parent
                else:
                    # No class parent found — it's top-level
                    function_nodes[node.id] = node

            for node in function_nodes.values():
                name = self._get_node_name(node)
                if not name:
                    continue

                start_line = node.start_point[0]
                end_line = node.end_point[0]

                chunks.append(Chunk(
                    chunk_type="function_def",
                    name=name,
                    spans=[SpanRef(source.file_cid, start_line, end_line)],
                    source=source,
                    heading_path=base_path + [f"{name}()"],
                    depth=depth,
                ))

        except Exception:
            pass

        return chunks

    def _get_node_name(self, node) -> Optional[str]:
        """Extract the name identifier from a node."""
        # Try to find the name child
        for child in node.children:
            if child.type in ("identifier", "property_identifier", "field_identifier",
                             "type_identifier", "simple_identifier", "name", "word",
                             "constant"):
                return child.text.decode("utf-8")

        # For some languages, the name might be nested differently
        name_child = node.child_by_field_name("name")
        if name_child:
            return name_child.text.decode("utf-8")

        return None

    def _create_summary_chunk(
        self,
        source: SourceFile,
        base_path: list[str],
        chunks: list[Chunk]
    ) -> Optional[Chunk]:
        """Create a module-level summary chunk with docstring and overview."""
        # Get first 20 lines or until first function/class
        first_code_line = min((c.line_start for c in chunks), default=len(source.lines))
        summary_end = min(20, first_code_line)

        if summary_end <= 1:
            return None

        return Chunk(
            chunk_type="module",
            name=source.path.stem,
            spans=[SpanRef(source.file_cid, 0, summary_end - 1)],
            source=source,
            heading_path=base_path,
            depth=0,
        )


# ── Fallback Chunker ───────────────────────────────────────────────────────────

def _fallback_line_chunker(source: SourceFile) -> list[Chunk]:
    """
    Fallback line-window chunker when tree-sitter parsing fails.
    Creates chunks of ~500 token windows with overlap.
    """
    chunks: list[Chunk] = []
    lines = source.lines
    target_tokens = MAX_CHUNK_TOKENS
    window_lines = max(20, target_tokens // 5)  # Rough estimate

    i = 0
    chunk_idx = 0
    while i < len(lines):
        end = min(i + window_lines, len(lines))

        chunks.append(Chunk(
            chunk_type="code_block",
            name=f"block_{chunk_idx}",
            spans=[SpanRef(source.file_cid, i, end - 1)],
            source=source,
            heading_path=[source.path.name, f"lines {i+1}-{end}"],
            depth=1,
            # Fallback chunks get unknown tier
            semantic_depth=0,
            structural_depth=1,
            language_tier="unknown",
        ))

        chunk_idx += 1
        i += window_lines - OVERLAP_LINES  # Overlap windows

    return chunks


# ── Public API ─────────────────────────────────────────────────────────────────

def get_treesitter_chunker(source: SourceFile) -> Optional[TreeSitterChunker]:
    """
    Create a TreeSitterChunker for the given source file.
    Returns None if language is not supported or tree-sitter is unavailable.
    """
    if not TREE_SITTER_AVAILABLE:
        return None

    ext = source.path.suffix.lower()
    language = EXTENSION_TO_LANGUAGE.get(ext)

    if language is None:
        return None

    return TreeSitterChunker(language)


def is_language_supported(extension: str) -> bool:
    """Check if an extension is supported by tree-sitter."""
    return extension.lower() in EXTENSION_TO_LANGUAGE and TREE_SITTER_AVAILABLE
