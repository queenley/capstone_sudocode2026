"""infra/airflow/dags/improvement_weekly.py without Airflow: the order of the steps and what each command runs."""
import importlib.util
import json
from pathlib import Path

from ai_agent_service.pipeline.improve import cli

ROOT = Path(__file__).resolve().parents[2]


def _dag():
    spec = importlib.util.spec_from_file_location("improvement_weekly", ROOT / "infra/airflow/dags/improvement_weekly.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_round_learns_waits_for_a_person_then_measures():
    dag = _dag()
    assert list(dag.STEPS) == ["restate_gaps", "weekly_learn", "wait_for_review", "weekly_measure"]
    assert all("--scripted" not in command and "activate" not in command for command in dag.STEPS.values())
    assert "weekly-status" in dag.STEPS["wait_for_review"]


def test_every_command_parses_and_every_set_it_names_exists():
    dag = _dag()
    for name, command in dag.STEPS.items():
        # Airflow renders the week before the shell runs; the template has spaces, so render it first here too.
        argv = command.replace(dag.WEEK, "2026-W46").split(" ")[3:]  # after "<python> -m ai_agent_service.pipeline.improve"
        assert cli.parser().parse_args(argv).command, name
    for path in [*dag.LEARN, *dag.FROZEN]:
        assert any((ROOT / path).glob("*.json")), path
    for path in dag.FROZEN_IDS:
        assert isinstance(json.loads((ROOT / path).read_text(encoding="utf-8")), list), path


def test_the_week_is_templated_once_and_the_measure_step_uses_the_learn_steps_frozen_sets():
    dag = _dag()
    assert dag.WEEK.count("{{") == 1
    frozen = [part for part in dag.STEPS["weekly_learn"].split(" ") if part.startswith("data/") and "frozen/" in part]
    assert all(path in dag.STEPS["weekly_measure"] for path in frozen)
