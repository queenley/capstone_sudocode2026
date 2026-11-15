"""The /admin pipeline view over Airflow's REST API (runtime/airflow_pipeline.py), on a fake Airflow."""
import asyncio
import json

import httpx
import pytest

from ai_agent_service.runtime import airflow_pipeline as pipeline


@pytest.fixture()
def airflow(monkeypatch):
    seen: list[tuple[str, str, dict]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        seen.append((request.method, request.url.path, body))
        path = request.url.path.removeprefix("/api/v1")
        if request.headers.get("authorization") != httpx.BasicAuth("api", "secret")._auth_header:
            return httpx.Response(401)
        if path == "/dags/improvement_weekly" and request.method == "GET":
            return httpx.Response(200, json={"is_paused": True})
        if path == "/dags/improvement_weekly/dagRuns" and request.method == "GET":
            return httpx.Response(200, json={"dag_runs": [{"dag_run_id": "manual__1", "state": "running",
                                                           "run_type": "manual", "conf": {"week": "2026-W46"}}]})
        if path.endswith("/taskInstances"):
            return httpx.Response(200, json={"task_instances": [
                {"task_id": "restate_gaps", "state": "success", "try_number": 1},
                {"task_id": "weekly_learn", "state": "running", "try_number": 1}]})
        if path == "/dags/improvement_weekly" and request.method == "PATCH":
            return httpx.Response(200, json={"is_paused": False})
        if path == "/dags/improvement_weekly/dagRuns" and request.method == "POST":
            return httpx.Response(200, json={"dag_run_id": "manual__2", "state": "queued"})
        if path == "/dags/improvement_weekly/clearTaskInstances":
            return httpx.Response(200, json={"task_instances": [{}, {}, {}]})
        return httpx.Response(404)

    monkeypatch.setenv("AIRFLOW_URL", "http://airflow:8080")
    monkeypatch.setenv("AIRFLOW_USER", "api")
    monkeypatch.setenv("AIRFLOW_PASSWORD", "secret")
    monkeypatch.setattr(pipeline, "_client", lambda: httpx.AsyncClient(
        base_url="http://airflow:8080/api/v1", auth=("api", "secret"), transport=httpx.MockTransport(handle)))
    return seen


def test_each_block_of_the_latest_run_has_its_state(airflow):
    found = asyncio.run(pipeline.status())
    assert found["available"] and found["paused"] is True and found["error"] is None
    run = found["runs"][0]
    assert run["week"] == "2026-W46"
    assert [b["id"] for b in found["blocks"]] == ["restate_gaps", "weekly_learn", "wait_for_review", "weekly_measure"]
    assert run["blocks"]["restate_gaps"]["state"] == "success"
    assert run["blocks"]["weekly_learn"]["state"] == "running"
    assert run["blocks"]["weekly_measure"]["state"] is None


def test_a_manual_run_unpauses_the_dag_and_names_its_week(airflow):
    started = asyncio.run(pipeline.trigger("2026-W47", by="staff:admin"))
    assert started == {"run_id": "manual__2", "state": "queued", "week": "2026-W47"}
    methods = [(m, p) for m, p, _ in airflow]
    assert methods.index(("PATCH", "/api/v1/dags/improvement_weekly")) < methods.index(("POST", "/api/v1/dags/improvement_weekly/dagRuns"))
    assert airflow[-1][2]["conf"] == {"week": "2026-W47"}
    with pytest.raises(pipeline.PipelineError):
        asyncio.run(pipeline.trigger("tuần này", by="staff:admin"))


def test_a_block_runs_again_with_the_blocks_after_it(airflow):
    assert asyncio.run(pipeline.rerun("manual__1", "weekly_learn"))["cleared"] == 3
    body = airflow[-1][2]
    assert body["task_ids"] == ["weekly_learn"] and body["include_downstream"] and not body["dry_run"]
    with pytest.raises(pipeline.PipelineError):
        asyncio.run(pipeline.rerun("manual__1", "rm_everything"))


def test_without_airflow_the_blocks_still_show_and_nothing_starts(monkeypatch):
    monkeypatch.delenv("AIRFLOW_URL", raising=False)
    found = asyncio.run(pipeline.status())
    assert not found["available"] and len(found["blocks"]) == 4 and found["runs"] == []


def test_a_wrong_password_is_said_plainly(monkeypatch, airflow):
    monkeypatch.setattr(pipeline, "_client", lambda: httpx.AsyncClient(
        base_url="http://airflow:8080/api/v1", auth=("api", "wrong"),
        transport=httpx.MockTransport(lambda request: httpx.Response(401))))
    assert "tài khoản API" in asyncio.run(pipeline.status())["error"]
