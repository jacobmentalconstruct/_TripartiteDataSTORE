# tripartite.spec
# PyInstaller specification file for building standalone Tripartite executable
#
# Usage:
#   pyinstaller tripartite.spec
#
# Output:
#   dist/tripartite.exe (Windows) or dist/tripartite (Linux/Mac)

import sys
from pathlib import Path

# Determine platform
IS_WINDOWS = sys.platform.startswith('win')
IS_MAC = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

block_cipher = None

# ── Analysis ───────────────────────────────────────────────────────────────────

a = Analysis(
    ['src/gui.py'],  # Entry point
    pathex=[],
    binaries=[],
    datas=[
        # Include all Python modules
        ('src', 'src'),
    ],
    hiddenimports=[
        # Core imports
        'src.gui',
        'src.viewer',
        'src.export',
        'src.export_cli',
        'src.settings_store',
        'src.settings_dialog',
        'src.model_profiles',
        'src.config',
        'src.utils',

        # Database
        'src.db.query',
        'src.db.schema',

        # Models
        'src.models.manager',

        # Pipeline
        'src.pipeline.detect',
        'src.pipeline.embed',
        'src.pipeline.extract',
        'src.pipeline.ingest',
        'src.pipeline.chunk_tree',
        'src.pipeline.graph',

        # Chunkers
        'src.chunkers.base',
        'src.chunkers.code',
        'src.chunkers.prose',
        'src.chunkers.structured',
        
        # Third-party
        'llama_cpp',
        'sqlite3',
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.scrolledtext',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'matplotlib',
        'numpy.distutils',
        'pytest',
        'IPython',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── PYZ (Python Zip Archive) ──────────────────────────────────────────────────

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

# ── EXE (Executable) ──────────────────────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='tripartite',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Compress with UPX
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico' if IS_WINDOWS else None,  # Optional: add your icon
)

# ── Platform-specific configurations ──────────────────────────────────────────

if IS_MAC:
    # macOS app bundle
    app = BUNDLE(
        exe,
        name='Tripartite.app',
        icon='assets/icon.icns',  # Optional: macOS icon
        bundle_identifier='com.tripartite.app',
        info_plist={
            'NSHighResolutionCapable': 'True',
            'CFBundleName': 'Tripartite',
            'CFBundleDisplayName': 'Tripartite Knowledge Store',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0',
        },
    )
