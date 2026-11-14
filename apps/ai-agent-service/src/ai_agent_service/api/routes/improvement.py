"""The admin's side of the weekly improvement loop, and the evaluation history.

``docs/plan/001-vong-cai-tien-hang-tuan-va-dashboard.md``, parts C and D. The weekly round
(``pipeline/improve/weekly.py``) files Reflection's proposals; here an admin reads each one with its evidence and
decides, reads the round's measurement (R0 against the candidate, R1), and switches the candidate on or not. The
evaluation history is what ``run_eval.py --ingest`` kept.

Reading is for ``admin`` and ``developer``; every decision and switch is ``admin`` only, under the signed-in
account. The rules of who may approve stay in ``components/improvement/review.py``: a decision recorded here goes back
into the round's review file before anything is published, and ``review.approved`` refuses an agent's name or the
proposal's author.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from src.api.routes.shared import staff

from ...components.improvement import review, skill_versions
from ...runtime import evaluations
from ...runtime.db import connection

router = APIRouter(prefix="/api/developer", tags=["improvement"])
READ = {"admin", "developer"}
ADMIN = {"admin"}


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=1000)


class Activation(BaseModel):
    note: str = Field(default="", max_length=500)


class Rollback(BaseModel):
    to: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)


def _reviewer(request: Request) -> str:
    """The signed-in person, as the review file records them: never a name ``review.approved`` would refuse."""
    actor = str(request.state.actor_id or "").strip()
    name = f"staff:{actor}" if actor else ""
    if not actor or actor.lower() in review.AGENTS:
        raise HTTPException(403, "A decision needs a person's account")
    return name


@router.get("/improvement/rounds")
async def rounds(request: Request) -> dict[str, Any]:
    staff(request, READ)
    async with connection() as conn:
        found = await evaluations.list_rounds(conn)
    return {"rounds": found, "skills_version": await asyncio.to_thread(skill_versions.active)}


@router.get("/improvement/rounds/{name}")
async def one_round(name: str, request: Request) -> dict[str, Any]:
    staff(request, READ)
    async with connection() as conn:
        found = await evaluations.get_round(conn, name)
    if found is None:
        raise HTTPException(404, "Round not found")
    return found


@router.post("/improvement/proposals/{proposal_id}/review")
async def decide(proposal_id: str, body: Decision, request: Request) -> dict[str, Any]:
    staff(request, ADMIN)
    if body.decision == "rejected" and len(body.note.strip()) < 3:
        raise HTTPException(422, "Từ chối cần ghi lý do")
    reviewer = _reviewer(request)
    async with connection() as conn:
        try:
            return await evaluations.decide(conn, proposal_id, decision=body.decision, reviewer=reviewer,
                                            note=body.note.strip())
        except KeyError as error:
            raise HTTPException(404, "Proposal not found") from error
        except PermissionError as error:
            raise HTTPException(409, str(error)) from error


@router.post("/improvement/rounds/{name}/activate")
async def activate(name: str, body: Activation, request: Request) -> dict[str, Any]:
    """Switch a measured candidate on. Refused when the measurement found harm, or when the skills in force are no
    longer the ones the round learned from (another version went live since)."""
    staff(request, ADMIN)
    reviewer = _reviewer(request)
    async with connection() as conn:
        found = await evaluations.get_round(conn, name)
        if found is None:
            raise HTTPException(404, "Round not found")
        if found["status"] == "harm":
            raise HTTPException(409, "Phép đo thấy vi phạm mới: không bật version này")
        if found["status"] != "measured" or found.get("candidate_skills_version") is None:
            raise HTTPException(409, f"Vòng đang ở trạng thái {found['status']}: chỉ bật được sau khi đã đo")
        active = await asyncio.to_thread(skill_versions.active)
        if active != found["base_skills_version"]:
            raise HTTPException(409, f"Skills đang chạy là v{active}, không phải v{found['base_skills_version']} "
                                     "mà vòng này học từ đó; chạy lại vòng")
        candidate = int(found["candidate_skills_version"])
        try:
            previous = await asyncio.to_thread(skill_versions.activate, candidate, reviewer=reviewer,
                                               note=body.note or f"weekly round {name}")
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        await evaluations.set_round(conn, name, status="active", detail={"activated_by": reviewer,
                                                                         "previous_skills_version": previous})
    return {"status": "active", "skills_version": candidate, "previous": previous, "reload_required": True}


@router.post("/improvement/skills/rollback")
async def rollback(body: Rollback, request: Request) -> dict[str, Any]:
    staff(request, ADMIN)
    reviewer = _reviewer(request)
    try:
        previous = await asyncio.to_thread(skill_versions.rollback, body.to, reviewer=reviewer, reason=body.reason)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"skills_version": body.to, "previous": previous, "reload_required": True}


@router.get("/evaluations")
async def history(request: Request, purpose: str | None = Query(default=None, max_length=32),
                  limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, Any]:
    staff(request, READ)
    async with connection() as conn:
        return {"runs": await evaluations.list_runs(conn, purpose=purpose, limit=limit)}
