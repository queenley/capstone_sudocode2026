"""What model calls cost, from token counts and the prices in ``config/models.yaml``.

Prices are per provider (``providers.<name>.rate_limits.*_token_price_per_million``,
USD). A provider whose price is not set costs 0 and is reported as unpriced,
so a missing price never passes for a free run.
"""

from __future__ import annotations

from typing import Any

CURRENCY = "USD"


def prices(provider: str) -> tuple[float, float] | None:
    """USD per million input and output tokens for *provider*, or None when unset or unknown."""
    from ai_agent_service.config.config_manager import get_models_config

    try:
        limits = get_models_config().provider(provider).rate_limits
    except (KeyError, ValueError):
        return None
    pair = (float(limits.input_token_price_per_million), float(limits.output_token_price_per_million))
    return pair if any(pair) else None


def cost(provider: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD for one batch of tokens, or None when *provider* has no price."""
    pair = prices(provider)
    if pair is None:
        return None
    return round((input_tokens * pair[0] + output_tokens * pair[1]) / 1_000_000, 8)


def usage(provider: str, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    """The harness's usage block: tokens, and the cost when the provider is priced."""
    spent = cost(provider, input_tokens, output_tokens)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost": spent, "currency": CURRENCY if spent is not None else None}
