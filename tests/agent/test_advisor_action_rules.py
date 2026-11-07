"""The advisor's hard rules keep the three act-now behaviours the evaluation showed it lacking."""
from ai_agent_service.agents.advisor import HARD_RULES
from ai_agent_service.components.context.skills import SKILLS


def test_order_is_prepared_then_requires_confirmation_of_the_exact_payload():
    body = SKILLS["place-order"]["body"]
    assert "CONFIRMATION_REQUIRED" in body
    assert "giá trong order_create do hệ thống điền" in body
    assert "tự lấy từ catalog_search" in body


def test_handoff_without_asking_again():
    assert "gọi handoff_transfer ngay trong lượt" in HARD_RULES
    assert "không hỏi lại \"anh có muốn chuyển không\"" in HARD_RULES


def test_no_information_is_a_reason_to_transfer():
    # BTC's answer (DIEU-CHINH-DE 4, GIAI-DAP-MENTOR 4): a transfer is a success for an out-of-scope question.
    assert "ngoai_pham_vi_tai_lieu" in HARD_RULES


def test_order_lookup_before_asking_for_the_code():
    assert "không xin khách đọc mã đơn" in SKILLS["change-order"]["body"]


def test_one_question_and_no_filler_closing():
    assert "Mỗi lượt tối đa một câu hỏi" in HARD_RULES
    assert "order_create chưa trả ok thì không nói đơn đã được tạo" in HARD_RULES
