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


@pytest.mark.parametrize("answer, reason", [
    ("Phí lắp đặt 200.000đ ạ.", "số tiền"),
    ("Dạ áp mã AIR-OCT nhé.", "mã khuyến mãi"),
    ("Dạ hiện còn hàng ạ.", "tồn kho"),
])
def test_approving_a_gap_goes_through_the_gate(knowledge, answer, reason):
    folder, config = knowledge
    gap = gaps.record("Phí lắp đặt bao nhiêu?", call_id="1", turn_id="t1")
    with pytest.raises(ValueError, match=reason):
        gaps.resolve(gap, answer=answer, cites=["PB-05"], reviewer="reviewer", directory=folder, config_path=config)
    assert gaps.list_gaps()[0]["status"] == "open" and versions.versions(folder) == [0]


def test_a_retired_policy_cannot_support_an_answer(knowledge):
    folder, config = knowledge
    gap = gaps.record("Đổi trả bao lâu?", call_id="1", turn_id="t1")
    with pytest.raises(ValueError, match="public"):
        gaps.resolve(gap, answer="Trong thời hạn đổi trả.", cites=["DT-OLD-01"], reviewer="reviewer",
                     directory=folder, config_path=config)


def test_a_question_can_be_dismissed_with_a_reason_and_open_ones_come_first(knowledge):
    closed = gaps.record("Thời tiết hôm nay?", call_id="1", turn_id="t1")
    gaps.record("Câu khác?", call_id="1", turn_id="t2")
    gaps.record("Thời tiết hôm nay?", call_id="2", turn_id="t1")
    with pytest.raises(ValueError, match="human"):
        gaps.dismiss(closed, reason="Ngoài phạm vi", reviewer="qa")
    with pytest.raises(KeyError):
        gaps.dismiss("0" * 16, reason="Ngoài phạm vi", reviewer="reviewer")
    gaps.dismiss(closed, reason="Ngoài phạm vi", reviewer="reviewer")
    assert [row["status"] for row in gaps.list_gaps()] == ["open", "dismissed"]
    assert gaps.list_gaps()[1]["reason"] == "Ngoài phạm vi"


def test_a_gap_that_became_an_faq_is_closed_for_both_other_paths(knowledge):
    folder, config = knowledge
    gap = gaps.record("Câu hỏi?", call_id="1", turn_id="t1")
    assert gaps.open_question(gap) == "Câu hỏi?"
    gaps.became_faq(gap, faq_id="FAQ-GAP-X", reviewer="reviewer")
    assert gaps.list_gaps()[0]["faq_id"] == "FAQ-GAP-X"
    with pytest.raises(ValueError):
        gaps.open_question(gap)
    with pytest.raises(ValueError, match="FAQ"):
        gaps.resolve(gap, answer="Em chưa có thông tin.", cites=["PB-05"], reviewer="reviewer", directory=folder,
                     config_path=config)
    with pytest.raises(ValueError):
        gaps.dismiss(gap, reason="Đổi ý", reviewer="reviewer")


def test_a_published_answer_cannot_be_dismissed(knowledge):
    folder, config = knowledge
    gap = gaps.record("Câu hỏi?", call_id="1", turn_id="t1")
    gaps.resolve(gap, answer="Em chưa có thông tin.", cites=["PB-05"], reviewer="reviewer", directory=folder, config_path=config)
    with pytest.raises(ValueError, match="published"):
        gaps.dismiss(gap, reason="Đổi ý", reviewer="reviewer")


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
