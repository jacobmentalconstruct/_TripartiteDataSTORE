"""
Central configuration for the Tripartite ingest pipeline.
All tuneable constants, model registry, and path resolution live here.
"""

import os
from pathlib import Path

# ── Cache directory ────────────────────────────────────────────────────────────
CACHE_DIR = Path(os.environ.get("TRIPARTITE_CACHE", Path.home() / ".tripartite"))
MODELS_DIR = CACHE_DIR / "models"

# ── Model registry ─────────────────────────────────────────────────────────────
# Full list of supported models. Add new entries here as the app grows.
# Fields:
#   role          — 'embedder' | 'extractor'
#   filename      — local cache filename
#   url           — HuggingFace direct download URL
#   display_name  — shown in the Settings UI dropdown
#   description   — one-line capability summary shown under the dropdown
#   dims          — embedding output dimensions (None for generative models)
#   context_length — max input tokens
#   min_size_bytes — minimum acceptable cached file size (truncation guard)
#   sha256        — None to skip hash verification; set to real digest to enable

KNOWN_MODELS: list[dict] = [
    # ── Embedders ──────────────────────────────────────────────────────────────
    {
        "role": "embedder",
        "filename": "nomic-embed-text-v1.5.Q4_K_M.gguf",
        "display_name": "Nomic Embed Text v1.5 (Q4_K_M)",
        "description": "Fast, small, 768-dim. Good all-round default. ~80 MB.",
        "url": (
            "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF"
            "/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf"
        ),
        "sha256": None,
        "dims": 768,
        "context_length": 8192,
        "min_size_bytes": 50_000_000,
    },
    {
        "role": "embedder",
        "filename": "mxbai-embed-large-v1.Q4_K_M.gguf",
        "display_name": "MixedBread Embed Large v1 (Q4_K_M)",
        "description": "Higher quality, 1024-dim. Better for technical docs. ~216 MB.",
        "url": (
            "https://huggingface.co/ChristianAzinn/mxbai-embed-large-v1-gguf"
            "/resolve/main/mxbai-embed-large-v1.Q4_K_M.gguf"
        ),
        "sha256": None,
        "dims": 1024,
        "context_length": 512,
        "min_size_bytes": 150_000_000,
    },
    {
        "role": "embedder",
        "filename": "all-MiniLM-L6-v2-Q4_K_M.gguf",
        "display_name": "All-MiniLM L6 v2 (Q4_K_M)",
        "description": "Tiny and very fast, 384-dim. Good for large codebases. ~22 MB.",
        "url": (
            "https://huggingface.co/second-state/All-MiniLM-L6-v2-Embedding-GGUF"
            "/resolve/main/all-MiniLM-L6-v2-Q4_K_M.gguf"
        ),
        "sha256": None,
        "dims": 384,
        "context_length": 512,
        "min_size_bytes": 15_000_000,
    },
    # ── Extractors ─────────────────────────────────────────────────────────────
    {
        "role": "extractor",
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "display_name": "Qwen 2.5 0.5B Instruct (Q4_K_M)",
        "description": "Tiny and fast. Lower extraction accuracy. ~398 MB.",
        "url": (
            "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF"
            "/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        ),
        "sha256": None,
        "dims": None,
        "context_length": 8192,
        "min_size_bytes": 300_000_000,
    },
    {
        "role": "extractor",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "display_name": "Qwen 2.5 1.5B Instruct (Q4_K_M)",
        "description": "Better entity extraction quality. ~1 GB.",
        "url": (
            "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF"
            "/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
        ),
        "sha256": None,
        "dims": None,
        "context_length": 8192,
        "min_size_bytes": 800_000_000,
    },
]

# Backwards-compat alias — pipeline code that references MODELS["embedder"] still works.
MODELS = {
    "embedder":  next(m for m in KNOWN_MODELS if m["role"] == "embedder"),
    "extractor": next(m for m in KNOWN_MODELS if m["role"] == "extractor"),
}


# ── Chunking ───────────────────────────────────────────────────────────────────
MAX_CHUNK_TOKENS = 512          # hard ceiling for a single chunk
OVERLAP_LINES = 3               # lines of overlap between adjacent prose chunks
SUMMARY_CHUNK_TOKENS = 256      # target size for document-level summary chunks

# ── Embedding ──────────────────────────────────────────────────────────────────
EMBEDDING_DIMS = 768            # must match embedder model output
EMBEDDING_BATCH = 16            # chunks embedded per llama.cpp call batch

# ── Entity extraction ──────────────────────────────────────────────────────────
ENTITY_EXTRACTION_PROMPT = """\
You are a precise information extractor. Given the text below, extract:
1. Named entities (people, organizations, products, technologies, locations)
2. Key concepts and domain terms
3. Relationships between entities where clearly stated

Return ONLY a JSON object with this exact schema — no explanation, no markdown:
{{
  "entities": [
    {{"text": "<entity text>", "type": "<PERSON|ORG|PRODUCT|TECH|LOCATION|CONCEPT>", "salience": <0.0-1.0>}}
  ],
  "relationships": [
    {{"subject": "<entity text>", "predicate": "<verb or relation>", "object": "<entity text>"}}
  ]
}}

TEXT:
{chunk_text}
"""

# ── Graph edge types ───────────────────────────────────────────────────────────
EDGE_TYPES = [
    "PART_OF",
    "PRECEDES",
    "FOLLOWS",
    "MENTIONS",
    "ELABORATES",
    "CONTRADICTS",
    "NEAR_DUPLICATE",
    "RELATES_TO",
]

# ── Source type detection ──────────────────────────────────────────────────────
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go",
                   ".rs", ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php",
                   ".swift", ".kt", ".scala", ".r", ".sh", ".bash", ".zsh"}

PROSE_EXTENSIONS = {".md", ".markdown", ".txt", ".rst", ".adoc", ".org",
                    ".tex", ".text"}

STRUCTURED_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
                          ".xml", ".csv", ".tsv"}

# Binary / skip extensions — never ingest these
SKIP_EXTENSIONS = {".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin",
                   ".jpg", ".jpeg", ".png", ".gif", ".pdf", ".zip", ".gz",
                   ".tar", ".rar", ".7z", ".mp3", ".mp4", ".mov", ".avi"}

# Directories to always skip when walking a folder
SKIP_DIRS = {".git", "__pycache__", ".mypy_cache", ".pytest_cache",
             "node_modules", ".venv", "venv", "env", ".env",
             "dist", "build", ".tox", ".eggs", "*.egg-info"}

# ── Pipeline version ───────────────────────────────────────────────────────────
PIPELINE_VERSION = "0.1.0"