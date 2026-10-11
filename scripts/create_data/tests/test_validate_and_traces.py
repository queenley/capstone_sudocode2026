"""Reference transcript -> trace rows -> official scoring."""
from datetime import date

from src.ground_truth.traces import conversation_rows
from src.metrics.btc_metrics import money_mentions, score_call
from src.schemas.conversation import Conversation

SPEC = {
    "must_carry_over": ["product_advised", "room_area_m2"], "must_not_ask": ["room_area_m2"],
    "expected_outcome": "chot_don",
    "success_if": {"tool_called": "order.create", "args_match": {"sku": "SKU-AP-Y", "price_vnd": 5200000}},
    "ground_truth_facts": {"price_vnd": 5200000, "in_stock": True},
}


def conversation(agent_turns: list[dict]) -> Conversation:
    turns = [{"speaker": "customer", "text": "Chồng chị đồng ý rồi em."}]
    for turn in agent_turns:
        turns += [{"speaker": "agent_ai", **turn}, {"speaker": "customer", "text": "Ừ em."}]
    return Conversation.model_validate({
        "conversation_id": "SCN-T__call_2", "scenario_id": "SCN-T", "call": "call_2", "customer_id": "C001",
        "session_index": 2, "channel": "hotline", "date": date(2026, 10, 17), "region": "bac",
        "category": "gia-dung/may-loc-khong-khi", "persona": "khach_do_du_hoi_nguoi_nha", "turns": turns,
        "gold": {"intent": "mua", "outcome": "chot_don", "sentiment": "positive"}})


def test_money_mentions_reads_vietnamese_formats():
    assert {5200000, 5500000, 500000} <= money_mentions("giá 5.200.000đ, tầm 5,5 triệu, giảm 500k")


def test_perfect_reference_scores_perfectly():
    conv = conversation([
        {"text": "Dạ AirPure Y 5.200.000đ cho phòng 25m² hôm trước ạ.", "facts_used": ["product_advised", "room_area_m2"],
         "claims": [{"field": "price_vnd", "value": 5200000}, {"field": "in_stock", "value": True}]},
        {"text": "Em lên đơn ạ.", "tool_calls": [{"name": "order.create", "args": {"sku": "SKU-AP-Y", "price_vnd": 5200000}}]},
    ])
    rows = conversation_rows(conv)
    assert [r["turn"] for r in rows] == [1, 2, 3]
    score = score_call("SCN-T", "call_2", SPEC, rows)
    assert score.failures == [] and score.tsr and score.ccr == (2, 2) and score.hr == (0, 2)


def test_flawed_reference_is_rejected():
    conv = conversation([
        {"text": "Phòng chị bao nhiêu m² ạ? Giá 4.900.000đ.", "questions": [{"slot": "room_area_m2", "type": "open"}],
         "claims": [{"field": "price_vnd", "value": 4900000}], "tool_calls": [{"name": "handoff.transfer", "args": {}}]},
    ])
    score = score_call("SCN-T", "call_2", SPEC, conversation_rows(conv))
    joined = " ".join(score.failures)
    assert "redundant_question:room_area_m2" in joined and "ccr_missing:product_advised" in joined
    assert "hallucination:price_vnd=4900000" in joined and "tsr:" in joined and "guardrail:over_escalation" in joined
