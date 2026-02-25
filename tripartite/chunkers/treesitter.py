"""
Tree-sitter based code chunker for multi-language support.

Provides AST-based chunking for 20+ programming languages using tree-sitter.
Falls back to prose chunker if parsing fails or language is unsupported.

Supported languages:
  Python, JavaScript, TypeScript, Java, Go, Rust, C, C++, C#, Ruby,
  PHP, Swift, Kotlin, Scala, Bash, JSON, YAML, TOML, HTML, CSS,
  and more...

Chunk hierarchy produced (language-specific):
  module/file (summary chunk)
  └── class_def
      └── method_def
  └── function_def
  └── import_block (consolidated imports)
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
    
    Falls back to line-window chunking if parsing fails.
    """
    
    def __init__(self, language: str):
        """
        Initialize chunker for a specific language.
        
        Args:
            language: Tree-sitter language name (e.g., 'python', 'javascript')
        """
        self.language = language
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
    
    def chunk(self, source: SourceFile) -> list[Chunk]:
        """
        Parse source file and extract chunks using tree-sitter AST.
        Falls back to line-window chunker if parsing fails.
        """
        parser = self._get_parser()
        if parser is None:
            return _fallback_line_chunker(source)
        
        try:
            # Parse the source code
            tree = parser.parse(bytes(source.text, "utf-8"))
            self._tree = tree
            root = tree.root_node
            
            # Check for parse errors
            if root.has_error:
                return _fallback_line_chunker(source)
            
        except Exception:
            return _fallback_line_chunker(source)
        
        chunks: list[Chunk] = []
        file_stem = source.path.stem
        base_path = [source.path.name]
        
        # Extract imports first
        import_chunks = self._extract_imports(source, base_path)
        chunks.extend(import_chunks)
        
        # Extract classes and their methods
        class_chunks = self._extract_classes(source, base_path)
        chunks.extend(class_chunks)
        
        # Extract top-level functions
        function_chunks = self._extract_functions(source, base_path, depth=1)
        chunks.extend(function_chunks)
        
        # Create module summary chunk
        summary = self._create_summary_chunk(source, base_path, chunks)
        if summary:
            chunks.insert(0, summary)
        
        # Fallback if no chunks found
        if not chunks:
            return _fallback_line_chunker(source)
        
        self._link_siblings(chunks, OVERLAP_LINES)
        return chunks
    
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
                # Get class name from child name node
                name = self._get_node_name(node)
                if not name:
                    continue
                
                start_line = node.start_point[0]
                end_line = node.end_point[0]
                
                class_path = base_path + [f"class {name}"]
                
                # Create class header chunk (just signature + docstring, not methods)
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
                    # No class parent found - it's top-level
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
