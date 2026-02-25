#!/usr/bin/env python3
"""
build_release.py

Automated build script for creating Tripartite release bundles.

Builds:
1. Standalone executable with PyInstaller
2. Profile-specific bundles (each with appropriate models)
3. Platform-specific release zips

Usage:
    python build_release.py --version 1.0.0 --profiles balanced code_heavy speed
    python build_release.py --version 1.0.0 --all-profiles
    python build_release.py --version 1.0.0 --platform windows --profiles balanced
"""

import argparse
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

DIST_DIR = Path("dist")
RELEASE_DIR = Path("releases")
BUILD_DIR = Path("build")

# Platform detection
PLATFORM = platform.system().lower()
if PLATFORM == "darwin":
    PLATFORM = "macos"
elif PLATFORM not in ["windows", "linux"]:
    print(f"Warning: Unknown platform {PLATFORM}, assuming Linux")
    PLATFORM = "linux"

# Executable name
EXE_NAME = "tripartite.exe" if PLATFORM == "windows" else "tripartite"
if PLATFORM == "macos":
    EXE_PATH = DIST_DIR / "Tripartite.app"
else:
    EXE_PATH = DIST_DIR / EXE_NAME


# ── Helper Functions ───────────────────────────────────────────────────────────

def run_command(cmd: list[str], description: str):
    """Run a command and handle errors."""
    print(f"[build] {description}...")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[build] ✗ {description} failed!")
        print(f"Error: {e.stderr}")
        return False


def download_model(url: str, dest: Path, model_name: str):
    """Download a model file with progress."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    if dest.exists():
        print(f"[build] ✓ {model_name} already downloaded")
        return True
    
    print(f"[build] Downloading {model_name}...")
    try:
        def progress_hook(count, block_size, total_size):
            if total_size > 0:
                percent = min(100, count * block_size * 100 // total_size)
                mb_done = count * block_size / 1_048_576
                mb_total = total_size / 1_048_576
                print(f"\r  {percent:3d}%  {mb_done:.1f} / {mb_total:.1f} MB", end="", flush=True)
        
        urllib.request.urlretrieve(url, dest, reporthook=progress_hook)
        print()  # Newline after progress
        print(f"[build] ✓ {model_name} downloaded")
        return True
    except Exception as e:
        print(f"\n[build] ✗ Download failed: {e}")
        return False


def get_profile_models(profile_id: str) -> dict:
    """Get model URLs for a profile."""
    # Import here to avoid issues before tripartite is built
    sys.path.insert(0, str(Path(__file__).parent))
    from tripartite.model_profiles import get_profile
    from tripartite.config import KNOWN_MODELS
    
    profile = get_profile(profile_id)
    if not profile:
        print(f"[build] ✗ Unknown profile: {profile_id}")
        return None
    
    # Find model specs
    embedder_spec = next(
        (m for m in KNOWN_MODELS if m["filename"] == profile.embedder_filename),
        None
    )
    extractor_spec = next(
        (m for m in KNOWN_MODELS if m["filename"] == profile.extractor_filename),
        None
    )
    
    if not embedder_spec or not extractor_spec:
        print(f"[build] ✗ Could not find model specs for profile {profile_id}")
        return None
    
    return {
        "profile": profile,
        "embedder": embedder_spec,
        "extractor": extractor_spec,
    }


# ── Build Steps ────────────────────────────────────────────────────────────────

def build_executable():
    """Build the standalone executable with PyInstaller."""
    print("\n" + "=" * 70)
    print("STEP 1: Building Executable")
    print("=" * 70 + "\n")
    
    # Check if PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("[build] ✗ PyInstaller not found. Installing...")
        if not run_command([sys.executable, "-m", "pip", "install", "pyinstaller"],
                          "Installing PyInstaller"):
            return False
    
    # Clean previous builds
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    
    # Build with PyInstaller
    if not run_command(
        [sys.executable, "-m", "PyInstaller", "tripartite.spec", "--clean"],
        "Building executable with PyInstaller"
    ):
        return False
    
    # Verify executable exists
    if not EXE_PATH.exists():
        print(f"[build] ✗ Executable not found at {EXE_PATH}")
        return False
    
    print(f"[build] ✓ Executable built: {EXE_PATH}")
    return True


def create_bundle(profile_id: str, version: str):
    """Create a release bundle for a specific profile."""
    print(f"\n[build] Creating bundle for profile: {profile_id}")
    
    # Get profile models
    profile_data = get_profile_models(profile_id)
    if not profile_data:
        return False
    
    profile = profile_data["profile"]
    embedder = profile_data["embedder"]
    extractor = profile_data["extractor"]
    
    # Create bundle directory
    bundle_name = f"tripartite-{profile_id}-v{version}-{PLATFORM}"
    bundle_dir = RELEASE_DIR / bundle_name
    
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy executable
    print(f"[build] Copying executable to {bundle_dir}/")
    if PLATFORM == "macos":
        shutil.copytree(EXE_PATH, bundle_dir / "Tripartite.app")
    else:
        shutil.copy2(EXE_PATH, bundle_dir / EXE_NAME)
    
    # Create models directory
    models_dir = bundle_dir / "models"
    models_dir.mkdir(exist_ok=True)
    
    # Download embedder
    embedder_path = models_dir / embedder["filename"]
    if not download_model(embedder["url"], embedder_path, embedder["display_name"]):
        return False
    
    # Download extractor
    extractor_path = models_dir / extractor["filename"]
    if not download_model(extractor["url"], extractor_path, extractor["display_name"]):
        return False
    
    # Create README
    readme_path = bundle_dir / "README.txt"
    readme_content = f"""Tripartite Knowledge Store - {profile.name} Edition
Version {version}

QUICK START:
============

1. Double-click 'tripartite{".exe" if PLATFORM == "windows" else ""}' to launch
2. The {profile.name} profile is pre-configured and models are included
3. Click 'Pick Folder' to select files to ingest
4. Click 'Run Ingest' to build your knowledge store

WHAT'S IN THIS BUNDLE:
======================

Profile: {profile.name}
{profile.description}

Models Included:
- Embedder: {embedder["display_name"]}
- Extractor: {extractor["display_name"]}

Total Size: ~{(embedder['min_size_bytes'] + extractor['min_size_bytes']) / 1_048_576:.0f} MB

DOCUMENTATION:
==============

For full documentation, visit:
https://github.com/yourusername/tripartite

SUPPORT:
========

Questions? Issues?
https://github.com/yourusername/tripartite/issues
"""
    readme_path.write_text(readme_content, encoding="utf-8")
    
    # Create launcher script (Windows only)
    if PLATFORM == "windows":
        launcher_path = bundle_dir / "Tripartite.bat"
        launcher_content = f"""@echo off
REM Tripartite Knowledge Store Launcher
REM {profile.name} Profile - Version {version}

echo Starting Tripartite Knowledge Store...
echo Profile: {profile.name}
echo.

REM Launch Tripartite
start "" "%~dp0tripartite.exe"
"""
        launcher_path.write_text(launcher_content, encoding="utf-8")
    
    print(f"[build] ✓ Bundle created: {bundle_dir}/")
    return bundle_dir


def create_zip(bundle_dir: Path):
    """Create a zip archive of the bundle."""
    zip_name = bundle_dir.name
    zip_path = RELEASE_DIR / f"{zip_name}.zip"
    
    print(f"[build] Creating zip archive: {zip_path.name}")
    
    # Create zip
    shutil.make_archive(
        str(RELEASE_DIR / zip_name),
        'zip',
        bundle_dir.parent,
        bundle_dir.name
    )
    
    # Get size
    size_mb = zip_path.stat().st_size / 1_048_576
    print(f"[build] ✓ Zip created: {zip_path} ({size_mb:.1f} MB)")
    
    return zip_path


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Build Tripartite release bundles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build balanced profile only
  python build_release.py --version 1.0.0 --profiles balanced
  
  # Build multiple profiles
  python build_release.py --version 1.0.0 --profiles balanced code_heavy speed
  
  # Build all profiles
  python build_release.py --version 1.0.0 --all-profiles
  
  # Build for specific platform (override detection)
  python build_release.py --version 1.0.0 --platform windows --profiles balanced
        """
    )
    
    parser.add_argument("--version", required=True, help="Release version (e.g., 1.0.0)")
    parser.add_argument("--profiles", nargs="+", help="Profile IDs to build")
    parser.add_argument("--all-profiles", action="store_true", help="Build all profiles")
    parser.add_argument("--platform", choices=["windows", "linux", "macos"],
                       help="Override platform detection")
    parser.add_argument("--skip-build", action="store_true",
                       help="Skip executable build (reuse existing)")
    parser.add_argument("--keep-bundles", action="store_true",
                       help="Keep unzipped bundles after creating zips")
    
    args = parser.parse_args()
    
    # Override platform if specified
    global PLATFORM, EXE_NAME, EXE_PATH
    if args.platform:
        PLATFORM = args.platform
        EXE_NAME = "tripartite.exe" if PLATFORM == "windows" else "tripartite"
        if PLATFORM == "macos":
            EXE_PATH = DIST_DIR / "Tripartite.app"
        else:
            EXE_PATH = DIST_DIR / EXE_NAME
    
    # Determine profiles to build
    if args.all_profiles:
        from tripartite.model_profiles import PROFILES
        profile_ids = [p.id for p in PROFILES]
    elif args.profiles:
        profile_ids = args.profiles
    else:
        print("Error: Must specify --profiles or --all-profiles")
        sys.exit(1)
    
    print(f"\n{'=' * 70}")
    print(f"Tripartite Release Builder")
    print(f"{'=' * 70}")
    print(f"Version:  {args.version}")
    print(f"Platform: {PLATFORM}")
    print(f"Profiles: {', '.join(profile_ids)}")
    print(f"{'=' * 70}\n")
    
    # Step 1: Build executable
    if not args.skip_build:
        if not build_executable():
            print("\n[build] ✗ Build failed!")
            sys.exit(1)
    else:
        print("\n[build] Skipping executable build (--skip-build)")
        if not EXE_PATH.exists():
            print(f"[build] ✗ Executable not found at {EXE_PATH}")
            sys.exit(1)
    
    # Step 2: Create bundles
    print("\n" + "=" * 70)
    print("STEP 2: Creating Profile Bundles")
    print("=" * 70 + "\n")
    
    RELEASE_DIR.mkdir(exist_ok=True)
    
    created_zips = []
    for profile_id in profile_ids:
        bundle_dir = create_bundle(profile_id, args.version)
        if not bundle_dir:
            print(f"\n[build] ✗ Failed to create bundle for {profile_id}")
            continue
        
        zip_path = create_zip(bundle_dir)
        created_zips.append(zip_path)
        
        # Clean up bundle directory unless --keep-bundles
        if not args.keep_bundles:
            shutil.rmtree(bundle_dir)
            print(f"[build] Cleaned up: {bundle_dir}/")
    
    # Summary
    print("\n" + "=" * 70)
    print("BUILD COMPLETE")
    print("=" * 70 + "\n")
    
    if created_zips:
        print("Created release bundles:")
        for zip_path in created_zips:
            size_mb = zip_path.stat().st_size / 1_048_576
            print(f"  ✓ {zip_path.name} ({size_mb:.1f} MB)")
        
        print(f"\nReleases saved to: {RELEASE_DIR.absolute()}/")
        print("\nNext steps:")
        print("1. Test each bundle")
        print("2. Upload to GitHub Releases")
        print("3. Update documentation with download links")
    else:
        print("✗ No bundles created successfully")
        sys.exit(1)


if __name__ == "__main__":
    main()
