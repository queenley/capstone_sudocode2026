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

from ...components.context import skills as skill_book
from ...components.improvement import market as battlecards, review, skill_versions
from ...runtime import airflow_pipeline, evaluations, k8s_pipeline
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
    await asyncio.to_thread(skill_book.reload)
    return {"status": "active", "skills_version": candidate, "previous": previous, "reload_required": False}


@router.post("/improvement/skills/rollback")
async def rollback(body: Rollback, request: Request) -> dict[str, Any]:
    staff(request, ADMIN)
    reviewer = _reviewer(request)
    try:
        previous = await asyncio.to_thread(skill_versions.rollback, body.to, reviewer=reviewer, reason=body.reason)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    await asyncio.to_thread(skill_book.reload)
    return {"skills_version": body.to, "previous": previous, "reload_required": False}


# ── battlecards from the market research (docs/plan/002) ──────────────────


@router.get("/improvement/market/cards")
async def market_cards(request: Request,
                       status: Literal["pending", "flagged", "approved", "rejected"] | None = Query(default=None)
                       ) -> dict[str, Any]:
    """The cards the research drafted, with the gate's reasons and what it saw of other sellers (staff only)."""
    staff(request, READ)
    return {"cards": await asyncio.to_thread(battlecards.cards, status)}


@router.get("/improvement/market/evidence")
async def market_evidence(request: Request, sku: str | None = Query(default=None, max_length=64)) -> dict[str, Any]:
    """The search results kept as evidence: internal, never shown to the advisor or a customer."""
    staff(request, READ)
    return {"evidence": await asyncio.to_thread(battlecards.evidence, sku)}


@router.get("/improvement/market/gap-suggestions")
async def market_gap_suggestions(request: Request) -> dict[str, Any]:
    """Draft answers from the web for the open knowledge gaps: for the consultant to read, never published as such."""
    staff(request, READ)
    from ...components.improvement import market_gaps

    return {"suggestions": await asyncio.to_thread(market_gaps.suggestions)}


@router.post("/improvement/market/cards/{card_id}/review")
async def market_decide(card_id: str, body: Decision, request: Request) -> dict[str, Any]:
    """Approve (publish as the next knowledge version) or reject one pending card, under the signed-in person."""
    staff(request, ADMIN)
    if body.decision == "rejected" and len(body.note.strip()) < 3:
        raise HTTPException(422, "Từ chối cần ghi lý do")
    reviewer = _reviewer(request)
    try:
        record = await asyncio.to_thread(battlecards.decide, card_id, body.decision, reviewer=reviewer,
                                         note=body.note.strip())
    except KeyError as error:
        raise HTTPException(404, "Battlecard not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    # The knowledge server reads its version at startup, as for a Knowledge Gap entry.
    return {"card": record, "reload_required": record["status"] == "approved"}


@router.get("/evaluations")
async def history(request: Request, purpose: str | None = Query(default=None, max_length=32),
                  limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, Any]:
    staff(request, READ)
    async with connection() as conn:
        return {"runs": await evaluations.list_runs(conn, purpose=purpose, limit=limit)}


@router.get("/evaluations/{run_id}/scenarios")
async def history_scenarios(run_id: str, request: Request) -> dict[str, Any]:
    """Each scenario of one ingested run: passed or not, the organisers' reasons, turns, tool calls, TTFT."""
    staff(request, READ)
    if len(run_id) > 200:
        raise HTTPException(422, "run_id too long")
    async with connection() as conn:
        return {"run_id": run_id, "scenarios": await evaluations.list_scenarios(conn, run_id)}


# ── the round's pipeline: Airflow locally, CronJobs on EKS ─────────────────


class PipelineRun(BaseModel):
    week: str | None = Field(default=None, max_length=10)


def _runner() -> str | None:
    """Which scheduler drives the round: Kubernetes when IMPROVE_RUNNER says so, else Airflow when configured."""
    if k8s_pipeline.configured():
        return "kubernetes"
    return "airflow" if airflow_pipeline.configured() else None


@router.get("/improvement/pipeline")
async def pipeline(request: Request) -> dict[str, Any]:
    """The weekly round's blocks and the latest runs, each block's state (runtime/airflow_pipeline.py,
    runtime/k8s_pipeline.py)."""
    staff(request, READ)
    if _runner() == "kubernetes":
        async with connection() as conn:
            rounds = {str(r["name"]): r for r in await evaluations.list_rounds(conn, limit=12)}
        return await k8s_pipeline.status(rounds)
    return {**await airflow_pipeline.status(), "runner": "airflow"}


@router.post("/improvement/pipeline/runs")
async def pipeline_run(body: PipelineRun, request: Request) -> dict[str, Any]:
    """Start the round by hand (paid model calls). It files proposals; it never approves or switches one on."""
    staff(request, ADMIN)
    reviewer = _reviewer(request)
    runner = _runner()
    if runner is None:
        raise HTTPException(503, "Chưa có Airflow (AIRFLOW_URL) hay CronJob cải tiến (IMPROVE_RUNNER=kubernetes)")
    module = k8s_pipeline if runner == "kubernetes" else airflow_pipeline
    try:
        return await module.trigger(body.week, by=reviewer)
    except airflow_pipeline.PipelineError as error:
        raise HTTPException(502, str(error)) from error


@router.post("/improvement/pipeline/runs/{run_id}/blocks/{block}/rerun")
async def pipeline_rerun(run_id: str, block: str, request: Request) -> dict[str, Any]:
    """One block of a run again, and every block after it."""
    staff(request, ADMIN)
    reviewer = _reviewer(request)
    runner = _runner()
    if runner is None:
        raise HTTPException(503, "Chưa có Airflow (AIRFLOW_URL) hay CronJob cải tiến (IMPROVE_RUNNER=kubernetes)")
    if len(run_id) > 200:
        raise HTTPException(422, "run_id too long")
    try:
        if runner == "kubernetes":
            return await k8s_pipeline.rerun(run_id, block, by=reviewer)
        return await airflow_pipeline.rerun(run_id, block)
    except airflow_pipeline.PipelineError as error:
        raise HTTPException(502, str(error)) from error


# ── the skills, for an admin to read and change ────────────────────────────


class SkillIn(BaseModel):
    description: str = Field(min_length=1, max_length=400)
    body: str = Field(min_length=1, max_length=8000)
    done_on: list[str] = Field(default_factory=list, max_length=10)


class SkillEdit(BaseModel):
    #: name -> the skill as it should read, or null to take it out.
    changes: dict[str, SkillIn | None] = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=500)
    #: False keeps the new version as a candidate; switch it on later.
    activate: bool = True


@router.get("/improvement/skills")
async def skills(request: Request, version: int | None = Query(default=None, ge=0)) -> dict[str, Any]:
    """The skills of the version in force (or of *version*), each marked when it differs from the original, and
    every version with who wrote it and what it changed."""
    staff(request, READ)

    def read() -> dict[str, Any]:
        active = skill_versions.active()
        shown = active if version is None else version
        book = skill_versions.read_version(shown)
        original = skill_versions.read_version(0)
        return {
            "active": active,
            "version": shown,
            "skills": [{"name": name, "description": skill.get("description", ""), "done_on": skill.get("done_on") or [],
                        "body": skill.get("body", ""), "changed": original.get(name) != skill,
                        "new": name not in original} for name, skill in book.items()],
            "versions": skill_versions.versions(),
            "limits": {"description": skill_versions.MAX_DESCRIPTION, "body": skill_versions.ADMIN_MAX_BODY},
            "served": skill_book.active_version(skill_book.versions_dir()) == active,
        }

    try:
        return await asyncio.to_thread(read)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/improvement/skills")
async def edit_skills(body: SkillEdit, request: Request) -> dict[str, Any]:
    """An admin's change to the skills, as the next version; switched on (and served at once) unless kept as a
    candidate. The original (version 0) is never changed: rolling back to it is always possible."""
    staff(request, ADMIN)
    reviewer = _reviewer(request)
    changes = {name: (skill.model_dump() if skill is not None else None) for name, skill in body.changes.items()}
    try:
        version = await asyncio.to_thread(skill_versions.edit, changes, reviewer=reviewer, note=body.note,
                                          activate=body.activate)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if body.activate:
        await asyncio.to_thread(skill_book.reload)
    return {"skills_version": version, "active": body.activate}


@router.post("/improvement/skills/versions/{version}/activate")
async def activate_skills(version: int, body: Activation, request: Request) -> dict[str, Any]:
    """Serve *version* from the next turn (a candidate, or an older one to go back to)."""
    staff(request, ADMIN)
    reviewer = _reviewer(request)
    try:
        if version == 0:
            previous = await asyncio.to_thread(skill_versions.rollback, 0, reviewer=reviewer,
                                               reason=body.note or "admin: về bản gốc")
        else:
            previous = await asyncio.to_thread(skill_versions.activate, version, reviewer=reviewer, note=body.note)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    await asyncio.to_thread(skill_book.reload)
    return {"skills_version": version, "previous": previous}


# ── the shop's policies, as the assistant reads them ─────────────────────────


@router.get("/policies")
async def policies(request: Request) -> dict[str, Any]:
    """Every section of the organisers' policy documents (read-only: data/btc/policy), as retrieval sees it: who may
    hear it (a document marked internal is never quoted to a customer), when it is in force, the changelog entries
    behind it; then what reviewers added on top, in the knowledge version in force (data/kb)."""
    staff(request, READ)

    def read() -> dict[str, Any]:
        from ...components.improvement import versions
        from ...components.knowledge.corpus import policy_chunks
        from ...config.config_manager import btc_data_dir

        documents: dict[str, dict[str, Any]] = {}
        for chunk in policy_chunks(btc_data_dir() / "policy"):
            doc = documents.setdefault(chunk.doc, {"doc": chunk.doc, "title": chunk.doc_title, "sections": []})
            doc["sections"].append({
                "id": chunk.chunk_id, "title": chunk.title, "text": chunk.text, "restricted": chunk.restricted,
                "valid_from": chunk.valid_from, "valid_to": chunk.valid_to, "changelog": list(chunk.changelog),
                "industry": chunk.industry,
            })
        for doc in documents.values():
            sections = doc["sections"]
            doc["internal"] = bool(sections) and all(s["restricted"] for s in sections)
            doc["retired"] = bool(sections) and all(s["valid_to"] for s in sections)
        active = versions.active()
        learned = versions.entries(active) if active else []
        return {
            "documents": list(documents.values()),
            "learned": {"version": active, "entries": [
                {k: entry.get(k) for k in ("chunk_id", "title", "text", "cites", "valid_from", "valid_to", "approved_by",
                                           "source", "question") if entry.get(k) is not None}
                for entry in learned]},
        }

    return await asyncio.to_thread(read)
