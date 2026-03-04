#!/bin/bash
# ============================================================
# _TripartiteDataSTORE - Environment Setup (Linux/Mac)
# ============================================================
# 
# This script creates a Python virtual environment and installs
# all required dependencies for the Tripartite knowledge management
# system, including tree-sitter for multi-language code parsing.
#
# Usage: chmod +x setup_env.sh && ./setup_env.sh

set -e  # Exit on error

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║         _TripartiteDataSTORE - Environment Setup              ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Check for Python ────────────────────────────────────
echo "[1/4] Checking Python installation..."

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 not found! Please install Python 3.10 or higher."
    echo "        - Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "        - macOS: brew install python3"
    echo "        - Or download from: https://www.python.org/downloads/"
    exit 1
fi

python3 --version
echo "[OK] Python found"
echo ""

# ── Step 2: Create Virtual Environment ─────────────────────────
echo "[2/4] Setting up virtual environment..."

if [ -d ".venv" ]; then
    echo "[INFO] Virtual environment already exists (.venv)"
    echo "       Delete .venv folder to recreate from scratch"
else
    echo "[SETUP] Creating .venv..."
    python3 -m venv .venv
    echo "[OK] Virtual environment created"
fi
echo ""

# ── Step 3: Activate and Upgrade pip ────────────────────────────
echo "[3/4] Upgrading pip..."

# Activate venv
source .venv/bin/activate

python -m pip install --upgrade pip --quiet
if [ $? -eq 0 ]; then
    echo "[OK] Pip upgraded"
else
    echo "[WARNING] Failed to upgrade pip, continuing anyway..."
fi
echo ""

# ── Step 4: Install Dependencies ───────────────────────────────
echo "[4/4] Installing dependencies..."

if [ -f "requirements.txt" ]; then
    echo "[INSTALL] Installing from requirements.txt..."
    echo ""
    echo "  ┌─────────────────────────────────────────────────┐"
    echo "  │ Installing core dependencies:                   │"
    echo "  │  • llama-cpp-python (embeddings)                │"
    echo "  │  • tree-sitter (multi-language parsing)         │"
    echo "  │  • tree-sitter-language-pack (20+ languages)    │"
    echo "  └─────────────────────────────────────────────────┘"
    echo ""
    
    pip install -r requirements.txt
    
    if [ $? -ne 0 ]; then
        echo ""
        echo "[ERROR] Failed to install some dependencies!"
        echo ""
        echo "Common issues:"
        echo "  • llama-cpp-python may need build tools:"
        echo "    Ubuntu/Debian: sudo apt install build-essential python3-dev"
        echo "    macOS: xcode-select --install"
        echo ""
        echo "  • tree-sitter-language-pack may not be available"
        echo "    Fallback: Install individual grammars (see requirements.txt)"
        echo ""
        echo "[INFO] You can continue - some features may be limited"
    else
        echo ""
        echo "[OK] All dependencies installed successfully!"
    fi
else
    echo "[WARNING] requirements.txt not found!"
    echo "          Skipping dependency installation"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                     SETUP COMPLETE!                            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Activate the environment:"
echo "     source .venv/bin/activate"
echo ""
echo "  2. Launch the application:"
echo "     python -m src.app"
echo ""
echo "  3. Or launch with a database path:"
echo "     python -m src.app mydata.db"
echo ""
echo "  4. For tree-sitter integration:"
echo "     See treesitter_integration/ folder for setup instructions"
echo ""
echo "Documentation:"
echo "  • README.md - Project overview"
echo "  • treesitter_integration/README.md - Multi-language support"
echo ""
