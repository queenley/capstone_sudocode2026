"""One configuration of a run graded alone: only when asked by name, and only a whole run of it."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from ai_agent_service.pipeline.eval import cli, relabel, report

from test_eval_guardrails import cohort, rows

#: What a run whose process died after writing its traces leaves: no problems, no failure, still INCOMPLETE.
STOPPED = {"status": "INCOMPLETE", "configs": {"full": {"memory": True}, "baseline_no_memory": {"memory": False}}}


def source(tmp_path, trace_rows, manifest=STOPPED):
    run = tmp_path / "source"
    run.mkdir()
    cohort(run / "scenarios")
    (run / "full.jsonl").write_text("\n".join(json.dumps(r) for r in trace_rows))
    (run / "manifest.json").write_text(json.dumps(manifest))
    return run


def test_a_silent_stop_is_refused_unless_a_configuration_is_named(tmp_path):
    run = source(tmp_path, rows())
    traces = {"full": run / "full.jsonl"}
    assert relabel.source_errors(run, traces, {"full": rows()}) == [
        "Source has an unresolved execution failure", "baseline_no_memory: missing source trace"]
    assert relabel.source_errors(run, traces, {"full": rows()}, chosen=True) == []


def test_a_recorded_failure_is_refused_even_when_named(tmp_path):
    run = source(tmp_path, rows(), {**STOPPED, "failure": {"stage": "turns", "type": "RuntimeError"}})
    assert relabel.source_errors(run, {"full": run / "full.jsonl"}, {"full": rows()}, chosen=True)


def test_a_failed_turn_is_refused_even_when_named(tmp_path):
    run = source(tmp_path, rows())
    (run / "diagnostics.jsonl").write_text(json.dumps({"config": "full", "error": "RuntimeError: synthetic"}))
    assert relabel.source_errors(run, {"full": run / "full.jsonl"}, {"full": rows()}, chosen=True)


def extractor():
    return SimpleNamespace(model_name="synthetic", stats=lambda: {})


def test_the_named_configuration_is_graded_alone(tmp_path, monkeypatch):
    run = source(tmp_path, rows())
    monkeypatch.setattr(cli, "_label", AsyncMock())
    grade = Mock(return_value=(0, "synthetic table"))
    monkeypatch.setattr(report, "grade", grade)
    out = tmp_path / "out"
    assert asyncio.run(relabel.relabel(run, out, extractor(), ("full",))) == 0
    assert grade.call_args.kwargs["baseline"] is None
    record = json.loads((out / "relabel.json").read_text(encoding="utf-8"))
    assert record["status"] == "COMPLETE" and record["configs"] == ["full"] and "note" in record


def test_a_named_configuration_missing_turns_is_not_labelled(tmp_path, monkeypatch):
    run = source(tmp_path, rows()[:1])
    label = AsyncMock()
    monkeypatch.setattr(cli, "_label", label)
    assert asyncio.run(relabel.relabel(run, tmp_path / "out", extractor(), ("full",))) == 1
    label.assert_not_awaited()


def test_a_configuration_the_run_lacks_is_bad_input(tmp_path):
    run = source(tmp_path, rows())
    assert asyncio.run(relabel.relabel(run, tmp_path / "out", extractor(), ("baseline_no_memory",))) == 2


def test_a_labelling_that_never_answers_stops_the_run_instead_of_waiting(monkeypatch):
    monkeypatch.setattr(cli, "LABEL_TIMEOUT_S", 0.05)

    class Hung:
        async def label(self, data):
            await asyncio.sleep(10)

        def stats(self):
            return {}

    run = cli.ConfigRun(rows=rows(), diagnostics=[{} for _ in rows()])
    asyncio.run(cli._label(run, Hung()))
    assert run.stopped and "no answer" in run.stopped[0]["error"]
    assert all(r["questions"] == [] for r in run.rows)


def test_an_item_that_is_none_of_the_three_kinds_is_dropped_not_fatal():
    from ai_agent_service.components.evaluation import scorers

    text = "Dạ hiện em chưa tra được giá chính xác lúc này."
    other = {"kind": "other", "slot_or_field": "other", "value": None, "question_type": "open", "speaker": "agent",
             "source_field": "agent_text", "quote": text, "purpose": "báo chưa tra được"}
    scorers.Items.model_validate({"items": [other]})  # v9 refused this, and the turn could never be labelled
    labels = scorers.label_items([other], scorers.turn_input(text))
    assert labels["items"] == [] and labels["questions"] == [] and labels["claims"] == [] and labels["changed"] == 1


def test_other_turns_are_still_labelled_after_one_fails_when_nothing_caps_spending(monkeypatch):
    monkeypatch.delenv("EVAL_BUDGET_DB", raising=False)
    empty = {"questions": [], "claims": [], "facts_used": [], "items": [], "dropped": 0, "changed": 0}
    answers = iter([{**empty, "error": "synthetic"}, empty, empty])
    extractor = SimpleNamespace(label=AsyncMock(side_effect=lambda data: next(answers)), stats=lambda: {})
    run = cli.ConfigRun(rows=rows(), diagnostics=[{} for _ in rows()])
    asyncio.run(cli._label(run, extractor))
    assert extractor.label.await_count == 3 and len(run.stopped) == 1
