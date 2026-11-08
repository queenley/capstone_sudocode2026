"""The console hears a handoff as it happens: a wake, a Kafka event, or the next poll."""
import asyncio
import json
from datetime import datetime, timezone

from ai_agent_service.api.routes import agent_calls
from ai_agent_service.runtime import alerts


def row(call_id, reason="Khách muốn gặp người"):
    return {"id": call_id, "conversation_id": None, "channel": "web", "tier": "VERIFIED", "lane": "NEW", "mode": "copilot",
            "started_at": datetime(2026, 11, 8, tzinfo=timezone.utc), "handoff_status": "pending",
            "handoff_reason": reason, "customer_label": "Chị Lan", "customer_id": "C1", "turn_count": 2}


class Request:
    def __init__(self):
        self.gone = False

    async def is_disconnected(self):
        return self.gone


def test_a_wake_releases_every_waiting_reader_at_once():
    async def go():
        hub = alerts.Hub()
        seen = hub.version
        readers = [asyncio.create_task(hub.wait(seen, timeout=5)) for _ in range(3)]
        await asyncio.sleep(0)
        hub.wake()
        return await asyncio.wait_for(asyncio.gather(*readers), 1)

    assert asyncio.run(go()) == [1, 1, 1]


def test_without_a_signal_the_reader_reads_again_after_the_poll():
    async def go():
        hub = alerts.Hub()
        return await hub.wait(hub.version, timeout=0.01)

    assert asyncio.run(go()) == 0


def test_a_wake_from_the_kafka_thread_reaches_the_loop():
    async def go():
        hub = alerts.Hub()
        reader = asyncio.create_task(hub.wait(hub.version, timeout=5))
        await asyncio.sleep(0)
        await asyncio.to_thread(hub.wake_threadsafe)
        return await asyncio.wait_for(reader, 1)

    assert asyncio.run(go()) == 1


def test_only_events_that_change_who_waits_ring():
    assert alerts.is_alert(json.dumps({"event_type": "handoff.requested", "payload": {}}).encode())
    assert alerts.is_alert(json.dumps({"event_type": "conversation.claimed"}))
    assert not alerts.is_alert(json.dumps({"event_type": "order.created"}))
    assert not alerts.is_alert(b"not json")
    assert not alerts.is_alert(None)


def test_without_kafka_the_console_polls():
    async def go():
        return alerts.start(None)

    assert asyncio.run(go()) is None and alerts.hub.source == "polling"


def test_the_stream_sends_who_waits_and_again_when_it_changes(monkeypatch):
    queue = [[row(7)], [row(7)], [row(7), row(9, "Hỏi đổi trả")], []]

    async def waiting():
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(alerts, "waiting", waiting)
    monkeypatch.setattr(alerts, "POLL_SECONDS", 0.01)

    async def go():
        request, events = Request(), []
        async for chunk in agent_calls._handoff_events(request, seconds=0.5):
            events.append(chunk)
            if sum(c.startswith("event: handoffs") for c in events) == 3:
                request.gone = True
        return events

    sent = [json.loads(c.split("data: ", 1)[1]) for c in asyncio.run(go()) if c.startswith("event: handoffs")]
    assert [[c["id"] for c in s["waiting"]] for s in sent] == [[7], [7, 9], []]
    assert sent[1]["waiting"][1]["handoff_reason"] == "Hỏi đổi trả" and sent[0]["source"] == "polling"


def test_a_handoff_wakes_the_stream_before_the_poll(monkeypatch):
    rows = [[]]

    async def waiting():
        return rows[0]

    monkeypatch.setattr(alerts, "waiting", waiting)
    monkeypatch.setattr(alerts, "POLL_SECONDS", 30)

    async def go():
        request = Request()
        stream = agent_calls._handoff_events(request, seconds=60)
        assert (await stream.__anext__()).startswith("retry:")
        assert '"waiting": []' in await stream.__anext__()
        nxt = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0.01)
        rows[0] = [row(11)]
        alerts.wake()
        chunk = await asyncio.wait_for(nxt, 1)
        request.gone = True
        await stream.aclose()
        return chunk

    assert '"id": 11' in asyncio.run(go())
