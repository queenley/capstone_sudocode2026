"""The rate limiter: one per model, counting every attempt, waiting only as long as a full budget asks.

The workbench's older tests import the temp-repo layout (``src.``) and do not run here; these carry the
three properties the limiter was repaired for (a slot is reserved before the call, the limiter is shared,
a 429 cools it down) onto the per-model scope. No model is called.
"""

import time

import pytest

from ai_agent_service.llm import factory
from ai_agent_service.llm.rate_limiter import AdvancedTokenRateLimiter

LIMITS = {
    "requests_per_minute": 2,
    "input_tokens_per_minute": 1_000,
    "output_tokens_per_minute": 1_000,
    "input_token_price_per_million": 0.0,
    "output_token_price_per_million": 0.0,
    "buffer_percentage": 0.0,
}


@pytest.fixture(autouse=True)
def fresh_registry():
    factory._LIMITERS.clear()
    yield
    factory._LIMITERS.clear()


def test_each_model_has_its_own_limiter_shared_by_every_caller():
    first = factory.limiter_for("google_genai", LIMITS, "gemini-a")
    again = factory.limiter_for("google_genai", LIMITS, "gemini-a")
    other = factory.limiter_for("google_genai", LIMITS, "gemini-b")
    assert first is again
    assert first is not other
    assert set(factory.limiter_stats()) == {"google_genai/gemini-a", "google_genai/gemini-b"}


def test_a_429_holds_back_that_model_only():
    first = factory.limiter_for("google_genai", LIMITS, "gemini-a")
    other = factory.limiter_for("google_genai", LIMITS, "gemini-b")
    first.record_rate_limited(retry_after=5)
    assert first.acquire(blocking=False) is False
    assert other.acquire(blocking=False) is True


def test_a_failed_call_still_uses_its_slot():
    limiter = factory.limiter_for("google_genai", LIMITS, "gemini-a")
    assert limiter.acquire(blocking=False) and limiter.acquire(blocking=False)
    limiter.record_failure()
    assert limiter.acquire(blocking=False) is False


def test_the_wait_is_the_full_budget_s_not_a_younger_token_entry_s():
    limiter = AdvancedTokenRateLimiter(provider="t/m", requests_per_minute=2, input_tokens_per_minute=1_000,
                                       output_tokens_per_minute=1_000, input_token_price_per_million=0.0,
                                       output_token_price_per_million=0.0, buffer_percentage=0.0)
    now = time.time()
    # Two requests 50 s ago fill the request budget; their tokens came back 10 s ago, far under budget.
    limiter.request_timestamps.extend([now - 50, now - 50])
    limiter.input_token_usage.append((now - 10, 100))
    limiter.output_token_usage.append((now - 10, 100))
    wait = next(limiter._delays())
    assert 9 <= wait <= 11, wait
    assert limiter.stats()["waited_s"] == pytest.approx(wait, abs=0.2)


def test_a_full_token_budget_still_waits():
    limiter = AdvancedTokenRateLimiter(provider="t/m", requests_per_minute=100, input_tokens_per_minute=1_000,
                                       output_tokens_per_minute=1_000, input_token_price_per_million=0.0,
                                       output_token_price_per_million=0.0, buffer_percentage=0.0)
    now = time.time()
    limiter.input_token_usage.append((now - 20, 1_000))
    wait = next(limiter._delays())
    assert 39 <= wait <= 41, wait
