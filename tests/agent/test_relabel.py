"""A finished run's replies are labelled again by today's extractor and graded, without running the agent."""
import json

import pytest

from ai_agent_service.components.evaluation import scorers
from ai_agent_service.pipeline.eval import relabel


def line(config, call, turn, agent_text, old_labels=True):
    return {"run_id": "old", "config": config, "scenario_id": "SAMPLE-01", "call": call, "turn": turn,
            "customer_text": "khach", "agent_text": agent_text,
            "questions": [{"slot": "budget_vnd", "type": "open", "text": "old"}] if old_labels else [],
            "claims": [], "facts_used": ["blocker"] if old_labels else [], "tool_calls": [],
            "latency": {"ttft_ms": 1, "total_ms": 2, "ttfa_ms": None}, "memory_writes": [], "customer_input_mode": "clean",
            **({"call_brief_latency_ms": 5} if call != "call_1" and turn == 1 else {})}


class Shown:
    """Records what the model would be shown; labels nothing."""

    def __init__(self):
        self.seen = []

    def with_structured_output(self, *args, **kwargs):
        outer = self

        class Runnable:
            async def ainvoke(self, request):
                outer.seen.append(json.loads(request[0].content.split(scorers.MARKER, 1)[1]))
                return scorers.Items(items=[])
        return Runnable()


@pytest.mark.asyncio
async def test_relabel_replaces_old_labels_feeds_history_and_grades(tmp_path):
    run = tmp_path / "run"
    (run / "evidence").mkdir(parents=True)
    (run / "inputs/scenarios").mkdir(parents=True)
    (run / "inputs/scenarios/SAMPLE-01.json").write_text(json.dumps({"scenario_id": "SAMPLE-01",
        "calls": {"call_1": {"customer_turns": ["khach"]}, "call_2": {"customer_turns": ["khach"]}}}))
    for name, config in (("full", "full"), ("baseline", "baseline_no_memory")):
        rows = [line(config, "call_2", 1, "agent 2"), line(config, "call_1", 1, "agent 1")]
        (run / f"evidence/{name}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in run.rglob("*") if p.is_file()}
    llm = Shown()
    code = await relabel.relabel(run, tmp_path / "out", scorers.Extractor(llm, model_name="stub", cache_path=None))
    assert code == 0
    assert {p: p.read_bytes() for p in run.rglob("*") if p.is_file()} == before          # the run is never changed
    rows = [json.loads(l) for l in (tmp_path / "out/full.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["call"], r["questions"], r["facts_used"]) for r in rows] == [("call_1", [], []), ("call_2", [], [])]
    assert sum("previous_sessions" in s for s in llm.seen) == 1                             # only call_2, per config
    assert (tmp_path / "out/report.json").is_file() and (tmp_path / "out/table.txt").is_file()


@pytest.mark.asyncio
async def test_a_directory_without_a_trace_is_refused(tmp_path):
    assert await relabel.relabel(tmp_path, tmp_path / "out", scorers.Extractor(Shown(), model_name="stub")) == 2
