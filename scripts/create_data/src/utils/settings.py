"""Load ``config/settings.yaml`` and build role-specific model clients."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from src.utils.paths import CACHE_DIR, CONFIG_DIR, MODEL_CALLS_LOG

_SAMPLING_DEFAULTS = {"temperature": 0.7, "judge_temperature": 0.1, "max_output_tokens": 8192}


@lru_cache(maxsize=1)
def load_settings() -> dict[str, Any]:
    return yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8"))


def sampling(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Provider-independent sampling parameters.

    Older configs stored these under ``gemini:`` even when OpenAI was selected;
    that block is still honoured as a fallback.
    """
    settings = settings or load_settings()
    legacy = settings.get("gemini", {})
    configured = settings.get("sampling", {})
    return {key: configured.get(key, legacy.get(key, default)) for key, default in _SAMPLING_DEFAULTS.items()}


def model_client(role: str, settings: dict[str, Any] | None = None):
    """Return the structured-output client configured for ``models.<role>``."""
    from src.providers import create_model_client  # lazy: avoids importing SDKs for offline stages

    return create_model_client(role, settings or load_settings(), CACHE_DIR, MODEL_CALLS_LOG)
