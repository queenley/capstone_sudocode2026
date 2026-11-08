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
