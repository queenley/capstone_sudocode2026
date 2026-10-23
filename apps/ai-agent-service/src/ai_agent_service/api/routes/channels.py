"""Messaging channels the agent serves itself: Zalo OA, and the status of every channel.

- ``POST /api/channels/zalo/webhook``: Zalo's webhook (public, signature-checked).
  It answers 200 at once and handles the event in the background, because an
  agent turn takes seconds and Zalo does not wait for it.
- ``GET /api/channels/status``: which channels are set up (staff).
- ``GET /api/channels/zalo/messages``: the Zalo message log (staff), newest last.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from src.api.routes.shared import staff

from ...runtime import harness, zalo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.post("/zalo/webhook")
async def zalo_webhook(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not zalo.verify(body, request.headers.get("X-ZEvent-Signature")):
        raise HTTPException(401, "Invalid Zalo signature")
    try:
        event = json.loads(body)
    except ValueError as error:
        raise HTTPException(400, "Body is not JSON") from error
    harness.spawn(_handle(request.app, event))
    return {"received": True}


async def _handle(app: Any, event: dict[str, Any]) -> None:
    try:
        outcome = await zalo.handle(app, event)
        logger.info("Zalo %s: %s", event.get("event_name"), outcome.get("status"))
    except Exception:  # noqa: BLE001 - background task: log, never crash the service
        logger.exception("Zalo event failed")


@router.get("/status")
def channel_status(request: Request) -> dict[str, Any]:
    staff(request, {"admin", "agent", "developer"})
    livekit = bool(os.environ.get("LIVEKIT_URL") and os.environ.get("LIVEKIT_API_KEY"))
    return {
        "web": {"enabled": True},
        "zalo": {"enabled": True, **zalo.configured()},
        "hotline": {"enabled": livekit, "livekit": livekit, "sip_trunk": bool(os.environ.get("SIP_TRUNK_ID"))},
    }


@router.get("/zalo/messages")
async def zalo_messages(request: Request, user_id: str | None = Query(default=None, max_length=64),
                        limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    staff(request, {"admin", "agent", "developer"})
    return await zalo.messages(user_id, limit)
