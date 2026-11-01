"""Signed deletion command from Identity's outbox; never exposed by the gateway."""
import hmac
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from src.identity.deletion import signature

from ...mcp.servers.memory import memory_delete_customer
from ...mcp.server_base import ToolFailure
from ...runtime.db import connection

router = APIRouter()


class Deletion(BaseModel):
    request_id: UUID
    customer_id: UUID
    conversation_ids: list[UUID] = Field(default_factory=list, max_length=10000)


@router.post("/internal/customer-deletions")
async def delete_customer(body: Deletion, request: Request):
    raw = await request.body()
    expected = signature(request.app.state.settings.secret, raw)
    if not hmac.compare_digest(request.headers.get("X-Deletion-Signature", ""), expected):
        raise HTTPException(403, "Invalid deletion signature")
    async with connection() as conn:
        rows = await (await conn.execute(
            "SELECT id, customer_id, tier FROM calls WHERE conversation_id = ANY(%s::uuid[])",
            ([str(value) for value in body.conversation_ids],))).fetchall()
    owners = {str(row["customer_id"]) for row in rows if row.get("customer_id") and row["tier"] == "VERIFIED"}
    owners.add(str(body.customer_id))
    owners.add(f"web:{body.customer_id}")
    try:
        for owner in owners:
            # Unconfirmed calls of this platform account may be erased, but cannot authorise erasing a claimed profile.
            await memory_delete_customer(owner, call_ids=[row["id"] for row in rows])
    except ToolFailure as error:
        raise HTTPException(503, "Deletion is waiting for active work to finish", headers={"Retry-After": "10"}) from error
    return {"status": "deleted", "request_id": str(body.request_id)}
