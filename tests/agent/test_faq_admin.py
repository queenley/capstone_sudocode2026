"""The admin's FAQ: drafts are never served, going live needs a person and the gate, and the shipped drafts are sound."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ai_agent_service.components import knowledge
from ai_agent_service.components.improvement import review
from ai_agent_service.components.improvement.versions import versions
from ai_agent_service.components.knowledge import corpus, faq
from ai_agent_service.components.knowledge.search import KnowledgeBase
from ai_agent_service.config.config_manager import kb_dir

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "apps" / "ai-agent-service" / "data" / "btc" / "policy"
ADMIN = {"Authorization": "Bearer local-admin-change-me"}
DEVELOPER = {"Authorization": "Bearer local-developer-change-me"}
GOOD = {"title": "Đổi trả đợt sale", "text": "Đổi trả theo chính sách thường.", "cites": ["DT-01"]}
DRAFTS = corpus.load_drafts(kb_dir())


@pytest.mark.parametrize("draft", DRAFTS, ids=lambda d: d["chunk_id"])
def test_each_shipped_draft_passes_every_check_a_person_would_need(draft):
    assert faq.problems(draft, status="live") == []


def test_the_shipped_drafts_are_not_a_knowledge_version_and_never_load_as_entries():
    assert len(DRAFTS) == 10 and len({d["chunk_id"] for d in DRAFTS}) == 10
    assert all(n == int(n) for n in versions())
    assert not corpus.load_version(kb_dir(), 0)


def test_a_promotion_not_started_stays_unsaid():
    """KM-02: the 11/11 entries must not be readable before the sale starts, however the question is worded."""
    chunks = corpus.with_campaigns([corpus.entry_chunk(d, doc="drafts") for d in DRAFTS if d["campaign"] == "11-11"],
                                   knowledge.promotions())
    kb = KnowledgeBase([*corpus.policy_chunks(POLICY), *chunks])
    question = "giảm giá đợt 11/11 có được cộng với khuyến mãi khác không"
    found = lambda on: [hit.chunk.chunk_id for hit in kb.search(question, on=on).hits]
    assert not any(chunk_id.startswith("FAQ-D") for chunk_id in found("2026-11-10"))
    assert "FAQ-D-1111-01" in found("2026-11-11")


def test_an_entry_about_the_day_ends_with_it_and_reaches_every_product():
    chunk = corpus.with_campaigns([corpus.entry_chunk(next(d for d in DRAFTS if d["chunk_id"] == "FAQ-D-1111-03"),
                                                      doc="drafts")], knowledge.promotions())[0]
    assert (chunk.valid_from, chunk.valid_to, chunk.applies_to) == ("2026-11-11", "2026-11-11", ("*",))


@pytest.mark.parametrize("change, reason", [
    ({"text": "Giảm ngay 300.000đ cho khách."}, "số tiền"),
    ({"text": "Dùng mã AIR-OCT nhé."}, "mã khuyến mãi"),
    ({"text": "Hiện còn hàng ạ."}, "tồn kho"),
    ({"cites": []}, "ít nhất một nguồn"),
    ({"cites": ["NB-01"]}, "không công khai"),
    ({"cites": ["DT-OLD-01"]}, "hết hiệu lực"),
    ({"applies_to": ["máy lọc"]}, "applies_to"),
    ({"valid_from": "2026-12-02", "valid_to": "2026-12-01"}, "sau ngày kết thúc"),
    ({"campaign": "Đợt không tên"}, "no valid_to"),
])
def test_going_live_is_refused_with_the_reason(change, reason):
    assert reason in " ".join(faq.problems({**GOOD, **change}, status="live"))


def test_a_draft_may_be_unfinished_but_must_be_well_formed():
    assert faq.problems({**GOOD, "cites": []}, status="draft") == []
    assert faq.problems({**GOOD, "applies_to": ["máy lọc"]}, status="draft")


class Conn:
    """Enough of a connection for :mod:`.faq`: rows by id, and what was written."""

    def __init__(self, *rows):
        self.rows = {row["chunk_id"]: row for row in rows}
        self.writes = []

    async def execute(self, sql, values=()):
        self.writes.append((sql, values))
        if sql.startswith("INSERT"):
            chunk_id, title, text, start, end, provenance, status, revoked = values
            import json
            self.rows[chunk_id] = row(chunk_id, title=title, text=text, valid_from=start, valid_to=end, status=status,
                                      provenance=json.loads(provenance), revoked=revoked)
        if sql.startswith("UPDATE"):
            self.rows[values[0]] = {**self.rows[values[0]], "status": "deleted", "revoked": True}
        found = self.rows.get(values[0]) if values else None
        found = None if found and found["status"] == "deleted" else found
        rows = list(self.rows.values())

        class Cursor:
            async def fetchone(self):
                return found

            async def fetchall(self):
                return rows

        return Cursor()


def row(chunk_id="FAQ-1", **more):
    return {"chunk_id": chunk_id, "source": "faq", "title": "Câu hỏi", "text": "Trả lời", "valid_from": None,
            "valid_to": None, "provenance": {}, "scope": "demo", "status": "draft", "updated_at": None, **more}


@pytest.fixture
def stored(monkeypatch, tmp_path):
    from contextlib import asynccontextmanager

    conn = Conn(row())

    @asynccontextmanager
    async def connection():
        yield conn

    from ai_agent_service.api.routes import developer

    monkeypatch.setattr(developer, "connection", connection)
    monkeypatch.setattr(review, "log_path", lambda: tmp_path / "log.jsonl")
    return conn


def test_only_an_admin_reaches_the_faq(client, stored):
    assert client.get("/api/developer/faq").status_code == 401
    assert client.get("/api/developer/faq", headers=DEVELOPER).status_code == 403
    assert client.delete("/api/developer/faq/FAQ-1", headers=DEVELOPER).status_code == 403
    body = client.get("/api/developer/faq", headers=ADMIN).json()
    assert body["entries"][0]["chunk_id"] == "FAQ-1" and body["promotions"]


def test_a_new_entry_is_a_draft_until_approved(client, stored):
    created = client.post("/api/developer/faq", json=GOOD, headers=ADMIN)
    assert created.status_code == 200 and created.json()["status"] == "draft" and not created.json()["in_force"]
    assert client.post("/api/developer/faq", json={**GOOD, "status": "live"}, headers=ADMIN).status_code == 422
    live = client.put(f"/api/developer/faq/{created.json()['chunk_id']}", json={**GOOD, "status": "live", "approved": True},
                      headers=ADMIN)
    assert live.status_code == 200 and live.json()["in_force"] and live.json()["approved_by"]


def test_switching_off_clears_the_approval_and_stops_the_service(client, stored):
    live = client.put("/api/developer/faq/FAQ-1", json={**GOOD, "status": "live", "approved": True}, headers=ADMIN).json()
    assert stored.rows["FAQ-1"]["revoked"] is False and live["approved_by"]
    off = client.put("/api/developer/faq/FAQ-1", json=GOOD, headers=ADMIN).json()
    assert stored.rows["FAQ-1"]["revoked"] is True and off["approved_by"] is None


def test_a_refused_entry_says_why_and_changes_nothing(client, stored):
    body = {**GOOD, "status": "live", "approved": True, "text": "Giảm 300.000đ"}
    response = client.put("/api/developer/faq/FAQ-1", json=body, headers=ADMIN)
    assert response.status_code == 422 and "số tiền" in response.json()["detail"]
    assert stored.rows["FAQ-1"]["text"] == "Trả lời"


def test_deleting_keeps_the_row_as_a_record(client, stored):
    assert client.delete("/api/developer/faq/FAQ-1", headers=ADMIN).json() == {"status": "deleted"}
    assert stored.rows["FAQ-1"]["status"] == "deleted" and stored.rows["FAQ-1"]["revoked"] is True
    assert client.delete("/api/developer/faq/FAQ-1", headers=ADMIN).status_code == 404
    assert client.put("/api/developer/faq/FAQ-1", json=GOOD, headers=ADMIN).status_code == 404


def test_a_release_entry_is_read_only_here(client, stored):
    stored.rows["FAQ-R"] = row("FAQ-R", scope="release", status="live")
    assert client.put("/api/developer/faq/FAQ-R", json=GOOD, headers=ADMIN).status_code == 409
    assert client.delete("/api/developer/faq/FAQ-R", headers=ADMIN).status_code == 409


def test_dates_come_back_as_the_console_reads_them():
    shown = faq.view(row(valid_to=date(2026, 12, 1), status="live", provenance={"campaign": "Tết"}), "2026-11-07")
    assert shown["valid_to"] == "2026-12-01" and shown["in_force"] and shown["effective"]["valid_to"] == "2026-12-01"
    assert not faq.view(row(valid_to=date(2026, 11, 1), status="live"), "2026-11-07")["in_force"]


def test_only_staff_may_dismiss_a_gap_and_an_unknown_one_is_not_found(client, monkeypatch, tmp_path):
    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path))
    body = {"reason": "Ngoài phạm vi"}
    assert client.post("/api/developer/knowledge-gaps/0000000000000000/dismiss", json=body).status_code == 401
    assert client.post("/api/developer/knowledge-gaps/0000000000000000/dismiss", json=body, headers=ADMIN).status_code == 404


def test_a_gap_becomes_a_draft_faq_never_a_live_one(client, stored, monkeypatch, tmp_path):
    from ai_agent_service.components.improvement import gaps

    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path))
    key = gaps.record("Máy dùng ở độ cao 3000m được không?", call_id="1", turn_id="t1")
    body = {"answer": "Dạ em chưa có thông tin ạ.", "cites": ["PB-05"]}
    path = f"/api/developer/knowledge-gaps/{key}/faq"
    assert client.post(path, json=body, headers=DEVELOPER).status_code == 403
    made = client.post(path, json=body, headers=ADMIN)
    assert made.status_code == 200
    assert made.json()["status"] == "draft" and not made.json()["in_force"]
    assert made.json()["chunk_id"] == f"FAQ-GAP-{key.upper()}"
    assert stored.rows[made.json()["chunk_id"]]["revoked"] is True
    assert client.post(path, json=body, headers=ADMIN).status_code == 422
    assert client.post("/api/developer/knowledge-gaps/0000000000000000/faq", json=body, headers=ADMIN).status_code == 404
