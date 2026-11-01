"""The advisor's hard rules keep the three act-now behaviours the evaluation showed it lacking."""
from ai_agent_service.agents.advisor import HARD_RULES


def test_order_is_prepared_then_requires_confirmation_of_the_exact_payload():
    assert "CONFIRMATION_REQUIRED" in HARD_RULES
    assert "mới gọi lại order_create với nguyên payload" in HARD_RULES
    assert "tự lấy từ catalog_search" in HARD_RULES


def test_handoff_without_asking_again():
    assert "gọi handoff_transfer ngay trong lượt đó" in HARD_RULES


def test_order_lookup_before_asking_for_the_code():
    assert "không xin khách đọc mã đơn" in HARD_RULES


def test_one_question_and_no_filler_closing():
    assert "Mỗi lượt tối đa một câu hỏi" in HARD_RULES
    assert "order_create chưa trả ok thì không nói đơn đã được tạo" in HARD_RULES
