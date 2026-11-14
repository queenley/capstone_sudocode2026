"""The weekly round: learn, wait for a person, measure, and leave the switch to the admin.

``docs/plan/001-vong-cai-tien-hang-tuan-va-dashboard.md``, part C. Each step is one command, so a scheduler
(``infra/airflow/dags/improvement_weekly.py``) runs them in order and a person can run any of them by hand::

    python -m ai_agent_service.pipeline.improve weekly-learn   --week 2026-W46 --learn <dir> --frozen <dir> --frozen-ids <ids.json>
    python -m ai_agent_service.pipeline.improve weekly-status  --week 2026-W46
    python -m ai_agent_service.pipeline.improve weekly-measure --week 2026-W46 --frozen <dir>

How it differs from ``improve round`` (the proof of the loop, ``cli._round``): a round starts from version 0 and goes
back to it; the weekly round starts from the skills in force, whatever version, and **never switches a version on**.

1. ``weekly-learn``: the frozen sets are measured with the skills in force (R0, a point of the weekly timeline), the
   learning sets are played and diagnosed (``harvest``, ``score``, ``reflect``), and every proposal goes to
   ``improvement_proposals`` with no decision. Nothing is approved here: there is no ``--scripted``.
2. ``weekly-status``: exit 0 once no proposal waits (or the round has nothing to review), 1 while one does; a round
   waiting more than :data:`REVIEW_DAYS` days expires. The scheduler's sensor polls it.
3. ``weekly-measure``: the admin's decisions go back into the review files (where ``review.approved`` applies the
   rules of who may approve), the approved changes become a **candidate** skills version (written, not active),
   the frozen sets are measured with it (R1), and the comparison is kept with the round. The admin then switches
   the candidate on, or not, from ``/admin`` (``api/routes/improvement.py``).

Every run is ingested into the evaluation history (``run_eval.py --ingest``), R0 as ``weekly_frozen`` and R1 as
``weekly_candidate``. The learning artifacts of a week stay in ``evaluation/runs/weekly-<week>``.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

#: Days a round waits for the admin before it expires and nothing of it is published.
REVIEW_DAYS = 7


def iso_week(value: str | None = None, *, today: date | None = None) -> str:
    """``2026-W46``: the week given, checked, or the current one."""
    if value:
        try:
            datetime.strptime(value + "-1", "%G-W%V-%u")
        except ValueError as error:
            raise ValueError(f"--week takes an ISO week such as 2026-W46, not {value!r}") from error
        return value
    year, week, _ = (today or datetime.now(timezone.utc).date()).isocalendar()
    return f"{year}-W{week:02d}"


def monday(week: str) -> date:
    return datetime.strptime(week + "-1", "%G-W%V-%u").date()


def round_name(week: str) -> str:
    return f"weekly-{week}"


def _folder(week: str) -> Path:
    from ..eval.cli import runs_dir

    return runs_dir() / round_name(week)


def _use_round_dir(week: str) -> Path:
    """Learning artifacts (lessons, diagnoses, review files) of this week, apart from production's and other weeks'."""
    folder = _folder(week)
    os.environ["IMPROVEMENT_DIR"] = str(folder / "improvement")
    from ..eval.cli import runs_dir

    os.environ.setdefault("IMPROVEMENT_CACHE", str(runs_dir() / "cache" / "improvement-answers.jsonl"))
    return folder


def _ingest(run: Path, purpose: str, week: str) -> None:
    from ..eval.cli import ingest

    if ingest(run, purpose=purpose, round_name=round_name(week)) != 0:
        raise RuntimeError(f"Could not ingest {run}")


async def learn(week: str, *, learn_sets: Sequence[Path], frozen_sets: Sequence[Path],
                frozen_ids: Sequence[Path]) -> int:
    from ...components.improvement import skill_versions
    from ...runtime import evaluations
    from . import cli

    name = round_name(week)
    folder = _use_round_dir(week)
    base = skill_versions.active()
    async with evaluations.cli_connection() as conn:
        await evaluations.start_round(conn, name, week=monday(week).isoformat(), base_skills_version=base)
    r0 = []
    try:
        for path in frozen_sets:  # R0: this week's point of the timeline, with the skills in force
            run = cli._evaluate(path, folder / f"r0-{cli._label(path)}")
            _ingest(run, "weekly_frozen", week)
            r0.append(str(run))
        reviews = []
        for path in learn_sets:
            label = cli._label(path)
            run = cli._evaluate(path, folder / f"learn-{label}")
            lesson = f"{name}-{label}"
            if cli.harvest(run, lesson, scenarios_dir=path, frozen=frozen_ids) != 0:
                raise RuntimeError(f"harvest of {run} failed")
            if await cli.score(lesson) != 0 or await cli.reflect(lesson) != 0:
                raise RuntimeError(f"score or reflect of {lesson} failed")
            review_file = folder / "improvement" / "review" / f"{lesson}.json"
            if review_file.is_file():
                reviews.append(review_file)
    except Exception as error:
        async with evaluations.cli_connection() as conn:
            await evaluations.set_round(conn, name, status="failed", detail={"error": f"{type(error).__name__}: {error}"})
        raise
    total = 0
    async with evaluations.cli_connection() as conn:
        for review_file in reviews:
            data = json.loads(review_file.read_text(encoding="utf-8"))
            total += await evaluations.add_proposals(conn, name, str(review_file), data.get("proposals") or [])
        await evaluations.set_round(conn, name, status="waiting_review" if total else "no_change",
                                    detail={"r0": r0, "reviews": [str(p) for p in reviews],
                                            "learn_sets": [str(p) for p in learn_sets],
                                            "frozen_sets": [str(p) for p in frozen_sets]})
    print(f"{name}: {total} proposals " + ("wait for the admin in /admin" if total else "(nothing to review)"))
    return 0


async def status(week: str, *, now: datetime | None = None) -> int:
    """0: nothing waits for a person (the sensor goes on); 1: a proposal still waits."""
    from ...runtime import evaluations

    name = round_name(week)
    async with evaluations.cli_connection() as conn:
        found = await evaluations.get_round(conn, name)
        if found is None:
            print(f"No round {name}")
            return 2
        waiting = evaluations.pending(found)
        if found["status"] != "waiting_review" or not waiting:
            print(f"{name}: {found['status']}, nothing waits")
            return 0
        if evaluations.age_days(found, now) > REVIEW_DAYS:
            await evaluations.set_round(conn, name, status="expired",
                                        detail={"expired": f"{len(waiting)} proposals undecided after {REVIEW_DAYS} days"})
            print(f"{name}: expired, {len(waiting)} proposals were never decided; nothing is published")
            return 0
    print(f"{name}: {len(waiting)} proposals wait for the admin")
    return 1


def write_decisions(review_file: Path, decided: Sequence[dict[str, Any]]) -> None:
    """The admin's decisions, from the table into the review file ``review.approved`` reads."""
    data = json.loads(review_file.read_text(encoding="utf-8"))
    by_id = {str(p["id"]): p for p in decided}
    for item in data.get("proposals") or []:
        choice = by_id.get(str(item.get("proposal_id")))
        if choice:
            item.update(decision=choice["decision"], reviewer=choice["reviewer"], note=choice.get("note") or "")
    review_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def measure(week: str, *, frozen_sets: Sequence[Path]) -> int:
    from ...components.improvement import review, skill_versions
    from ...runtime import evaluations
    from . import cli

    name = round_name(week)
    folder = _use_round_dir(week)
    async with evaluations.cli_connection() as conn:
        found = await evaluations.get_round(conn, name)
    if found is None:
        print(f"No round {name}")
        return 2
    if found["status"] != "waiting_review" or evaluations.pending(found):
        print(f"{name}: {found['status']}; nothing to measure")
        return 0
    taken: list[dict[str, Any]] = []
    refused: list[dict[str, str]] = []
    for review_file, decided in evaluations.decisions_by_file(found).items():
        write_decisions(Path(review_file), decided)
        approved, not_taken = review.approved(Path(review_file))
        taken += approved
        refused += not_taken
    async with evaluations.cli_connection() as conn:
        if not taken:
            await evaluations.set_round(conn, name, status="rejected", detail={"refused": refused})
            print(f"{name}: no change approved; the frozen sets are not run again")
            return 0
        if skill_versions.active() != found["base_skills_version"]:
            await evaluations.set_round(conn, name, status="failed", detail={
                "error": f"skills moved from v{found['base_skills_version']} to v{skill_versions.active()} "
                         "since the round learned; run the week again"})
            return 2
        await evaluations.set_round(conn, name, status="measuring", detail={"refused": refused})
    reviewers = sorted({str(item["reviewer"]).strip() for item in taken})
    candidate = skill_versions.publish([item["patch"] for item in taken], reviewer=", ".join(reviewers),
                                       note=f"weekly round {name}, candidate", activate=False)
    comparisons: dict[str, Any] = {}
    r1 = []
    try:
        for path in frozen_sets:
            label = cli._label(path)
            run = cli._evaluate(path, folder / f"r1-{label}",
                                ("--profile", "reflection", "--skills-version", str(candidate)))
            _ingest(run, "weekly_candidate", week)
            r1.append(str(run))
            comparisons[label] = cli.comparison([folder / f"r0-{label}"], [run])
    except Exception as error:
        async with evaluations.cli_connection() as conn:
            await evaluations.set_round(conn, name, status="failed", candidate_skills_version=candidate,
                                        detail={"error": f"{type(error).__name__}: {error}"})
        raise
    harm = sum(len(c["harm"]) for c in comparisons.values())
    async with evaluations.cli_connection() as conn:
        await evaluations.set_round(conn, name, status="harm" if harm else "measured",
                                    candidate_skills_version=candidate,
                                    detail={"r1": r1, "comparison": comparisons, "approved": len(taken)})
    print(f"{name}: candidate skills v{candidate} measured; "
          + (f"HARM: {harm} new violations, do not switch it on" if harm else "waits for the admin to switch it on"))
    return 0
