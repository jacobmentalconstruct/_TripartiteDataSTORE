"""
Run this ONCE from inside your _TripartiteDataStore folder:

    python reorganize.py

It will:
  1. Create the tripartite/ package directory
  2. Move all source files into it
  3. Add __init__.py to every package directory
  4. Move test_pipeline.py into tests/
  5. Delete tripartite.egg-info so it rebuilds cleanly
  6. Print next steps

After running, do:
    pip install -e .
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
PKG  = ROOT / "tripartite"
TESTS = ROOT / "tests"

def banner(msg):
    print(f"\n{'─'*52}\n  {msg}\n{'─'*52}")

def move(src, dst):
    src, dst = Path(src), Path(dst)
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        print(f"  moved  {src.relative_to(ROOT)}  →  {dst.relative_to(ROOT)}")
    else:
        print(f"  skip   {src.relative_to(ROOT)} (not found)")

def touch(p):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text('"""Tripartite package."""\n')
        print(f"  created {p.relative_to(ROOT)}")

# ── Guard: don't run if already reorganised ───────────────────────────────────
if (PKG / "cli.py").exists():
    print("✓ Already looks reorganised — nothing to do.")
    sys.exit(0)

banner("Step 1: Create package directory")
PKG.mkdir(exist_ok=True)
TESTS.mkdir(exist_ok=True)

banner("Step 2: Add __init__.py files")
for d in [PKG, PKG/"chunkers", PKG/"db", PKG/"models", PKG/"pipeline"]:
    touch(d / "__init__.py")
touch(TESTS / "__init__.py")

banner("Step 3: Move top-level source files")
for fname in ["cli.py", "config.py", "utils.py"]:
    move(ROOT / fname, PKG / fname)

banner("Step 4: Move sub-packages")
for pkg in ["chunkers", "db", "models", "pipeline"]:
    src_dir = ROOT / pkg
    dst_dir = PKG / pkg
    if src_dir.exists() and src_dir.is_dir():
        # Move each file individually so we don't clobber the __init__.py we just made
        for f in src_dir.iterdir():
            if f.name != "__init__.py":
                move(f, dst_dir / f.name)
        # Remove now-empty source dir
        try:
            src_dir.rmdir()
            print(f"  removed empty {src_dir.relative_to(ROOT)}/")
        except OSError:
            pass  # not empty, leave it

banner("Step 5: Move test file")
for candidate in ["test_pipeline.py", "tests/test_pipeline.py"]:
    move(ROOT / candidate, TESTS / "test_pipeline.py")

banner("Step 6: Delete stale egg-info")
egg = ROOT / "tripartite.egg-info"
if egg.exists():
    shutil.rmtree(egg)
    print(f"  removed tripartite.egg-info/")

banner("Done!")
print("""
Your project is now structured correctly. Run:

    pip install -e .

Then test the structural pipeline (no models needed):

    python -m unittest tests.test_pipeline -v

Then launch the UI:

    python -m tripartite.gui
""")
