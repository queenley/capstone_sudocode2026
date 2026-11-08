"""product-extractor-v12: a reply that says an earlier call's value again uses that slot (BTC ``facts_used``).

Synthetic turns; catalogue products are the organisers' (read-only pack).
"""
from ai_agent_service.components.evaluation import scorers

EARLIER = [{"call": "call_1", "turns": [
    {"customer": "Phòng chị khoảng 25 mét vuông, có trẻ nhỏ.",
     "agent": "Dạ em gợi ý máy lọc không khí Samsung AX40, giá 6.490.000đ ạ."},
    {"customer": "Chị thanh toán qua ngân hàng nhé.", "agent": "Dạ em đã lên đơn OD600001 cho chị ạ."}]}]


def used(agent_text, previous=EARLIER, crm=None):
    data = scorers.turn_input(agent_text, [], previous, today="2026-10-20", crm_history=crm)
    return sorted(item["slot_or_field"] for item in scorers.reused_values(data))


def test_naming_the_product_price_and_order_again_uses_them():
    assert used("Dạ đơn Samsung AX40 mã OD600001, shop hoàn chị 6.490.000đ ạ.") == [
        "order_id", "price_quoted_vnd", "product_advised"]


def test_a_payment_said_in_other_words_is_the_same_value():
    assert "payment" in used("Dạ đơn của chị thanh toán chuyển khoản rồi ạ.")


def test_a_different_product_or_amount_is_not_reuse():
    assert used("Dạ máy AirPure X giá 4.890.000đ ạ.") == []


def test_a_room_rating_equal_by_chance_is_not_reuse():
    assert used("Dạ máy phù hợp phòng tối đa 25 mét vuông ạ.") == []


def test_the_crm_history_counts_as_an_earlier_session():
    crm = [{"date": "2026-05-07", "channel": "web", "summary": "Mua xe đẩy", "outcome": "chot_don",
            "facts": {"owned_sku": "SKU-MB-STR1"}}]
    assert used("Dạ xe đẩy gấp gọn Joie Pact của anh vẫn trong bảo hành ạ.", previous=None, crm=crm) == ["owned_sku"]


def test_a_first_call_without_history_uses_nothing():
    assert used("Dạ đơn Samsung AX40 mã OD600001 ạ.", previous=None) == []


def test_the_rule_adds_only_slots_the_model_did_not_label():
    data = scorers.turn_input("Dạ đơn Samsung AX40 mã OD600001 ạ.", [], EARLIER, today="2026-10-20")
    raw = [{"kind": "fact_usage", "slot_or_field": "order_id", "value": None, "question_type": None,
            "source_field": "agent_text", "quote": "OD600001", "purpose": "x"}]
    labels = scorers.label_items(raw, data)
    assert labels["facts_used"] == ["order_id", "product_advised"]
