"""The advisor's prompt holds what the turn needs: nothing it relies on is cut, and a doubt keeps more, not less."""

from datetime import date

import pytest

from ai_agent_service.agents.advisor import ALL_RULES, HARD_RULES, RULE_PACKS, AgentContext, system_prompt
from ai_agent_service.agents.memory import goal_of
from ai_agent_service.components.context import focus
from ai_agent_service.components.context.budget import tokens
from ai_agent_service.components.memory import brief
from ai_agent_service.components.memory.brief import BriefLine
from ai_agent_service.mcp.servers.memory import matching_lines
from ai_agent_service.pipeline.hot import call_state


def context(**fields):
    return AgentContext(call_id="x", **fields)


def rule_numbers(text):
    return [line.split(".")[0] for line in text.split("\n") if line[:2].strip(".").isdigit()]


LINES = (
    BriefLine("B1", "Khách quen.", kind="history"),
    BriefLine("B2", "Lần gần nhất tư vấn xe đẩy.", kind="history"),
    BriefLine("B3", "Đã tư vấn xe đẩy.", kind="product"),
    BriefLine("B4", "Đã báo giá.", True, kind="quote"),
    BriefLine("B5", "Ngân sách: 3.500.000đ.", kind="need"),
    BriefLine("B6", "Việc còn dở: cần hỏi vợ.", kind="open"),
    BriefLine("B7", "Đơn OD1: giao rồi.", True, kind="order"),
)


def shown(said, **fields):
    return [line.id for line in focus.lines(LINES, said, **{"first_turn": False, "blocked": False, **fields})]


def test_every_rule_stays_in_the_prompts_once():
    numbers = "".join(f"\n{text}" for text in (HARD_RULES, *RULE_PACKS.values()))
    assert sorted(map(int, {n for n in rule_numbers(numbers)})) == list(range(1, 24))
    assert ALL_RULES.count("12. ") == 1


@pytest.mark.parametrize("text", ["Không bao giờ nhận là người", "Danh tính chưa xác minh", "Không đọc lại đầy đủ số điện thoại"])
def test_a_prohibition_every_turn_needs_stays_in_the_core(text):
    assert text in HARD_RULES


def test_nothing_the_rules_rely_on_is_cut_when_the_prompt_is_over_budget():
    passage = {"chunk_id": "DT-01", "doc": "doi-tra", "title": "Đổi trả", "text": "Đổi trả trong 7 ngày. " * 300}
    prompt, cut = system_prompt(context(
        knowledge=(passage,), working_summary="Tóm tắt " * 500, seen_products=({"sku": "SKU-X", "name": "Xe"},),
        created_orders=({"order_id": "OD1", "sku": "SKU-X"},)), max_tokens=100)
    assert cut == ()
    assert "SKU-X" in prompt and "OD1" in prompt and "Tóm tắt" in prompt and "Đổi trả trong 7 ngày" in prompt


def test_the_rules_come_first_and_the_request_last():
    prompt, _ = system_prompt(context(customer_said="xe này còn hàng không", call_state=("Sản phẩm vừa báo giá: SKU-X.",)))
    assert prompt.startswith(HARD_RULES)
    assert prompt.rstrip().endswith("thông tin ở trên chỉ dùng khi phục vụ yêu cầu này.")
    assert prompt.index("Trạng thái cuộc") > prompt.index("Lane:")


def test_a_quiet_turn_loads_no_pack_and_saves_the_tokens():
    prompt, _ = system_prompt(context(customer_said="alo em"))
    assert "Luật cho tình huống" not in prompt
    assert tokens(HARD_RULES) < tokens(ALL_RULES) * 0.65


@pytest.mark.parametrize("said, pack", [
    ("cho anh lấy cái này", "purchase"), ("chi can ban voi gia dinh", "callback"), ("đơn của chị giao chưa", "orders"),
    ("bên khác rẻ hơn em", "objection"), ("gio hang cua chi", "account"), ("nha co phong thu hai", "second_air"),
])
def test_the_words_load_a_pack_with_or_without_marks(said, pack):
    assert pack in focus.packs(context(customer_said=said), RULE_PACKS)


def test_what_the_call_holds_keeps_a_pack_whatever_the_customer_says():
    assert "purchase" in focus.packs(context(customer_said="ừ", seen_products=({"sku": "X"},)), RULE_PACKS)
    assert "orders" in focus.packs(context(customer_said="ừ", known_orders=frozenset({"OD1"})), RULE_PACKS)
    assert "callback" in focus.packs(context(brief_lines=(LINES[5],)), RULE_PACKS)
    assert "account" in focus.packs(context(account_id="A1"), RULE_PACKS)


def test_a_tool_called_this_turn_brings_its_rules():
    assert "callback" in focus.packs(context(customer_said="ừ"), RULE_PACKS, ["schedule_callback"])


def test_a_blocked_draft_reads_every_rule_since_its_reason_may_name_one():
    assert focus.packs(context(block_reasons=("Làm theo luật 20.",)), RULE_PACKS) == tuple(RULE_PACKS)


def test_the_switch_restores_everything(monkeypatch):
    monkeypatch.setenv("ADVISOR_CONTEXT", "full")
    assert focus.packs(context(customer_said="alo"), RULE_PACKS) == tuple(RULE_PACKS)
    assert shown("đơn của chị giao chưa") == [line.id for line in LINES]


def test_the_first_turn_after_a_block_and_an_unknown_topic_see_the_whole_brief():
    whole = [line.id for line in LINES]
    assert shown("đơn giao chưa", first_turn=True) == whole
    assert shown("đơn giao chưa", blocked=True) == whole
    assert shown("alo em nghe không") == whole


def test_a_question_about_an_order_reads_the_order_and_what_is_open():
    assert shown("đơn của chị tới đâu rồi") == ["B3", "B6", "B7"]


def test_advice_reads_the_needs_keeps_what_is_open_and_drops_the_history():
    assert shown("tu van giup chi san pham khac") == ["B3", "B4", "B5", "B6"]


def test_at_most_six_lines_but_what_is_open_is_never_dropped():
    many = tuple(BriefLine(f"N{i}", "nhu cầu", kind="need") for i in range(9)) + (BriefLine("O", "còn dở", kind="open"),)
    kept = focus.lines(many, "tu van san pham", first_turn=False, blocked=False)
    assert len(kept) == 6 and kept[-1].id == "O"


def test_the_state_remembers_the_customer_and_the_open_question():
    facts = call_state.heard("anh co ngan sach khoang 3 trieu", None)
    facts = call_state.heard("nha co be nho", facts)
    text = call_state.lines(facts, {"SKU-X": 100}, "Dạ vâng. Anh lấy màu nào ạ?")
    assert any("không hỏi lại" in line and "có" in line for line in text)
    assert "Sản phẩm vừa báo giá: SKU-X." in text
    assert "Em đang chờ khách trả lời:  Anh lấy màu nào ạ?".replace("  ", " ") in text


def test_no_question_is_open_after_a_statement():
    assert call_state.open_question("Dạ em đã hẹn gọi lại anh.") is None


def facts_with_blocker():
    return [{"slot": "blocker", "value": "cần hỏi vợ", "status": "active", "fact_id": "F1", "valid_from": "2026-10-16"}]


@pytest.mark.parametrize("outcome, still_open", [("hen_goi_lai", True), ("chot_don", False), ("tu_choi", False)])
def test_a_blocker_a_later_close_answered_is_no_longer_open(outcome, still_open):
    episodes = [{"date": "2026-10-18", "outcome": outcome, "channel": "hotline", "summary": "s"}]
    made, lines = brief.render(customer={"customer_id": "C"}, facts=facts_with_blocker(), episodes=episodes, orders=[],
                               products=[], warnings=[], now=_now(), latency_ms=1)
    assert bool(made["open_blockers"]) is still_open
    assert any(line.kind == "open" for line in lines) is still_open
    # Past, not forgotten: the organisers' must_carry_over can still ask for it after a close.
    assert any("cần hỏi vợ" in line.text and line.fact_ids == ("F1",) for line in lines)


def _now():
    from datetime import datetime
    return datetime(2026, 10, 19, 9)


def test_a_line_keeps_its_kind_through_the_state():
    assert BriefLine("B1", "x", kind="open").as_dict()["kind"] == "open"
    assert date(2026, 10, 19)


@pytest.mark.parametrize("said, pack", [
    ("hôm trước em báo khác mà", "past"), ("xoa du lieu cua chi di", "deletion"), ("may nay con hang khong", "advice")])
def test_the_rules_moved_last_are_loaded_by_their_words(said, pack):
    assert pack in focus.packs(context(customer_said=said), RULE_PACKS)


def test_a_customer_with_a_brief_always_reads_how_to_use_the_past():
    assert "past" in focus.packs(context(customer_said="ừ", brief_lines=(LINES[0],)), RULE_PACKS)


def test_a_promise_of_the_last_call_is_open_and_a_fact_is_not_repeated():
    episodes = [{"date": "2026-10-18", "outcome": "hen_goi_lai", "channel": "hotline", "summary": "s",
                 "open_items": ["khách cần hỏi vợ", "gửi ảnh sản phẩm qua Zalo"]}]
    _, lines = brief.render(customer={"customer_id": "C"}, facts=facts_with_blocker(), episodes=episodes, orders=[],
                            products=[], warnings=[], now=_now(), latency_ms=1)
    left = [line.text for line in lines if line.text.startswith("Việc còn dở lần trước")]
    assert left == ["Việc còn dở lần trước: gửi ảnh sản phẩm qua Zalo."]


def test_the_goal_is_the_customers_first_real_line_without_personal_tokens():
    transcript = [{"speaker": "customer", "text": "Alo em"}, {"speaker": "agent", "text": "Dạ em chào anh ạ"},
                  {"speaker": "customer", "text": "Anh ở <ADDR_1> muốn hỏi xe đẩy cho bé"}]
    assert goal_of(transcript) == "Anh ở muốn hỏi xe đẩy cho bé"
    assert goal_of(transcript[:2]) is None


def test_a_past_line_is_found_by_its_words_with_or_without_marks_and_its_tokens_are_masked():
    rows = [{"content": "Giá này chưa gồm phí ship", "speaker": "agent", "started_at": "2026-10-16T09:00:00"},
            {"content": "Bảo hành máy lọc 24 tháng, gọi <PHONE_1>", "speaker": "agent", "started_at": "2026-10-16T09:01:00"}]
    found = matching_lines(rows, "bao hanh may loc")
    assert len(found) == 1
    assert found[0]["text"] == "Bảo hành máy lọc 24 tháng, gọi [đã che]" and found[0]["date"] == "2026-10-16"
    assert matching_lines(rows, "voucher") == []


def test_only_a_verified_customer_with_a_brief_can_look_back():
    from ai_agent_service.config.config_manager import get_lanes
    lanes = get_lanes()
    assert {"memory_get_episodes", "memory_search_calls"} <= set(lanes["CONTINUITY"])
    assert not {"memory_get_episodes", "memory_search_calls"} & set(lanes["NEW"])


def test_the_model_is_told_today_so_tomorrow_has_a_date():
    from datetime import datetime
    from ai_agent_service.components.clock import VIETNAM
    prompt, _ = system_prompt(context(now=datetime(2026, 10, 16, 10, 0, tzinfo=VIETNAM)))
    assert "thứ Sáu 16/10/2026" in prompt
