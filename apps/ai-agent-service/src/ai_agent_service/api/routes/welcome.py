"""A read-only welcome for the verified website account; never opens an agent call."""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from src.api.routes.shared import bearer
from src.db.models import Customer, CustomerIdentity

from ...components.clock import VIETNAM
from ...components.identity.resolver import digest
from ...components.intake.pii import normalise_phone
from ...components.memory.ontology import slot
from ...mcp.servers import memory
from ...runtime.vault import identity_secret

router = APIRouter(prefix="/api/agent", tags=["welcome"])
logger = logging.getLogger(__name__)


class WelcomeBlocker(BaseModel):
    text: str = Field(max_length=400)
    valid_until: datetime


class Welcome(BaseModel):
    returning: bool = False
    name: str | None = Field(default=None, max_length=160)
    blocker: WelcomeBlocker | None = None
    expires_at: datetime


def _account(request: Request, token: str) -> tuple[str, str | None, str | None]:
    with request.app.state.database.sessions() as db:
        customer_id = request.app.state.security.customer(db, token)
        customer = db.get(Customer, customer_id)
        if customer is None or customer.deleted_at is not None:
            raise HTTPException(401, "Customer access expired or invalid")
        identity = db.scalar(select(CustomerIdentity).where(
            CustomerIdentity.customer_id == customer_id, CustomerIdentity.kind == "phone",
            CustomerIdentity.verified_at.is_not(None), CustomerIdentity.revoked_at.is_(None),
            CustomerIdentity.encrypted_value.is_not(None),
        ).order_by(CustomerIdentity.verified_at.desc()))
        phone = request.app.state.security.decrypt(identity.encrypted_value) if identity else None
        return str(customer_id), customer.full_name, normalise_phone(phone) if phone else None


def _erased(profile: dict[str, Any]) -> bool:
    return bool(profile.get("deleted_at") or profile.get("deletion_pending"))


def _active(fact: dict[str, Any], on: date) -> bool:
    try:
        return (fact.get("status") == "active" and date.fromisoformat(fact["valid_from"]) <= on
                and (not fact.get("valid_to") or on <= date.fromisoformat(fact["valid_to"])))
    except (KeyError, TypeError, ValueError):
        return False


def _observed(fact: dict[str, Any]) -> tuple[datetime, datetime] | None:
    source = fact.get("source") or {}
    if not isinstance(source, dict):
        return None
    raw = source.get("observed_at") or fact.get("valid_from")
    try:
        if isinstance(raw, str) and len(raw) == 10:
            start = datetime.combine(date.fromisoformat(raw), time.min, VIETNAM)
            return start, start + timedelta(days=1)
        moment = datetime.fromisoformat(raw)
        if moment.tzinfo is None:
            return None
        moment = moment.astimezone(timezone.utc)
        return moment, moment
    except (ValueError, TypeError):
        return None


def _blocker(facts: list[dict[str, Any]], now: datetime, episodes: list[dict[str, Any]] | None = None) -> WelcomeBlocker | None:
    blockers = [f for f in facts if f.get("slot") == "blocker" and _active(f, now.date())]
    if len(blockers) != 1:
        return None
    fact = blockers[0]
    source = fact.get("source") or {}
    text = fact.get("value")
    if not isinstance(source, dict) or isinstance(fact.get("confidence"), bool):
        return None
    call_id, turn = source.get("call_id"), source.get("turn")
    valid_call = ((isinstance(call_id, str) and bool(call_id.strip()))
                  or (type(call_id) is int and call_id > 0))
    if not valid_call or type(turn) is not int or turn < 1:
        return None
    try:
        confidence = float(fact.get("confidence", 0))
    except (TypeError, ValueError, OverflowError):
        return None
    if (not isinstance(text, str) or not text.strip() or len(text) > 400
            or not math.isfinite(confidence) or not 0.6 <= confidence <= 1
            or source.get("said_by") != "customer"):
        return None
    # Enforce the ontology's TTL even on old rows which have no valid_to.
    end = date.fromisoformat(fact["valid_from"]) + timedelta(days=slot("blocker").ttl_days)
    if fact.get("valid_to"):
        end = min(end, date.fromisoformat(fact["valid_to"]))
    until = datetime.combine(end + timedelta(days=1), time.min, VIETNAM)
    if now >= until:
        return None
    # An order or a closed/rejected outcome newer than the blocker settles that discussion.
    observed = _observed(fact)
    if observed is None or observed[0] > now:
        return None
    for episode in episodes or []:
        if episode.get("outcome") not in ("chot_don", "tu_choi"):
            continue
        when = _observed({"source": {"observed_at": episode.get("date")}})
        if (when is None or when[1] > observed[0] or when[0] == observed[0]
                or episode.get("call_id") == call_id):
            return None
    for other in facts:
        if not _active(other, now.date()):
            continue
        if other.get("slot") in ("order_id", "order_ids") or (
            other.get("slot") == "outcome" and other.get("value") in ("chot_don", "tu_choi")
        ):
            when = _observed(other)
            # Date-only evidence spans the whole day. Ambiguous/malformed ordering hides the blocker.
            if when is None or when[1] > observed[0] or when[0] == observed[0]:
                return None
    return WelcomeBlocker(text=" ".join(text.split()), valid_until=until)


@router.get("/welcome", response_model=Welcome)
async def welcome(request: Request, response: Response) -> Welcome:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Vary"] = "Authorization"
    token = bearer(request)
    account = await asyncio.to_thread(_account, request, token)
    now = datetime.now(VIETNAM)
    empty = Welcome(expires_at=now + timedelta(seconds=30))
    customer_id, name, phone = account
    if not phone:
        return empty
    try:
        own_id = f"web:{customer_id}"
        own = await memory.memory_get_profile(own_id, now.date().isoformat())
        if _erased(own):
            return empty
        matches = (await memory.identity_find("phone", digest("phone", phone, identity_secret())))["matches"]
        # A shared/provisional key must be confirmed in chat; an automatic popup cannot do that.
        if matches and (len(matches) != 1 or matches[0].get("status") != "confirmed"):
            return empty
        owner = matches[0]["customer_id"] if matches else own_id
        if owner.startswith("web:") and owner != own_id:
            return empty
        profile = own if owner == own_id else await memory.memory_get_profile(owner, now.date().isoformat())
        if _erased(profile):
            return empty
        episodes = (await memory.memory_get_episodes(owner, 1))["episodes"]
        # Recheck both stores after I/O: logout/revocation/erasure can race the reads above.
        for identity in {owner, own_id}:
            latest = await memory.memory_get_profile(identity, now.date().isoformat())
            if _erased(latest):
                return empty
            if identity == owner:
                profile = latest
        if (await memory.identity_find("phone", digest("phone", phone, identity_secret())))["matches"] != matches:
            return empty
        if await asyncio.to_thread(_account, request, token) != account:
            return empty
        facts = [f for f in profile.get("facts", []) if _active(f, now.date())]
        result = Welcome(returning=bool(facts or episodes), expires_at=empty.expires_at)
        if result.returning:
            result.name = " ".join(name.split())[:160] if name else None
            result.blocker = _blocker(facts, now, episodes)
            if result.blocker:
                result.expires_at = min(result.expires_at, result.blocker.valid_until)
        return result
    except HTTPException:
        raise
    except Exception as error:
        logger.warning("Welcome memory unavailable (%s)", type(error).__name__)
        raise HTTPException(503, "Chưa tải được lời chào. Bạn vẫn có thể mở chat.") from error
