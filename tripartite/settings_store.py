"""
tripartite/settings_store.py

Simple JSON-backed settings persistence.
Stored at ~/.tripartite/settings.json (same cache dir as models).

Usage:
    from .settings_store import Settings
    s = Settings.load()
    s.embedder_filename = "mxbai-embed-large-v1-q4_k_m.gguf"
    s.save()
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import CACHE_DIR, KNOWN_MODELS

SETTINGS_PATH = CACHE_DIR / "settings.json"

# Default model filenames — first in KNOWN_MODELS list for each role
_DEFAULT_EMBEDDER  = next(m["filename"] for m in KNOWN_MODELS if m["role"] == "embedder")
_DEFAULT_EXTRACTOR = next(m["filename"] for m in KNOWN_MODELS if m["role"] == "extractor")


@dataclass
class Settings:
    embedder_filename:  str = field(default_factory=lambda: _DEFAULT_EMBEDDER)
    extractor_filename: str = field(default_factory=lambda: _DEFAULT_EXTRACTOR)

    # ── Persistence ───────────────────────────────────────────────────────────

    @classmethod
    def load(cls) -> "Settings":
        """Load from disk, falling back to defaults on any error."""
        try:
            if SETTINGS_PATH.exists():
                data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception:
            pass
        return cls()

    def save(self) -> None:
        """Persist to disk.  Creates parent directory if needed."""
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(asdict(self), indent=2),
            encoding="utf-8",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_embedder_spec(self) -> dict:
        """Return the full KNOWN_MODELS entry for the selected embedder."""
        return _spec_for("embedder", self.embedder_filename)

    def get_extractor_spec(self) -> dict:
        """Return the full KNOWN_MODELS entry for the selected extractor."""
        return _spec_for("extractor", self.extractor_filename)

    # Convenience aliases used by gui.py
    @property
    def embedder_model(self) -> str:
        return self.embedder_filename

    def spec_for(self, role: str) -> dict:
        filename = self.embedder_filename if role == "embedder" else self.extractor_filename
        return _spec_for(role, filename)

    def model_is_cached(self, role: str) -> bool:
        """Return True if the selected model for *role* is present and large enough."""
        from .config import MODELS_DIR
        spec = self.spec_for(role)
        path = MODELS_DIR / spec["filename"]
        return path.exists() and path.stat().st_size >= spec.get("min_size_bytes", 0)


def _spec_for(role: str, filename: str) -> dict:
    for m in KNOWN_MODELS:
        if m["role"] == role and m["filename"] == filename:
            return m
    # Filename not found — fall back to first available for that role
    return next(m for m in KNOWN_MODELS if m["role"] == role)
