"""Saying the call is put through is a claim about what the system did: the hard guard wants the tool call behind it."""
from ai_agent_service.components.guardrails import hard

DONE = ({"name": "handoff.transfer", "args": {}, "result": {"ok": True, "data": {"ticket_id": "T1"}}},)
FAILED = ({"name": "handoff.transfer", "args": {}, "result": {"ok": False, "error": {"code": "X"}}},)


def guard(text, tool_results=(), **extra):
    return hard.check(hard.GuardInput(text=text, tool_results=tuple(tool_results), tier="VERIFIED", **extra))


def test_a_promise_to_transfer_without_the_tool_is_blocked():
    verdict = guard("Dạ em sẽ chuyển máy ngay cho nhân viên hỗ trợ anh ạ.")
    assert not verdict.passed
    assert any("handoff_transfer" in reason for reason in verdict.reasons)


def test_the_promise_passes_once_the_transfer_ran():
    assert guard("Dạ em sẽ chuyển máy ngay cho nhân viên hỗ trợ anh ạ.", DONE).passed


def test_a_failed_transfer_does_not_license_the_promise():
    assert not guard("Dạ em sẽ chuyển máy ngay cho nhân viên hỗ trợ anh ạ.", FAILED).passed


def test_an_offer_or_a_question_is_not_a_promise():
    assert guard("Dạ nếu anh muốn, em có thể chuyển máy cho nhân viên ạ.").passed
    assert guard("Dạ anh có muốn em chuyển máy cho nhân viên không ạ?").passed


def test_a_consultants_text_is_only_warned_about_other_things():
    view = hard.GuardInput(text="", tool_results=(), tier="VERIFIED")
    assert hard.warnings_for(["Dạ em sẽ chuyển máy cho đồng nghiệp ạ."], view) == []
