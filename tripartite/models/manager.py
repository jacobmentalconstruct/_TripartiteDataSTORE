"""
Model manager: download-on-first-run, sha256 verification, and llama.cpp loading.

Models are cached in ~/.tripartite/models/.
On first run, missing models are downloaded with a progress bar.
Subsequent runs load from cache — fully offline, no server required.

v0.3.0 — Fixed root cause of llama.cpp "embeddings required but some input
  tokens were not marked as outputs -> overriding" warning by:
    1. Setting n_batch = n_ctx for embedding models (all tokens in one pass)
    2. Setting pooling_type explicitly from the model spec
    3. Installing a proper C-level log callback to prevent ctypes exceptions
  The suppress_stderr hack is retained ONLY for model-load (where llama.cpp
  prints unavoidable hardware-detection noise), not for embed() calls.
"""

import ctypes
import os
import sys
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from ..config import MODELS_DIR


# ── C-level log callback ─────────────────────────────────────────────────────
# llama.cpp fires log messages from C via a callback. When no callback is
# installed, it writes to stderr directly, which causes the ctypes/unraisablehook
# exceptions when Python's GIL state is wrong.  Installing a proper callback
# routes ALL C-level log output through Python's logging, eliminating both the
# stderr noise and the ctypes exception.

_LOG_CALLBACK_INSTALLED = False


def _install_llama_log_callback():
    """
    Install a Python-side log callback for llama.cpp's C logging system.

    This prevents the 'Exception ignored while calling ctypes callback function'
    error by ensuring the callback is properly registered and GIL-safe.
    Called once, before any model is loaded.
    """
    global _LOG_CALLBACK_INSTALLED
    if _LOG_CALLBACK_INSTALLED:
        return

    try:
        import llama_cpp
        # llama_cpp exposes llama_log_set which accepts a ctypes callback.
        # The callback signature is: void(enum ggml_log_level, const char*, void*)
        # We define a no-op callback that swallows all C-level log output.
        # For debug builds, you could route this to Python's logging module.

        @ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)
        def _quiet_log_callback(level, text, user_data):
            # Silently discard.  For debugging, uncomment:
            # if text: print(f"[llama.cpp L{level}] {text.decode('utf-8', errors='replace').rstrip()}")
            pass

        # Keep a reference so the callback isn't garbage-collected
        _install_llama_log_callback._ref = _quiet_log_callback

        # llama_log_set is the C function — available in llama_cpp.llama_cpp module
        if hasattr(llama_cpp, 'llama_log_set'):
            llama_cpp.llama_log_set(_quiet_log_callback, ctypes.c_void_p(0))
        elif hasattr(llama_cpp.llama_cpp, 'llama_log_set'):
            llama_cpp.llama_cpp.llama_log_set(_quiet_log_callback, ctypes.c_void_p(0))

        _LOG_CALLBACK_INSTALLED = True
    except Exception:
        # If the API surface has changed, fall back to suppress_stderr
        pass


# ── Suppress llama.cpp C-level stderr noise (retained for model load only) ────

@contextmanager
def suppress_stderr():
    """
    Context manager that silences C-level stderr output from llama.cpp.

    Uses OS-level file descriptor redirection so it catches output from
    native C/C++ code that bypasses Python's sys.stderr.

    Used during model load (hardware detection noise).  NOT needed for
    embed() calls once the log callback is installed and n_batch is correct.
    """
    sys.stderr.flush()
    _orig_fd = os.dup(2)
    _devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(_devnull, 2)
        yield
    finally:
        os.dup2(_orig_fd, 2)
        os.close(_orig_fd)
        os.close(_devnull)


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

def ensure_model(spec: dict) -> Path:
    """
    Ensure the model described by *spec* is present in the cache directory.
    Downloads if missing or clearly truncated, then returns the local path.

    Verification strategy: size check (not sha256).
    sha256 hashes are not bundled because they change with model updates on HF.
    A file above min_size_bytes is considered intact — a truncated download
    would be obviously smaller.
    """
    dest = MODELS_DIR / spec["filename"]
    min_size = spec.get("min_size_bytes", 10_000_000)

    if dest.exists():
        actual_size = dest.stat().st_size
        if actual_size >= min_size:
            return dest
        print(f"[model] {spec['filename']} appears truncated ({actual_size / 1e6:.1f} MB) — re-downloading.")
        dest.unlink()

    print(f"[model] {spec['filename']} not found in cache.")
    print(f"[model] Downloading from Hugging Face (~{_size_hint(spec)})…")
    _download(spec["url"], dest, spec["filename"])

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


def _size_hint(spec: dict) -> str:
    """Estimate download size from spec min_size_bytes."""
    min_mb = spec.get("min_size_bytes", 0) / 1_048_576
    return f"~{min_mb:.0f} MB"


# ── Model-aware parameter computation ─────────────────────────────────────────

def _compute_embedder_params(spec: dict) -> dict:
    """
    Derive llama.cpp constructor kwargs from the embedder model spec.

    Key insight: embedding models need ALL input tokens processed in a single
    batch to compute the pooled output correctly.  Setting n_batch < n_ctx
    causes llama.cpp to process in multiple batches, triggering the
    'input tokens not marked as outputs' warning and potentially degrading
    embedding quality for inputs longer than n_batch.

    Returns a dict of kwargs to pass to Llama().
    """
    ctx = spec.get("context_length", 512)

    params = {
        "embedding": True,
        "n_ctx": ctx,
        # CRITICAL: n_batch must equal n_ctx for embedding models.
        # This ensures all tokens are processed in one pass, which:
        #   1. Eliminates the "not marked as outputs" warning
        #   2. Produces correct pooled embeddings for long inputs
        #   3. Avoids redundant reprocessing overhead
        "n_batch": ctx,
        "n_threads": _cpu_threads(),
        "verbose": False,
    }

    # Pooling type: most embedding models use mean pooling.
    # Some (e.g. nomic-embed) use CLS.  Read from spec if present.
    pooling = spec.get("pooling_type")
    if pooling is not None:
        # llama.cpp pooling_type enum: 0=UNSPECIFIED, 1=MEAN, 2=CLS, 3=LAST
        _pooling_map = {"none": 0, "mean": 1, "cls": 2, "last": 3}
        if isinstance(pooling, str):
            pooling = _pooling_map.get(pooling.lower(), 1)
        params["pooling_type"] = pooling

    # type_k and type_v can be set for quantized KV cache on large-context models.
    # For small embedding models (ctx ≤ 2048) this doesn't matter.
    # For large-context models, quantized KV saves VRAM.
    if ctx > 2048:
        try:
            import llama_cpp
            # GGMLType.F16 = 1 — use f16 KV cache for large-context embedders
            params["type_k"] = 1
            params["type_v"] = 1
        except ImportError:
            pass

    return params


def _compute_extractor_params(spec: dict) -> dict:
    """
    Derive llama.cpp constructor kwargs from the extractor (text-gen) model spec.

    For text generation models, n_batch can be smaller than n_ctx because
    generation is autoregressive — we only need to process the prompt in one go,
    and prompts are typically much shorter than the full context window.
    """
    ctx = spec.get("context_length", 2048)

    params = {
        "n_ctx": ctx,
        # For text-gen: n_batch = min(ctx, 512) is a good balance between
        # prompt processing speed and memory usage
        "n_batch": min(ctx, 512),
        "n_threads": _cpu_threads(),
        "verbose": False,
    }

    return params


# ── llama.cpp wrappers ─────────────────────────────────────────────────────────

_embedder_instance = None
_extractor_instance = None
_embedder_model_name = None   # track which model is loaded
_extractor_model_name = None
_embedder_failed = False   # set True after first load failure — stops retrying
_extractor_failed = False


def get_embedder():
    """
    Return a loaded llama_cpp.Llama instance configured for embedding.
    Loads on first call; cached for the process lifetime.
    Returns None (without retrying) if the first load attempt failed for any reason.

    Automatically invalidates and reloads if the selected model in Settings has changed.

    v0.3.0: Constructor params are now derived from the model spec via
    _compute_embedder_params(), ensuring n_batch, n_ctx, and pooling_type
    are correctly scaled to the active model.
    """
    global _embedder_instance, _embedder_model_name, _embedder_failed

    # Install C-level log callback before any model load
    _install_llama_log_callback()

    # Read current selected model from Settings
    from ..settings_store import Settings
    settings = Settings.load()
    current_filename = settings.embedder_filename

    # Invalidate cache if model changed
    if _embedder_model_name is not None and _embedder_model_name != current_filename:
        print(f"[model] Embedder changed from {_embedder_model_name} to {current_filename} — reloading.")
        _embedder_instance = None
        _embedder_model_name = None
        _embedder_failed = False

    if _embedder_instance is not None:
        return _embedder_instance
    if _embedder_failed:
        return None

    try:
        from llama_cpp import Llama
        spec = settings.get_embedder_spec()
        model_path = ensure_model(spec)

        # Compute model-aware params
        llama_kwargs = _compute_embedder_params(spec)

        print(f"[model] Loading embedder ({spec['filename']})…", flush=True)
        print(f"[model]   n_ctx={llama_kwargs['n_ctx']}  "
              f"n_batch={llama_kwargs['n_batch']}  "
              f"dims={spec.get('dims', '?')}  "
              f"pooling={llama_kwargs.get('pooling_type', 'default')}", flush=True)

        with suppress_stderr():
            _embedder_instance = Llama(
                model_path=str(model_path),
                **llama_kwargs,
            )
        _embedder_model_name = current_filename
        print("[model] ✓ Embedder ready.")
        return _embedder_instance
    except ImportError:
        _embedder_failed = True
        raise RuntimeError("llama-cpp-python is not installed. Run:  pip install llama-cpp-python")
    except Exception as e:
        _embedder_failed = True
        raise


def get_extractor():
    """
    Return a loaded llama_cpp.Llama instance configured for text generation.
    Returns None (without retrying) if the first load attempt failed for any reason.

    Automatically invalidates and reloads if the selected model in Settings has changed.

    v0.3.0: Constructor params now derived from _compute_extractor_params().
    """
    global _extractor_instance, _extractor_model_name, _extractor_failed

    # Install C-level log callback before any model load
    _install_llama_log_callback()

    # Read current selected model from Settings
    from ..settings_store import Settings
    settings = Settings.load()
    current_filename = settings.extractor_filename

    # Invalidate cache if model changed
    if _extractor_model_name is not None and _extractor_model_name != current_filename:
        print(f"[model] Extractor changed from {_extractor_model_name} to {current_filename} — reloading.")
        _extractor_instance = None
        _extractor_model_name = None
        _extractor_failed = False

    if _extractor_instance is not None:
        return _extractor_instance
    if _extractor_failed:
        return None

    try:
        from llama_cpp import Llama
        spec = settings.get_extractor_spec()
        model_path = ensure_model(spec)

        # Compute model-aware params
        llama_kwargs = _compute_extractor_params(spec)

        print(f"[model] Loading extractor ({spec['filename']})…", flush=True)
        print(f"[model]   n_ctx={llama_kwargs['n_ctx']}  "
              f"n_batch={llama_kwargs['n_batch']}", flush=True)

        with suppress_stderr():
            _extractor_instance = Llama(
                model_path=str(model_path),
                **llama_kwargs,
            )
        _extractor_model_name = current_filename
        print("[model] ✓ Extractor ready.")
        return _extractor_instance
    except ImportError:
        _extractor_failed = True
        raise RuntimeError("llama-cpp-python is not installed. Run:  pip install llama-cpp-python")
    except Exception as e:
        _extractor_failed = True
        raise


def _cpu_threads() -> int:
    """Use half the logical CPUs, minimum 2."""
    import os
    count = os.cpu_count() or 4
    return max(2, count // 2)


def unload_all() -> None:
    """Release both model instances (useful for testing)."""
    global _embedder_instance, _extractor_instance, _embedder_model_name, _extractor_model_name
    _embedder_instance = None
    _extractor_instance = None
    _embedder_model_name = None
    _extractor_model_name = None


def safe_embed(embedder, text: str) -> list[float]:
    """
    Call embedder.embed() and return the embedding vector as a flat list of floats.

    v0.3.0: No longer wraps in suppress_stderr().  With n_batch == n_ctx and
    the C-level log callback installed, there is no stderr noise to suppress.
    The overhead of fd-level redirection per embed call was ~0.1ms each,
    which added up over thousands of chunks.

    Handles both list[float] and list[list[float]] return formats
    from different llama-cpp-python versions.
    """
    result = embedder.embed(text)
    # Normalise return format
    if result and isinstance(result[0], list):
        return result[0]
    return result


def get_active_embedder_spec() -> dict:
    """Return the KNOWN_MODELS spec dict for the currently selected embedder."""
    from ..settings_store import Settings
    return Settings.load().get_embedder_spec()
