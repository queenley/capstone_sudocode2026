"""The /admin pipeline view over the improvement CronJobs on EKS (runtime/k8s_pipeline.py), on a fake Kubernetes API."""
import asyncio
from pathlib import Path

import httpx
import pytest
import yaml

from ai_agent_service.runtime import k8s_pipeline as pipeline

ROOT = Path(__file__).resolve().parents[2]
NS = "telesales-production"
JOBS = f"/apis/batch/v1/namespaces/{NS}/jobs"


def _job(name, *, action="improve-learn", done=None, week=None, by=None, created="2026-11-16T19:00:00Z"):
    annotations = {k: v for k, v in (("telesales/week", week), ("telesales/by", by)) if v}
    conditions = [{"type": done, "status": "True", "lastTransitionTime": "2026-11-16T21:00:00Z"}] if done else []
    return {"metadata": {"name": name, "labels": {"telesales/improve": action}, "annotations": annotations,
                         "creationTimestamp": created},
            "status": {"startTime": created, "active": 0 if done else 1, "conditions": conditions,
                       **({"completionTime": "2026-11-16T21:00:00Z"} if done == "Complete" else {})}}


@pytest.fixture()
def kube(monkeypatch):
    state = {"jobs": [_job("improve-learn-29000000", done="Complete")], "posted": []}

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/cronjobs/improve-learn") or path.endswith("/cronjobs/improve-tick"):
            action = "learn" if path.endswith("learn") else "tick"
            return httpx.Response(200, json={"spec": {"suspend": False, "jobTemplate": {
                "metadata": {"labels": {"telesales/improve": f"improve-{action}"}},
                "spec": {"backoffLimit": 0, "template": {"spec": {"containers": [
                    {"name": "improve", "image": "x/telesales-improve:abc", "args": [action]}]}}}}}})
        if path == JOBS and request.method == "GET":
            selector = request.url.params.get("labelSelector", "")
            items = [j for j in state["jobs"]
                     if "=" not in selector or j["metadata"]["labels"]["telesales/improve"] == selector.split("=")[1]]
            return httpx.Response(200, json={"items": items})
        if path.startswith(JOBS + "/") and request.method == "GET":
            name = path.rsplit("/", 1)[1]
            found = [j for j in state["jobs"] if j["metadata"]["name"] == name]
            return httpx.Response(200, json=found[0]) if found else httpx.Response(404)
        if path == JOBS and request.method == "POST":
            import json
            body = json.loads(request.content)
            state["posted"].append(body)
            return httpx.Response(201, json=body)
        return httpx.Response(404)

    monkeypatch.setenv("IMPROVE_RUNNER", "kubernetes")
    monkeypatch.setenv("IMPROVE_NAMESPACE", NS)
    monkeypatch.setattr(pipeline, "_client", lambda: httpx.AsyncClient(
        base_url="https://kubernetes", transport=httpx.MockTransport(handle)))
    return state


def test_blocks_three_and_four_follow_the_round_of_the_jobs_week(kube):
    found = asyncio.run(pipeline.status({"weekly-2026-W47": {"status": "waiting_review", "updated_at": "x"}}))
    assert found["available"] and found["runner"] == "kubernetes" and found["error"] is None
    run = found["runs"][0]
    assert run["week"] == "2026-W47"  # created 02:00 Monday 17/11 in Viet Nam
    assert run["blocks"]["weekly_learn"]["state"] == "success"
    assert run["blocks"]["wait_for_review"]["state"] == "up_for_reschedule"
    assert run["blocks"]["weekly_measure"]["state"] is None
    assert run["state"] == "running" and run["kind"] == "scheduled"
    measured = asyncio.run(pipeline.status({"weekly-2026-W47": {"status": "measured", "updated_at": "x"}}))
    assert measured["runs"][0]["blocks"]["weekly_measure"]["state"] == "success"


def test_the_button_creates_a_learn_job_from_the_cronjob_acting_in_that_week(kube):
    started = asyncio.run(pipeline.trigger("2026-W48", by="staff:42"))
    job = kube["posted"][-1]
    assert started["week"] == "2026-W48" and job["metadata"]["name"].startswith("improve-learn-manual-")
    assert job["metadata"]["labels"]["telesales/improve"] == "improve-learn"
    assert job["metadata"]["annotations"] == {"telesales/week": "2026-W48", "telesales/by": "staff:42"}
    assert job["spec"]["template"]["spec"]["containers"][0]["args"] == ["learn", "--now", "2026-11-23T02:00:00+07:00"]
    assert job["spec"]["backoffLimit"] == 0  # the CronJob's own template, not a new one
    with pytest.raises(pipeline.PipelineError):
        asyncio.run(pipeline.trigger("tuần này", by="staff:42"))


def test_nothing_starts_while_an_improvement_job_runs(kube):
    kube["jobs"].append(_job("improve-tick-1", action="improve-tick"))
    with pytest.raises(pipeline.PipelineError, match="improve-tick-1"):
        asyncio.run(pipeline.trigger("2026-W48", by="staff:42"))
    assert kube["posted"] == []


def test_running_measure_again_is_a_tick_in_the_runs_week(kube):
    out = asyncio.run(pipeline.rerun("improve-learn-29000000", "weekly_measure", by="staff:42"))
    job = kube["posted"][-1]
    assert out["started"].startswith("improve-tick-manual-")
    args = job["spec"]["template"]["spec"]["containers"][0]["args"]
    assert args[0] == "tick" and pipeline.week_of(pipeline.datetime.fromisoformat(args[2])) == "2026-W47"
    with pytest.raises(pipeline.PipelineError):
        asyncio.run(pipeline.rerun("improve-learn-29000000", "wait_for_review"))


def test_without_the_runner_nothing_is_asked_of_kubernetes(monkeypatch):
    monkeypatch.delenv("IMPROVE_RUNNER", raising=False)
    found = asyncio.run(pipeline.status())
    assert not found["available"] and found["runs"] == [] and len(found["blocks"]) == 4


def test_the_cronjobs_run_the_runners_two_actions_without_the_shops_config():
    docs = list(yaml.safe_load_all((ROOT / "infra/kubernetes/overlays/aws-production/improve.yaml").read_text("utf-8")))
    crons = {d["metadata"]["name"]: d for d in docs if d["kind"] == "CronJob"}
    assert set(crons) == {pipeline.LEARN, pipeline.TICK}
    for name, cron in crons.items():
        pod = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        container = pod["containers"][0]
        assert cron["spec"]["jobTemplate"]["metadata"]["labels"] == {"telesales/improve": name}
        assert container["args"] == [name.removeprefix("improve-")]
        # never telesales-config: its MCP_TRANSPORT=http would send an evaluation to the shop's MCP servers
        assert container["envFrom"] == [{"secretRef": {"name": "telesales-secrets"}}]
        assert cron["spec"]["timeZone"] == "Asia/Ho_Chi_Minh" and cron["spec"]["concurrencyPolicy"] == "Forbid"
        assert {m["subPath"] for m in container["volumeMounts"]} == {"skills", "improvement", "kb", "runs"}
