"""A skill is in the prompt only while its task is on; the model chooses it, code chooses nothing."""

import json
from datetime import datetime, timedelta, timezone

from ai_agent_service.agents.advisor import HARD_RULES, AgentContext, system_prompt, tool_results_of
from ai_agent_service.components.context import skills
from langchain_core.messages import AIMessage, ToolMessage


def context(**changes):
    now = datetime(2026, 11, 7, 10, tzinfo=timezone(timedelta(hours=7)))
    return AgentContext(**{"call_id": "c", "lane": "NEW", "tier": "VERIFIED", "now": now, **changes})


def test_catalogue_is_always_there_and_a_body_only_once_loaded(monkeypatch):
    monkeypatch.setenv("ADVISOR_SKILLS", "1")
    prompt, _ = system_prompt(context())
    assert "place-order" in prompt and skills.SKILLS["place-order"]["description"] in prompt
    assert skills.SKILLS["place-order"]["body"] not in prompt
    prompt, _ = system_prompt(context(skills=["place-order"]))
    assert prompt.count(skills.SKILLS["place-order"]["body"]) == 1


def test_a_lane_with_no_tools_offers_no_skill(monkeypatch):
    monkeypatch.setenv("ADVISOR_SKILLS", "1")
    assert "load_skill" not in system_prompt(context(lane="CLARIFY"))[0]


def test_loading_is_idempotent_bounded_and_refuses_what_is_not_listed():
    loaded = []
    assert skills.load(loaded, "../../etc/passwd")["error"]["code"] == "UNKNOWN_SKILL" and not loaded
    skills.load(loaded, "place-order")
    skills.load(loaded, "place-order")
    assert loaded == ["place-order"]
    skills.load(loaded, "change-order")
    skills.load(loaded, "order-lookup")
    skills.load(loaded, "product-advice")
    assert loaded == ["change-order", "order-lookup", "product-advice"]


def test_a_skill_leaves_when_its_task_succeeded_not_when_it_failed():
    ok = {"name": "order.create", "result": {"ok": True, "data": {}}}
    refused = {"name": "order.create", "result": {"ok": False, "error": {"code": "CONFIRMATION_REQUIRED"}}}
    assert skills.after_turn(["place-order", "order-lookup"], [ok]) == ["order-lookup"]
    assert skills.after_turn(["place-order"], [refused]) == ["place-order"]


def test_off_every_body_is_in_the_prompt(monkeypatch):
    monkeypatch.setenv("ADVISOR_SKILLS", "0")
    prompt, _ = system_prompt(context())
    assert all(skill["body"] in prompt for skill in skills.SKILLS.values())


def test_loading_is_not_a_business_tool_in_the_trace():
    call = {"id": "1", "name": "load_skill", "args": {"name": "place-order"}}
    produced = [AIMessage(content="", tool_calls=[call]),
                ToolMessage(content=json.dumps({"ok": True, "data": {}}), tool_call_id="1", name="load_skill")]
    assert tool_results_of(produced) == []


def test_the_day_is_stated_so_a_relative_date_needs_no_guess():
    prompt, _ = system_prompt(context())
    assert "Hôm nay: thứ Bảy, 07/11/2026" in prompt and "Ngày mai: Chủ nhật, 08/11/2026" in prompt


def test_the_moved_procedures_are_out_of_the_standing_rules():
    assert "basket_skus" not in HARD_RULES and "needs_confirmation_call" not in HARD_RULES


def test_a_loaded_skill_is_marked_so_it_is_not_loaded_again():
    assert "place-order: đã nạp, không gọi lại." in skills.catalogue(["place-order"])


def test_skills_are_general_not_keyed_to_a_persona_or_a_scenario():
    import json
    from ai_agent_service.config.config_manager import btc_data_dir
    personas = json.loads((btc_data_dir() / "simulator" / "personas.json").read_text(encoding="utf-8"))
    ids = [p["persona_id"] for p in (personas if isinstance(personas, list) else personas["personas"])]
    text = json.dumps(skills.SKILLS, ensure_ascii=False)
    assert not any(pid in text for pid in ids) and "SCN-" not in text and "SKU-" not in text


def test_every_skill_says_when_to_use_it():
    assert all(skill["description"].startswith("Dùng khi") and skill["body"] for skill in skills.SKILLS.values())


def test_every_skill_in_the_prompt_never_pushes_the_documents_out(monkeypatch):
    monkeypatch.setenv("ADVISOR_SKILLS", "0")
    passage = {"chunk_id": "BH-05", "source": "policy", "title": "Bảo hành mở rộng", "text": "Gói bảo hành mở rộng thêm 12 tháng."}
    prompt, cut = system_prompt(context(knowledge=(passage,), seen_products=({"sku": "SKU-A", "name": "Máy", "price_vnd": 1000},)))
    assert "Gói bảo hành mở rộng thêm 12 tháng." in prompt and "SKU-A" in prompt and cut == ()


def test_the_rules_a_learned_line_cites_are_known_and_the_original_skills_have_none():
    original = {"objection-handling": {"description": "d", "body": "- Chê đắt: nêu quyền lợi (PB-02, PB-04)."}}
    learned = {"objection-handling": {"description": "d", "body": original["objection-handling"]["body"]
                                      + "\n- Khách lo máy hỏng sau bảo hành: giới thiệu gói bảo hành mở rộng (BH-05)."}}
    assert skills.learned_cites(original, original) == ()
    assert skills.learned_cites(learned, original) == ("BH-05",)
    assert skills.LEARNED_CITES == ()  # the tests run on the original agent
