"""Revision r1 of data/test's labels: the fixes of data/dev's revision r4, carried over, every change recorded.

Run from the repository root:  python evaluation/datasets/ground-truth-review/build_test_r1.py
It starts from the labels at SOURCE_REF and replaces the label folders of data/test, as build_dev_r4.py does for data/dev.

data/test is a regeneration of the first 50 SCN-ADV and 49 SCN-GEN scenarios of data/dev: same ids, customers, personas
and call plans, the customer's words written again. So the faults of dev-r4 recur, but at other words: a dev-r4 list
of ids cannot be copied. Two kinds of change, kept apart in the report (SKILL.md of this folder):

- rule_from "dev-r4 group N", decision "revise": a group the reviewer approved on dev whose rule decides it from the
  data alone and reproduces the approved dev list exactly (groups 5 and 9), or is a fixed format rule (the format part
  of 11, and 12). The reviewer asked on 2026-11-08 to apply dev-r4's fixes to the test set.
- proposed_by "claude", decision "pending": a change Claude proposes after reading the test set's own sentences, as
  was done for dev (groups 1, 2, 3, 4, 7, 8, 10 and the meaning part of 11). The reviewer has not decided these.

Only the label folders of data/test change. official_gt_approved stays false.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
#: The last commit of data/test before this revision.
SOURCE_REF = "cfb43fbb"
DEST = ROOT / "data" / "test"
SRC = DEST  # set by main()
OUT = ROOT / "data" / ".build" / "test"
BTC = ROOT / "apps" / "ai-agent-service" / "data" / "btc"
REVIEWER = "dngan0365"
DAY = "2026-11-08"
SOURCE = "Các nhóm sửa của data/dev-r4 (08/11/2026), áp sang data/test theo yêu cầu của người duyệt"
HAND_WRITTEN = ("DISPUTES.md",)
#: The reviewer's notes live in git beside this script (data/test-r*/ is not in git); a build copies them in.
NOTES = HERE / "notes" / "test"
#: The reviewer accepted every row of "Đã sửa, chờ duyệt (đề xuất của Claude)" in DISPUTES.md. None: they stay pending.
CLAUDE_PROPOSALS_REVIEWED: str | None = "2026-11-08"

# The dev-r4 builder: its helpers and the format rules of group 11.
_spec = importlib.util.spec_from_file_location("build_dev_r4", HERE / "build_dev_r4.py")
r4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r4)
ref, calls, plain, as_anh = r4.ref, r4.calls, r4.plain, r4.as_anh

changes: list[dict] = []
disputed: dict[str, str] = {}


def by_rule(sid, call, field, source, proposed, evidence, group):
    changes.append({"scenario_id": sid, "call": call, "field": field, "source": source, "proposed": proposed,
                    "evidence": evidence, "group": group, "rule_from": f"dev-r4 nhóm {group}", "reviewer": REVIEWER,
                    "proposed_by": None, "decision": "revise"})


def claude_status() -> dict:
    """A proposal Claude made after reading the test set: pending, or reviewed once CLAUDE_PROPOSALS_REVIEWED is set."""
    if CLAUDE_PROPOSALS_REVIEWED:
        return {"reviewer": REVIEWER, "proposed_by": "claude", "decision": "revise", "reviewed_on": CLAUDE_PROPOSALS_REVIEWED}
    return {"reviewer": None, "proposed_by": "claude", "decision": "pending"}


def proposed(sid, call, field, source, new, evidence, group):
    changes.append({"scenario_id": sid, "call": call, "field": field, "source": source, "proposed": new,
                    "evidence": evidence, "group": group, "rule_from": f"dev-r4 nhóm {group}", **claude_status()})


# ── Read in the test set's own sentences (Claude's proposals) ────────────────────────────────────────────────
#: Group 1: chat calls whose channel id is not in the CRM, the customer never reads their number, and a later call
#: needs to know them (the same seven ids the reviewer approved on dev).
G1 = calls("ADV-0049/c1, GEN-0011/c1, GEN-0027/c1, GEN-0030/c1, GEN-0030/c2, GEN-0043/c1, GEN-0046/c2")
G1_ANON = calls("ADV-0050/c1")
#: Group 7: hotline calls where the customer reads a CCCD number, not their phone.
G7_HOTLINE = calls("GEN-0021/c2, GEN-0037/c2")
#: Group 2: an order looked up or changed whose product is not the one the customer owns.
G2 = calls("ADV-0016/c1, ADV-0048/c1, GEN-0019/c1, GEN-0019/c2, GEN-0035/c1, GEN-0035/c2")
#: Group 3: over the COD limit, payment by transfer, but the customer only asks for COD.
G3 = calls("GEN-0017/c2, GEN-0033/c2")
#: Group 4: the last words are not a decision to buy today.
G4 = {ref("ADV-0023/c1"): "\"Chị đang chờ cuối tháng nhận lương thì mới chốt được đơn…\", blocker \"chờ cuối tháng nhận lương\"",
      ref("ADV-0028/c1"): "\"Thế chị sẽ suy nghĩ thêm rồi chốt đơn nhé.\""}
#: Group 8: (label, the number the customer said).
G8 = {ref(k): v for k, v in {"ADV-0046/c1": (8500000, 8000000), "GEN-0010/c1": (8500000, 8000000),
                            "GEN-0036/c2": (8100000, 8500000), "GEN-0049/c1": (8500000, 8000000),
                            "GEN-0049/c2": (8500000, 8000000)}.items()}
#: A budget the customer never states in the call (as SCN-GEN-0083/call_1 of dev): left for the reviewer.
BUDGET_NOT_SAID = calls("ADV-0012/c1, ADV-0013/c1, ADV-0014/c1, ADV-0020/c1, ADV-0022/c1, ADV-0025/c1, ADV-0026/c1, "
                        "ADV-0028/c1, ADV-0031/c1, ADV-0034/c2, ADV-0037/c1, ADV-0044/c1, ADV-0045/c1, GEN-0003/c1, "
                        "GEN-0004/c2, GEN-0005/c2, GEN-0015/c1, GEN-0025/c1, GEN-0031/c2, GEN-0044/c1, GEN-0047/c2")
#: Group 10: what the customer calls themselves, to match the label "anh".
G10 = {"SCN-ADV-0021": "co"}

#: Group 14 for test-r1, read by hand.
G14 = {
    "ADV-0010/c1": "room_area_m2 has_children",
    "ADV-0012/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0013/c1": "budget_vnd",
    "ADV-0014/c1": "budget_vnd",
    "ADV-0020/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0022/c1": "budget_vnd",
    "ADV-0025/c1": "budget_vnd",
    "ADV-0026/c1": "room_area_m2 has_children budget_vnd",
    "ADV-0028/c1": "budget_vnd",
    "ADV-0031/c1": "budget_vnd",
    "ADV-0034/c2": "child_age_months budget_vnd",
    "ADV-0037/c1": "budget_vnd",
    "ADV-0044/c1": "child_age_months budget_vnd",
    "ADV-0045/c1": "budget_vnd",
    "ADV-0046/c1": "room_area_m2 has_children",
    "GEN-0003/c1": "budget_vnd",
    "GEN-0004/c2": "room_area_m2",
    "GEN-0007/c1": "has_children",
    "GEN-0009/c1": "child_age_months",
    "GEN-0010/c1": "has_children",
    "GEN-0015/c1": "budget_vnd",
    "GEN-0025/c1": "budget_vnd",
    "GEN-0029/c1": "has_children",
    "GEN-0039/c1": "has_children",
    "GEN-0044/c1": "budget_vnd",
    "GEN-0048/c1": "has_children",
    "GEN-0050/c1": "child_age_months",
}
#: Group 15: order.create is required, but no customer line says yes (data/dev had these added before r3).
G15 = calls("ADV-0006/c2, ADV-0013/c1, ADV-0038/c2, ADV-0045/c1, GEN-0015/c2, GEN-0027/c2, GEN-0033/c2, GEN-0042/c3")

# Group 11, meaning part (asr_reference): read line by line.
PROMO_EXPIRY_NOT = {"SCN-ADV-0022-call_1-t3": "ngày sale 11/11 bắt đầu", "SCN-GEN-0006-call_1-t4": "lịch gọi lại",
                    "SCN-GEN-0010-call_3-t4": "ngày có hàng", "SCN-GEN-0012-call_1-t4": "lịch gọi lại"}
PHONE_NOT = {"SCN-GEN-0037-call_2-t3": "số CCCD"}
MONEY = {
    ("SCN-ADV-0004-call_2-t4", "competitor_price_vnd"): "price_vnd",  # "xác nhận lại giá là ..."
    ("SCN-ADV-0011-call_1-t4", "competitor_price_vnd"): None,         # "chị mua cái này giá ...": a past purchase
    ("SCN-ADV-0014-call_1-t2", "competitor_price_vnd"): "price_vnd",  # "chị đã xem giá là ... đúng không"
    ("SCN-ADV-0021-call_2-t2", "competitor_price_vnd"): "price_vnd",  # "cô nhớ là giá khoảng ... đúng không"
    ("SCN-ADV-0026-call_2-t4", "budget_vnd"): "price_vnd",            # "chị đồng ý với giá ..."
    ("SCN-ADV-0038-call_1-t3", "competitor_price_vnd"): None,         # "em nói nồi phi líp giá ...": already price_vnd
    ("SCN-GEN-0008-call_1-t3", "competitor_price_vnd"): "price_vnd",  # "giá là ... đúng không em"
    ("SCN-GEN-0014-call_3-t3", "competitor_price_vnd"): "price_vnd",  # "hôm trước em nói giá là ..."
    ("SCN-GEN-0030-call_2-t2", "competitor_price_vnd"): "price_vnd",  # the shop's Zalo
    ("SCN-GEN-0030-call_3-t3", "competitor_price_vnd"): "price_vnd",  # the shop's website
}
BLOCKER = {
    **{k: None for k in """SCN-ADV-0006-call_1-t2 SCN-ADV-0015-call_2-t2 SCN-ADV-0038-call_1-t3 SCN-ADV-0043-call_1-t4
    SCN-ADV-0043-call_1-t5 SCN-GEN-0008-call_2-t1 SCN-GEN-0012-call_2-t4 SCN-GEN-0017-call_2-t6 SCN-GEN-0018-call_2-t3
    SCN-GEN-0026-call_3-t4 SCN-GEN-0028-call_2-t4 SCN-GEN-0033-call_2-t7 SCN-GEN-0036-call_1-t4
    SCN-GEN-0038-call_2-t3""".split()},
    "SCN-GEN-0007-call_1-t4": "so sanh gia",  # "ngân sách 5 triệu nhưng giá này cao hơn chỗ khác": not over budget
}
BLOCKER_WHY = {
    "SCN-ADV-0006-call_1-t2": "khách nhờ so sánh hai máy, không nêu lý do chưa mua",
    "SCN-ADV-0015-call_2-t2": "hỏi trả góp", "SCN-ADV-0038-call_1-t3": "hỏi điểm khác nhau giữa hai nồi",
    "SCN-ADV-0043-call_1-t4": "xin trả hàng", "SCN-ADV-0043-call_1-t5": "xin trả hàng",
    "SCN-GEN-0008-call_2-t1": "xin đổi size", "SCN-GEN-0012-call_2-t4": "không nêu lý do (không nhắc người nhà)",
    "SCN-GEN-0017-call_2-t6": "câu nói ngân sách mới", "SCN-GEN-0018-call_2-t3": "hết hàng, không phải cần suy nghĩ",
    "SCN-GEN-0026-call_3-t4": "không nêu lý do", "SCN-GEN-0028-call_2-t4": "đồng ý chuyển máy",
    "SCN-GEN-0033-call_2-t7": "câu nói ngân sách mới", "SCN-GEN-0036-call_1-t4": "câu nói ngân sách",
    "SCN-GEN-0038-call_2-t3": "hẹn giờ gọi lại", "SCN-GEN-0007-call_1-t4": "giá cao hơn chỗ khác: so sánh giá",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_text(c: dict, index: int, new: str) -> None:
    c["customer_turns"][index] = new
    if c.get("customer_turns_asr"):
        c["customer_turns_asr"][index] = plain(new)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="accepted for old commands; every run rebuilds")
    parser.parse_args()
    global SRC
    SRC = r4.source_tree("test", SOURCE_REF)
    kept: dict[str, str] = {}
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "scenarios").mkdir(parents=True)
    for folder in ("metadata", "asr_reference", "tools", "call_brief", "handoff_brief"):
        shutil.copytree(SRC / folder, OUT / folder)
    for name, text in kept.items():
        (OUT / name).write_text(text, encoding="utf-8")
    for name in HAND_WRITTEN:  # the notes in git win over a kept copy; byte for byte
        if (NOTES / name).exists():
            shutil.copyfile(NOTES / name, OUT / name)
    scenarios = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((SRC / "scenarios").glob("*.json"))}
    source_sha = {p.name: sha(p) for p in sorted((SRC / "scenarios").glob("*.json"))}

    def call(sid, name):
        return scenarios[sid]["calls"][name]

    tool =lambda c: (c.get("success_if") or {}).get("tool_called")  # noqa: E731

    # ── by rule ────────────────────────────────────────────────────────────────────────────────────────────
    # Group 5: an order looked up or changed needs no room area or blocker.
    for sid, s in scenarios.items():
        for name, c in s["calls"].items():
            slots = {"room_area_m2", "blocker"} & set(c.get("must_carry_over") or [])
            if tool(c) in ("order.status", "order.update") and slots:
                before = list(c["must_carry_over"])
                c["must_carry_over"] = [x for x in before if x not in slots]
                by_rule(sid, name, "must_carry_over", before, c["must_carry_over"], f"{SOURCE}. Nhóm 5: cuộc {tool(c)} "
                        f"không cần {', '.join(sorted(slots))}. Quy tắc tái tạo đúng 22/22 mục đã duyệt ở dev.", 5)

    # Group 9: promo_active means a discount or a gift; freeship and COD-0 are not.
    promotions = json.loads((BTC / "catalog" / "promotions.json").read_text(encoding="utf-8"))
    kinds = {p["promo_code"]: p["type"] for p in promotions.get("promotions", promotions)}
    for sid, s in scenarios.items():
        for name, c in s["calls"].items():
            g = c.get("ground_truth_facts") or {}
            active = [k[6:-7] for k, v in g.items() if k.startswith("promo_") and k.endswith("_active") and k != "promo_active" and v is True]
            if g.get("promo_active") is True and active and all(kinds.get(a) in r4.NOT_A_PROMOTION for a in active):
                g["promo_active"] = False
                by_rule(sid, name, "ground_truth_facts.promo_active", True, False, f"{SOURCE}. Nhóm 9: chỉ có "
                        f"{', '.join(f'{a} ({kinds[a]})' for a in active)}. Quy tắc tái tạo đúng 130/130 mục đã duyệt ở dev.", 9)

    # Group 12: where each scenario's customer comes from.
    btc_phones = {c.get("phone") for c in json.loads((BTC / "catalog" / "crm_seed.json").read_text(encoding="utf-8"))["customers"]}
    for path in sorted((OUT / "metadata").glob("*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta["tags"] = sorted({*meta.get("tags", []), "source:btc" if scenarios[path.stem]["customer_phone"] in btc_phones else "source:team"})
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    by_rule("*", "*", "metadata.tags", None, "source:btc | source:team", f"{SOURCE}. Nhóm 12.", 12)

    # ── read (pending) ────────────────────────────────────────────────────────────────────────────────────
    for sid, name in G1:
        s, c = scenarios[sid], call(sid, name)
        assert c.get("channel") in ("chat_fanpage", "zalo_oa"), (sid, name)
        line = f"Số {s['honorific']} là {s['customer_phone']}."
        old = c["customer_turns"][-1]
        set_text(c, len(c["customer_turns"]) - 1, f"{old.rstrip()} {line}")
        proposed(sid, name, "customer_turns[-1]", old, c["customer_turns"][-1], f"{SOURCE}. Nhóm 1: kênh {c['channel']} "
                 f"mã {c.get('channel_identity')} không có trong CRM, khách không đọc SĐT, cuộc sau cần biết khách.", 1)
        if (c.get("facts_established") or {}).get("phone_provided") is not True:
            proposed(sid, name, "facts_established.phone_provided", (c.get("facts_established") or {}).get("phone_provided"),
                     True, "Khách đọc SĐT ở lượt vừa thêm.", 1)
            c.setdefault("facts_established", {})["phone_provided"] = True
    for sid, name in G1_ANON:
        disputed[f"{sid}/{name}"] = "Nhóm 1: khách ẩn danh có chủ đích (fb.anon), giữ lời thoại như dev-r4."

    for sid, name in G7_HOTLINE:
        c = call(sid, name)
        for key in ("facts_established", "memory_expectation"):
            if (c.get(key) or {}).get("phone_provided") is not None:
                proposed(sid, name, f"{key}.phone_provided", c[key]["phone_provided"], "<bỏ>", f"{SOURCE}. Nhóm 7: khách "
                         "đọc số CCCD, không đọc SĐT của mình.", 7)
                del c[key]["phone_provided"]
                if not c[key]:
                    del c[key]

    for sid, name in G2:
        c = call(sid, name)
        before = list(c["must_carry_over"])
        c["must_carry_over"] = [x for x in before if x != "owned_sku"]
        proposed(sid, name, "must_carry_over", before, c["must_carry_over"], f"{SOURCE}. Nhóm 2: cuộc {tool(c)} về một đơn "
                 "khác món khách đã mua (lịch sử CRM).", 2)

    for sid, name in G3:
        s, c = scenarios[sid], call(sid, name)
        index = max(i for i, t in enumerate(c["customer_turns"]) if r4.COD_WORDS.search(t))
        line = f"Vậy {s['honorific']} chuyển khoản nhé."
        c["customer_turns"].insert(index + 1, line)
        if c.get("customer_turns_asr"):
            c["customer_turns_asr"].insert(index + 1, plain(line))
        proposed(sid, name, f"customer_turns[{index + 1}]", "<không có>", line, f"{SOURCE}. Nhóm 3: cod_allowed false, đơn "
                 f"chuyển khoản, khách chỉ đòi COD (\"{c['customer_turns'][index]}\").", 3)

    for (sid, name), why in G4.items():
        c = call(sid, name)
        new = {"tool_called": None, "must_not_call_tools": ["order.create"],
               **{k: v for k, v in c["success_if"].items() if k in ("forbidden_claims", "must_say_any", "max_agent_questions")}}
        proposed(sid, name, "success_if", c["success_if"], new, f"{SOURCE}. Nhóm 4: câu cuối {why}: khách chưa đặt hôm nay.", 4)
        proposed(sid, name, "expected_outcome", c["expected_outcome"], "hen_goi_lai", "Cùng lý do.", 4)
        c["success_if"], c["expected_outcome"] = new, "hen_goi_lai"
        for key in ("facts_established", "memory_expectation", "ground_truth_facts"):
            if "order_id" in (c.get(key) or {}):
                proposed(sid, name, f"{key}.order_id", c[key].pop("order_id"), "<bỏ>", "Không có đơn được tạo.", 4)
        tools = OUT / "tools" / f"scenarios_{sid}" / f"{name}.json"
        if tools.exists():
            planned = json.loads(tools.read_text(encoding="utf-8"))
            kept_calls = [t for t in planned if t.get("name") != "order.create"]
            if kept_calls != planned:
                tools.write_text(json.dumps(kept_calls, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                proposed(sid, name, "tools (oracle)", [t["name"] for t in planned], [t["name"] for t in kept_calls],
                         "Agent lý tưởng không tạo đơn khi khách chưa quyết.", 4)

    for (sid, name), (old, new) in G8.items():
        c = call(sid, name)
        said = next(t for t in c["customer_turns"] if "triệu" in t and ("ngân sách" in t or "8 triệu" in t))
        for key in ("facts_established", "memory_expectation"):
            if (c.get(key) or {}).get("budget_vnd") == old:
                c[key]["budget_vnd"] = new
                proposed(sid, name, f"{key}.budget_vnd", old, new, f"{SOURCE}. Nhóm 8: khách nói \"{said}\".", 8)
    for sid, name in BUDGET_NOT_SAID:
        disputed[f"{sid}/{name}"] = ("budget_vnd có trong nhãn nhưng khách không nói ngân sách trong cuộc này (như "
                                     "SCN-GEN-0083/call_1 của dev); chưa sửa vì must_not_ask của cuộc sau có thể dựa vào nó.")

    for sid, who in G10.items():
        for name, c in scenarios[sid]["calls"].items():
            for i, old in enumerate(list(c["customer_turns"])):
                new = as_anh(old, who)
                if new != old:
                    set_text(c, i, new)
                    proposed(sid, name, f"customer_turns[{i}]", old, new, f"{SOURCE}. Nhóm 10: nhãn và CRM là \"anh\" "
                             f"({scenarios[sid]['customer_name']}), khách tự xưng \"cô\".", 10)
            for key in ("facts_established", "memory_expectation"):
                if (c.get(key) or {}).get("blocker") == "cần hỏi con cháu":
                    c[key]["blocker"] = "cần hỏi người nhà"
                    proposed(sid, name, f"{key}.blocker", "cần hỏi con cháu", "cần hỏi người nhà",
                             "Nhóm 10: lời khách đổi \"con cháu\" thành \"người nhà\".", 10)

    def add_action(sid, name, field, source, new, evidence, group):
        changes.append({"scenario_id": sid, "call": name, "field": field, "source": source, "proposed": new,
                        "evidence": evidence, "group": group, **r4.status_action()})

    r4.apply_actions(scenarios, OUT, add_action, "test")
    r4.apply_g26(scenarios, lambda sid, name, field, source, new, evidence: changes.append({
        "scenario_id": sid, "call": name, "field": field, "source": source, "proposed": new, "evidence": evidence,
        "group": 26, "rule_from": "dev-r4 nhóm 26", "reviewer": REVIEWER, "proposed_by": None, "decision": "revise"}))

    def add_new(sid, name, field, source, new, evidence, group=14):
        changes.append({"scenario_id": sid, "call": name, "field": field, "source": source, "proposed": new,
                        "evidence": evidence, "group": group, **r4.status_new()})

    r4.add_stated_facts(scenarios, G14, add_new)
    r4.apply_anon_and_owned(scenarios, r4.G17, r4.G18, add_new)
    for sid, name in G15:
        s, c = scenarios[sid], call(sid, name)
        line = f"Đúng rồi em, lên đơn giúp {s['honorific']} nhé."
        c["customer_turns"].append(line)
        if c.get("customer_turns_asr"):
            c["customer_turns_asr"].append(plain(line))
        add_new(sid, name, f"customer_turns[{len(c['customer_turns']) - 1}]", "<không có>", line,
                f"{r4.NEW_SOURCE}, nhóm 15: success_if đòi order.create nhưng hai lượt cuối không có lời đồng ý "
                f"(\"{c['customer_turns'][-2]}\"); PB-09 đọc lại đơn rồi chờ khách xác nhận.", 15)

    disputed["SCN-ADV-0045/call_1"] = ("Khách nói đã mua AirPure Pro, nhưng lịch sử CRM (seed_history) là nồi chiên "
                                       "Lock&Lock 4L; owned_sku trong must_carry_over chưa rõ là món nào.")
    for sid, s in scenarios.items():
        (OUT / "scenarios" / f"{sid}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    asr_changes = relabel_asr()
    report = {"revision": "test-r1", "source": "test", "built_by": "evaluation/datasets/ground-truth-review/build_test_r1.py",
              "official_gt_approved": False,
              "reviewer": {"name": REVIEWER, "date": DAY, "scope": "Yêu cầu áp các nhóm sửa của dev-r4 sang tập test. "
                           "Mục có rule_from và decision revise: quy tắc đã duyệt ở dev, tái tạo đúng danh sách dev "
                           "(nhóm 5, 9) hoặc là quy tắc định dạng (phần định dạng của 11, nhóm 12). Mục proposed_by "
                           "claude: Claude đề xuất sau khi đọc câu của tập test"
                           + (f"; người duyệt chấp nhận cả bảng ngày {CLAUDE_PROPOSALS_REVIEWED}."
                              if CLAUDE_PROPOSALS_REVIEWED else ", chờ duyệt.")},
              "source_scenario_sha256": source_sha, "changes": changes + asr_changes, "disputed": disputed}
    (OUT / "conversion-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    r4.install(OUT, DEST)
    counts: dict = {}
    for item in report["changes"]:
        counts[f"{item['group']}/{item['decision']}"] = counts.get(f"{item['group']}/{item['decision']}", 0) + 1
    print(json.dumps(dict(sorted(counts.items())), ensure_ascii=False))
    return 0


def relabel_asr() -> list[dict]:
    """Group 11 on asr_reference: ground_truth.json and the per-call files it is built from."""
    out: list[dict] = []
    path = OUT / "asr_reference" / "ground_truth.json"
    truth = json.loads(path.read_text(encoding="utf-8"))
    timeline = json.dumps(json.loads((BTC / "catalog" / "inventory_timeline.json").read_text(encoding="utf-8")))
    per_call: dict[Path, dict] = {}

    def turn_file(key: str):
        sid, call, t = re.match(r"(SCN-\w+-\d+)-(call_\d+)-t(\d+)$", key).groups()
        file = OUT / "asr_reference" / f"scenarios_{sid}" / f"{call}.json"
        if not file.exists():
            return {"entities": {}}
        if file not in per_call:
            per_call[file] = json.loads(file.read_text(encoding="utf-8"))
        return next((x for x in per_call[file]["turns"] if x["idx"] == int(t)), {"entities": {}})

    def change(d, field, new, why, rule, rename=None):
        old = d["entities"][field]
        for entities in (d["entities"], d["turns"][0]["entities"], turn_file(d["id"])["entities"]):
            if entities.get(field) != old:
                continue
            del entities[field]
            if new is not None:
                entities[rename or field] = new
        item = {"scenario_id": d["id"], "call": "asr_reference", "field": f"entities.{field}", "source": old,
                "proposed": "<bỏ>" if new is None else ({rename: new} if rename else new),
                "evidence": f"{SOURCE}. Nhóm 11: \"{d['full_text'][:160]}\". {why}", "group": 11, "rule_from": "dev-r4 nhóm 11"}
        item.update({"reviewer": REVIEWER, "proposed_by": None, "decision": "revise"} if rule else claude_status())
        out.append(item)

    for d in truth["dialogues"]:
        e = d["entities"]
        # format (by rule)
        if e.get("color") in r4.COLOR:
            change(d, "color", r4.COLOR[e["color"]], "Không dấu, như catalog; \"màu này\" không phải một màu.", True)
        if isinstance(e.get("order_id"), str) and e["order_id"] != e["order_id"].upper():
            change(d, "order_id", e["order_id"].upper(), "Mã đơn viết hoa như tool trả.", True)
        for field in ("size_new", "size_old"):
            value = e.get(field)
            if isinstance(value, str):
                fixed = r4.SIZE_WORDS.get(value, value.upper())
                if fixed != value:
                    change(d, field, fixed, "Size số bằng chữ số, size chữ viết hoa như catalog.", True)
        if isinstance(e.get("restock_date"), str) and e["restock_date"].startswith("2024-"):
            fixed = "2026" + e["restock_date"][4:]
            if fixed in timeline:
                change(d, "restock_date", fixed, "Năm theo inventory_timeline.json.", True)
        # meaning (read, pending)
        if d["id"] in PROMO_EXPIRY_NOT and "promo_expiry" in e:
            change(d, "promo_expiry", None, f"Câu nói {PROMO_EXPIRY_NOT[d['id']]}, không nói hạn khuyến mãi (đề xuất của Claude).", False)
        if d["id"] in PHONE_NOT and "phone" in e:
            change(d, "phone", None, f"Là {PHONE_NOT[d['id']]}, không phải SĐT liên hệ; entity_schema không có id_number (đề xuất của Claude).", False)
        for field in ("budget_vnd", "competitor_price_vnd", "price_vnd"):
            if (d["id"], field) in MONEY and field in e:
                target = MONEY[(d["id"], field)]
                if target and target in e:
                    change(d, field, None, f"Đã có {target}; nhãn trùng (đề xuất của Claude).", False)
                elif target:
                    change(d, field, e[field], "Giá shop báo, khách nhắc lại (đề xuất của Claude).", False, rename=target)
                else:
                    change(d, field, None, "Giá đã mua hoặc trùng với price_vnd: không có trường tương ứng (đề xuất của Claude).", False)
        if d["id"] in BLOCKER and "blocker" in e:
            change(d, "blocker", BLOCKER[d["id"]], f"Đọc câu: {BLOCKER_WHY[d['id']]} (đề xuất của Claude).", False)
    path.write_text(json.dumps(truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for file, data in per_call.items():
        file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.exit(main())
