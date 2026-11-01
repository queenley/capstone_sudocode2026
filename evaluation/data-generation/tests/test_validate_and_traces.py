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
    # The part after the millions is the same amount: "4 triệu rưỡi" was read as 4.000.000 and flagged as unverified.
    assert money_mentions("ngân sách 4 triệu rưỡi") == {4_500_000}
    assert money_mentions("giá 4 triệu 290 ngàn") == {4_290_000}
    assert money_mentions("5tr2 thôi, hoặc 5 triệu 25") == {5_200_000, 5_250_000}
    assert money_mentions("dưới 2 triệu, 3 trăm cái") == {2_000_000}


def test_amounts_the_shop_publishes_or_the_customer_said_are_trusted():
    from src.pipeline.validate_rules import published_money

    # VC-05's confirmation call, VC-03's COD limit, MOM-FREESHIP's minimum order, TRADE-IN-AP's discount.
    assert {2_000_000, 10_000_000, 500_000, 400_000} <= published_money()


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


def test_the_pipeline_sets_the_labels_the_model_kept_missing():
    from src.pipeline.generate_dialogue import set_labels

    talk = conversation([
        {"text": "Dạ em chào chị ạ, em là trợ lý ảo của shop.", "facts_used": ["blocker"]},
        {"text": "Dạ máy giá 4.890.000đ. Chị muốn em lên đơn luôn không ạ?",
         "questions": [{"slot": "order_create", "type": "confirm", "text": "Chị muốn em lên đơn luôn không ạ?"}]},
        {"text": "Dạ em đã tạo đơn cho chị. Chị cần hỗ trợ thêm gì không ạ?",
         "questions": [{"slot": "other", "type": "confirm", "text": "Chị cần hỗ trợ thêm gì không ạ?"}]},
    ])
    set_labels(talk, ["blocker", "product_advised"])
    first, offer, closing = talk.agent_turns()
    assert first.facts_used == ["blocker", "product_advised"]                       # rule 1: every carried slot
    assert [(q.slot, q.type) for q in offer.questions] == [("other", "open")]      # a name outside the vocabulary
    assert closing.text == "Dạ em đã tạo đơn cho chị." and closing.questions == []  # the courtesy question dropped


def test_exporting_again_keeps_the_reviewers_decisions_on_unchanged_transcripts(tmp_path, monkeypatch):
    import csv as csvlib

    from src.pipeline import export_manual_review as review

    monkeypatch.setattr(review, "_read_json", lambda path: {})
    target = tmp_path / "needs_manual_review.csv"
    records = [{"conversation_id": "S__call_1", "scenario_id": "S", "call": "call_1", "validator_pass": False,
                "errors": ["x"]}]
    review.export(records, target)
    rows = list(csvlib.DictReader(target.open(encoding="utf-8-sig")))
    rows[0].update(approve="N", notes="sai giá")
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csvlib.DictWriter(stream, fieldnames=review.FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    review.export(records, target)                       # a later run that added data exports again
    again = list(csvlib.DictReader(target.open(encoding="utf-8-sig")))
    assert (again[0]["approve"], again[0]["notes"]) == ("N", "sai giá")
