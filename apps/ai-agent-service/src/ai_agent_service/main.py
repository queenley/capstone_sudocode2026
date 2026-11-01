"""AI Agent Service: the telesales agent of ``docs/design.md`` behind the platform gateway.

Startup order (each step logged; a failure degrades /health instead of killing
the process, so the cause can be read):

1. platform runtime (backend-common): shared DB session, ``Security``, settings;
2. the agent schema, its call tables and the LangGraph checkpointer (``runtime.db``);
3. the MCP servers and the hot graph (``runtime.harness.ready``), then
   ``after_call`` for calls that ended without being remembered;
4. background: voice models (download once, then load) and the reconciler that
   hangs up calls whose platform conversation was closed or went idle.

Routes: customer turns (``/api/conversations/{id}/turns|stream|voice``), the
staff console (``/api/agent/*``), developer/admin (``/api/developer/*``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from src.core.service_runtime import configure_service, database_ready

from .api.routes import agent_calls, channels, conversations, developer, voice, privacy, welcome
from .components import voice as voice_component
from .llm import tracing
from .mcp import client as mcp_client
from .observability.turns import TurnTracker
from .runtime import calls, db, harness, platform

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

VERSION = "1.0.0"
STARTED_AT = datetime.now(timezone.utc)
RECONCILE_SECONDS = 60


class StampArrival:
    """When a request reached the service: where TTFT starts (``huong-dan-do-latency.md`` rule 1).
    Plain ASGI, so it never buffers the SSE stream behind it."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["arrived"] = time.perf_counter()
        await self.app(scope, receive, send)


async def _prepare_voice() -> None:
    """Download the weights this machine lacks (once, into VOICE_MODELS_DIR), then load the chosen models."""
    from .components.voice import fetch

    started = time.perf_counter()
    try:
        await asyncio.to_thread(fetch.fetch_all)
        loaded = await voice.warm()
    except Exception:  # noqa: BLE001 - a call tries again and says why it cannot
        logger.exception("Voice preparation failed")
        return
    logger.info("Voice ready in %.1f s: %s, %s", time.perf_counter() - started, loaded["asr"], loaded["tts"])


async def _reconcile_forever(app: FastAPI) -> None:
    """Remember calls whose conversation Sales closed, and calls left idle."""
    while True:
        await asyncio.sleep(RECONCILE_SECONDS)
        try:
            open_ids = await calls.open_conversation_ids()
            closed = await platform.closed_conversations(app, open_ids)
            await calls.reconcile(closed)
            await harness.remember_unfinished()
        except Exception:  # noqa: BLE001 - try again next minute
            logger.exception("Call reconciliation failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = configure_service(app)
    app.state.turn_tracker = TurnTracker()
    app.state.startup_error = None
    try:
        await db.init_db()
        await db.init_checkpointer()
        logger.info("Agent storage ready")
    except Exception as error:  # noqa: BLE001 - reported through /health
        app.state.startup_error = str(error)
        logger.error("Agent storage unavailable at startup: %s", error)
    else:
        try:
            await harness.ready()
            harness.spawn(harness.remember_unfinished())
        except Exception as error:  # noqa: BLE001 - retried on the first turn
            logger.error("Agent warm-up failed, will retry on first request: %s", error)
        harness.spawn(_reconcile_forever(app))
    if not voice_component.status()["missing_packages"]:
        harness.spawn(_prepare_voice())
    yield
    app.state.turn_tracker.close()
    tracing.flush()
    await mcp_client.close_all()
    from .components.voice import asr
    asr.close()
    await db.close_pool()
    database.engine.dispose()


app = FastAPI(title="AI Agent Service", version=VERSION, lifespan=lifespan)
app.add_middleware(StampArrival)
app.include_router(conversations.router)
app.include_router(voice.router)
app.include_router(agent_calls.router)
app.include_router(developer.router)
app.include_router(channels.router)
app.include_router(privacy.router)
app.include_router(welcome.router)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Cheap enough to poll; each part that can fail on its own is reported on its own."""
    error = getattr(app.state, "startup_error", None)
    report: dict[str, Any] = {
        "status": "ok" if error is None else "degraded",
        "service": "ai-agent",
        "version": VERSION,
        "uptime_seconds": int((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
    }
    if error is not None:
        report["startup_error"] = error.splitlines()[0]
        return report
    report["components"] = {
        "database": await db.ping(),
        "checkpointer": {"status": "ok" if db.checkpointer_ready() else "not initialised"},
        "mcp": mcp_client.status() or {"status": "not connected"},
        "agent": harness.status(),
        "voice": voice_component.status(),
        "tracing": {"status": "on" if tracing.is_configured() else "off"},
    }
    return report


@app.get("/health/ready")
async def ready() -> Any:
    """Ready when the platform database and the agent storage both answer."""
    if getattr(app.state, "startup_error", None) is None and database_ready(app) and (await db.ping())["status"] == "ok":
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not ready"})
