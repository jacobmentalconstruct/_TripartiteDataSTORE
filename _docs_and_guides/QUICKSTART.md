# _TripartiteDataSTORE - Quick Start Guide

Get up and running with Tripartite in **5 minutes**! 🚀

---

## Prerequisites

- **Python 3.10+** installed
- **Windows:** [Python from python.org](https://www.python.org/downloads/)
- **Linux:** `sudo apt install python3 python3-venv python3-pip`
- **macOS:** `brew install python3`

---

## Step 1: Get the Code

```bash
# Clone or download the repository
cd _TripartiteDataSTORE
```

---

## Step 2: Run Setup

### Windows
```batch
setup_env.bat
```

### Linux/Mac
```bash
chmod +x setup_env.sh
./setup_env.sh
```

This will:
- ✅ Create a `.venv` virtual environment
- ✅ Install `llama-cpp-python` (for embeddings)
- ✅ Install `tree-sitter` (for multi-language code parsing)
- ✅ Install `tree-sitter-language-pack` (20+ language grammars)

**Note:** If `llama-cpp-python` fails to install, you may need build tools:
- **Windows:** [Build Tools for Visual Studio](https://visualstudio.microsoft.com/downloads/)
- **Linux:** `sudo apt install build-essential python3-dev`
- **macOS:** `xcode-select --install`

---

## Step 3: Activate Environment

### Windows
```batch
.venv\Scripts\activate
```

### Linux/Mac
```bash
source .venv/bin/activate
```

You should see `(.venv)` in your terminal prompt.

---

## Step 4: Ingest Your First Project

```bash
# Ingest a directory of code/docs
python -m tripartite.cli ingest /path/to/your/project --db myproject.db --verbose

# Example: Ingest this repository
python -m tripartite.cli ingest . --db tripartite_self.db --verbose
```

**What happens:**
1. **Detects** all text files (code, markdown, etc.)
2. **Chunks** them using AST parsing (functions, classes) or prose chunking
3. **Embeds** chunks using a local GGUF model
4. **Extracts** entities and builds a knowledge graph
5. **Stores** everything in a SQLite database

**Time:** ~30 seconds per 1000 files (depends on model and hardware)

---

## Step 5: View Your Data

```bash
python -m tripartite.viewer myproject.db
```

This opens a **Tkinter GUI** with three panels:

1. **Browse** - Navigate files → chunks
2. **Search** - Hybrid FTS + semantic search
3. **Graph** - Explore entities and relationships

**Tips:**
- Browse panel: Click a file to see its chunks
- Search panel: Try "authentication logic" or "error handling"
- Graph panel: Click an entity to see where it's mentioned

---

## Step 6: Enable Multi-Language Support (Optional)

If you want **tree-sitter** for JavaScript, TypeScript, Go, Rust, etc.:

1. **Check if already installed:**
   ```bash
   python -c "import tree_sitter_language_pack; print('✓ Tree-sitter available')"
   ```

2. **If not installed:**
   ```bash
   pip install tree-sitter tree-sitter-language-pack
   ```

3. **Copy the chunker** to your project:
   ```bash
   cp treesitter_integration/treesitter.py tripartite/chunkers/
   ```

4. **Update imports** in `tripartite/chunkers/__init__.py`:
   ```python
   from .treesitter import TreeSitterChunker, get_treesitter_chunker
   ```

5. **Update routing** in `tripartite/pipeline/ingest.py`:
   - Replace `_get_chunker()` function with code from `treesitter_integration/updated_get_chunker.py`

6. **Re-ingest** to get better chunks:
   ```bash
   python -m tripartite.cli ingest /path/to/project --db project_v2.db --verbose
   ```

**See:** `treesitter_integration/TREESITTER_INTEGRATION.md` for detailed instructions

---

## Common Tasks

### Search Your Codebase
```bash
# Interactive search
python -m tripartite.cli search myproject.db "authentication"

# Or use the viewer GUI
python -m tripartite.viewer myproject.db
```

### Export Files Back to Disk
```bash
python -m tripartite.export_cli myproject.db /output/directory --preserve-structure
```

### Re-Embed with Different Model
```bash
# Delete old embeddings
python -m tripartite.cli reset-embeddings myproject.db

# Re-embed with new model
python -m tripartite.cli embed myproject.db --model /path/to/new_model.gguf
```

### Query the Database Directly
```bash
sqlite3 myproject.db

# Useful queries:
SELECT COUNT(*) FROM source_files;
SELECT COUNT(*) FROM chunk_manifest;
SELECT chunk_type, COUNT(*) FROM chunk_manifest GROUP BY chunk_type;
SELECT * FROM graph_nodes WHERE node_type = 'entity' LIMIT 10;
```

---

## Project Structure

```
_TripartiteDataSTORE/
├── tripartite/              # Main package
│   ├── chunkers/            # Code/prose chunkers
│   │   ├── base.py          # Abstract chunker
│   │   ├── code.py          # Python AST chunker
│   │   ├── prose.py         # Text/markdown chunker
│   │   └── treesitter.py    # Multi-language AST chunker (NEW)
│   ├── db/                  # Database schema & queries
│   ├── models/              # GGUF model loading
│   ├── pipeline/            # Ingestion stages
│   ├── cli.py               # Command-line interface
│   ├── viewer.py            # Tkinter GUI
│   └── export.py            # File export utilities
├── treesitter_integration/  # Tree-sitter docs & tests
├── tests/                   # Unit tests
├── requirements.txt         # Python dependencies
├── setup_env.bat            # Windows setup script
├── setup_env.sh             # Linux/Mac setup script
└── README.md                # Project overview
```

---

## Next Steps

### Learn More
- **Tree-sitter integration:** `treesitter_integration/README.md`
- **Migration guide:** `treesitter_integration/MIGRATION_GUIDE.md`
- **Feature docs:** `treesitter_integration/TREESITTER_README.md`

### Customize
- **Add language grammars:** Install `tree-sitter-{language}` and add query patterns
- **Tune chunk size:** Edit `MAX_CHUNK_TOKENS` in `tripartite/config.py`
- **Change models:** Point to different GGUF embeddings/extraction models

### Develop
- **Run tests:** `pytest tests/`
- **Format code:** `black tripartite/`
- **Lint:** `ruff check tripartite/`

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'llama_cpp'"
**Fix:** Make sure you activated the venv:
```bash
# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate
```

### "Failed to load model"
**Fix:** Download a GGUF embedding model:
```bash
# Example: Download all-MiniLM-L6-v2 (small, fast)
# Place in tripartite/models/ or specify path
```

### "Tree-sitter not available"
**Fix:** This is optional. Install with:
```bash
pip install tree-sitter tree-sitter-language-pack
```

### "Build error when installing llama-cpp-python"
**Fix:** Install build tools:
- **Windows:** [Build Tools for Visual Studio](https://visualstudio.microsoft.com/downloads/)
- **Linux:** `sudo apt install build-essential`
- **macOS:** `xcode-select --install`

### "Database locked"
**Fix:** Close the viewer GUI or any other programs accessing the .db file

---

## Getting Help

1. Check documentation in `treesitter_integration/`
2. Run test suite: `python treesitter_integration/test_treesitter_integration.py`
3. Enable verbose logging: `--verbose` flag on CLI commands
4. Check database with: `sqlite3 myproject.db ".schema"`

---

## What's Next?

You now have a **local-first knowledge base** that:
- ✅ Understands code structure (not just text)
- ✅ Supports 20+ programming languages
- ✅ Provides semantic search
- ✅ Builds knowledge graphs
- ✅ Works completely offline

**Try it on:**
- Your personal code projects
- Documentation repositories
- Research papers (after conversion to text)
- Technical notes and wikis

**Enjoy exploring your knowledge base!** 🎉
