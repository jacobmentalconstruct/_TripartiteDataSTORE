"""
Model manager: download-on-first-run, sha256 verification, and llama.cpp loading.

Models are cached in ~/.tripartite/models/.
On first run, missing models are downloaded with a progress bar.
Subsequent runs load from cache — fully offline, no server required.
"""

import sys
import urllib.request
from pathlib import Path
from typing import Optional

from ..config import MODELS, MODELS_DIR


# ── Download helpers ───────────────────────────────────────────────────────────

class _ProgressReporter(urllib.request.BaseHandler):
    """urllib hook that prints a simple progress bar to stderr."""

    def __init__(self, filename: str):
        self.filename = filename
        self.seen = 0
        self.total = 0

    def http_response(self, request, response):
        content_length = response.headers.get("Content-Length")
        self.total = int(content_length) if content_length else 0
        return response

    https_response = http_response


def _progress_hook(filename: str):
    """Return an urlretrieve-compatible reporthook closure."""
    label = f"  Downloading {filename}"
    bar_width = 30

    def hook(block_num: int, block_size: int, total_size: int):
        downloaded = block_num * block_size
        if total_size > 0:
            frac = min(downloaded / total_size, 1.0)
            filled = int(bar_width * frac)
            bar = "█" * filled + "░" * (bar_width - filled)
            mb_done = downloaded / 1_048_576
            mb_total = total_size / 1_048_576
            sys.stderr.write(
                f"\r{label}  [{bar}]  {mb_done:.1f} / {mb_total:.1f} MB"
            )
        else:
            mb_done = downloaded / 1_048_576
            sys.stderr.write(f"\r{label}  {mb_done:.1f} MB downloaded…")
        sys.stderr.flush()

    return hook


def _download(url: str, dest: Path, filename: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    try:
        urllib.request.urlretrieve(url, tmp, reporthook=_progress_hook(filename))
        sys.stderr.write("\n")
        tmp.rename(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


# ── Public API ─────────────────────────────────────────────────────────────────

def ensure_model(role: str) -> Path:
    """
    Ensure the model for *role* ('embedder' | 'extractor') is present in the
    cache directory.  Downloads if missing or clearly truncated, then returns
    the local path.

    Verification strategy: size check (not sha256).
    sha256 hashes are not bundled because they change with model updates on HF.
    A file above min_size_bytes is considered intact — a truncated download
    would be obviously smaller.
    """
    spec = MODELS[role]
    dest = MODELS_DIR / spec["filename"]
    min_size = spec.get("min_size_bytes", 10_000_000)

    if dest.exists():
        actual_size = dest.stat().st_size
        if actual_size >= min_size:
            return dest
        # File exists but is too small — must be a truncated download
        print(f"[model] {spec['filename']} appears truncated ({actual_size / 1e6:.1f} MB) — re-downloading.")
        dest.unlink()

    print(f"[model] {spec['filename']} not found in cache.")
    print(f"[model] Downloading from Hugging Face (~{_size_hint(role)})…")
    _download(spec["url"], dest, spec["filename"])

    # Post-download size check
    actual_size = dest.stat().st_size
    if actual_size < min_size:
        dest.unlink()
        raise RuntimeError(
            f"Downloaded {spec['filename']} is only {actual_size / 1e6:.1f} MB "
            f"(expected at least {min_size / 1e6:.0f} MB). "
            "The download may have been interrupted or the URL has changed."
        )

    print(f"[model] ✓ {spec['filename']} ready ({actual_size / 1e6:.0f} MB).")
    return dest


def _size_hint(role: str) -> str:
    sizes = {"embedder": "274 MB", "extractor": "398 MB"}
    return sizes.get(role, "unknown size")


# ── llama.cpp wrappers ─────────────────────────────────────────────────────────

_embedder_instance = None
_extractor_instance = None
_embedder_failed = False   # set True after first load failure — stops retrying
_extractor_failed = False


def get_embedder():
    """
    Return a loaded llama_cpp.Llama instance configured for embedding.
    Loads on first call; cached for the process lifetime.
    Returns None (without retrying) if the first load attempt failed for any reason.
    """
    global _embedder_instance, _embedder_failed
    if _embedder_instance is not None:
        return _embedder_instance
    if _embedder_failed:
        return None

    try:
        from llama_cpp import Llama
        model_path = ensure_model("embedder")
        spec = MODELS["embedder"]
        print(f"[model] Loading embedder ({spec['filename']})…", flush=True)
        _embedder_instance = Llama(
            model_path=str(model_path),
            embedding=True,
            n_ctx=spec["context_length"],
            n_threads=_cpu_threads(),
            verbose=False,
        )
        print("[model] ✓ Embedder ready.")
        return _embedder_instance
    except ImportError:
        _embedder_failed = True
        raise RuntimeError("llama-cpp-python is not installed. Run:  pip install llama-cpp-python")
    except Exception as e:
        _embedder_failed = True  # any failure — download, size check, load — stops retries
        raise


def get_extractor():
    """
    Return a loaded llama_cpp.Llama instance configured for text generation.
    Returns None (without retrying) if the first load attempt failed for any reason.
    """
    global _extractor_instance, _extractor_failed
    if _extractor_instance is not None:
        return _extractor_instance
    if _extractor_failed:
        return None

    try:
        from llama_cpp import Llama
        model_path = ensure_model("extractor")
        spec = MODELS["extractor"]
        print(f"[model] Loading extractor ({spec['filename']})…", flush=True)
        _extractor_instance = Llama(
            model_path=str(model_path),
            n_ctx=spec["context_length"],
            n_threads=_cpu_threads(),
            verbose=False,
        )
        print("[model] ✓ Extractor ready.")
        return _extractor_instance
    except ImportError:
        _extractor_failed = True
        raise RuntimeError("llama-cpp-python is not installed. Run:  pip install llama-cpp-python")
    except Exception as e:
        _extractor_failed = True  # any failure — download, size check, load — stops retries
        raise


def _cpu_threads() -> int:
    """Use half the logical CPUs, minimum 2."""
    import os
    count = os.cpu_count() or 4
    return max(2, count // 2)


def unload_all() -> None:
    """Release both model instances (useful for testing)."""
    global _embedder_instance, _extractor_instance
    _embedder_instance = None
    _extractor_instance = None
