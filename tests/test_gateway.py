"""Gateway failures and streaming contracts, with an in-memory HTTP upstream."""
import importlib.util
import os
from uuid import uuid4
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    path = Path(__file__).parents[1] / "apps/api-gateway/src/main.py"
    spec = importlib.util.spec_from_file_location("gateway_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TestClient(module.app) as client:
        yield module, client


def upstream(module, handler):
    module.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_proxy_keeps_patch_query_auth_and_retry_headers(gateway):
    module, client = gateway
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(429, json={"detail": "wait"}, headers={"Retry-After": "7"})
    upstream(module, handle)
    result = client.patch("/api/customer/me?x=1", headers={"Authorization": "Bearer test", "X-Request-ID": "req-1"}, json={"full_name": "Test"})
    assert result.status_code == 429
    assert result.headers["retry-after"] == "7"
    assert result.headers["x-request-id"] == "req-1"
    assert seen[0].method == "PATCH" and seen[0].url.query == b"x=1"
    assert seen[0].headers["authorization"] == "Bearer test"


@pytest.mark.parametrize("error,status", [(httpx.ReadTimeout("test"), 504), (httpx.ConnectError("test"), 502)])
def test_proxy_dependency_errors_are_safe(gateway, error, status):
    module, client = gateway
    def handle(_):
        raise error
    upstream(module, handle)
    result = client.get("/api/catalog")
    assert result.status_code == status
    assert "test" not in result.text


def test_payload_limit_applies_without_content_length(gateway):
    module, client = gateway
    def handle(_):
        pytest.fail("Oversized request reached upstream")
    upstream(module, handle)
    result = client.post("/api/conversations", content=iter([b"x" * (module.MAX_BODY + 1)]))
    assert result.status_code == 413


def test_local_rate_limit_is_bounded_and_explains_retry(gateway):
    module, client = gateway
    upstream(module, lambda _: httpx.Response(200, json=[]))
    for _ in range(120):
        assert client.get("/api/catalog").status_code == 200
    for _ in range(3):
        result = client.get("/api/catalog")
        assert result.status_code == 429 and result.headers["retry-after"] == "60"
    assert max(map(len, module.app.state.rate_buckets.values())) <= 121


def test_stream_is_forwarded_without_reformatting(gateway):
    module, client = gateway
    data = b'event: delta\ndata: {"text":"test"}\n\nevent: done\ndata: {}\n\n'
    upstream(module, lambda _: httpx.Response(200, content=data, headers={"Content-Type": "text/event-stream"}))
    result = client.post("/api/conversations/example/stream", json={})
    assert result.content == data
    assert result.headers["content-type"].startswith("text/event-stream")


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="Requires local TEST_REDIS_URL")
def test_real_redis_rate_counter_is_bounded_and_expires(gateway, monkeypatch):
    from redis import Redis
    from redis.asyncio import Redis as AsyncRedis
    module, client = gateway
    prefix = "offline-test-" + uuid4().hex
    monkeypatch.setattr(module, "RATE_PREFIX", prefix)
    module.app.state.redis = AsyncRedis.from_url(os.environ["TEST_REDIS_URL"])
    upstream(module, lambda _: httpx.Response(200, json=[]))
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"])
    try:
        for _ in range(120):
            assert client.get("/api/catalog").status_code == 200
        assert client.get("/api/catalog").status_code == 429
        keys = list(redis.scan_iter(prefix + ":*"))
        assert keys and all(0 < redis.ttl(key) <= 120 for key in keys)
    finally:
        for key in redis.scan_iter(prefix + ":*"):
            redis.delete(key)
        redis.close()
