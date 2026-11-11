"""Only the policy in force reaches the model: filtered by the day that matters, before the top is taken."""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_agent_service.agents.advisor import shown_passages
from ai_agent_service.components.knowledge.corpus import policy_chunks
from ai_agent_service.components.knowledge.search import KnowledgeBase, stated_order_day
from ai_agent_service.pipeline.hot.nodes import _knowledge_note, _order_days, _passages

POLICY = Path(__file__).resolve().parents[2] / "apps" / "ai-agent-service" / "data" / "btc" / "policy"
AFTER = "2026-10-20"
BEFORE = "2026-09-28"


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase(policy_chunks(POLICY))


def ids(result) -> list[str]:
    return [hit.chunk.chunk_id for hit in result.hits]


@pytest.mark.parametrize("question", ["Bên em cho đổi trả trong 14 ngày đúng không?", "Hoàn tiền mất 7 ngày làm việc à?",
                                      "lỗi nhà sản xuất đổi mới trong bao lâu"])
def test_a_retired_passage_is_not_read_and_its_changelog_entry_still_comes(kb, question):
    result = kb.search(question, on=AFTER)
    assert not any(chunk_id.startswith("DT-OLD") for chunk_id in ids(result))
    assert any(chunk_id.startswith("DT-OLD") for chunk_id in result.withheld)
    assert "CL-01" in result.changelog


def test_the_advisor_reads_why_the_rule_changed_only_when_a_passage_was_withheld(kb):
    result = kb.search("hoàn tiền mất 7 ngày làm việc à", on=AFTER)
    assert "CL-01" in result.explains
    # The hits as the search ranks them, the entry last: past the three passages the model reads.
    hits = [{"chunk_id": chunk_id, "text": "x"} for chunk_id in ("DT-04", "QT-04", "QT-01", "QT-05", "CL-01")]
    found = {"hits": hits, "explains": list(result.explains), "reason": None,
             "changelog": [{"chunk_id": c.chunk_id, "title": c.title, "text": c.text} for c in result.changelog.values()]}
    read, _ = shown_passages(_passages({"knowledge": found}))
    assert [p["chunk_id"] for p in read] == ["DT-04", "QT-04", "QT-01", "CL-01"]
    assert "14 → **7 ngày**" in read[-1]["text"]
    assert "CL-01" not in [p["chunk_id"] for p in shown_passages(_passages({"knowledge": {**found, "explains": []}}))[0]]


def test_an_order_placed_before_the_change_reads_the_old_version_only(kb):
    found = ids(kb.search("đổi trả trong bao lâu", on=AFTER, order_date=BEFORE))
    assert "DT-OLD-01" in found and "DT-01" not in found


def test_without_a_day_nothing_is_filtered(kb):
    assert "DT-OLD-01" in ids(kb.search("đổi trả trong 14 ngày"))


def test_staff_rules_and_internal_notes_give_no_text_to_the_agent(kb):
    assert all(chunk.restricted for chunk in kb.chunks if chunk.doc == "noi-quy-nhan-vien.md")
    assert not any(chunk.restricted for chunk in kb.chunks if chunk.doc == "chinh-sach-doi-tra.md")


def test_a_title_alone_retires_a_document(tmp_path):
    (tmp_path / "cu.md").write_text("# Chính sách X — **HẾT HIỆU LỰC từ 01/03/2026**\n\n## [XX-01] Điều\nNội dung.\n",
                                    encoding="utf-8")
    chunk = policy_chunks(tmp_path)[0]
    assert chunk.valid_to == "2026-02-28" and not chunk.in_force("2026-03-01") and chunk.in_force("2026-02-28")


@pytest.mark.parametrize("said, day", [
    ("Đơn tạo ngày 28/09/2026, khách đòi đổi trả ngày 09/10", "2026-09-28"),
    ("em mua hôm 28/9 giờ muốn trả", "2026-09-28"),
    ("đơn đặt tháng 9/2026", "2026-09-01"),
    ("đơn giao ngày 09/10 bị lỗi", None),
    ("đơn đặt ngày 25/12", None),  # after the call: not an order placed
    ("đơn đặt ngày 31/02/2026", None),
    ("đổi trả mấy ngày", None),
])
def test_the_order_day_is_read_from_the_customers_words(said, day):
    assert stated_order_day(said, AFTER) == day


def state(*orders):
    return {"on": AFTER, "brief": {"orders": [{"order_id": o, "date": d} for o, d in orders]}}


def test_a_customer_with_orders_on_both_sides_is_asked_which_one(kb):
    two = state(("OD1", BEFORE), ("OD2", "2026-10-10"))
    assert _order_days(two, "em muốn đổi size") == ("2026-10-10", (BEFORE,))
    result = kb.search("đổi trả trong bao lâu", on=AFTER, order_date="2026-10-10", other_order_dates=[BEFORE])
    assert result.version_differs == (BEFORE,)
    assert BEFORE in _knowledge_note({"knowledge": {"version_differs": list(result.version_differs)}})


def test_a_named_order_or_a_stated_day_settles_it():
    two = state(("OD1", BEFORE), ("OD2", "2026-10-10"))
    assert _order_days(two, "đổi size đơn OD1") == (BEFORE, ())
    assert _order_days(two, "em mua hôm 28/9 muốn đổi size") == (BEFORE, ())


def test_passages_outside_the_version_do_not_raise_the_question(kb):
    result = kb.search("giới hạn COD", on=AFTER, order_date="2026-10-10", other_order_dates=[BEFORE])
    assert result.version_differs == ()


WORRY = "Chị sợ mấy năm sau máy trục trặc thì không ai lo cho."


def test_a_rule_a_published_lesson_cites_comes_along_without_changing_the_ranking_or_the_abstention(kb):
    plain, pinned = kb.search(WORRY, on=AFTER), kb.search(WORRY, on=AFTER, include=["BH-05", "BH-05", "NOT-A-RULE"])
    assert "BH-05" not in ids(plain)  # a worry does not retrieve the rule that answers it
    assert ids(pinned) == [*ids(plain), "BH-05"]
    assert (pinned.top_score, pinned.abstain, pinned.reason) == (plain.top_score, plain.abstain, plain.reason)
    ranked = ids(plain)[0]
    assert ids(kb.search(WORRY, on=AFTER, include=[ranked])) == ids(plain)  # never twice


def test_an_internal_or_retired_passage_never_comes_along(kb):
    internal = next(chunk.chunk_id for chunk in policy_chunks(POLICY) if chunk.restricted)
    retired = next(chunk.chunk_id for chunk in policy_chunks(POLICY) if not chunk.in_force(AFTER))
    assert not {internal, retired} & set(ids(kb.search(WORRY, on=AFTER, include=[internal, retired])))


def test_the_advisor_is_shown_the_cited_rule_beyond_the_three_it_reads_and_only_once(kb):
    result = kb.search(WORRY, on=AFTER, include=["BH-05"])
    assert [hit.pinned for hit in result.hits] == [False] * (len(result.hits) - 1) + [True]
    hits = [{"chunk_id": hit.chunk.chunk_id, "text": hit.chunk.text, "pinned": hit.pinned} for hit in result.hits]
    policy, _ = shown_passages(hits)
    assert [p["chunk_id"] for p in policy] == [*ids(result)[:3], "BH-05"]
    policy, _ = shown_passages([{"chunk_id": "BH-05", "text": "x", "pinned": True}, *hits[:3]])
    assert [p["chunk_id"] for p in policy].count("BH-05") == 1


def test_what_was_read_earlier_in_the_call_stays_readable_when_a_follow_up_does_not_bring_it_back():
    from ai_agent_service.pipeline.hot.nodes import _passages_in_reach

    # "Nếu gửi hàng thì mất bao lâu để xử lý": the delivery table ranks first, the warranty section is not shown.
    hits = [{"chunk_id": code, "title": code, "text": f"text of {code}"} for code in ("VC-01", "QT-05", "QT-02", "QT-03")]
    read = {"DT-05": "Đổi mới 1-1 trong 30 ngày.", "BH-03": "Thời gian xử lý 7–15 ngày làm việc.", "VC-01": "text of VC-01"}
    readable = _passages_in_reach({"knowledge": {"hits": hits, "reason": None}, "passages_read": read})
    assert [p["chunk_id"] for p in readable[:4]] == ["VC-01", "QT-05", "QT-02", "QT-03"]
    assert [p["chunk_id"] for p in readable if p.get("earlier")] == ["BH-03", "DT-05"]  # the latest first, none twice
    policy, _ = shown_passages(readable)
    assert [p["chunk_id"] for p in policy] == ["VC-01", "QT-05", "QT-02", "BH-03", "DT-05"]
    assert _passages_in_reach({"knowledge": {"hits": hits, "reason": None}}) == tuple(hits)  # a first turn reads only its own


def test_a_learned_entry_is_found_by_the_questions_written_for_it_and_they_are_never_read_out():
    from ai_agent_service.components.knowledge.corpus import entry_chunk

    entry = {"chunk_id": "FAQ-GAP-X", "source": "faq", "title": "Cửa hàng có cho khách đến xem trực tiếp không?",
             "text": "Dạ hiện bên em chỉ bán online, chưa có cửa hàng trưng bày."}
    asked = "Shop có showroom ở đâu để anh ghé coi máy không?"
    plain = KnowledgeBase([*policy_chunks(POLICY), entry_chunk(entry, doc="v1.jsonl")])
    wider = KnowledgeBase([*policy_chunks(POLICY), entry_chunk(
        {**entry, "questions": ["Shop có showroom không em?", "Anh ghé coi máy trực tiếp ở đâu được?"]}, doc="v1.jsonl")])
    assert "FAQ-GAP-X" not in ids(plain.search(asked, on=AFTER))[:3]
    found = wider.search(asked, on=AFTER)
    assert ids(found)[0] == "FAQ-GAP-X"
    chunk = found.hits[0].chunk
    assert "showroom" not in chunk.text and len(chunk.questions) == 2
    # The service reads entries back from kb_chunks as their provenance plus their own columns: the questions survive.
    from ai_agent_service.mcp.servers.knowledge import _row_chunk

    row = {"chunk_id": chunk.chunk_id, "source": chunk.source, "title": chunk.title, "text": chunk.text, "situation": None,
           "persona": None, "valid_from": None, "valid_to": None, "provenance": dict(chunk.provenance), "scope": "release"}
    assert _row_chunk(row).questions == chunk.questions
