"""Automatic checks on every call of data/dev or data/test, and the review sheet a person signs. Not a golden set.

Run from the repository root with evaluation/data-generation's venv, after the build scripts, mark_conversations.py
and validate_rules (reports/validation.json on the current labels):

    evaluation/data-generation/.venv/Scripts/python evaluation/datasets/ground-truth-review/auto_verify.py

Writes, for each dataset:
- review/auto_verified.json: the calls whose labels pass every check below, and the conversations also usable as
  examples. "not_golden": true. Nothing here is a person's approval.
- review/review_sheet.csv: one row per call, Claude's suggestions and why, for the labels (they decide
  official_gt_approved) and for the reference conversation (it decides golden_manifest.json), and empty approve_labels /
  approve_conversation columns for the reviewer (a rerun keeps what the reviewer wrote). approve_gold.py turns the reviewer's column into the golden manifest.

Checks (no model call; BTC's mock_tools read-only):
  keys          the scenario passes contracts/scenario/scenario-keys.yaml (src/schemas/keys.py)
  pending       no change on the call waits for the reviewer (conversion-report.json)
  grounded      the value of room_area_m2 / has_children / child_age_months / budget_vnd in facts_established is
                said by the customer in this call or an earlier one (not the CRM history, which may be stale; on a
                shared phone only this call, the earlier one being the other person's)
  consent       order.create is asked for only after a yes in the last two customer turns
  outcome       expected_outcome agrees with success_if.tool_called
  btc_facts     price_vnd, list_price_vnd, in_stock and promo_<CODE>_active agree with BTC's mock on the call's day
  callback      ground_truth_facts.callback_at equals the callback the oracle's tool call returned
  validator     the reference conversation passes validate_rules (BTC's reference_eval on the current labels)
  judge         the LLM judge passed it without asking for a person (judgments/, written before this revision)
  not_marked    the reviewer has not marked the conversation N (needs_manual_review.csv)
A failed check keeps the call out; some are known to be strict (a fact said in words: "một tháng"), so a person may
still approve it.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import re
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BTC = ROOT / "apps" / "ai-agent-service" / "data" / "btc"
sys.path.insert(0, str(ROOT / "evaluation" / "data-generation"))
from src.schemas.keys import check_scenario  # noqa: E402

DAY = date.today().isoformat()
SHEET_FIELDS = ["conversation_id", "scenario_id", "call", "suggest_labels", "why_labels", "suggest_conversation",
                "why_conversation", "approve_labels", "approve_conversation", "notes"]
_spec = importlib.util.spec_from_file_location("btc_mock_tools", BTC / "eval" / "mock_tools.py")
mock = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock)
PROMOS = {p["promo_code"]: p for p in json.loads((BTC / "catalog/promotions.json").read_text(encoding="utf-8"))["promotions"]}


def plain(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


NUMBERS = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5, "sau": 6, "bay": 7, "tam": 8, "chin": 9, "muoi": 10}
NUM = r"(\d+(?:[.,]\d+)?|(?:muoi|mot|hai|bay|bon|ba|nam|sau|tam|chin)(?![a-z]))"  # "bay" before "ba"; "12m²" stays a number
KIDS = re.compile(r"\b(co (mot |hai |ba )?(be|tre|con|chau|em nho)|be nha|be (nho|cua|\d)|con (chi|anh|em|minh|toi|nha)|"
                  r"tre nho|chau nho|cho be|cho con|(cua|phong) (con|be)\b)")
NO_KIDS = re.compile(r"\b(khong co (tre|be|con|chau)|chua co (con|be)|nha (chi|anh|co|em) khong co tre)")


def _num(word: str) -> float:
    return float(word.replace(",", ".")) if word[0].isdigit() else NUMBERS[word]


def said_values(slot: str, text: str) -> set:
    """The values of *slot* a customer's words state (plain text). A fact is grounded only when its value is here."""
    if slot == "room_area_m2":
        return {int(_num(m.group(1))) for m in re.finditer(rf"{NUM}\s*(m2|m²|met vuong|m vuong)", text)}
    if slot == "child_age_months":
        out = {int(_num(m.group(1))) for m in re.finditer(rf"{NUM}( \w+)? thang", text)}
        out |= {int(_num(m.group(1))) * 12 for m in re.finditer(rf"{NUM} tuoi", text)}
        return out | ({0, 1} if re.search(r"so sinh|moi sinh", text) else set())
    if slot == "budget_vnd":
        out = set()
        for m in re.finditer(rf"{NUM}\s*trieu(\s*(ruoi|{NUM})(\s*tram)?)?", text):
            value = _num(m.group(1)) * 1_000_000
            tail = m.group(3)
            if tail == "ruoi":
                value += 500_000
            elif tail:  # "6 triệu 2", "5 triệu bảy trăm (nghìn)", "4 triệu 890"
                value += _num(tail) * (100_000 if m.group(5) or _num(tail) < 10 else 1_000)
            out.add(int(value))
        out |= {int(m.replace(".", "")) for m in re.findall(r"\b\d{1,3}(?:\.\d{3}){2,}(?!\d)", text)}  # 4.500.000đ
        out |= {int(_num(m.group(1))) * 1000 for m in re.finditer(rf"{NUM}\s*(nghin|ngan|k)\b", text) if _num(m.group(1)) >= 100}
        return out | {int(x) for x in re.findall(r"\b\d{6,}\b", text)}
    if slot == "has_children":
        return ({True} if KIDS.search(text) else set()) | ({False} if NO_KIDS.search(text) else set())
    return set()


GROUNDED = ("room_area_m2", "has_children", "child_age_months", "budget_vnd")
YES = re.compile(r"\b(dung roi|dong y|xac nhan|chinh xac|len don|chot|dat (don|hang)|lam don|ghi don|vang|u)\b")


def call_days(scenario: dict) -> dict[str, str]:
    out, day = {}, None
    for name in sorted(scenario["calls"]):
        c = scenario["calls"][name]
        if c.get("call_date"):
            day = date.fromisoformat(c["call_date"])
        elif day is not None and c.get("days_later") is not None:
            day += timedelta(days=int(c["days_later"]))
        else:
            day = day or date(2026, 10, 15)
        out[name] = day.isoformat()
    return out


def label_checks(root: Path, scenario: dict, report_pending: set[tuple[str, str]]) -> dict[str, list[str]]:
    sid = scenario["scenario_id"]
    days = call_days(scenario)
    errors = check_scenario(scenario)
    # Two people on one phone: an earlier call is the other person's, not what this caller said.
    shared_phone = scenario.get("persona") == "hai_nguoi_chung_sdt"
    said_before = ""
    found: dict[str, list[str]] = {}
    for name in sorted(scenario["calls"]):
        c = scenario["calls"][name]
        why: list[str] = []
        why += [f"keys: {e}" for e in errors if e.startswith(f"{sid}.{name}.") or not re.match(rf"{re.escape(sid)}\.call_\d", e)]
        if (sid, name) in report_pending:
            why.append("pending: thay đổi trên cuộc này đang chờ duyệt")
        text = plain(" ".join(c.get("customer_turns") or []))
        for slot in GROUNDED:
            value = (c.get("facts_established") or {}).get(slot)
            if value is None:
                continue
            # The CRM history does not count: it may be stale (the returning customers moved house).
            heard = said_values(slot, text) | (set() if shared_phone else said_values(slot, said_before))
            if value not in heard:
                why.append(f"grounded: {slot}={value} không thấy khách nói (nghe được: {sorted(heard, key=str) or 'không'})")
        si = c.get("success_if") or {}
        tool = si.get("tool_called")
        if tool == "order.create" and not any(YES.search(plain(t)) for t in (c.get("customer_turns") or [])[-2:]):
            why.append("consent: order.create nhưng hai lượt cuối không có lời đồng ý")
        outcome = c.get("expected_outcome")
        if outcome == "chot_don" and tool != "order.create" or tool == "order.create" and outcome not in ("chot_don", None) \
                or outcome == "chuyen_may" and tool != "handoff.transfer":
            why.append(f"outcome: {outcome} với tool_called {tool}")
        g = c.get("ground_truth_facts") or {}
        tools_path = root / "tools" / f"scenarios_{sid}" / f"{name}.json"
        oracle = json.loads(tools_path.read_text(encoding="utf-8")) if tools_path.exists() else []
        quote_args = next((o.get("args") or {} for o in oracle if o["name"] == "pricing.get_quote"), {})
        sku = (si.get("args_match") or {}).get("sku") or quote_args.get("sku") or \
            (c.get("memory_expectation") or {}).get("variant_sku") or (c.get("memory_expectation") or {}).get("product_advised")
        if sku and any(k in g for k in ("price_vnd", "list_price_vnd", "in_stock")):
            q = mock.pricing_get_quote(sku, on=days[name], qty=quote_args.get("qty", 1),
                                       customer_phone=quote_args.get("customer_phone", scenario["customer_phone"]),
                                       address=quote_args.get("address"), basket_skus=quote_args.get("basket_skus"))
            if "error" not in q:
                if "price_vnd" in g and g["price_vnd"] != q["final_price_vnd"]:
                    why.append(f"btc_facts: price_vnd {g['price_vnd']} ≠ mock {q['final_price_vnd']}")
                if "list_price_vnd" in g and g["list_price_vnd"] != q["list_price_vnd"]:
                    why.append(f"btc_facts: list_price_vnd {g['list_price_vnd']} ≠ mock {q['list_price_vnd']}")
            inv = mock.inventory_check(sku, on=days[name])
            if "in_stock" in g and "in_stock" in inv and g["in_stock"] != inv["in_stock"]:
                why.append(f"btc_facts: in_stock {g['in_stock']} ≠ mock {inv['in_stock']}")
        for key, value in g.items():
            m = re.match(r"promo_(.+)_active$", key)
            if m and m.group(1) in PROMOS and value is True and not (PROMOS[m.group(1)]["start"] <= days[name] <= PROMOS[m.group(1)]["end"]):
                why.append(f"btc_facts: {key} nhưng chương trình không chạy ngày {days[name]}")
        cb = next((o for o in oracle if o["name"] == "schedule.callback"), None)
        if g.get("callback_at") and cb and cb.get("result", {}).get("callback_at") != g["callback_at"]:
            why.append(f"callback: ground_truth {g['callback_at']} ≠ kết quả tool {cb['result'].get('callback_at')}")
        found[name] = why
        said_before += " " + text
    return found


def run(name: str) -> dict[str, int]:
    root = ROOT / "data" / name
    report = json.loads((root / "conversion-report.json").read_text(encoding="utf-8"))
    pending = set()
    for ch in report["changes"]:
        if ch.get("decision") == "pending":
            m = re.match(r"(SCN-\w+-\d+)-(call_\d+)-t\d+$", ch["scenario_id"])
            pending.add((m.group(1), m.group(2)) if m else (ch["scenario_id"], ch["call"]))
    validation = {r["conversation_id"]: r for r in json.loads((root / "reports" / "validation.json").read_text(encoding="utf-8"))
                  if "conversation_id" in r}
    with (root / "review" / "needs_manual_review.csv").open(newline="", encoding="utf-8-sig") as stream:
        marked = {r["conversation_id"]: r["notes"] for r in csv.DictReader(stream) if r.get("approve", "").strip().upper() == "N"}
    sheet_path = root / "review" / "review_sheet.csv"
    previous = {}
    if sheet_path.exists():
        with sheet_path.open(newline="", encoding="utf-8-sig") as stream:
            previous = {r["conversation_id"]: r for r in csv.DictReader(stream)}

    labels_ok, usable, excluded, rows = [], [], {}, []
    for path in sorted((root / "scenarios").glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        for call, why in label_checks(root, scenario, pending).items():
            cid = f"{scenario['scenario_id']}__{call}"
            if not why:
                labels_ok.append(cid)
            conv = []
            v = validation.get(cid)
            if v is None:
                conv.append("validator: không có hội thoại mẫu")
            elif str(v.get("validator_pass")) != "True":
                conv.append(f"validator: {str(v.get('errors'))[:160]}")
            jp = root / "judgments" / f"scenarios_{scenario['scenario_id']}" / f"{call}.json"
            j = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else {}
            if not j or not j.get("overall_pass") or j.get("needs_manual_review"):
                conv.append("judge: chưa qua hoặc cần người đọc")
            if cid in marked:
                conv.append(f"not_marked: {marked[cid]}")
            if why or conv:
                excluded[cid] = why + conv
            if not why and not conv:
                usable.append(cid)
            keep = previous.get(cid, {})
            rows.append({"conversation_id": cid, "scenario_id": scenario["scenario_id"], "call": call,
                         "suggest_labels": "N" if why else "Y", "why_labels": "; ".join(why) or "qua mọi kiểm nhãn",
                         "suggest_conversation": "N" if why or conv else "Y",
                         "why_conversation": "; ".join(conv + (["nhãn chưa qua kiểm"] if why else [])) or "qua mọi kiểm",
                         "approve_labels": keep.get("approve_labels", ""), "approve_conversation": keep.get("approve_conversation", ""),
                         "notes": keep.get("notes", "")})
    out = {"kind": "auto_verified", "not_golden": True, "dataset": name, "labels_revision": report.get("revision"),
           "generated_on": DAY, "generated_by": "evaluation/datasets/ground-truth-review/auto_verify.py",
           "note": "Kiểm tự động, không phải người duyệt. Bộ vàng chỉ có khi người duyệt ký review_sheet.csv và chạy approve_gold.py.",
           "checks": ["keys", "pending", "grounded", "consent", "outcome", "btc_facts", "callback", "validator", "judge", "not_marked"],
           "calls_total": len(rows), "labels_verified": labels_ok, "conversations_usable": usable, "excluded": excluded}
    (root / "review" / "auto_verified.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with sheet_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return {"calls": len(rows), "labels_verified": len(labels_ok), "conversations_usable": len(usable), "excluded": len(excluded)}


if __name__ == "__main__":
    for dataset in sys.argv[1:] or ("dev", "test"):
        print(dataset, run(dataset))
