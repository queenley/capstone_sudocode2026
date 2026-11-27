"""``run_eval.py --simulate``: the organisers' simulator over seeds, without a model."""

from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from ai_agent_service.config.config_manager import btc_data_dir
from ai_agent_service.pipeline.eval import cli, simulate

SAMPLES = btc_data_dir() / "test_set" / "public_sample"
DEV = Path(__file__).resolve().parents[2] / "data" / "dev" / "scenarios"


def _scenarios(folder: Path, limit: int | None = None) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))[:limit]]


@pytest.mark.parametrize("scenario", _scenarios(SAMPLES) + _scenarios(DEV, 20), ids=lambda s: s["scenario_id"])
def test_the_customer_prompt_hides_the_labels(scenario):
    """Specification 5c: must_not_ask, success_if and the other labels never reach the persona's prompt."""
    for call in scenario["calls"]:
        assert simulate.leaks(scenario, simulate.simulator_prompt(scenario, call)) == []


def test_a_label_in_the_prompt_is_caught():
    scenario = {"calls": {"call_1": {"facts_established": {"budget_vnd": 5000000},
                                     "must_not_ask": ["room_area_m2", "budget_vnd"], "success_if": {"tool_called": "x"}}}}
    assert simulate.leaks(scenario, 'Đã biết: {"budget_vnd": 5000000}') == []
    assert simulate.leaks(scenario, 'Không hỏi "room_area_m2"') == ["call_1.must_not_ask:room_area_m2"]
    assert simulate.leaks(scenario, "success_if: order.create") == ["call_1.success_if"]


def test_summary_reports_mean_stdev_and_the_10_point_range():
    reports = {0: {"task_success_rate": {"value": 60.0}}, 1: {"task_success_rate": {"value": 80.0}},
               2: {"task_success_rate": {"value": 70.0}}}
    logs = [{"outcome": "chot_don", "ended_by": "agent", "patience_trace": [3, 3, 2], "errors": []},
            {"outcome": "tu_choi", "ended_by": "customer", "patience_trace": [2, 1, 0], "errors": []}]
    summary = simulate.summarise(reports, logs)
    assert summary["tsr_mean"] == 70.0 and summary["tsr_stdev"] == 10.0 and summary["tsr_range"] == 20.0
    assert summary["within_10_points"] is False
    assert summary["outcomes"] == {"chot_don": 1, "tu_choi": 1}
    assert summary["ended_by"] == {"agent": 1, "customer": 1, "timeout": 0}
    assert summary["repeat_complaints"] == 3
    close = simulate.summarise({0: {"task_success_rate": {"value": 60.0}}, 1: {"task_success_rate": {"value": 70.0}}}, [])
    assert close["within_10_points"] is True


def test_a_seed_is_graded_by_the_organisers_script(tmp_path):
    """The organisers' example trace, graded through :func:`simulate.grade`, gives their own TSR."""
    btc = btc_data_dir() / "eval"
    report = simulate.grade(SAMPLES, btc / "runs" / "full.jsonl")
    assert "value" in report["task_success_rate"]


@pytest.mark.parametrize("extra", [["--config", "full"], ["--judge"], ["--no-extract"]])
def test_simulate_refuses_options_of_the_scripted_run(extra, capsys):
    assert cli.main(["--simulate", "--scenarios", str(SAMPLES), *extra]) == 2
    assert "--simulate" in capsys.readouterr().out


def test_simulate_never_writes_over_evidence(tmp_path, capsys):
    (tmp_path / "kept.txt").write_text("x", encoding="utf-8")
    assert cli.main(["--simulate", "--scenarios", str(SAMPLES), "--out", str(tmp_path)]) == 2
    assert "not empty" in capsys.readouterr().out


def test_each_seed_has_its_own_checkpoint_thread_and_model_seed():
    """Two seeds on one rig must not share the graph's thread, and the persona's model carries the seed."""
    import inspect

    assert "seed-{seed}" in inspect.getsource(simulate.play_call)
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="gpt-4.1-mini", api_key="test", temperature=0.3)
    assert simulate.seeded(llm, 2).seed == 2 and llm.seed is None
    assert simulate.seeded(None, 1) is None
    assert simulate.seeded(object(), 1) is not None


@pytest.mark.asyncio
async def test_the_observer_is_given_the_extractor_input_of_today():
    """2026-11-17: the first live run failed here: observe still called the extractor's label() of before 2026-11-07."""
    from ai_agent_service.agents.simulator import Customer, Session

    seen = []

    class Observer:
        async def label(self, data):
            seen.append(data)
            return {"questions": [{"slot": "budget_vnd", "type": "open"}], "claims": []}

    agent = SimpleNamespace(observer=Observer(), errors=[])
    scenario = _scenarios(SAMPLES, 1)[0]
    session = Session(agent, Customer(scenario, "call_1", seed=0), set())
    labels = await session.observe("Dạ chị cần máy cho phòng bao nhiêu mét vuông ạ?",
                                   [{"name": "catalog.search", "args": {"q": "máy lọc"}, "result": {"x": 1}}],
                                   today="2026-10-15")
    assert labels["questions"][0]["slot"] == "budget_vnd"
    assert seen[0]["agent_text"].startswith("Dạ chị") and seen[0]["today"] == "2026-10-15"
    assert seen[0]["tool_texts"] and "result" not in seen[0]["tool_texts"][0]


def test_a_challenge_costs_patience_and_the_customer_leaves_when_it_runs_out():
    """Specification rule 3 then rule 2: 2026-11-17 a persona challenged ten times to the twelve-turn limit."""
    from ai_agent_service.agents.simulator import Customer, Observation

    scenario = _scenarios(SAMPLES, 1)[0]
    customer = Customer(scenario, "call_2", seed=0)
    start = customer.patience
    assert customer.first() is not None
    said = []
    for _ in range(start):
        line = customer.step(Observation(agent_text="Dạ giá hôm nay 4.890.000đ ạ.", reaction="challenge",
                                         persona_line="Sao hôm trước em báo khác?"))
        said.append(line)
        if customer.ended:
            break
    assert customer.ended and customer.outcome == "tu_choi" and customer.ended_by == "customer"
    assert customer.patience == 0 and said[-1].startswith("Thôi để")
    assert customer.log()["patience_trace"][1:] == list(range(start - 1, -1, -1))


def test_a_hold_costs_nothing():
    from ai_agent_service.agents.simulator import Customer, Observation

    customer = Customer(_scenarios(SAMPLES, 1)[0], "call_2", seed=0)
    start = customer.patience
    customer.first()
    customer.step(Observation(agent_text="Dạ chị chờ em chút ạ.", reaction="hold", persona_line="Ừ em."))
    assert customer.patience == start and not customer.ended


@pytest.mark.asyncio
async def test_after_the_parting_line_the_call_ends_instead_of_asking_the_kernel_again():
    """2026-11-17: a customer who left (rule 2) was asked for another line and the run stopped with "The call is over"."""
    from ai_agent_service.agents.simulator import Customer, Session

    customer = Customer(_scenarios(SAMPLES, 1)[0], "call_2", seed=0)
    customer.first()
    customer._finish("tu_choi", "customer")
    session = Session(SimpleNamespace(observer=None, errors=[]), customer, set())
    assert await session.reply("Dạ vâng ạ, em chào chị.", [], {"questions": [], "claims": []}) is None
