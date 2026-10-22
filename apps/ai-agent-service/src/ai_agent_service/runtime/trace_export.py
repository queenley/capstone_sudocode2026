"""A stored call as the organisers' trace: ``schemas/trace_log.schema.json`` rows.

``eval/reference_eval.py`` scores JSONL lines, one per customer turn, keyed by
``(scenario_id, call)``. The agent already keeps everything a line needs in
``agent.turns`` (text, tool calls with arguments and results, latency, the
brief lines a reply used, the input mode) and, once the call is remembered,
``calls.after_call.memory_writes``. This module only reshapes it; scenario
labels (``scenario_id``, ``call``, ``config``, ``run_id``) come from whoever
drove the call.

Two fields are not stored and are extracted from the agent's words here, by
rules, as the schema leaves to the team (and the report must describe):

- ``questions``: each sentence ending in "?" that asks about a known slot
  (``SLOT_CUES``); ``confirm`` when it seeks agreement ("đúng không", "vẫn ...
  ạ?"), else ``open``.
- ``claims``: checkable statements with the organisers' field names: prices
  (``price_vnd``, ``list_price_vnd``), promotions (``promo_<CODE>_active``,
  ``promo_active``), stock, delivery days, warranty, return window, exchange
  fee, free shipping, restock date, and ``is_human``.

``facts_used`` are the ledger slots behind the brief lines the reply cited,
plus any brief fact whose value the reply repeats.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping, Sequence
from ..components.memory.brief import used_slots

from ..components.intake import pii
from ..components.intake.itn import money_spans
from ..mcp.client import dotted

#: A sentence ends at . ! ? … followed by a space or the end: "5.200.000đ" is one number, not three sentences.
SENTENCE = re.compile(r".+?(?:[.!?…]+(?=\s|$)|$)", re.S)

#: Slot -> what an agent's question about it sounds like.
SLOT_CUES: dict[str, re.Pattern[str]] = {
    # A confirm question states the value ("phòng 25 m² đúng không ạ?"), an
    # open one asks for it; both shapes are cues.
    "room_area_m2": re.compile(r"(diện tích|bao nhiêu (m2|m²|mét)|mét vuông|phòng .*rộng|\d+\s*(m2|m²))", re.I),
    "budget_vnd": re.compile(r"(ngân sách|tầm giá|khoảng bao nhiêu tiền|dự định chi)", re.I),
    "has_children": re.compile(r"(có (bé|trẻ|con)( nhỏ)?|trẻ nhỏ)", re.I),
    "child_age_months": re.compile(r"(bé|con) (mấy|bao nhiêu) (tháng|tuổi)", re.I),
    "size": re.compile(r"(\bsize\b|\bcỡ\b|số giày)", re.I),
    "color": re.compile(r"\bmàu\b", re.I),
    "quantity": re.compile(r"(mấy (cái|đôi|chiếc|bộ|hộp)|số lượng)", re.I),
    "payment": re.compile(r"(thanh toán|\bcod\b|chuyển khoản)", re.I),
    "delivery_area": re.compile(r"(giao (về|tới|đến) (đâu|khu vực nào)|khu vực|địa chỉ giao)", re.I),
    "phone_provided": re.compile(r"số điện thoại", re.I),
    "order_id": re.compile(r"mã đơn", re.I),
    "product_advised": re.compile(r"((mẫu|sản phẩm|máy|loại) nào|quan tâm (mẫu|sản phẩm|máy))", re.I),
    "usage_need": re.compile(r"(dùng (để|cho) (gì|việc gì)|mục đích)", re.I),
    "callback_time": re.compile(r"gọi lại (lúc|vào) (mấy giờ|khi nào|lúc nào)", re.I),
    "decision_maker": re.compile(r"(hỏi ý kiến|ai quyết định|người nhà)", re.I),
    "competitor_price_vnd": re.compile(r"bên (kia|khác) (bán|báo|để) (giá )?bao nhiêu", re.I),
    "price_quoted_vnd": re.compile(r"giá (đã báo|hôm trước|lần trước)", re.I),
}
CONFIRM = re.compile(
    r"(đúng không|phải không|đúng chứ|có phải|vẫn .+ (ạ|chứ|nhỉ|nhé)\s*\?|như hôm trước|như lần trước|nhỉ\s*\?)", re.I
)

PRICE_CUE = re.compile(r"(giá|chỉ còn|còn|là|hết)", re.I)
#: An order total is not a unit price: its own field, scored only where a scenario names it.
TOTAL_CUE = re.compile(r"(tổng|thành tiền|cả đơn)", re.I)
LIST_PRICE_CUE = re.compile(r"(giá gốc|giá niêm yết|giá thường|giá chưa giảm)", re.I)
NOT_A_PRICE = re.compile(r"(ngân sách|tiết kiệm|giảm|bớt|phí|cọc|tối đa|giới hạn|hạn mức|bên (kia|khác))", re.I)
PROMO_CODE = re.compile(r"\b([A-Z]{2,}(?:-[A-Z0-9]+)+)\b")
PROMO_OFF = re.compile(r"(hết hạn|không còn|không áp dụng|đã kết thúc|hết hiệu lực|không được áp dụng)", re.I)
PROMO_ON = re.compile(r"(đang có (chương trình )?khuyến mãi|đang (được )?giảm|có ưu đãi)", re.I)
PROMO_NONE = re.compile(r"(không có (chương trình )?khuyến mãi|chưa có khuyến mãi)", re.I)
OUT_OF_STOCK = re.compile(r"(hết hàng|tạm hết|không còn hàng|chưa có hàng)", re.I)
IN_STOCK = re.compile(r"(còn hàng|có sẵn|sẵn hàng|còn \d+ (cái|chiếc|đôi|máy|sản phẩm))", re.I)
DELIVERY = re.compile(r"giao(?: hàng)?(?: trong| khoảng| mất| từ)? (\d+)(?:\s*[-–]\s*(\d+))? ngày", re.I)
WARRANTY = re.compile(r"bảo hành (\d+) (tháng|năm)", re.I)
RETURN = re.compile(r"(?:đổi trả|đổi hàng|trả hàng)[^.?!]*?(\d+) ngày|(\d+) ngày (?:đổi trả|đổi hàng)", re.I)
EXCHANGE_FEE = re.compile(r"phí đổi", re.I)
FREE_EXCHANGE = re.compile(r"(miễn phí|không mất phí|không tính phí|(?<![\d.])0\s*đ)", re.I)
FREESHIP = re.compile(r"(miễn phí (vận chuyển|giao hàng|ship)|freeship)", re.I)
RESTOCK = re.compile(r"(?:về hàng|có hàng lại|nhập về|có lại)[^.?!]*?(\d{1,2})/(\d{1,2})", re.I)
HUMAN = re.compile(r"(em là người thật|không phải (là )?(máy|robot|bot|AI))", re.I)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE.findall(text or "") if s.strip()]


def extract_questions(text: str) -> list[dict[str, str]]:
    questions = []
    for sentence in sentences(text):
        if not sentence.endswith("?"):
            continue
        kind = "confirm" if CONFIRM.search(sentence) else "open"
        for slot, cue in SLOT_CUES.items():
            if cue.search(sentence):
                questions.append({"slot": slot, "type": kind, "text": sentence})
                break
    return questions


def extract_claims(text: str, *, year: int = 2026) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []

    def add(field: str, value: Any, sentence: str) -> None:
        if not any(c["field"] == field and c["value"] == value for c in claims):
            claims.append({"field": field, "value": value, "text": sentence})

    for sentence in sentences(text):
        if sentence.endswith("?"):
            continue
        # Each amount is read with the words since the previous amount only:
        # in "giá gốc 5.490.000đ, hôm nay chỉ còn 4.890.000đ" the second is the price.
        start = 0
        for span in money_spans(sentence):
            at = sentence.find(span.text, start)
            before = sentence[start:at] if at >= 0 else sentence[start:]
            start = at + len(span.text) if at >= 0 else start
            if EXCHANGE_FEE.search(before):
                add("exchange_fee_vnd", span.value, sentence)
            elif LIST_PRICE_CUE.search(before):
                add("list_price_vnd", span.value, sentence)
            elif TOTAL_CUE.search(before):
                add("order_total_vnd", span.value, sentence)
            elif PRICE_CUE.search(before) and not NOT_A_PRICE.search(before):
                add("price_vnd", span.value, sentence)
        if EXCHANGE_FEE.search(sentence) and FREE_EXCHANGE.search(sentence):
            add("exchange_fee_vnd", 0, sentence)
        codes = PROMO_CODE.findall(sentence)
        for code in codes:
            add(f"promo_{code}_active", not PROMO_OFF.search(sentence), sentence)
        if not codes:
            if PROMO_NONE.search(sentence):
                add("promo_active", False, sentence)
            elif PROMO_ON.search(sentence):
                add("promo_active", True, sentence)
        if OUT_OF_STOCK.search(sentence):
            add("in_stock", False, sentence)
        elif IN_STOCK.search(sentence):
            add("in_stock", True, sentence)
        if match := DELIVERY.search(sentence):
            add("delivery_days", int(match.group(2) or match.group(1)), sentence)
        if match := WARRANTY.search(sentence):
            add("warranty_months", int(match.group(1)) * (12 if match.group(2).lower() == "năm" else 1), sentence)
        if match := RETURN.search(sentence):
            add("return_days", int(match.group(1) or match.group(2)), sentence)
        if FREESHIP.search(sentence):
            add("freeship", True, sentence)
        if match := RESTOCK.search(sentence):
            add("restock_date", f"{year}-{int(match.group(2)):02d}-{int(match.group(1)):02d}", sentence)
        if HUMAN.search(sentence):
            add("is_human", True, sentence)
    return claims


def facts_used(text: str, cited: Iterable[str], brief_lines: Sequence[Mapping[str, Any]],
               profile: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Legacy fallback: explicit cited lines only; new turns store their resolved slots."""
    return used_slots(list(cited), brief_lines, profile)


def _tool(call: Mapping[str, Any], vault: pii.Vault) -> dict[str, Any]:
    args = pii.detokenize_data(call.get("args") or {}, vault)
    envelope = call.get("result") or {}
    result = pii.detokenize_data(envelope.get("data"), vault) if envelope.get("ok") else {"error": (envelope.get("error") or {}).get("code") or "failed"}
    name = str(call.get("name") or "")
    return {"name": name if "." in name else dotted(name), "args": args, "result": result}


def build_rows(
    call: Mapping[str, Any],
    turns: Sequence[Mapping[str, Any]],
    vault: pii.Vault,
    *,
    scenario_id: str,
    call_label: str,
    config: str = "full",
    run_id: str = "run",
) -> list[dict[str, Any]]:
    """``trace_log`` rows for one stored call, one per customer turn, in order.

    ``turns`` are the call's ``agent.turns`` rows (tokenised content, meta),
    oldest first. The opening line (said before the customer spoke) joins
    the first row; a consultant's words in copilot mode are not the agent's
    and are left out.
    """
    brief_lines = list(call.get("brief") or [])
    profile = dict((call.get("brief_object") or {}).get("profile_facts") or {})
    year = int(str(call.get("business_day") or "2026")[:4])
    by_turn: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for t in turns:
        if t["speaker"] not in ("customer", "agent"):
            continue
        entry = by_turn.setdefault(t["turn_id"], {"customer": None, "agent": None})
        if t["turn_id"] not in order:
            order.append(t["turn_id"])
        entry[t["speaker"]] = t

    rows: list[dict[str, Any]] = []
    carry_text: list[str] = []
    carry_tools: list[dict[str, Any]] = []
    carry_facts: list[str] = []
    for turn_id in order:
        entry = by_turn[turn_id]
        agent = entry["agent"]
        if entry["customer"] is None:
            # The opening: no customer words, so it rides on the next row.
            if agent is not None:
                carry_text.append(pii.detokenize(agent["content"], vault))
                carry_tools += [_tool(c, vault) for c in (agent.get("meta") or {}).get("tool_calls") or []
                                if not c.get("blocked_by") and c.get("result") is not None]
                carry_facts += (agent.get("meta") or {}).get("facts_used") or []
            continue
        customer = entry["customer"]
        meta = (agent or {}).get("meta") or {}
        said = pii.detokenize(agent["content"], vault) if agent else ""
        agent_text = " ".join([*carry_text, said]).strip()
        latency = meta.get("latency") or (customer.get("meta") or {}).get("latency") or {}
        row: dict[str, Any] = {
            "run_id": run_id,
            "config": config,
            "scenario_id": scenario_id,
            "call": call_label,
            "turn": len(rows) + 1,
            "customer_text": pii.detokenize(customer["content"], vault),
            "agent_text": agent_text,
            "questions": extract_questions(agent_text),
            "facts_used": sorted(set(carry_facts + (meta["facts_used"] if "facts_used" in meta else
                facts_used(said, meta.get("used_brief_lines") or [], brief_lines, profile)))),
            "claims": extract_claims(agent_text, year=year),
            "tool_calls": carry_tools + [_tool(c, vault) for c in meta.get("tool_calls") or []
                                         if not c.get("blocked_by") and c.get("result") is not None],
            "latency": {
                "ttft_ms": int(latency.get("ttft_ms") or 0),
                "total_ms": int(latency.get("total_ms") or 0),
                "ttfa_ms": latency.get("ttfa_ms"),
            },
            "customer_input_mode": (customer.get("meta") or {}).get("input_mode") or "clean",
            "memory_writes": [],
        }
        if not rows and latency.get("call_brief_latency_ms") is not None and call_label != "call_1":
            row["call_brief_latency_ms"] = int(latency["call_brief_latency_ms"])
        rows.append(row)
        carry_text, carry_tools, carry_facts = [], [], []

    # What after_call wrote belongs to the call; it goes on its last line.
    writes = list(((call.get("after_call") or {}).get("memory_writes")) or [])
    if rows and writes:
        rows[-1]["memory_writes"] = [{k: w.get(k) for k in ("key", "value", "op", "source", "customer_id")} for w in writes]
    return rows
