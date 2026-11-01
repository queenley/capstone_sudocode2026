"""Create a structured-output client for a configured pipeline role.

Each role selects its provider and model in config/settings.yaml. Provider
adapters are registered here so pipeline stages do not depend on a vendor.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

#: provider -> (module, class), imported only when a role uses it: an OpenAI run needs no Gemini SDK.
_PROVIDERS = {"gemini": ("src.providers.gemini_client", "GeminiClient"),
              "openai": ("src.providers.openai_client", "OpenAIClient")}


def create_model_client(
    role: str,
    settings: dict[str, Any],
    cache_dir: Path,
    log_path: Path,
) -> Any:
    """Build the configured client for ``role`` (scenario, dialogue, etc.)."""
    roles = settings.get("models", {})
    role_config = roles.get(role)
    if not isinstance(role_config, dict):
        raise ValueError(
            f"Missing models.{role} configuration in config/settings.yaml"
        )

    provider = str(role_config.get("provider", "gemini")).lower()
    model = role_config.get("model")
    if not model:
        raise ValueError(f"Missing models.{role}.model in config/settings.yaml")
    if provider not in _PROVIDERS:
        supported = ", ".join(sorted(_PROVIDERS))
        raise ValueError(
            f"Unsupported provider '{provider}' for models.{role}; supported: {supported}"
        )
    module, name = _PROVIDERS[provider]
    client_type = getattr(importlib.import_module(module), name)

    provider_settings = settings.get(provider, {})
    return client_type(
        model=model,
        cache_dir=cache_dir / provider,
        log_path=log_path,
        retries=provider_settings.get("retries", 3),
        rpm_limit=provider_settings.get("rpm_limit", 10),
        rpd_limit=provider_settings.get("rpd_limit", 100),
        retry_backoff_seconds=provider_settings.get("retry_backoff_seconds", 2),
    )
