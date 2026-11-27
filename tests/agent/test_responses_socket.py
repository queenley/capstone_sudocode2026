"""The advisor's Responses calls over kept WebSockets (llm/websocket.py): events pass through, sockets are reused,
and a socket that fails sends the call over HTTP."""
from types import SimpleNamespace

import pytest

from ai_agent_service.llm.websocket import SocketClient


class Connection:
    def __init__(self, replies, fail_send=False):
        self.replies, self.fail_send, self.sent = list(replies), fail_send, []
        self.response = SimpleNamespace(create=self.create)

    async def create(self, **body):
        if self.fail_send:
            raise ConnectionError("socket closed")
        self.sent.append(body)

    async def recv(self):
        return self.replies.pop(0)


class Manager:
    def __init__(self, connection):
        self.connection, self.closed = connection, False

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *exc):
        self.closed = True


class HttpStream:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def __aiter__(self):
        async def gen():
            for event in self.events:
                yield event
        return gen()


def event(kind):
    return SimpleNamespace(type=kind)


class Client:
    def __init__(self, connections):
        self.managers = [Manager(c) for c in connections]
        self.opened = 0
        self.http_bodies = []

        async def http_create(**payload):
            self.http_bodies.append(payload)
            return HttpStream([event("response.created"), event("response.completed")])

        def connect(**_):
            manager = self.managers[self.opened]
            self.opened += 1
            return manager

        self.responses = SimpleNamespace(connect=connect, create=http_create)


async def read(client, payload):
    stream = await client.responses.create(**payload)
    async with stream as response:
        return [e.type async for e in response]


@pytest.mark.asyncio
async def test_a_response_streams_over_one_socket_kept_for_the_next_call():
    connection = Connection([event("response.created"), event("response.output_text.delta"), event("response.completed"),
                             event("response.created"), event("response.completed")])
    raw = Client([connection])
    client = SocketClient(raw)
    assert await read(client, {"model": "m", "input": [], "stream": True}) == [
        "response.created", "response.output_text.delta", "response.completed"]
    assert await read(client, {"model": "m", "input": [], "stream": True}) == ["response.created", "response.completed"]
    assert raw.opened == 1  # the socket was reused
    assert connection.sent[0] == {"model": "m", "input": []}  # the transport's own fields stay off the socket


@pytest.mark.asyncio
async def test_a_socket_that_fails_sends_the_call_over_http_and_is_not_reused():
    broken, healthy = Connection([], fail_send=True), Connection([event("response.created"), event("response.completed")])
    raw = Client([broken, healthy])
    client = SocketClient(raw)
    assert await read(client, {"model": "m", "input": [], "stream": True}) == ["response.created", "response.completed"]
    assert raw.http_bodies == [{"model": "m", "input": [], "stream": True}]
    assert raw.managers[0].closed
    assert await read(client, {"model": "m", "input": [], "stream": True}) == ["response.created", "response.completed"]
    assert raw.opened == 2  # a new socket, not the broken one
