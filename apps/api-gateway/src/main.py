import os
import time
import asyncio
from collections import deque
from contextlib import asynccontextmanager

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from redis.asyncio import Redis

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=None)
    redis_url = os.getenv("REDIS_URL", "")
    app.state.redis = Redis.from_url(redis_url) if redis_url else None
    app.state.rate_buckets = {}
    yield
    await app.state.http.aclose()
    if app.state.redis:
        await app.state.redis.aclose()


app = FastAPI(title="Telesales API Gateway", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        redis = request.app.state.redis
        if redis:
            try:
                minute = int(time.time() / 60)
                bucket = f"ratelimit:{key}:{minute}"
                count = await redis.incr(bucket)
                if count == 1:
                    await redis.expire(bucket, 120)
            except Exception:
                return JSONResponse(
                    status_code=503, content={"detail": "Rate limiter unavailable"}
                )
        else:
            buckets = request.app.state.rate_buckets
            queue = buckets.setdefault(key, deque())
            while queue and queue[0] < now - 60:
                queue.popleft()
            queue.append(now)
            count = len(queue)
            if len(buckets) > 10000:
                for old_key, old_queue in list(buckets.items()):
                    if not old_queue or old_queue[-1] < now - 60:
                        del buckets[old_key]
        if count > 120:
            return JSONResponse(status_code=429, content={"detail": "Too many requests"})
    return await call_next(request)


COMMERCE_SERVICE_URL = os.getenv(
    "COMMERCE_SERVICE_URL", "http://commerce-service:8100"
)
IDENTITY_SERVICE_URL = os.getenv(
    "IDENTITY_SERVICE_URL", "http://identity-service:8200"
)
SALES_SERVICE_URL = os.getenv("SALES_SERVICE_URL", "http://sales-service:8300")
AI_AGENT_SERVICE_URL = os.getenv(
    "AI_AGENT_SERVICE_URL", "http://ai-agent-service:8400"
)
HEALTH_TARGETS = {
    "commerce": (COMMERCE_SERVICE_URL, "/health/ready"),
    "identity": (IDENTITY_SERVICE_URL, "/health/ready"),
    "sales": (SALES_SERVICE_URL, "/health/ready"),
    "ai_agent": (AI_AGENT_SERVICE_URL, "/health/ready"),
}


def upstream_for(path: str) -> str:
    if path == "api/catalog" or path.startswith("api/catalog/"):
        return COMMERCE_SERVICE_URL
    if path.startswith("api/auth/") or path.startswith("api/customer/"):
        return IDENTITY_SERVICE_URL
    if path == "api/conversations" or path.startswith("api/conversations/"):
        if "/identity/" in path:
            return IDENTITY_SERVICE_URL
        if path.endswith("/turns") or path.endswith("/stream"):
            return AI_AGENT_SERVICE_URL
        return SALES_SERVICE_URL
    if path.startswith("api/admin/users"):
        return IDENTITY_SERVICE_URL
    if path.startswith(
        ("api/admin/catalog", "api/admin/inventory/", "api/admin/promotions")
    ):
        return COMMERCE_SERVICE_URL
    if path.startswith(("api/admin/proposals", "api/staff/", "api/seller/")):
        if path.startswith(("api/admin/proposals", "api/staff/")):
            return SALES_SERVICE_URL
        return COMMERCE_SERVICE_URL
    if path.startswith(("api/developer/", "api/agent/", "api/channels/")):
        return AI_AGENT_SERVICE_URL
    return None


@app.get("/health")
async def health():
    return {"gateway": "ok", "service": "api-gateway"}


@app.get("/health/ready")
async def readiness(request: Request):
    async def check(name, target):
        base_url, path = target
        try:
            response = await request.app.state.http.get(
                base_url.rstrip("/") + path, timeout=2.0
            )
            return name, "ready" if response.is_success else "unavailable"
        except httpx.HTTPError:
            return name, "unavailable"

    checks = await asyncio.gather(
        *(check(name, target) for name, target in HEALTH_TARGETS.items())
    )
    services = dict(checks)
    services["api_gateway"] = "ready"
    ready = all(status == "ready" for status in services.values())
    body = {"status": "ready" if ready else "degraded", "services": services}
    return body if ready else JSONResponse(status_code=503, content=body)


@app.websocket("/api/conversations/{conversation_id}/voice")
async def voice_proxy(websocket: WebSocket, conversation_id: str):
    """Relay a voice call to the AI service frame by frame, both directions.

    The AI service authorises the call itself (the first text frame carries the
    conversation token), so the gateway only copies frames and close codes.
    """
    await websocket.accept()
    url = AI_AGENT_SERVICE_URL.replace("http", "ws", 1).rstrip("/")
    url += f"/api/conversations/{conversation_id}/voice"
    try:
        upstream = await websockets.connect(url, max_size=None, open_timeout=5)
    except (OSError, websockets.WebSocketException):
        await websocket.close(code=1011, reason="Upstream service is unavailable")
        return

    async def client_to_upstream():
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("bytes")
            await upstream.send(data if data is not None else message.get("text") or "")

    async def upstream_to_client():
        async for data in upstream:
            if isinstance(data, bytes):
                await websocket.send_bytes(data)
            else:
                await websocket.send_text(data)

    tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect, websockets.WebSocketException):
        pass
    finally:
        for task in tasks:
            task.cancel()
        code = upstream.close_code or 1000
        await upstream.close()
        try:
            await websocket.close(code=code)
        except RuntimeError:
            pass  # the browser already went away


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(path: str, request: Request):
    upstream_url = upstream_for(path)
    if upstream_url is None:
        return JSONResponse(status_code=404, content={"detail": "No service owns this route"})
    url = upstream_url.rstrip("/") + "/" + path
    if request.url.query:
        url += "?" + request.url.query
    headers = {
        key: value
        for key, value in request.headers.items()
        # x-zevent-signature: Zalo signs its webhooks (api/channels/zalo/webhook).
        if key.lower() in {"authorization", "content-type", "accept", "x-request-id", "x-zevent-signature"}
    }
    client = request.app.state.http
    try:
        upstream = await client.send(
            client.build_request(
                request.method,
                url,
                headers=headers,
                content=await request.body(),
            ),
            stream=True,
        )
    except httpx.HTTPError:
        return JSONResponse(
            status_code=502,
            content={"detail": "Upstream service is unavailable"},
        )

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in {"content-type", "cache-control", "x-accel-buffering"}
    }

    async def body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        body(), status_code=upstream.status_code, headers=response_headers
    )
