"""The weekly improvement round's pipeline on Airflow, as the admin sees and drives it from /admin.

The DAG ``improvement_weekly`` (infra/airflow/dags/improvement_weekly.py) runs four blocks in order:
restate_gaps -> weekly_learn -> wait_for_review -> weekly_measure. This reads its latest runs and each block's state
through Airflow's stable REST API (v1, Airflow 2.x), starts a run by hand, and re-runs one block (with the blocks
after it): what the Airflow UI does, inside the shop's own admin page.

Configured by ``AIRFLOW_URL`` (http://airflow:8080 when infra/airflow/docker-compose.airflow.yml is loaded),
``AIRFLOW_USER`` and ``AIRFLOW_PASSWORD`` (basic auth, the API user that compose file creates), and
``AIRFLOW_PUBLIC_URL`` (where a person opens Airflow's own UI). Without ``AIRFLOW_URL`` the blocks are still shown,
with no state, and nothing can be started.

Nothing here approves a proposal or switches a version on: the DAG never does, and neither does a manual run.
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

import httpx

DAG_ID = "improvement_weekly"

#: The DAG's blocks, in order, as the admin reads them (the DAG file's STEPS, in words).
BLOCKS: list[dict[str, str]] = [
    {"id": "restate_gaps", "label": "Gom câu hỏi thiếu kiến thức",
     "detail": "Câu khách thật hỏi mà tài liệu chưa có: viết lại, gộp trùng, đưa vào tab Kiến thức để duyệt."},
    {"id": "weekly_learn", "label": "Đo R0 và học (Reflection)",
     "detail": "Chạy bộ frozen với version đang dùng (điểm của tuần), học từ bộ learn, nộp đề xuất. Tốn phí model."},
    {"id": "wait_for_review", "label": "Chờ admin duyệt",
     "detail": "Kiểm tra mỗi 30 phút đến khi mọi đề xuất được duyệt hoặc từ chối; tối đa 7 ngày."},
    {"id": "weekly_measure", "label": "Đo version ứng viên (R1)",
     "detail": "Gộp đề xuất đã duyệt thành version ứng viên, đo lại bộ frozen. Admin tự bật hoặc không."},
]
WEEK = re.compile(r"^\d{4}-W\d{2}$")


class PipelineError(Exception):
    """Airflow refused or could not be reached; the message says which, never a secret."""


def configured() -> bool:
    return bool(os.environ.get("AIRFLOW_URL", "").strip())


def public_url() -> str | None:
    return os.environ.get("AIRFLOW_PUBLIC_URL", "").strip() or None


def current_week(today: date | None = None) -> str:
    year, week, _ = (today or date.today()).isocalendar()
    return f"{year}-W{week:02d}"


def _client() -> httpx.AsyncClient:
    base = os.environ["AIRFLOW_URL"].rstrip("/") + "/api/v1"
    auth = (os.environ.get("AIRFLOW_USER", "api"), os.environ.get("AIRFLOW_PASSWORD", ""))
    return httpx.AsyncClient(base_url=base, auth=auth, timeout=10.0)


async def _call(method: str, path: str, **kwargs: Any) -> Any:
    try:
        async with _client() as client:
            response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as error:
        raise PipelineError(f"Không kết nối được Airflow ({type(error).__name__})") from error
    if response.status_code in (401, 403):
        raise PipelineError("Airflow từ chối tài khoản API (AIRFLOW_USER / AIRFLOW_PASSWORD)")
    if response.status_code == 404:
        raise PipelineError(f"Airflow không có DAG {DAG_ID} hoặc lần chạy này")
    if response.status_code >= 400:
        detail = ""
        try:
            detail = str(response.json().get("detail") or "")[:200]
        except ValueError:
            pass
        raise PipelineError(f"Airflow trả lỗi {response.status_code}{': ' + detail if detail else ''}")
    return response.json() if response.content else {}


async def status(limit: int = 5) -> dict[str, Any]:
    """The blocks, and the latest runs with each block's state: what the admin's pipeline view draws."""
    out: dict[str, Any] = {"available": configured(), "airflow_ui": public_url(), "dag_id": DAG_ID,
                           "blocks": BLOCKS, "runs": [], "paused": None, "error": None,
                           "current_week": current_week()}
    if not configured():
        return out
    try:
        dag = await _call("GET", f"/dags/{DAG_ID}")
        out["paused"] = bool(dag.get("is_paused"))
        runs = await _call("GET", f"/dags/{DAG_ID}/dagRuns", params={"order_by": "-execution_date", "limit": limit})
        for run in runs.get("dag_runs") or []:
            tasks = await _call("GET", f"/dags/{DAG_ID}/dagRuns/{run['dag_run_id']}/taskInstances")
            by_id = {t["task_id"]: t for t in tasks.get("task_instances") or []}
            out["runs"].append({
                "run_id": run["dag_run_id"],
                "state": run.get("state"),
                "kind": run.get("run_type"),
                "week": ((run.get("conf") or {}).get("week")) or None,
                "started_at": run.get("start_date"),
                "ended_at": run.get("end_date"),
                "blocks": {block["id"]: {
                    "state": (by_id.get(block["id"]) or {}).get("state"),
                    "started_at": (by_id.get(block["id"]) or {}).get("start_date"),
                    "ended_at": (by_id.get(block["id"]) or {}).get("end_date"),
                    "tries": (by_id.get(block["id"]) or {}).get("try_number"),
                } for block in BLOCKS},
            })
    except PipelineError as error:
        out["error"] = str(error)
    return out


async def trigger(week: str | None, *, by: str) -> dict[str, Any]:
    """A run started by hand for *week* (this ISO week by default); the DAG is unpaused first, or it never starts."""
    week = week or current_week()
    if not WEEK.match(week):
        raise PipelineError("Tuần phải có dạng 2026-W46")
    await _call("PATCH", f"/dags/{DAG_ID}", params={"update_mask": "is_paused"}, json={"is_paused": False})
    run = await _call("POST", f"/dags/{DAG_ID}/dagRuns",
                      json={"conf": {"week": week}, "note": f"Chạy tay từ /admin bởi {by}"})
    return {"run_id": run.get("dag_run_id"), "state": run.get("state"), "week": week}


async def rerun(run_id: str, block: str) -> dict[str, Any]:
    """Block *block* of run *run_id* again, with every block after it (Airflow's "clear", downstream included)."""
    if block not in {b["id"] for b in BLOCKS}:
        raise PipelineError(f"Không có block {block}")
    cleared = await _call("POST", f"/dags/{DAG_ID}/clearTaskInstances", json={
        "dag_run_id": run_id, "task_ids": [block], "include_downstream": True, "include_upstream": False,
        "only_failed": False, "reset_dag_runs": True, "dry_run": False,
    })
    return {"run_id": run_id, "block": block, "cleared": len(cleared.get("task_instances") or [])}
