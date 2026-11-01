"""The Knowledge Gap Loop's gate (``docs/design.md`` 10.2): what code refuses before a person's approval counts."""

from ai_agent_service.components.improvement.gap import gate
from ai_agent_service.components.knowledge.corpus import entry_chunk


def test_a_grounded_answer_passes():
    assert gate("Bao lâu thì thay màng lọc?", "Màng HEPA nên thay sau 6 đến 12 tháng tùy môi trường.") == ()


def test_prices_promotions_and_stock_stay_with_the_tools():
    reasons = gate("Phí lắp đặt bao nhiêu?", "Phí lắp đặt 200.000đ, áp mã AIR-OCT, hiện còn hàng.")
    assert len(reasons) == 3


def test_no_entry_on_a_topic_that_must_go_to_a_person():
    assert gate("Bà bầu dùng máy này được không?", "Dạ được ạ.")


def test_an_entry_of_the_loop_is_a_gap_entry():
    chunk = entry_chunk({"chunk_id": "GAP-1", "source": "gap", "title": "Q", "text": "A"}, doc="kb_chunks:demo")
    assert chunk.source == "gap"
