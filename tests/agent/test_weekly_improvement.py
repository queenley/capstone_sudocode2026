"""The weekly improvement round and the evaluation history (docs/plan/001, parts B and C), with no model and no database."""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_agent_service.api.routes import improvement as routes
from ai_agent_service.components.improvement import review, skill_versions
from ai_agent_service.pipeline.eval import history
from ai_agent_service.pipeline.improve import weekly
from ai_agent_service.runtime import evaluations


def _run(directory, *, report=True, manifest_name="manifest.json"):
    directory.mkdir()
    (directory / manifest_name).write_text(json.dumps({
        "run_id": "20261109-020000", "status": "COMPLETE", "started_at": "2026-11-11T02:00:00+00:00",
        "scenarios": {"files": {"A.json": "aa", "B.json": "bb"}},
        "models": {"advisor": {"model": "gpt-x"}, "extractor": {"extractor_version": "product-extractor-v13"}},
        "evaluation": {"profile": "reflection", "knowledge_version_override": None, "skills_version_override": 3},
        "knowledge": {"version": 0}}), encoding="utf-8")
    if report:
        rate = lambda v: {"value": v}  # noqa: E731
        section = {"repeat_question_rate": rate(4.0), "context_carryover_rate": rate(60.0),
                   "task_success_rate": rate(40.0), "hallucination_rate": {"value": 9.0, "price_promo_only": rate(2.5)}}
        (directory / "report.json").write_text(json.dumps({"n_scenarios": 2, "system": section,
                                                           "baseline": {**section, "task_success_rate": rate(20.0)}}))
    return directory


def test_a_scored_run_becomes_one_record_with_the_organisers_rates(tmp_path):
    record = history.summary(_run(tmp_path / "r"), purpose="weekly_candidate", round_name="weekly-2026-W46")
    run = record["run"]
    assert (run["purpose"], run["round"], run["profile"], run["skills_version"]) == (
        "weekly_candidate", "weekly-2026-W46", "reflection", 3)
    assert run["week"] == "2026-11-09" and run["extractor_version"] == "product-extractor-v13"
    assert run["cohort_sha256"] == history.cohort_sha256({"scenarios": {"files": {"B.json": "bb", "A.json": "aa"}}})
    got = {(m["config"], m["metric"]): m["value"] for m in record["metrics"]}
    assert got[("full", "HR")] == 2.5  # the figure the organisers' own table prints
    assert got[("full", "TSR")] == 40.0 and got[("baseline_no_memory", "TSR")] == 20.0


def test_an_unscored_run_is_refused_and_a_single_trace_layout_is_read(tmp_path):
    with pytest.raises(ValueError, match="not scored"):
        history.summary(_run(tmp_path / "unscored", report=False))
    assert history.summary(_run(tmp_path / "single", manifest_name="full.manifest.json"))["run"]["run_id"]
    with pytest.raises(ValueError, match="purpose"):
        history.summary(_run(tmp_path / "bad"), purpose="whenever")


def test_an_old_run_belongs_to_the_week_it_ran_not_to_today(tmp_path):
    directory = _run(tmp_path / "old")
    manifest = json.loads((directory / "manifest.json").read_text())
    del manifest["started_at"]
    manifest["run_id"] = "20261103-101500"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert history.summary(directory)["run"]["week"] == "2026-11-02"


def test_the_history_never_goes_into_an_eval_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AGENT_DATABASE_URL", raising=False)
    monkeypatch.setenv("EVAL_DATABASE_URL", "postgresql://u:p@localhost:5432/app_db_eval")
    assert "dbname=app_db " in evaluations.app_database_url() + " "
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/app_db_eval")
    with pytest.raises(RuntimeError, match="_eval"):
        evaluations.app_database_url()


def test_iso_weeks():
    assert weekly.iso_week("2026-W46") == "2026-W46"
    assert weekly.monday("2026-W46").isoformat() == "2026-11-09"
    assert weekly.iso_week(today=datetime(2026, 11, 12).date()) == "2026-W46"
    with pytest.raises(ValueError):
        weekly.iso_week("46")


def test_a_candidate_is_written_without_being_switched_on(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path / "improvement"))
    monkeypatch.delenv("EVAL_SKILLS_VERSION", raising=False)
    folder = tmp_path / "skills"
    book = skill_versions.skill_book.read_book(folder)
    skill = next(iter(book))
    part = next(key for key, value in book[skill].items() if isinstance(value, str) and value)
    patch = {"skill": skill, "part": part, "find": "", "text": "Một câu mới.", "cites": []}
    candidate = skill_versions.publish([patch], reviewer="staff:1", folder=folder, activate=False)
    assert candidate == 1 and skill_versions.active(folder) == 0
    assert skill_versions.activate(candidate, reviewer="staff:1", folder=folder) == 0
    assert skill_versions.active(folder) == 1
    with pytest.raises(ValueError):
        skill_versions.activate(9, reviewer="staff:1", folder=folder)


def test_the_admins_decisions_go_back_into_the_review_file(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"proposals": [
        {"proposal_id": "SK-1", "author": "reflection", "patch": {"skill": "s"}, "decision": None, "reviewer": None},
        {"proposal_id": "SK-2", "author": "reflection", "patch": {"skill": "s"}, "decision": None, "reviewer": None}]}))
    weekly.write_decisions(path, [{"id": "SK-1", "decision": "approved", "reviewer": "staff:7", "note": "ok"},
                                  {"id": "SK-2", "decision": "rejected", "reviewer": "staff:7", "note": "sai"}])
    taken, refused = review.approved(path)
    assert [t["proposal_id"] for t in taken] == ["SK-1"] and refused[0]["proposal_id"] == "SK-2"


class FakeStore:
    def __init__(self, found):
        self.found, self.updates = found, []

    def install(self, monkeypatch):
        @asynccontextmanager
        async def connection():
            yield object()

        async def get_round(conn, name):
            return self.found

        async def set_round(conn, name, **fields):
            self.updates.append(fields)

        monkeypatch.setattr(evaluations, "cli_connection", connection)
        monkeypatch.setattr(evaluations, "get_round", get_round)
        monkeypatch.setattr(evaluations, "set_round", set_round)
        monkeypatch.setattr(routes, "connection", connection)
        return self


def _round(status="waiting_review", decided=(None,), updated=None):
    return {"name": "weekly-2026-W46", "status": status, "base_skills_version": 0, "candidate_skills_version": None,
            "updated_at": (updated or datetime.now(timezone.utc)).isoformat(),
            "proposals": [{"id": f"SK-{i}", "decision": d, "review_file": "x.json"} for i, d in enumerate(decided)]}


@pytest.mark.asyncio
async def test_the_sensor_waits_while_a_proposal_waits_and_a_forgotten_round_expires(monkeypatch):
    store = FakeStore(_round()).install(monkeypatch)
    assert await weekly.status("2026-W46") == 1
    store.found = _round(decided=("approved",))
    assert await weekly.status("2026-W46") == 0
    store.found = _round(updated=datetime.now(timezone.utc) - timedelta(days=weekly.REVIEW_DAYS + 1))
    assert await weekly.status("2026-W46") == 0 and store.updates[-1]["status"] == "expired"


@pytest.mark.asyncio
async def test_nothing_approved_is_not_measured_and_moved_skills_stop_the_round(tmp_path, monkeypatch):
    review_file = tmp_path / "x.json"
    review_file.write_text(json.dumps({"proposals": [{"proposal_id": "SK-0", "author": "reflection",
                                                      "patch": {"skill": "s"}}]}))
    found = _round(decided=("rejected",))
    found["proposals"][0].update(review_file=str(review_file), reviewer="staff:7", note="không")
    store = FakeStore(found).install(monkeypatch)
    monkeypatch.setattr(weekly, "_use_round_dir", lambda week: tmp_path)
    measured = []
    monkeypatch.setattr("ai_agent_service.pipeline.improve.cli._evaluate", lambda *a, **k: measured.append(a))
    assert await weekly.measure("2026-W46", frozen_sets=[tmp_path]) == 0
    assert store.updates[-1]["status"] == "rejected" and not measured

    found["proposals"][0]["decision"] = "approved"
    review_file.write_text(json.dumps({"proposals": [{"proposal_id": "SK-0", "author": "reflection",
                                                      "patch": {"skill": "s"}}]}))
    monkeypatch.setattr(skill_versions, "active", lambda folder=None: 2)
    assert await weekly.measure("2026-W46", frozen_sets=[tmp_path]) == 2
    assert store.updates[-1]["status"] == "failed" and not measured


def _request(actor="u-1"):
    return SimpleNamespace(state=SimpleNamespace(actor_id=actor))


@pytest.mark.asyncio
async def test_the_admin_cannot_switch_on_a_harmful_or_stale_candidate(monkeypatch):
    monkeypatch.setattr(routes, "staff", lambda request, roles: "admin")
    store = FakeStore({**_round(status="harm"), "candidate_skills_version": 1}).install(monkeypatch)
    with pytest.raises(HTTPException) as refused:
        await routes.activate("weekly-2026-W46", routes.Activation(), _request())
    assert refused.value.status_code == 409
    store.found = {**_round(status="measured"), "candidate_skills_version": 1}
    monkeypatch.setattr(skill_versions, "active", lambda folder=None: 5)
    with pytest.raises(HTTPException) as stale:
        await routes.activate("weekly-2026-W46", routes.Activation(), _request())
    assert "v5" in stale.value.detail
    switched = []
    monkeypatch.setattr(skill_versions, "active", lambda folder=None: 0)
    monkeypatch.setattr(skill_versions, "activate", lambda v, **k: switched.append((v, k["reviewer"])) or 0)
    result = await routes.activate("weekly-2026-W46", routes.Activation(), _request())
    assert result["reload_required"] and switched == [(1, "staff:u-1")]
    assert store.updates[-1]["status"] == "active"


@pytest.mark.asyncio
async def test_a_decision_needs_a_person_and_a_refusal_a_reason(monkeypatch):
    monkeypatch.setattr(routes, "staff", lambda request, roles: "admin")
    with pytest.raises(HTTPException) as agent:
        await routes.decide("SK-1", routes.Decision(decision="approved"), _request("reflection"))
    assert agent.value.status_code == 403
    with pytest.raises(HTTPException) as reason:
        await routes.decide("SK-1", routes.Decision(decision="rejected"), _request())
    assert reason.value.status_code == 422
