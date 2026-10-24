"""The consultant's 👍/👎 on a suggestion becomes a ``consultant`` signal; nothing else is touched."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai_agent_service.api.routes.agent_calls import SuggestionFeedback
from ai_agent_service.components.improvement import signals
from ai_agent_service.runtime import calls


def test_the_request_accepts_only_up_or_down():
    assert SuggestionFeedback(thumb="up").thumb == "up"
    with pytest.raises(ValidationError):
        SuggestionFeedback(thumb="meh")


def test_signals_are_appended_and_read_back(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path))
    asyncio.run(signals.record("consultant", call_id="7", turn_id="t1", value={"thumb": "up"}))
    asyncio.run(signals.record("violation", call_id="7", turn_id=None, value={"reason": "x"}))
    assert [r["kind"] for r in signals.read()] == ["consultant", "violation"]
    assert signals.read("consultant")[0]["value"] == {"thumb": "up"}
    assert signals.read("consultant")[0]["call_id"] == "7"


def _patch_call(monkeypatch, row, last_turn="t9"):
    async def call_row(_):
        return row

    class Cursor:
        async def fetchone(self):
            return {"turn_id": last_turn} if last_turn else None

    class Conn:
        async def execute(self, *_):
            return Cursor()

    @asynccontextmanager
    async def connection():
        yield Conn()

    monkeypatch.setattr(calls, "call_row", call_row)
    monkeypatch.setattr(calls, "connection", connection)


ACTOR = SimpleNamespace(id="u1", label="Lan")


def test_a_thumb_on_the_current_suggestion_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path))
    _patch_call(monkeypatch, {"ended_at": None, "accepted_by": "u1", "suggestion": {"text": "Dạ giá là X ạ."}})
    out = asyncio.run(calls.suggestion_feedback(3, actor=ACTOR, thumb="down", reason="  sai giá  "))
    assert out == {"recorded": True, "thumb": "down"}
    row = signals.read("consultant")[0]
    assert row["turn_id"] == "t9"
    assert row["value"]["thumb"] == "down" and row["value"]["reason"] == "sai giá" and row["value"]["consultant"] == "Lan"


@pytest.mark.parametrize("row,fragment", [
    ({"ended_at": "x", "accepted_by": "u1", "suggestion": {"text": "a"}}, "ended"),
    ({"ended_at": None, "accepted_by": "other", "suggestion": {"text": "a"}}, "holding"),
    ({"ended_at": None, "accepted_by": "u1", "suggestion": None}, "no suggestion"),
])
def test_feedback_is_refused_when_it_has_nothing_to_rate(tmp_path, monkeypatch, row, fragment):
    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path))
    _patch_call(monkeypatch, row)
    with pytest.raises(calls.CallError) as error:
        asyncio.run(calls.suggestion_feedback(3, actor=ACTOR, thumb="up", reason=None))
    assert fragment in str(error.value)
    assert signals.read() == []
