"""The organisers' earlier calls seeded into the live shop (runtime/seed_prior_calls.py): the memory, and the
call-backs call_1 booked, which the sales team's "Hẹn gọi lại" lists."""
import json

import pytest

from ai_agent_service.mcp.servers import btc
from ai_agent_service.runtime import seed_prior_calls as seed


def _scenario(tmp_path, scenario_id="SCN-T-0001", phone="0981000001", tool_calls=()):
    folder = tmp_path / "conversations" / f"scenarios_{scenario_id}"
    folder.mkdir(parents=True)
    turns = [{"speaker": "agent", "text": "Dạ em hẹn gọi lại chị.", "tool_calls": list(tool_calls)}]
    (folder / "call_1.json").write_text(json.dumps({"turns": turns}, ensure_ascii=False), encoding="utf-8")
    return {"scenario_id": scenario_id, "customer_phone": phone}


def test_the_call_backs_of_the_first_call_are_read_from_its_conversation(tmp_path):
    scenario = _scenario(tmp_path, tool_calls=[
        {"name": "schedule.callback", "args": {"callback_at": "2026-10-19T19:00", "note": "hỏi người nhà"}},
        {"name": "order.status", "args": {"order_id": "OD1"}},
        {"name": "schedule.callback", "args": {}},  # no time: nothing to book
    ])
    booked = seed.callbacks_of(scenario, tmp_path / "conversations")
    assert booked == [{"customer_phone": "0981000001", "callback_at": "2026-10-19T19:00", "note": "hỏi người nhà"}]
    assert seed.callbacks_of({"scenario_id": "SCN-NONE", "customer_phone": "x"}, tmp_path / "conversations") == []


@pytest.mark.asyncio
async def test_a_second_seed_books_the_same_call_back_once(tmp_path, monkeypatch):
    scenario = _scenario(tmp_path, tool_calls=[
        {"name": "schedule.callback", "args": {"callback_at": "2026-10-19T19:00", "customer_phone": "0981000001"}},
    ])
    seen = []

    async def call(name, fn, /, *, idempotency_key=None, **kwargs):
        seen.append((name, idempotency_key, kwargs))
        return {}

    monkeypatch.setattr(btc, "call", call)
    assert await seed.book_callbacks(scenario, tmp_path / "conversations") == 1
    assert await seed.book_callbacks(scenario, tmp_path / "conversations") == 1
    assert seen[0][0] == "schedule.callback" and seen[0][1] == seen[1][1] == "btc-SCN-T-0001-call_1-callback-0"
    assert seen[0][2]["callback_at"] == "2026-10-19T19:00"
