"""The weekly improvement round on Kubernetes (EKS), as the admin sees and drives it from /admin.

There is no Airflow on EKS: two CronJobs run the same commands (infra/kubernetes/overlays/aws-production/improve.yaml,
infra/improve/run.py):

* ``improve-learn``, Monday 02:00 (Asia/Ho_Chi_Minh): ``restate_gaps`` then ``weekly_learn``;
* ``improve-tick``, 10:00, 16:00 and 22:00: ``wait_for_review`` (``weekly-status``), then ``weekly_measure`` once
  every proposal is decided.

A run here is one ``improve-learn`` Job, scheduled or started by hand. Blocks 1 and 2 are that Job's state; blocks 3
and 4 are the round's (``improvement_rounds``, name ``weekly-<week>``), because the tick Jobs that move it run every few
hours and say nothing on their own. A button creates a Job from the CronJob's own template, through the in-cluster API
with the agent's service account (a Role allows get on the two CronJobs and create, list on Jobs).

Configured by ``IMPROVE_RUNNER=kubernetes``; ``IMPROVE_NAMESPACE`` defaults to the pod's own namespace.

Nothing here approves a proposal or switches a version on, as the CronJobs never do.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx

from .airflow_pipeline import BLOCKS, PipelineError, current_week

LEARN, TICK = "improve-learn", "improve-tick"
LABEL = "telesales/improve"
ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
VIETNAM = timezone(timedelta(hours=7))
WEEK = re.compile(r"^(\d{4})-W(\d{2})$")
#: A round's status (runtime/evaluations.py STATUSES) as the states of blocks 3 and 4, in Airflow's words, which the
#: admin page already draws.
ROUND_BLOCKS: dict[str, tuple[str | None, str | None]] = {
    "learning": (None, None),
    "no_change": ("skipped", "skipped"),
    "waiting_review": ("up_for_reschedule", None),
    "expired": ("failed", "skipped"),
    "rejected": ("success", "skipped"),
    "measuring": ("success", "running"),
    "measured": ("success", "success"),
    "harm": ("success", "success"),
    "active": ("success", "success"),
    "failed": (None, "failed"),
}


def configured() -> bool:
    return os.environ.get("IMPROVE_RUNNER", "").strip().lower() == "kubernetes"


def namespace() -> str:
    given = os.environ.get("IMPROVE_NAMESPACE", "").strip()
    if given:
        return given
    try:
        return (ACCOUNT / "namespace").read_text(encoding="utf-8").strip()
    except OSError:
        return "default"


def monday(week: str) -> date:
    found = WEEK.match(week)
    if not found:
        raise PipelineError("Tuần phải có dạng 2026-W46")
    return date.fromisocalendar(int(found[1]), int(found[2]), 1)


def week_of(moment: datetime) -> str:
    year, number, _ = moment.astimezone(VIETNAM).isocalendar()
    return f"{year}-W{number:02d}"


def _client() -> httpx.AsyncClient:
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    try:
        token = (ACCOUNT / "token").read_text(encoding="utf-8").strip()
    except OSError as error:
        raise PipelineError("Pod không có service account token để gọi Kubernetes API") from error
    ca = ACCOUNT / "ca.crt"
    return httpx.AsyncClient(base_url=f"https://{host}:{port}", headers={"Authorization": f"Bearer {token}"},
                             verify=str(ca) if ca.is_file() else True, timeout=10.0)


async def _call(method: str, path: str, **kwargs: Any) -> Any:
    try:
        async with _client() as client:
            response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as error:
        raise PipelineError(f"Không kết nối được Kubernetes API ({type(error).__name__})") from error
    if response.status_code in (401, 403):
        raise PipelineError("Kubernetes từ chối service account của agent (Role improve-runner trong improve.yaml)")
    if response.status_code == 404:
        raise PipelineError("Không có CronJob improve-learn / improve-tick trong namespace (improve.yaml)")
    if response.status_code >= 400:
        detail = ""
        try:
            detail = str(response.json().get("message") or "")[:200]
        except ValueError:
            pass
        raise PipelineError(f"Kubernetes trả lỗi {response.status_code}{': ' + detail if detail else ''}")
    return response.json() if response.content else {}


def _jobs_path() -> str:
    return f"/apis/batch/v1/namespaces/{namespace()}/jobs"


def _state(job: Mapping[str, Any]) -> str:
    status = job.get("status") or {}
    for condition in status.get("conditions") or []:
        if condition.get("status") == "True" and condition.get("type") == "Complete":
            return "success"
        if condition.get("status") == "True" and condition.get("type") == "Failed":
            return "failed"
    return "running" if status.get("active") or status.get("startTime") else "queued"


def _action(job: Mapping[str, Any]) -> str:
    return str(((job.get("metadata") or {}).get("labels") or {}).get(LABEL) or "")


def _week(job: Mapping[str, Any]) -> str:
    meta = job.get("metadata") or {}
    given = (meta.get("annotations") or {}).get("telesales/week")
    if given:
        return str(given)
    created = meta.get("creationTimestamp")
    moment = datetime.fromisoformat(str(created).replace("Z", "+00:00")) if created else datetime.now(timezone.utc)
    return week_of(moment)


def _run(job: Mapping[str, Any], rounds: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    meta, status = job.get("metadata") or {}, job.get("status") or {}
    state, week = _state(job), _week(job)
    started, ended = status.get("startTime"), status.get("completionTime")
    if state == "failed":
        ended = next((c.get("lastTransitionTime") for c in status.get("conditions") or [] if c.get("type") == "Failed"),
                     None)
    learn = {"state": state, "started_at": started, "ended_at": ended, "tries": 1}
    round_ = rounds.get(f"weekly-{week}") or {}
    wait, measure = ROUND_BLOCKS.get(str(round_.get("status") or ""), (None, None)) if state == "success" else (None, None)
    updated = round_.get("updated_at")
    run_state = state if state != "success" else (
        "running" if wait == "up_for_reschedule" or measure == "running" else
        "failed" if "failed" in (wait, measure) else "success")
    return {
        "run_id": meta.get("name"),
        "state": run_state,
        "kind": "manual" if (meta.get("annotations") or {}).get("telesales/by") else "scheduled",
        "week": week,
        "started_at": started or meta.get("creationTimestamp"),
        "ended_at": ended,
        "blocks": {
            "restate_gaps": learn,
            "weekly_learn": learn,
            "wait_for_review": {"state": wait, "started_at": ended if wait else None,
                                "ended_at": updated if wait and wait != "up_for_reschedule" else None, "tries": None},
            "weekly_measure": {"state": measure, "started_at": None, "ended_at": updated if measure else None,
                               "tries": None},
        },
    }


async def status(rounds: Mapping[str, Mapping[str, Any]] | None = None, limit: int = 5) -> dict[str, Any]:
    """The blocks and the latest learn Jobs, in the shape runtime/airflow_pipeline.py gives the admin page."""
    out: dict[str, Any] = {"available": configured(), "runner": "kubernetes", "airflow_ui": None,
                           "dag_id": f"CronJob {LEARN} + {TICK}", "blocks": BLOCKS, "runs": [], "paused": None,
                           "error": None, "current_week": current_week()}
    if not configured():
        return out
    try:
        cron = await _call("GET", f"/apis/batch/v1/namespaces/{namespace()}/cronjobs/{LEARN}")
        out["paused"] = bool((cron.get("spec") or {}).get("suspend"))
        jobs = await _call("GET", _jobs_path(), params={"labelSelector": f"{LABEL}={LEARN}"})
        items = sorted(jobs.get("items") or [], key=lambda j: str((j.get("metadata") or {}).get("creationTimestamp")),
                       reverse=True)
        out["runs"] = [_run(job, rounds or {}) for job in items[:limit]]
    except PipelineError as error:
        out["error"] = str(error)
    return out


async def _active() -> list[str]:
    jobs = await _call("GET", _jobs_path(), params={"labelSelector": LABEL})
    return [str(job["metadata"]["name"]) for job in jobs.get("items") or [] if _state(job) in ("running", "queued")]


async def _start(cronjob: str, week: str, now: datetime, *, by: str) -> dict[str, Any]:
    """A Job from *cronjob*'s own template, acting as at *now* (run.py --now), as ``kubectl create job --from`` does."""
    busy = await _active()
    if busy:
        raise PipelineError(f"Đang có Job cải tiến chạy ({', '.join(busy)}): chờ nó xong rồi bấm lại")
    cron = await _call("GET", f"/apis/batch/v1/namespaces/{namespace()}/cronjobs/{cronjob}")
    template = (cron.get("spec") or {}).get("jobTemplate") or {}
    spec = dict(template.get("spec") or {})
    pod = dict(spec.get("template") or {})
    pod_spec = dict(pod.get("spec") or {})
    containers = [dict(c) for c in pod_spec.get("containers") or []]
    if not containers:
        raise PipelineError(f"CronJob {cronjob} không có container")
    action = "learn" if cronjob == LEARN else "tick"
    containers[0]["args"] = [action, "--now", now.isoformat()]
    pod_spec["containers"] = containers
    pod["spec"] = pod_spec
    spec["template"] = pod
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    labels = {**((template.get("metadata") or {}).get("labels") or {}), LABEL: cronjob}
    job = {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": f"{cronjob}-manual-{stamp}", "namespace": namespace(), "labels": labels,
                     "annotations": {"telesales/week": week, "telesales/by": by[:63]}},
        "spec": spec,
    }
    created = await _call("POST", _jobs_path(), json=job)
    return {"run_id": (created.get("metadata") or {}).get("name"), "state": "queued", "week": week}


async def trigger(week: str | None, *, by: str) -> dict[str, Any]:
    """The round for *week* (this ISO week by default) started by hand: restate gaps, R0, learn. Paid model calls."""
    week = week or current_week()
    start = datetime.combine(monday(week), time(2, 0), tzinfo=VIETNAM)
    return await _start(LEARN, week, start, by=by)


async def rerun(run_id: str, block: str, *, by: str = "admin") -> dict[str, Any]:
    """Blocks 1-2 again: the learn Job for that run's week. Block 4: a tick now, which measures once all is decided."""
    if block not in {b["id"] for b in BLOCKS} or block == "wait_for_review":
        raise PipelineError(f"Không chạy lại được block {block}")
    job = await _call("GET", f"{_jobs_path()}/{run_id}")
    if _action(job) != LEARN:
        raise PipelineError(f"{run_id} không phải một lần chạy của {LEARN}")
    week = _week(job)
    if block == "weekly_measure":
        # tick looks at the week it acts in and the one before: acting on Monday noon of the week covers it.
        now = min(datetime.now(VIETNAM), datetime.combine(monday(week), time(12, 0), tzinfo=VIETNAM)
                  + timedelta(days=6))
        started = await _start(TICK, week, max(now, datetime.combine(monday(week), time(12, 0), tzinfo=VIETNAM)),
                               by=by)
    else:
        started = await trigger(week, by=by)
    return {"run_id": run_id, "block": block, "started": started["run_id"]}
