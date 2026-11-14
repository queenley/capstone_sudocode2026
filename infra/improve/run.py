"""The weekly improvement round without Airflow: two entry points an external scheduler calls.

    python infra/improve/run.py learn   # Monday 02:00 (Asia/Ho_Chi_Minh): restate_gaps, then weekly_learn
    python infra/improve/run.py tick    # every few hours: for this week and the last, weekly_status, then
                                        # weekly_measure once nothing waits for the admin

The commands are the DAG's own (``STEPS`` in infra/airflow/dags/improvement_weekly.py), with its week template
filled in, so Airflow locally and EventBridge + Fargate on AWS run the same thing. No sensor is needed: weekly-status
only expires an overdue round, and weekly-measure does nothing unless the round waits for review with every proposal
decided (pipeline/improve/weekly.py). The last week is ticked too, because a round started on a Monday may be
decided up to seven days later, in the next ISO week.

Exit code: 0, or 1 when a step failed (the scheduler's alarm). Standard library only.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

REPO = Path(os.environ.get("IMPROVE_REPO") or Path(__file__).resolve().parents[2])
DAG_FILE = REPO / "infra" / "airflow" / "dags" / "improvement_weekly.py"
#: Viet Nam has no daylight saving time: a fixed offset needs no tz database in a slim image.
VIETNAM = timezone(timedelta(hours=7))
#: weekly-status: nothing waits / a proposal still waits / there is no round for the week.
SETTLED, WAITING, NO_ROUND = 0, 1, 2


def _dag():
    os.environ.setdefault("IMPROVE_REPO", str(REPO))
    os.environ.setdefault("IMPROVE_PYTHON", sys.executable)
    spec = importlib.util.spec_from_file_location("improvement_weekly", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # Airflow is not installed: the DAG file then only defines STEPS
    return module


def iso_week(moment: datetime) -> str:
    return moment.astimezone(VIETNAM).strftime("%G-W%V")


def command(step: str, week: str) -> str:
    dag = _dag()
    return dag.STEPS[step].replace(dag.WEEK, week)


def _shell(line: str) -> int:
    print(f"$ {line}", flush=True)
    return subprocess.run(line, shell=True, cwd=REPO).returncode


def learn(now: datetime, run: Callable[[str], int] = _shell) -> int:
    week = iso_week(now)
    for step in ("restate_gaps", "weekly_learn"):
        code = run(command(step, week))
        if code:
            print(f"{step} for {week} failed with {code}", file=sys.stderr)
            return 1
    return 0


def tick(now: datetime, run: Callable[[str], int] = _shell) -> int:
    failed = False
    for week in dict.fromkeys((iso_week(now - timedelta(days=7)), iso_week(now))):
        code = run(command("wait_for_review", week))
        if code in (WAITING, NO_ROUND):
            continue
        if code != SETTLED:
            print(f"weekly-status for {week} failed with {code}", file=sys.stderr)
            failed = True
            continue
        if run(command("weekly_measure", week)):
            print(f"weekly-measure for {week} failed", file=sys.stderr)
            failed = True
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=["learn", "tick"])
    parser.add_argument("--now", type=datetime.fromisoformat, help="ISO time to act as (tests, a missed week).")
    args = parser.parse_args(argv)
    now = args.now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=VIETNAM)
    return learn(now) if args.action == "learn" else tick(now)


if __name__ == "__main__":
    sys.exit(main())
