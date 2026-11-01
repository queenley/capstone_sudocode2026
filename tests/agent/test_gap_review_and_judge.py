from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.components.improvement import gaps, versions
from ai_agent_service.components.evaluation.judge import BtcJudge, Criterion, Judgment, applicable


@pytest.fixture
def knowledge(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path / "improvement"))
    folder = tmp_path / "kb"
    folder.mkdir()
    (folder / "v0.jsonl").write_text("")
    config = tmp_path / "knowledge.yaml"
    config.write_text("version: 0\n")
    return folder, config


def test_gap_capture_is_private_idempotent_and_cannot_learn_without_review(knowledge):
    folder, config = knowledge
    gap = gaps.record("Số 0900000001 có hỗ trợ không?", call_id="1", turn_id="t1")
    assert gaps.record("Số 0900000001 có hỗ trợ không?", call_id="1", turn_id="t1") == gap
    captured = gaps.list_gaps()
    assert len(captured) == 1 and len(captured[0]["occurrences"]) == 1
    assert "0900000001" not in json.dumps(captured)
    with pytest.raises(ValueError, match="human"):
        gaps.resolve(gap, answer="Em chưa có thông tin.", cites=["PB-05"], reviewer="qa", directory=folder, config_path=config)
    with pytest.raises(ValueError, match="Citations"):
        gaps.resolve(gap, answer="Em chưa có thông tin.", cites=["INVENTED"], reviewer="reviewer", directory=folder, config_path=config)
    version = gaps.resolve(gap, answer="Em chưa có thông tin.", cites=["PB-05"], reviewer="reviewer", directory=folder, config_path=config)
    assert version == 1
    assert gaps.resolve(gap, answer="Em chưa có thông tin.", cites=["PB-05"], reviewer="reviewer", directory=folder, config_path=config) == 1
    assert versions.versions(folder) == [0, 1]
    proposal = next((gaps.signals.home() / "regression-proposals").glob("*.json"))
    assert json.loads(proposal.read_text())["status"] == "pending_human_review"
    gaps.forget_calls([1])
    assert gaps.list_gaps() == []
    assert gaps.record("Số 0900000001 có hỗ trợ không?", call_id="1", turn_id="late") is None
    assert not proposal.exists()


def test_concurrent_publications_preserve_both_versions(knowledge):
    folder, config = knowledge
    def publish(number):
        return versions.publish([{"chunk_id": f"TEAM-{number}", "source": "faq", "title": "Review",
                                  "text": "Nội dung đã duyệt."}], reviewer="reviewer", directory=folder, config_path=config)
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(publish, [1, 2])) == [1, 2]
    assert {item["chunk_id"] for item in versions.entries(2, folder)} == {"TEAM-1", "TEAM-2"}


@pytest.mark.parametrize("invalid", ['{"chunk_id":"BROKEN"}\n', '[]\n', '{broken json}\n'])
def test_rollback_refuses_corrupt_versions_without_moving_the_live_pointer(knowledge, invalid):
    folder, config = knowledge
    (folder / "v1.jsonl").write_text(invalid)
    with pytest.raises(ValueError):
        versions.rollback(1, reviewer="reviewer", reason="test", directory=folder, config_path=config)
    assert versions.active(config) == 0


@pytest.mark.asyncio
async def test_rubric_missing_duplicate_or_invented_evidence_is_incomplete():
    ids = applicable({}, "call_1")
    good = [Criterion(criterion_id=key, verdict="PASS", evidence="Dạ em chưa có thông tin.") for key in ids]
    writer = SimpleNamespace(ainvoke=AsyncMock(return_value=Judgment(verdicts=good)))
    judge = BtcJudge(SimpleNamespace(with_structured_output=lambda _: writer))
    rows = [{"customer_text": "Số của chị 0900000001", "agent_text": "Dạ em chưa có thông tin.", "tool_calls": []}]
    assert (await judge.grade({}, "call_1", rows))["status"] == "COMPLETE"
    assert "0900000001" not in writer.ainvoke.await_args.args[0]
    for verdicts in (good[:-1], good + [good[0]], [item.model_copy(update={"evidence": "Invented quote"}) for item in good],
                     [item.model_copy(update={"evidence": "   "}) for item in good]):
        writer.ainvoke.return_value = Judgment(verdicts=verdicts)
        assert (await judge.grade({}, "call_1", rows))["status"] == "INCOMPLETE"
    writer.ainvoke.side_effect = RuntimeError("provider failed")
    assert (await judge.grade({}, "call_1", rows))["status"] == "INCOMPLETE"
