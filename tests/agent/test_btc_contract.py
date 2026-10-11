"""What the agent stores and emits, checked against the organisers' contract (``data/btc``).

CallBrief, HandoffBrief and trace lines against ``schemas/*.json``; the
ledger's slot names against the sample scenarios; an exported trace scored
by ``eval/reference_eval.py`` itself.
"""

import asyncio
import datetime as dt
import glob
import importlib.util
import json
from pathlib import Path

import pytest

from ai_agent_service.agents.memory import MemoryAgent
from ai_agent_service.components import btc_schemas
from ai_agent_service.components.guardrails import actions
from ai_agent_service.components.intake import pii
from ai_agent_service.components.memory import brief, ontology
from ai_agent_service.config.config_manager import btc_data_dir
from ai_agent_service.runtime import trace_export

NOW = dt.datetime(2026, 10, 15, 10, tzinfo=dt.timezone(dt.timedelta(hours=7)))
SAMPLES = sorted(glob.glob(str(btc_data_dir() / "test_set" / "public_sample" / "*.json")))


def as_json(value):
    return json.loads(json.dumps(value, default=str))


# ── CallBrief and HandoffBrief ────────────────────────────────────────────


def returning_brief():
    return brief.render(
        customer={"customer_id": "C001", "name": "Hoa", "honorific": "chị", "phone_last4": "6714"},
        facts=[
            {"fact_id": "f1", "slot": "room_area_m2", "value": 25, "status": "active"},
            {"fact_id": "f2", "slot": "blocker", "value": "cần hỏi ý kiến chồng", "status": "active"},
            {"fact_id": "f3", "slot": "payment", "value": "COD", "status": "active"},
            {"fact_id": "f4", "slot": "product_advised", "value": "SKU-AP-Y", "status": "active"},
        ],
        episodes=[{"call_id": 7, "date": dt.date(2026, 10, 13), "channel": "hotline",
                   "summary": "tư vấn SKU-AP-Y 5.200.000đ", "outcome": "hen_goi_lai"}],
        orders=[],
        products=[{"sku": "SKU-AP-Y", "name": "AirPure Y", "price_quoted_vnd": 5_200_000, "promo_code": "GIFT-FILTER",
                   "promo_still_active": True, "quoted_on": dt.date(2026, 10, 13), "fact_ids": ["f4"]}],
        warnings=[], now=NOW, latency_ms=410,
    )


def test_call_brief_matches_the_schema():
    built, lines = returning_brief()
    assert btc_schemas.errors("call_brief", as_json(built)) == []
    assert btc_schemas.errors("call_brief", as_json(brief.empty(NOW, 3))) == []
    # Business facts are protected too, as SAMPLE-02..04 expect.
    assert {"room_area_m2", "payment", "product_advised"} <= set(built["must_not_ask"])
    assert lines[0].id == "B1"


HANDOFF_DEFAULTS = {
    "customer_phone": "0984726714", "customer_name": "Hoa", "customer_id": "C001", "channel": "hotline",
    "product_advised": "SKU-AP-Y", "price_quoted_vnd": 5_200_000, "generated_at": NOW.isoformat(),
}
MODEL_BRIEF = {"escalation_reason": "cau_hoi_y_te",
               "conversation_summary": "Khách hỏi máy lọc có phù hợp cho bé bị hen suyễn không; cần chuyên môn y tế.",
               "next_action": "Gọi lại tư vấn y tế rồi chốt SKU-AP-Y."}


def test_filled_handoff_brief_matches_the_schema():
    filled = actions.fill_handoff(MODEL_BRIEF, HANDOFF_DEFAULTS)
    assert btc_schemas.errors("handoff_brief", filled) == []
    assert actions.handoff_problems(filled) == []


@pytest.mark.parametrize("change,expected", [
    ({"escalation_reason": "vi_sao_khong_biet"}, "escalation_reason"),
    ({"conversation_summary": "ngắn"}, "conversation_summary"),
    ({"sentiment": "buon"}, "sentiment"),
])
def test_handoff_schema_violations_reach_the_model(change, expected):
    problems = actions.handoff_problems(actions.fill_handoff({**MODEL_BRIEF, **change}, HANDOFF_DEFAULTS))
    assert any(expected in p for p in problems)


def test_handoff_without_a_phone_only_blocks_on_the_hotline():
    chat = actions.fill_handoff(MODEL_BRIEF, {**HANDOFF_DEFAULTS, "customer_phone": "", "channel": "web_chat"})
    assert actions.handoff_problems(chat) == []
    call = actions.fill_handoff(MODEL_BRIEF, {**HANDOFF_DEFAULTS, "customer_phone": ""})
    assert any("số điện thoại" in p for p in actions.handoff_problems(call))


# ── the ledger's vocabulary ───────────────────────────────────────────────

#: Facts the organisers record about a call that are not customer memory.
NOT_MEMORY = {"channel"}


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: Path(p).stem)
def test_every_graded_slot_exists_in_the_ledger(path):
    scenario = json.loads(Path(path).read_text(encoding="utf-8"))
    for spec in scenario["calls"].values():
        named = set(spec.get("must_carry_over") or []) | set(spec.get("must_not_ask") or [])
        named |= set(spec.get("facts_established") or {}) - NOT_MEMORY
        assert not {n for n in named if ontology.slot(n) is None}, scenario["scenario_id"]


def test_memory_agent_writes_the_organisers_slot_names():
    said = ["Bên khác bán 4 triệu 5 thôi", "Giao về quận Cầu Giấy, Hà Nội nhé", "Chị lấy 2 cái",
            "Bé nhà chị 8 tháng", "Số chị là <PHONE_1>, nhắn qua zalo nhé"]
    transcript = [{"speaker": "customer", "text": t, "turn": i + 1} for i, t in enumerate(said)]
    tools = [{"name": "crm.get_customer", "turn": 1, "result": {"ok": True, "data": {"orders": [{"sku": "SKU-AP-X-2024"}]}}}]
    found = {c.slot: c.value for c in asyncio.run(MemoryAgent().extract(transcript, tools, on="2026-10-15"))}
    assert found == {
        "owned_sku": "SKU-AP-X-2024", "objection": "so_sanh_gia", "competitor_price_vnd": 4_500_000,
        "delivery_area": "quận Cầu Giấy, Hà Nội", "quantity": 2, "child_age_months": 8,
        "phone_provided": True, "preferred_channel": "zalo",
    }


def test_synthetic_crm_customers_are_found():
    from ai_agent_service.mcp.servers import btc

    synthetic = json.loads((btc_data_dir() / "catalog" / "crm_seed_synthetic.json").read_text(encoding="utf-8"))
    first = synthetic["customers"][0]
    assert btc.mock().crm_get_customer(phone=first["phone"])["customer_id"] == first["customer_id"]


# ── the trace ─────────────────────────────────────────────────────────────


def stored_call_2():
    """SAMPLE-01, call 2, as the agent would have stored it."""
    vault = pii.Vault()
    phone = vault.put("PHONE", "0984726714")
    built, lines = returning_brief()
    call = {"brief": [l.as_dict() for l in lines], "brief_object": as_json(built), "business_day": "2026-10-15",
            "after_call": {"memory_writes": [{"key": "outcome", "value": "chot_don", "op": "set", "source": "call_2#turn3",
                                              "customer_id": "C001", "fact_id": "F-1"}]}}
    latency = {"ttft_ms": 900, "total_ms": 2100, "ttfa_ms": None, "call_brief_latency_ms": 410}
    quote = {"name": "pricing_get_quote", "args": {"sku": "SKU-AP-Y", "customer_phone": phone},
             "result": {"ok": True, "data": {"sku": "SKU-AP-Y", "final_price_vnd": 5_200_000}}}
    order = {"name": "order_create",
             "args": {"customer_phone": phone, "sku": "SKU-AP-Y", "qty": 1, "price_vnd": 5_200_000, "payment": "COD"},
             "result": {"ok": True, "data": {"order_id": "OD00001"}}}
    turns = [
        {"turn_id": "open", "speaker": "agent", "content": "Dạ em chào chị Hoa, hôm trước chị quan tâm máy AirPure Y.",
         "meta": {"tool_calls": []}},
        {"turn_id": "t1", "speaker": "customer", "content": "Alo, hôm trước chị có gọi hỏi máy lọc không khí đó em.", "meta": {}},
        {"turn_id": "t1", "speaker": "agent", "content": "Dạ vẫn là phòng 25 m² của chị đúng không ạ?",
         "meta": {"used_brief_lines": ["B4"], "tool_calls": [], "latency": latency}},
        {"turn_id": "t2", "speaker": "customer", "content": "Ông xã chị đồng ý rồi, giá vẫn như hôm trước đúng không?", "meta": {}},
        {"turn_id": "t2", "speaker": "agent",
         "content": "Dạ giá hôm nay vẫn là 5.200.000đ, kèm GIFT-FILTER còn hiệu lực, máy còn hàng và giao trong 2 ngày ạ.",
         "meta": {"tool_calls": [quote], "latency": {**latency, "call_brief_latency_ms": None}}},
        {"turn_id": "t3", "speaker": "customer", "content": "Ừ em lên đơn cho chị đi, giao về địa chỉ cũ nhé.", "meta": {}},
        {"turn_id": "t3", "speaker": "agent", "content": f"Dạ em đã lên đơn OD00001 cho số {phone} ạ.",
         "meta": {"tool_calls": [order], "latency": latency}},
    ]
    return call, turns, vault


def test_exported_trace_lines_match_the_schema():
    call, turns, vault = stored_call_2()
    rows = trace_export.build_rows(call, turns, vault, scenario_id="SAMPLE-01", call_label="call_2", run_id="t")
    assert [r["turn"] for r in rows] == [1, 2, 3]
    for row in rows:
        assert btc_schemas.errors("trace_log", as_json(row)) == []
    first, second, third = rows
    assert first["agent_text"].startswith("Dạ em chào chị Hoa")  # the opening joins turn 1
    assert first["call_brief_latency_ms"] == 410 and "call_brief_latency_ms" not in second
    assert first["questions"] == [{"slot": "room_area_m2", "type": "confirm", "text": "Dạ vẫn là phòng 25 m² của chị đúng không ạ?"}]
    assert "room_area_m2" in first["facts_used"]
    claims = {c["field"]: c["value"] for c in second["claims"]}
    assert claims == {"price_vnd": 5_200_000, "promo_GIFT-FILTER_active": True, "in_stock": True, "delivery_days": 2}
    assert third["tool_calls"][0]["name"] == "order.create"
    assert third["tool_calls"][0]["args"]["customer_phone"] == "0984726714"  # detokenised
    assert "0984726714" in third["agent_text"]
    assert third["memory_writes"] == [{"key": "outcome", "value": "chot_don", "op": "set", "source": "call_2#turn3", "customer_id": "C001"}]


def test_reference_eval_scores_an_exported_trace():
    spec = importlib.util.spec_from_file_location("reference_eval", btc_data_dir() / "eval" / "reference_eval.py")
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    scenario = json.loads((btc_data_dir() / "test_set" / "public_sample" / "SAMPLE-01.json").read_text(encoding="utf-8"))
    scenario["calls"] = {"call_2": scenario["calls"]["call_2"]}
    call, turns, vault = stored_call_2()
    rows = trace_export.build_rows(call, turns, vault, scenario_id="SAMPLE-01", call_label="call_2", run_id="t")
    trace = {("SAMPLE-01", "call_2"): rows}
    scenarios = {"SAMPLE-01": scenario}
    assert reference.task_success_rate(scenarios, trace)["value"] == 100.0
    assert reference.hallucination_rate(scenarios, trace)["value"] == 0.0
    assert reference.repeat_question_rate(scenarios, trace)["value"] == 0.0
    assert reference.context_carryover_rate(scenarios, trace)["used"] >= 2


@pytest.mark.parametrize("said,expected", [
    ("Dạ giá gốc 5.490.000đ, hôm nay chỉ còn 4.890.000đ ạ.", {"list_price_vnd": 5_490_000, "price_vnd": 4_890_000}),
    ("Tổng đơn 9.780.000đ, bảo hành 2 năm, giao 2-3 ngày.", {"order_total_vnd": 9_780_000, "warranty_months": 24, "delivery_days": 3}),
    ("Đổi trả trong 7 ngày, phí đổi size 30.000đ.", {"return_days": 7, "exchange_fee_vnd": 30_000}),
    ("Bên khác bán 4.500.000đ nhưng bên em giá 4.890.000đ.", {"price_vnd": 4_890_000}),
    ("Mã AIR-OCT đã hết hạn rồi ạ.", {"promo_AIR-OCT_active": False}),
    ("Máy tạm hết hàng, dự kiến về hàng 20/10.", {"in_stock": False, "restock_date": "2026-10-20"}),
    ("Chị cần mấy cái ạ?", {}),
])
def test_claim_extraction(said, expected):
    assert {c["field"]: c["value"] for c in trace_export.extract_claims(said)} == expected


def test_trace_endpoint_returns_valid_rows_and_jsonl(client, monkeypatch):
    from ai_agent_service.runtime import calls

    call, turns, vault = stored_call_2()

    async def rows(call_id, *, scenario_id, call_label, config, run_id):
        return trace_export.build_rows(call, turns, vault, scenario_id=scenario_id, call_label=call_label,
                                       config=config, run_id=run_id)

    monkeypatch.setattr(calls, "trace_rows", rows)
    developer = {"Authorization": "Bearer local-developer-change-me"}
    query = "scenario_id=SAMPLE-01&call=call_2&config=baseline_no_memory&run_id=r1"
    body = client.get(f"/api/developer/calls/7/trace?{query}", headers=developer).json()
    assert body["schema_errors"] == {} and len(body["rows"]) == 3
    assert {r["config"] for r in body["rows"]} == {"baseline_no_memory"}
    lines = client.get(f"/api/developer/calls/7/trace?{query}&format=jsonl", headers=developer).text.splitlines()
    assert [json.loads(l)["turn"] for l in lines] == [1, 2, 3]
    assert client.get(f"/api/developer/calls/7/trace?{query}").status_code == 401
