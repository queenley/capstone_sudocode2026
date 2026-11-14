"""The weekly improvement round, every Monday at 02:00 (Asia/Ho_Chi_Minh).

docs/plan/001-vong-cai-tien-hang-tuan-va-dashboard.md, part C. Each task runs one command of the agent's
``pipeline.improve`` (pipeline/improve/weekly.py documents them); this file only orders them:

    restate_gaps -> weekly_learn -> wait_for_review -> weekly_measure

- ``restate_gaps``: the questions real customers asked that the documents do not answer, restated and joined, so
  the admin reviews clean ones in /admin (Kiến thức). Nothing is published: answers are the admin's.
- ``weekly_learn``: R0 on the frozen sets (this week's point of the dashboard), Reflection on the learning sets,
  proposals filed for the admin. Nothing is approved here.
- ``wait_for_review``: polls ``weekly-status`` every 30 minutes, in reschedule mode (no worker slot held), up to
  eight days; a round undecided for seven days expires and the next task does nothing.
- ``weekly_measure``: the approved changes as a candidate skills version, measured on the frozen sets (R1). The
  admin switches it on, or not, in /admin (Cải tiến hằng tuần). This DAG never switches a version on.

Configuration, all optional, as environment variables of the scheduler (infra/airflow/docker-compose.airflow.yml):
``IMPROVE_REPO`` (the repository checkout, default /opt/telesales), ``IMPROVE_PYTHON`` (the agent's interpreter,
default /opt/agent-venv/bin/python). Model calls are paid: set ``EVAL_BUDGET_DB`` to cap each run.

``STEPS`` is plain data, so tests/agent/test_airflow_dag.py checks the commands without Airflow installed.
"""

from __future__ import annotations

import os

REPO = os.environ.get("IMPROVE_REPO", "/opt/telesales")
PYTHON = os.environ.get("IMPROVE_PYTHON", "/opt/agent-venv/bin/python")
#: The ISO week the run is for: the week the scheduled interval ends in (the Monday it fires).
WEEK = "{{ data_interval_end.strftime('%G-W%V') }}"

LEARN = ["data/reflection/budget/learn/scenarios"]
FROZEN = ["data/reflection/budget/frozen/scenarios", "data/gap-loop/frozen/scenarios"]
FROZEN_IDS = ["data/reflection/budget/frozen.json", "data/gap-loop/frozen.json"]


def _improve(*args: str) -> str:
    return " ".join([PYTHON, "-m", "ai_agent_service.pipeline.improve", *args])


def _many(flag: str, paths: list[str]) -> list[str]:
    return [part for path in paths for part in (flag, path)]


#: task id -> shell command, in order.
STEPS: dict[str, str] = {
    "restate_gaps": _improve("gaps"),
    "weekly_learn": _improve("weekly-learn", "--week", WEEK, *_many("--learn", LEARN), *_many("--frozen", FROZEN),
                             *_many("--frozen-ids", FROZEN_IDS)),
    "wait_for_review": _improve("weekly-status", "--week", WEEK),
    "weekly_measure": _improve("weekly-measure", "--week", WEEK, *_many("--frozen", FROZEN)),
}

ENV = {
    "PYTHONPATH": f"{REPO}/apps/ai-agent-service/src:{REPO}/packages/backend-common",
    "PYTHONUTF8": "1",
}

try:  # Airflow is only on the scheduler; tests import STEPS without it
    import pendulum
    from airflow import DAG
    from airflow.operators.bash import BashOperator
    from airflow.sensors.bash import BashSensor
except ImportError:  # pragma: no cover - exercised where Airflow is installed
    DAG = None

if DAG is not None:  # pragma: no cover
    with DAG(
        dag_id="improvement_weekly",
        description="Weekly Gap Loop + Reflection round; the admin reviews and switches versions on in /admin",
        schedule="0 2 * * 1",
        start_date=pendulum.datetime(2026, 11, 9, tz="Asia/Ho_Chi_Minh"),
        catchup=False,
        max_active_runs=1,  # evaluations share one *_eval database and its lock
        default_args={"retries": 0},  # a model call is paid; a failed step is looked at, not retried blindly
        tags=["improvement", "evaluation"],
    ) as dag:
        common = {"cwd": REPO, "env": ENV, "append_env": True}
        restate = BashOperator(task_id="restate_gaps", bash_command=STEPS["restate_gaps"], **common)
        learn = BashOperator(task_id="weekly_learn", bash_command=STEPS["weekly_learn"],
                             execution_timeout=pendulum.duration(hours=6), **common)
        # BashSensor takes neither cwd nor append_env. Exit 1 ("a proposal still waits") pokes again; any other
        # non-zero exit (2: no round this week) fails the task at once instead of waiting eight days.
        wait = BashSensor(task_id="wait_for_review", bash_command=f"cd {REPO} && {STEPS['wait_for_review']}",
                          env={**os.environ, **ENV}, retry_exit_code=1, mode="reschedule",
                          poke_interval=30 * 60, timeout=8 * 24 * 3600)
        measure = BashOperator(task_id="weekly_measure", bash_command=STEPS["weekly_measure"],
                               execution_timeout=pendulum.duration(hours=6), **common)
        restate >> learn >> wait >> measure
