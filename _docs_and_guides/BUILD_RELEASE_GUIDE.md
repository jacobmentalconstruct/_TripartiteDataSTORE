# Build & Release Guide

## Overview

This guide covers building standalone Tripartite executables and creating release bundles with PyInstaller.

**Why PyInstaller?**
- ✅ No Python installation required for users
- ✅ Single executable per platform
- ✅ Bundle models with profiles
- ✅ Cross-platform (Windows, macOS, Linux)
- ✅ Keeps your Python architecture

---

## Prerequisites

### Development Machine

**Required:**
- Python 3.11+
- pip
- Git

**Install dependencies:**
```bash
pip install -r requirements.txt
pip install pyinstaller
```

**Platform-specific:**
- Windows: No additional requirements
- macOS: Xcode Command Line Tools
- Linux: `python3-dev`, `python3-tk`

---

## Quick Start

### Build Single Profile (Local Testing)

```bash
# Build balanced profile for your current platform
python build_release.py --version 1.0.0 --profiles balanced

# Result:
# releases/tripartite-balanced-v1.0.0-windows.zip  (or macos/linux)
```

### Build Multiple Profiles

```bash
# Build three common profiles
python build_release.py --version 1.0.0 --profiles balanced code_heavy speed

# Results:
# releases/tripartite-balanced-v1.0.0-windows.zip     (1.1 GB)
# releases/tripartite-code_heavy-v1.0.0-windows.zip  (1.7 GB)
# releases/tripartite-speed-v1.0.0-windows.zip       (420 MB)
```

### Build All Profiles

```bash
python build_release.py --version 1.0.0 --all-profiles

# Builds: balanced, code_heavy, research, speed, quality
```

---

## Release Bundle Structure

Each bundle contains:

```
tripartite-balanced-v1.0.0-windows/
├── tripartite.exe           # Standalone executable (50 MB)
├── models/
│   ├── nomic-embed-text-v1.5.Q4_K_M.gguf        # Embedder (80 MB)
│   └── qwen2.5-1.5b-instruct-q4_k_m.gguf        # Extractor (1 GB)
├── README.txt               # Quick start guide
└── Tripartite.bat          # Launcher script (Windows only)
```

**User experience:**
1. Download zip
2. Extract
3. Double-click executable (or .bat on Windows)
4. **Just works** - no installation, no model downloads

---

## Build Process Details

### Step 1: Build Executable

```bash
# Manual build with PyInstaller
pyinstaller tripartite.spec --clean

# Output: dist/tripartite.exe (or dist/tripartite on Unix)
```

**What gets bundled:**
- Python interpreter
- All Tripartite modules
- llama-cpp-python binaries
- Tkinter and dependencies
- SQLite

**What doesn't get bundled:**
- GGUF model files (too large, added per-profile)
- User data

### Step 2: Download Models

For each profile, the build script:
1. Reads profile definition from `model_profiles.py`
2. Downloads embedder model from Hugging Face
3. Downloads extractor model from Hugging Face
4. Verifies file sizes

**Model cache:**
Models are cached in `models/` during build. Subsequent builds reuse cached models.

### Step 3: Create Bundle

```
1. Create bundle directory
2. Copy executable
3. Create models/ subdirectory
4. Copy/download profile models
5. Generate README.txt
6. Create launcher script (Windows)
```

### Step 4: Create Zip

```bash
# Bundle zipped for distribution
zip -r tripartite-balanced-v1.0.0-windows.zip tripartite-balanced-v1.0.0-windows/
```

---

## Build Script Options

### `build_release.py` Arguments

```bash
--version VERSION         # Release version (required)
--profiles P1 P2 P3      # Profile IDs to build
--all-profiles           # Build all profiles
--platform PLATFORM      # Override platform detection (windows/macos/linux)
--skip-build            # Skip PyInstaller step (reuse existing exe)
--keep-bundles          # Don't delete unzipped bundles after zipping
```

### Examples

**Test build (skip models):**
```bash
# Build exe only, don't create bundles
pyinstaller tripartite.spec
./dist/tripartite  # Test locally
```

**Build specific platform:**
```bash
# Cross-compile is NOT supported by PyInstaller
# Build on Windows for Windows, Mac for Mac, Linux for Linux

# But you can override detection for testing:
python build_release.py --version 1.0.0 --platform linux --profiles balanced
```

**Incremental build:**
```bash
# Build exe once
python build_release.py --version 1.0.0 --profiles balanced

# Add more profiles without rebuilding exe
python build_release.py --version 1.0.0 --skip-build --profiles code_heavy speed
```

---

## Automated Releases (GitHub Actions)

### Setup

1. Copy workflow file:
```bash
mkdir -p .github/workflows
cp github_actions_release.yml .github/workflows/release.yml
```

2. Commit and push:
```bash
git add .github/workflows/release.yml
git commit -m "Add automated release workflow"
git push
```

### Trigger Release

**Option 1: Tag-based (recommended)**
```bash
# Create and push version tag
git tag v1.0.0
git push origin v1.0.0

# GitHub Actions automatically:
# 1. Builds on Windows, macOS, Linux runners
# 2. Creates bundles for all platforms
# 3. Creates GitHub Release
# 4. Uploads all zips as release assets
```

**Option 2: Manual trigger**
1. Go to GitHub → Actions → "Build Release Bundles"
2. Click "Run workflow"
3. Enter version and profiles
4. Click "Run workflow"
5. Artifacts available for download (not a release)

### What Gets Built

For each platform (Windows, macOS, Linux):
- Balanced profile bundle
- Code-Heavy profile bundle
- Speed profile bundle

**Total:** 9 release bundles (3 profiles × 3 platforms)

---

## Profile-Specific Bundles

### Balanced (Default)
**Size:** ~1.1 GB  
**Models:** Nomic 768d + Qwen 1.5B  
**Best for:** General use, mixed content  
**Target users:** Most users, first-time users

### Code-Heavy
**Size:** ~1.7 GB  
**Models:** MixedBread 1024d + Qwen 1.5B  
**Best for:** Software projects, multi-language codebases  
**Target users:** Developers, code-focused knowledge bases

### Speed
**Size:** ~420 MB  
**Models:** MiniLM 384d + Qwen 0.5B  
**Best for:** Large corpora, quick testing  
**Target users:** Power users, CI/CD, testing

### Research Papers
**Size:** ~1.7 GB  
**Models:** MixedBread 1024d + Qwen 1.5B  
**Best for:** Academic writing, technical docs  
**Target users:** Researchers, technical writers

### Quality
**Size:** ~1.7 GB  
**Models:** MixedBread 1024d + Qwen 1.5B  
**Best for:** Production, high-value knowledge bases  
**Target users:** Enterprise, critical applications

---

## Testing Releases

### Before Publishing

**Test each bundle:**
```bash
# Extract bundle
unzip tripartite-balanced-v1.0.0-windows.zip
cd tripartite-balanced-v1.0.0-windows/

# Run executable
./tripartite.exe  # Windows
./tripartite      # Linux/Mac

# Verify:
✓ App launches without errors
✓ Settings shows correct profile
✓ Models are detected (✓ Cached)
✓ Can ingest test files
✓ Can search ingested content
✓ Can export
```

**Test checklist:**
- [ ] Windows bundle launches
- [ ] macOS bundle launches (may need to allow in Security settings)
- [ ] Linux bundle launches
- [ ] Models detected automatically
- [ ] Ingest works
- [ ] Search works (semantic + FTS)
- [ ] Export works
- [ ] No Python errors in console

---

## Publishing Releases

### Manual (GitHub)

1. Go to Releases → Draft new release
2. Create tag (e.g., `v1.0.0`)
3. Upload zips
4. Write release notes
5. Publish

### Automated (GitHub Actions)

Just push a tag:
```bash
git tag v1.0.0
git push origin v1.0.0
```

Release created automatically with all bundles.

---

## Download Page Template

Add this to your README.md:

```markdown
## Download

### Windows
- [Balanced (1.1 GB)](https://github.com/you/tripartite/releases/download/v1.0.0/tripartite-balanced-v1.0.0-windows.zip) - Recommended for most users
- [Code-Heavy (1.7 GB)](https://github.com/you/tripartite/releases/download/v1.0.0/tripartite-code_heavy-v1.0.0-windows.zip) - Optimized for codebases
- [Speed (420 MB)](https://github.com/you/tripartite/releases/download/v1.0.0/tripartite-speed-v1.0.0-windows.zip) - Fastest, lower quality

### macOS
- [Balanced (1.1 GB)](https://github.com/you/tripartite/releases/download/v1.0.0/tripartite-balanced-v1.0.0-macos.zip)
- [Code-Heavy (1.7 GB)](https://github.com/you/tripartite/releases/download/v1.0.0/tripartite-code_heavy-v1.0.0-macos.zip)
- [Speed (420 MB)](https://github.com/you/tripartite/releases/download/v1.0.0/tripartite-speed-v1.0.0-macos.zip)

### Linux
- [Balanced (1.1 GB)](https://github.com/you/tripartite/releases/download/v1.0.0/tripartite-balanced-v1.0.0-linux.zip)
- [Code-Heavy (1.7 GB)](https://github.com/you/tripartite/releases/download/v1.0.0/tripartite-code_heavy-v1.0.0-linux.zip)
- [Speed (420 MB)](https://github.com/you/tripartite/releases/download/v1.0.0/tripartite-speed-v1.0.0-linux.zip)

**Don't know which one to pick?** Start with **Balanced**.
```

---

## Troubleshooting

### Build Issues

**"PyInstaller not found"**
```bash
pip install pyinstaller
```

**"llama-cpp-python import failed"**
```bash
# Reinstall with binary wheel
pip uninstall llama-cpp-python
pip install llama-cpp-python --no-cache-dir
```

**"Executable won't run"**
- Windows: Check antivirus (sometimes flags PyInstaller exes)
- macOS: Right-click → Open (bypass Gatekeeper)
- Linux: `chmod +x tripartite`

**"Model download failed"**
- Check internet connection
- Verify Hugging Face is accessible
- Try manual download and copy to `models/`

### Runtime Issues

**"DLL load failed" (Windows)**
- Missing Visual C++ Runtime
- Download from Microsoft: vc_redist.x64.exe

**"Library not loaded" (macOS)**
- Bundle may be incomplete
- Rebuild with `--clean` flag

**"Models not detected"**
- Check `models/` directory exists in bundle
- Verify model filenames match profile
- Check file sizes (truncated downloads)

---

## Advanced: Custom Bundles

### Add New Profile

1. Edit `tripartite/model_profiles.py`:
```python
PROFILES.append(
    ModelProfile(
        id="custom_profile",
        name="Custom Profile",
        description="Your custom combination",
        embedder_filename="your-embedder.gguf",
        extractor_filename="your-extractor.gguf",
    )
)
```

2. Add models to `tripartite/config.py` KNOWN_MODELS

3. Build:
```bash
python build_release.py --version 1.0.0 --profiles custom_profile
```

### Bundle Additional Files

Edit `tripartite.spec`:
```python
datas=[
    ('tripartite', 'tripartite'),
    ('assets', 'assets'),  # ← Add custom files
],
```

---

## Performance Optimization

### Reduce Executable Size

**Enable UPX compression:**
```python
# In tripartite.spec
exe = EXE(
    ...
    upx=True,  # Compress with UPX (~40% size reduction)
    ...
)
```

**Exclude unused modules:**
```python
# In tripartite.spec
excludes=[
    'matplotlib',
    'numpy.distutils',
    'pytest',
    'IPython',
    'jupyter',
],
```

### Speed Up Builds

**Use build cache:**
```bash
# First build
python build_release.py --version 1.0.0 --profiles balanced

# Subsequent builds (reuse exe)
python build_release.py --version 1.0.0 --skip-build --profiles code_heavy
```

**Cache models:**
Models download to `models/` and are reused across builds.

---

## Release Checklist

Before publishing:

- [ ] Version bumped in code
- [ ] CHANGELOG.md updated
- [ ] All tests pass
- [ ] Build script works on target platforms
- [ ] Each bundle tested locally
- [ ] README.md has correct download links
- [ ] GitHub release notes written
- [ ] Tag created and pushed

---

## Future Enhancements

### Planned
- [ ] Code signing (Windows/Mac)
- [ ] Auto-update mechanism
- [ ] Delta updates (download only changed files)
- [ ] Installer packages (.msi, .pkg, .deb)

### Ideas
- Profile bundles on demand (download base + profile)
- Portable mode (all data in bundle directory)
- Multi-version support (side-by-side installs)

---

## Summary

**Building releases is now:**
1. Run `python build_release.py --version X.X.X --all-profiles`
2. Test bundles
3. Push tag `vX.X.X`
4. GitHub Actions builds all platforms
5. Download links auto-generated

**Users get:**
- No Python installation required
- No model downloads required
- Double-click and it works
- Profile-optimized bundles

**You maintain:**
- One Python codebase
- Profile definitions in code
- Automated build process
- Cross-platform releases

🎉 **Distribution solved!**
