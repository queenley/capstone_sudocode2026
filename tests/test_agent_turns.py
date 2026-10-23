"""The AI service's turn routes around the agent: contract, replay, SSE, handoff, transcript."""

import json

from sqlalchemy import select

from src.db.models import Handoff, Message
from ai_agent_service.pipeline.hot.graph import NODES
from conftest import AGENT, conversation


def turn(client, c, h, message, **extra):
    return client.post(f"/api/conversations/{c}/turns", headers=h, json={"message": message, **extra})


def test_turn_result_matches_the_web_contract(client):
    c, h = conversation(client)
    response = turn(client, c, h, "Tư vấn laptop giúp em")
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result) >= {"reply", "route", "confidence", "trace_id", "products", "stages",
                           "stage_timings_ms", "tool_calls", "signals"}
    assert result["route"] == "NEW" and result["confidence"] == 1.0
    assert result["stages"] == list(NODES)
    assert result["tool_calls"] == ["catalog.search"]
    product = result["products"][0]
    assert (product["sku_code"], product["list_price"], product["sale_price"]) == ("SKU-1", "18000000", "17500000")


def test_selected_sku_is_context_and_memory_switch_reaches_the_agent(client, agent):
    c, h = conversation(client)
    turn(client, c, h, "Còn hàng không?", selected_sku="SKU-1", memory_enabled=False)
    sent = agent.turns[-1]
    assert sent["content"].startswith("Còn hàng không?") and "SKU-1" in sent["content"]
    assert sent["memory"] is False


def test_retried_turn_replays_the_stored_reply(client, agent):
    c, h = conversation(client)
    first = turn(client, c, h, "Xin chào", turn_id="t-1").json()
    again = turn(client, c, h, "Xin chào", turn_id="t-1").json()
    assert again["replayed"] and again["reply"] == first["reply"]
    assert len(agent.turns) == 1


def test_customer_visible_transcript_is_appended_masked(client):
    c, h = conversation(client)
    turn(client, c, h, "Số em là 0901234567")
    with client.app.state.database.sessions() as db:
        bodies = [(m.speaker, m.body) for m in db.scalars(
            select(Message).where(Message.conversation_id == c).order_by(Message.sequence))]
    assert bodies[-2][0] == "customer" and "0901234567" not in bodies[-2][1]
    assert bodies[-1][0] == "assistant"


def test_assistant_handoff_moves_the_conversation_to_staff(client):
    c, h = conversation(client)
    result = turn(client, c, h, "Cho em gặp nhân viên").json()
    assert result["signals"]["handoff_required"] and result["route"] == "HANDOFF"
    with client.app.state.database.sessions() as db:
        handoff = db.scalar(select(Handoff).where(Handoff.conversation_id == c))
        assert handoff.reason == "customer_asked"
    # The outbox event has an owner, so the relay can publish it.
    from src.db.models import Outbox
    from src.messaging.worker import topic_for_event
    with client.app.state.database.sessions() as db:
        event = db.scalar(select(Outbox).where(Outbox.event_type == "handoff.requested"))
        assert topic_for_event(event.event_type) == "telesales.sales.events"
    # With a person on it, the agent only drafts: no reply, the words reach the chat.
    waiting = turn(client, c, h, "Alo, còn đó không?").json()
    assert waiting["waiting"] and waiting["reply"] == ""
    with client.app.state.database.sessions() as db:
        last = db.scalars(select(Message).where(Message.conversation_id == c).order_by(Message.sequence)).all()[-1]
        assert (last.speaker, last.body) == ("customer", "Alo, còn đó không?")


def test_staff_handover_without_the_agent_only_records_the_message(client, agent):
    c, h = conversation(client)
    turn(client, c, h, "Xin chào")
    assert client.post(f"/api/staff/conversations/{c}/claim", headers=AGENT, json={}).status_code == 200
    with client.app.state.database.sessions() as db:
        from src.db.models import Conversation
        db.get(Conversation, c).status = "handed_off"
        db.commit()
    before = len(agent.turns)
    result = turn(client, c, h, "Cho hỏi thêm").json()
    assert result["waiting"] and result["route"] == "HUMAN"
    assert len(agent.turns) == before


def test_wrong_token_and_closed_conversation(client):
    c, h = conversation(client)
    assert turn(client, c, {"Authorization": "Bearer wrong"}, "hi").status_code == 404
    assert client.post(f"/api/conversations/{c}/end", headers=h, json={}).status_code == 200
    assert turn(client, c, h, "hi").status_code == 409


def test_stream_emits_start_delta_done(client):
    c, h = conversation(client)
    response = client.post(f"/api/conversations/{c}/stream", headers=h, json={"message": "Tư vấn giúp em"})
    assert response.status_code == 200
    events = [block.split("\n") for block in response.text.strip().split("\n\n")]
    names = [lines[0].removeprefix("event: ") for lines in events if lines[0].startswith("event:")]
    assert names[0] == "start" and names[-1] == "done" and "delta" in names
    done = json.loads(events[-1][1].removeprefix("data: "))
    deltas = "".join(json.loads(lines[1].removeprefix("data: "))["text"]
                     for lines in events if lines[0] == "event: delta")
    assert deltas == done["reply"]


def test_stream_sends_each_checked_sentence_once_as_it_is_said(client, streaming_agent):
    c, h = conversation(client)
    response = client.post(f"/api/conversations/{c}/stream", headers=h, json={"message": "Tư vấn giúp em"})
    assert response.status_code == 200
    events = [block.split("\n") for block in response.text.strip().split("\n\n")]
    deltas = [json.loads(lines[1].removeprefix("data: "))["text"] for lines in events if lines[0] == "event: delta"]
    done = json.loads(events[-1][1].removeprefix("data: "))
    assert deltas == ["Dạ, bên em có mẫu này ạ.", " Anh/chị muốn xem thêm không?"], "no filler, no repeat"
    assert "".join(deltas) == done["reply"]


def test_consultant_reply_from_the_call_console_reaches_the_chat(client, agent, monkeypatch):
    from ai_agent_service.runtime import calls

    c, h = conversation(client)
    turn(client, c, h, "Cho em gặp nhân viên")
    row = agent.calls[c]

    async def reply(call_id, *, actor, content, action, force):
        from datetime import datetime, timezone
        return True, [], {**row, "id": call_id, "tier": "UNKNOWN", "lane": "HANDOFF", "mode": "copilot",
                          "started_at": datetime.now(timezone.utc), "handoff_status": "accepted"}

    monkeypatch.setattr(calls, "consultant_reply", reply)
    sent = client.post(f"/api/agent/calls/{row['id']}/reply", headers=AGENT,
                       json={"content": "Dạ em là nhân viên, em hỗ trợ anh ạ.", "action": "own"})
    assert sent.status_code == 200 and sent.json()["sent"]
    messages = client.get(f"/api/conversations/{c}", headers=h).json()["messages"]
    assert (messages[-1]["speaker"], messages[-1]["text"]) == ("agent", "Dạ em là nhân viên, em hỗ trợ anh ạ.")


def test_a_phone_verified_by_one_time_code_identifies_the_caller(client, agent):
    """After OTP verification the agent gets the verified number, as a hotline caller id."""
    from conftest import identify

    c, h = conversation(client)
    assert turn(client, c, h, "Chào shop").status_code == 200
    assert "caller_phone" not in agent.calls[c]  # anonymous: no number to identify by
    identify(client, c, h, phone="0901234567")
    assert turn(client, c, h, "Tư vấn laptop giúp em").status_code == 200
    assert agent.calls[c]["caller_phone"] in ("0901234567", "+84901234567")
