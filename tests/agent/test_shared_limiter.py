"""The model limiter counted across pods in Valkey (eks-architecture.md 3.1). Needs a Redis: LIMITER_TEST_REDIS_URL
(e.g. docker run --rm -p 6391:6379 redis:7-alpine, then redis://127.0.0.1:6391/0); skipped without one."""
import os
import uuid

import pytest

from ai_agent_service.llm.shared_limiter import SharedTokenRateLimiter

URL = os.getenv("LIMITER_TEST_REDIS_URL", "redis://127.0.0.1:6391/0")


def _redis():
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url(URL, socket_timeout=0.5, socket_connect_timeout=0.5)
    try:
        client.ping()
    except Exception:  # noqa: BLE001
        pytest.skip(f"no Redis at {URL}")
    return client


CONFIG = {"requests_per_minute": 2, "input_tokens_per_minute": 1000, "output_tokens_per_minute": 1000,
          "input_token_price_per_million": 1.0, "output_token_price_per_million": 2.0, "buffer_percentage": 0.0}


def _pods(client, n=2, pods=1, **override):
    key = f"test/{uuid.uuid4().hex}"
    return [SharedTokenRateLimiter.from_config_shared(key, {**CONFIG, **override}, client=client, pods=pods) for _ in range(n)]


def test_two_pods_share_one_request_budget():
    a, b = _pods(_redis())
    assert a.acquire(blocking=False) and b.acquire(blocking=False)
    assert not a.acquire(blocking=False) and not b.acquire(blocking=False)  # 2 per minute, across both


def test_one_pods_429_holds_every_pod():
    a, b = _pods(_redis(), requests_per_minute=100)
    a.record_rate_limited(retry_after=30)
    assert not b.acquire(blocking=False)


def test_tokens_one_pod_spent_count_for_the_other():
    a, b = _pods(_redis(), requests_per_minute=100)
    assert a.acquire(blocking=False)
    a.record_request(1200, 10)  # over the minute's 1000 input tokens
    assert not b.acquire(blocking=False)


def test_a_blocking_acquire_waits_for_the_window_then_goes(monkeypatch):
    a, b = _pods(_redis())
    for limiter in (a, b):
        limiter.window_seconds = 0.5
    assert a.acquire(blocking=False) and b.acquire(blocking=False)
    assert b.acquire(blocking=True)  # waits about half a second for the oldest to age out
    assert b.total_waited > 0


def test_without_valkey_each_pod_keeps_its_share():
    import redis

    down = redis.Redis.from_url("redis://127.0.0.1:1/0", socket_timeout=0.1, socket_connect_timeout=0.1)
    (a,) = _pods(down, n=1, pods=2, requests_per_minute=4)
    assert a.acquire(blocking=False) and a.acquire(blocking=False)
    assert not a.acquire(blocking=False)  # 4 per minute over 2 pods: 2 here
