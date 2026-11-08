"""Call backs: the time as the organisers compare it, a holiday left to the tool, a promise only after booking."""

from dataclasses import replace

import pytest

from ai_agent_service.components import clock
from ai_agent_service.components.guardrails import actions, hard, purchase

BOOKED = {"name": "schedule.callback", "result": {"ok": True, "data": {"callback_at": "2026-10-27T09:00",
                                                                       "moved_from": "2026-10-26T09:00"}}}
VIEW = hard.GuardInput(text="", tool_results=(), tier="VERIFIED")


def test_a_tool_time_has_no_offset_whatever_the_model_wrote():
    assert clock.tool_time(clock.parse_local("2026-10-17T19:00+07:00")) == "2026-10-17T19:00"
    assert clock.tool_time(clock.parse_local("2026-10-17T12:00+00:00")) == "2026-10-17T19:00"


@pytest.mark.parametrize("asked,passes", [
    ("2026-10-26T09:00", True),   # LN-02: the tool moves it and says so
    ("2027-01-01T09:00", True),
    ("2026-10-17T22:00", False),  # LN-01: the model proposes the nearest slot first
    ("2026-10-18T19:00", False),  # a Sunday's closing is 18:00
    ("2026-10-16T09:00", False),  # already past
])
def test_a_holiday_goes_to_the_tool_and_outside_the_hours_is_proposed(asked, passes):
    now = clock.parse_local("2026-10-16T10:00")
    assert (actions._schedule_callback({"callback_at": asked}, now=now) == []) is passes


def test_a_moved_call_back_must_be_told():
    assert hard.moved_callback("Dạ em đã đặt lịch rồi ạ.", [BOOKED]) == clock.moment_label(clock.parse_local("2026-10-27T09:00"))
    assert hard.moved_callback("Dạ em dời sang 27/10 ạ.", [BOOKED]) is None
    assert hard.moved_callback("Dạ em gọi lại vào thứ Ba nhé.", [BOOKED]) is None


@pytest.mark.parametrize("said", [
    "Đúng rồi em.", "Ừ, đúng rồi.", "Vâng, chị xác nhận nhé.", "Chị đồng ý.", "Anh xác nhận đúng rồi em nhé.",
    "Đúng rồi em, lên đơn giúp anh nhé.", "Ừ, em đặt luôn giúp chị nhé.", "Đúng rồi, thông tin như vậy là chính xác.",
    "Em làm đơn cho chị luôn đi.", "dung roi em", "u dung roi chau len don cho co nhe", "dong y",
])
def test_a_yes_as_people_say_it_is_a_yes(said):
    assert purchase.agrees(said)


@pytest.mark.parametrize("said", [
    "Chị cần suy nghĩ thêm một chút.", "Đúng rồi nhưng đổi địa chỉ giúp chị.", "Cảm ơn em nhé.", "Không, chưa đặt đâu.",
    "Mua cái khác được không em?", "Ừ để anh hỏi vợ đã.", "Đúng rồi em, nhưng chưa đặt vội nhé.",
])
def test_anything_more_than_a_yes_is_not_one(said):
    assert not purchase.agrees(said)
