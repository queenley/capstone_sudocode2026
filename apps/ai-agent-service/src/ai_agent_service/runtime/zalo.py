"""Zalo Official Account: customers message the shop's OA and the agent answers.

The flow, per message Zalo posts to ``POST /api/channels/zalo/webhook``:

1. The signature is checked: ``X-ZEvent-Signature: mac=<sha256(app_id + body +
   timestamp + OA secret key)>``, as Zalo documents for OA webhooks.
2. Each Zalo message is handled once (Zalo retries; ``msg_id`` is the key).
3. The sender gets one platform conversation (channel ``zalo``) while it is
   open; the agent's call carries their Zalo user id as ``channel_ref``, the
   key the agent identifies customers by (``crm.get_customer(zalo_id=...)``).
4. The turn runs exactly as a web chat turn (``conversations.answer_turn``);
   the reply goes back through the OA customer-service message API. When a
   consultant has the conversation, the agent stays silent and the
   consultant's reply from the console is sent to Zalo instead.

Configuration (``.env``):

- ``ZALO_APP_ID``, ``ZALO_OA_SECRET_KEY``: verify webhooks;
- ``ZALO_APP_SECRET`` and ``ZALO_REFRESH_TOKEN`` (or ``ZALO_ACCESS_TOKEN``):
  send messages. Access tokens live about a day and refresh tokens are single
  use, so the newest pair is kept in ``zalo_tokens`` and refreshed before expiry.
- ``ZALO_WEBHOOK_INSECURE=1``: accept unsigned events, for the local simulator
  (``scripts/dev/zalo_simulator.py``) only. Never in production.
- ``ZALO_OPENAPI_URL``, ``ZALO_OAUTH_URL``: where the OA API and OAuth live,
  ``https://openapi.zalo.me`` and ``https://oauth.zaloapp.com`` unless set.
  The local mock platform (``scripts/dev/zalo_mock.py``) stands in for both, so
  replies are really sent, without an OA. Never set them in production.

Without send credentials, replies are logged in ``zalo_messages`` with status
``not_sent`` (visible to staff), so the whole flow can be tried without an OA.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .db import connection

logger = logging.getLogger(__name__)

OPENAPI_URL = "https://openapi.zalo.me"
OAUTH_URL = "https://oauth.zaloapp.com"
SEND_PATH = "/v3.0/oa/message/cs"
TOKEN_PATH = "/v4/oa/access_token"
#: Zalo's limit for one text message.
MAX_TEXT = 2000
#: Text events the agent answers; other events (images, stickers, follows) get a short note or nothing.
TEXT_EVENTS = {"user_send_text"}
MEDIA_EVENTS = {"user_send_image", "user_send_sticker", "user_send_gif", "user_send_audio", "user_send_video",
                "user_send_file", "user_send_location", "user_send_link"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS zalo_threads (
    user_id          TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL,
    display_name     TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS zalo_messages (
    id               BIGSERIAL PRIMARY KEY,
    user_id          TEXT NOT NULL,
    direction        TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    text             TEXT NOT NULL,
    zalo_msg_id      TEXT UNIQUE,
    conversation_id  TEXT,
    status           TEXT NOT NULL,
    error            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS zalo_messages_user_idx ON zalo_messages (user_id, id);
CREATE TABLE IF NOT EXISTS zalo_tokens (
    id               INT PRIMARY KEY CHECK (id = 1),
    access_token     TEXT,
    refresh_token    TEXT,
    expires_at       TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_ready = False


async def ensure_tables() -> None:
    global _ready
    if _ready:
        return
    async with connection() as conn:
        # One statement per call: the pool prepares statements, and a prepared
        # statement holds a single command.
        for statement in filter(None, (part.strip() for part in SCHEMA.split(";"))):
            await conn.execute(statement)
    _ready = True


# ── configuration and status ──────────────────────────────────────────────


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _url(variable: str, default: str, path: str) -> str:
    return (_env(variable) or default).rstrip("/") + path


def configured() -> dict[str, bool]:
    """What is set up, for the staff status view (never the secrets themselves)."""
    return {
        "webhook_verification": bool(_env("ZALO_APP_ID") and _env("ZALO_OA_SECRET_KEY")),
        "insecure_webhook": _env("ZALO_WEBHOOK_INSECURE") == "1",
        "can_send": bool(_env("ZALO_ACCESS_TOKEN") or (_env("ZALO_REFRESH_TOKEN") and _env("ZALO_APP_SECRET"))),
        "oa_id": bool(_env("ZALO_OA_ID")),
        # Replies go to another platform than Zalo's own: the local mock.
        "mock_platform": bool(_env("ZALO_OPENAPI_URL") or _env("ZALO_OAUTH_URL")),
    }


# ── webhook signature ─────────────────────────────────────────────────────


def verify(body: bytes, signature: str | None) -> bool:
    """Zalo's ``mac=sha256(app_id + body + timestamp + OA secret key)``, compared in constant time."""
    if _env("ZALO_WEBHOOK_INSECURE") == "1":
        return True
    app_id, secret = _env("ZALO_APP_ID"), _env("ZALO_OA_SECRET_KEY")
    if not (app_id and secret and signature):
        return False
    try:
        timestamp = str(json.loads(body).get("timestamp", ""))
    except ValueError:
        return False
    expected = hashlib.sha256((app_id + body.decode("utf-8") + timestamp + secret).encode("utf-8")).hexdigest()
    given = signature.split("=", 1)[1] if signature.startswith("mac=") else signature
    return hmac.compare_digest(expected, given.strip())


def sign(body: bytes) -> str:
    """The header value Zalo would send for *body*: used by the simulator and the tests."""
    timestamp = str(json.loads(body).get("timestamp", ""))
    digest = hashlib.sha256((_env("ZALO_APP_ID") + body.decode("utf-8") + timestamp + _env("ZALO_OA_SECRET_KEY")).encode("utf-8"))
    return "mac=" + digest.hexdigest()


# ── message log and threads ───────────────────────────────────────────────


async def record_incoming(user_id: str, text: str, msg_id: str | None) -> bool:
    """Log an incoming message; False when this ``msg_id`` was already handled (a Zalo retry)."""
    await ensure_tables()
    async with connection() as conn:
        cursor = await conn.execute(
            "INSERT INTO zalo_messages (user_id, direction, text, zalo_msg_id, status) VALUES (%s, 'in', %s, %s, 'received') "
            "ON CONFLICT (zalo_msg_id) DO NOTHING RETURNING id",
            (user_id, text, msg_id),
        )
        return await cursor.fetchone() is not None


async def thread_conversation(user_id: str) -> str | None:
    await ensure_tables()
    async with connection() as conn:
        cursor = await conn.execute("SELECT conversation_id FROM zalo_threads WHERE user_id = %s", (user_id,))
        row = await cursor.fetchone()
    return row["conversation_id"] if row else None


async def set_thread(user_id: str, conversation_id: str) -> None:
    async with connection() as conn:
        await conn.execute(
            "INSERT INTO zalo_threads (user_id, conversation_id) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET conversation_id = EXCLUDED.conversation_id, updated_at = now()",
            (user_id, conversation_id),
        )


async def mark_incoming(msg_id: str | None, conversation_id: str, status: str, error: str | None = None) -> None:
    if not msg_id:
        return
    async with connection() as conn:
        await conn.execute(
            "UPDATE zalo_messages SET conversation_id = %s, status = %s, error = %s WHERE zalo_msg_id = %s",
            (conversation_id, status, error, msg_id),
        )


async def messages(user_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    await ensure_tables()
    async with connection() as conn:
        if user_id:
            cursor = await conn.execute(
                "SELECT * FROM zalo_messages WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user_id, limit))
        else:
            cursor = await conn.execute("SELECT * FROM zalo_messages ORDER BY id DESC LIMIT %s", (limit,))
        rows = await cursor.fetchall()
    return [{**row, "created_at": row["created_at"].isoformat()} for row in reversed(rows)]


# ── sending ───────────────────────────────────────────────────────────────


async def _token() -> str | None:
    """A valid access token: the stored one, refreshed when it is about to expire."""
    await ensure_tables()
    async with connection() as conn:
        row = await (await conn.execute("SELECT * FROM zalo_tokens WHERE id = 1")).fetchone()
    now = datetime.now(timezone.utc)
    if row and row["access_token"] and row["expires_at"] and row["expires_at"] > now + timedelta(minutes=5):
        return row["access_token"]
    refresh = (row["refresh_token"] if row and row["refresh_token"] else None) or _env("ZALO_REFRESH_TOKEN")
    if refresh and _env("ZALO_APP_SECRET") and _env("ZALO_APP_ID"):
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                _url("ZALO_OAUTH_URL", OAUTH_URL, TOKEN_PATH),
                headers={"secret_key": _env("ZALO_APP_SECRET")},
                data={"refresh_token": refresh, "app_id": _env("ZALO_APP_ID"), "grant_type": "refresh_token"},
            )
        body = response.json() if response.content else {}
        if response.is_success and body.get("access_token"):
            expires = now + timedelta(seconds=int(body.get("expires_in") or 3600))
            async with connection() as conn:
                await conn.execute(
                    "INSERT INTO zalo_tokens (id, access_token, refresh_token, expires_at) VALUES (1, %s, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET access_token = EXCLUDED.access_token, "
                    "refresh_token = EXCLUDED.refresh_token, expires_at = EXCLUDED.expires_at, updated_at = now()",
                    (body["access_token"], body.get("refresh_token") or refresh, expires),
                )
            return body["access_token"]
        logger.warning("Zalo token refresh failed: %s", body.get("error_name") or body.get("message") or response.status_code)
    return _env("ZALO_ACCESS_TOKEN") or None


async def send(user_id: str, text: str, conversation_id: str | None = None) -> dict[str, Any]:
    """Send *text* to a Zalo user (split at Zalo's length limit) and log it."""
    await ensure_tables()
    text = (text or "").strip()
    if not text:
        return {"status": "skipped"}
    chunks = [text[i:i + MAX_TEXT] for i in range(0, len(text), MAX_TEXT)]
    token = await _token()
    status, error = ("not_sent", "No Zalo access token configured") if not token else ("sent", None)
    if token:
        async with httpx.AsyncClient(timeout=10) as client:
            for chunk in chunks:
                try:
                    response = await client.post(_url("ZALO_OPENAPI_URL", OPENAPI_URL, SEND_PATH),
                                                 headers={"access_token": token},
                                                 json={"recipient": {"user_id": user_id}, "message": {"text": chunk}})
                    body = response.json() if response.content else {}
                    if not response.is_success or body.get("error", 0) != 0:
                        status, error = "failed", f"{body.get('error')}: {body.get('message')}"[:300]
                        break
                except httpx.HTTPError as exc:
                    status, error = "failed", f"{type(exc).__name__}: {exc}"[:300]
                    break
    async with connection() as conn:
        await conn.execute(
            "INSERT INTO zalo_messages (user_id, direction, text, conversation_id, status, error) VALUES (%s, 'out', %s, %s, %s, %s)",
            (user_id, text, conversation_id, status, error),
        )
    if status == "failed":
        logger.warning("Zalo send to %s failed: %s", user_id[-4:], error)
    return {"status": status, "error": error}


# ── one incoming event ────────────────────────────────────────────────────


async def handle(app: Any, event: dict[str, Any]) -> dict[str, Any]:
    """Answer one webhook event; runs after the webhook has returned 200."""
    from ..api.routes.conversations import TurnRequest, answer_turn
    from . import platform

    name = event.get("event_name")
    user_id = str((event.get("sender") or {}).get("id") or "")
    message = event.get("message") or {}
    msg_id = message.get("msg_id")
    if not user_id or (name not in TEXT_EVENTS and name not in MEDIA_EVENTS):
        return {"status": "ignored", "event": name}
    text = str(message.get("text") or "").strip() if name in TEXT_EVENTS else f"[{name}]"
    if not await record_incoming(user_id, text, msg_id):
        return {"status": "duplicate"}
    if name in MEDIA_EVENTS:
        await send(user_id, "Dạ hiện em chỉ đọc được tin nhắn chữ. Anh/chị nhắn giúp em nội dung cần hỗ trợ nhé ạ.")
        return {"status": "media"}

    # The user's open conversation, or a new one.
    conversation = None
    existing = await thread_conversation(user_id)
    if existing:
        conversation = await platform.view(app, existing)
        if conversation is None or conversation.status not in ("open", "handed_off"):
            conversation = None
    if conversation is None:
        conversation = await platform.view(app, await platform.open_channel_conversation(app, "zalo"))
        await set_thread(user_id, conversation.id)

    started = time.perf_counter()
    try:
        result = await answer_turn(app, conversation, TurnRequest(message=text[:4000], turn_id=msg_id),
                                   arrived=started, channel_ref=user_id)
    except Exception as exc:  # noqa: BLE001 - the customer still gets an answer
        logger.exception("Zalo turn failed for conversation %s", conversation.id)
        await mark_incoming(msg_id, conversation.id, "failed", f"{type(exc).__name__}: {exc}"[:300])
        await send(user_id, "Dạ hệ thống đang bận, anh/chị vui lòng nhắn lại sau ít phút hoặc gọi hotline giúp em ạ.",
                   conversation.id)
        return {"status": "failed"}
    await mark_incoming(msg_id, conversation.id, "answered")
    if result.get("waiting") or not result.get("reply"):
        # A consultant has it: their reply from the console goes to Zalo.
        return {"status": "waiting_for_staff", "conversation_id": conversation.id}
    sent = await send(user_id, result["reply"], conversation.id)
    return {"status": sent["status"], "conversation_id": conversation.id}
