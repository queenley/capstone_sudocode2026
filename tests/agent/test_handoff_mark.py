"""The customer messages the staff console highlights around a handoff (``turns.meta.handoff``)."""
from ai_agent_service.runtime.harness import handoff_mark


def _transfer(reason, ok=True):
    return {"tool_results": [{"name": "handoff.transfer", "args": {"brief": {"escalation_reason": reason}},
                              "result": {"ok": ok}}]}


def test_the_message_the_assistant_handed_over_after_is_the_trigger():
    mark = handoff_mark(_transfer("khach_yeu_cau_gap_nguoi"), None)
    assert mark == {"role": "trigger", "reason": "khach_yeu_cau_gap_nguoi", "label": "khách muốn gặp người"}


def test_messages_while_the_handoff_waits_are_marked_waiting():
    assert handoff_mark({"tool_results": []}, "pending")["role"] == "waiting"
    assert handoff_mark(_transfer("khac"), "pending")["role"] == "waiting"


def test_nothing_is_marked_without_a_transfer_or_once_a_person_holds_the_call():
    assert handoff_mark({"tool_results": []}, None) is None
    assert handoff_mark(_transfer("cau_hoi_y_te", ok=False), None) is None
    assert handoff_mark(_transfer("cau_hoi_y_te"), "accepted") is None
