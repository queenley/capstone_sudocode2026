"""The Responses API over kept WebSockets, under LangChain's ``ChatOpenAI`` (``ADVISOR_TRANSPORT=websocket``).

LangChain streams a Responses call through exactly one place, ``root_async_client.responses.create(**payload)``, and
reads the stream events it returns. A WebSocket sends the same body as a ``response.create`` event and answers with
the same events (developers.openai.com/api/docs/guides/websocket-mode), so :class:`SocketClient` stands in for that one
call and LangChain does everything else as before: the message it builds, the tool calls, usage, the callbacks.

Why: the advisor's turn is one or two model calls, each paying the connection's setup and the request's trip from
Vietnam before OpenAI starts. On the advisor's real requests (workbench/latency/bench_transport.py, 2026-11-26, 30
calls each, warmed) the model's decision came at 844/1162 ms (p50/p95) over a kept socket against 1176/1828 ms over
Chat Completions. Sockets are pooled: a call takes an idle one or opens one, and gives it back once its response is
over; one that fails is closed. A socket that cannot be opened, or fails before its first event, sends the call
over HTTP instead, so the transport can only make a turn faster, never lose it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

#: Fields of an HTTP Responses body that a socket does not take (the guide: "transport-specific fields").
HTTP_ONLY = ("stream", "stream_options", "background")
#: The events that end one response on a socket.
TERMINAL = frozenset({"response.completed", "response.incomplete", "response.failed", "error"})


class SocketError(RuntimeError):
    """A response the socket reported as failed, or an error event."""


class _Pool:
    """Idle sockets of one client, opened on demand and kept while they work."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._idle: list[tuple[Any, Any]] = []
        self._lock = asyncio.Lock()

    async def take(self) -> tuple[Any, Any]:
        async with self._lock:
            if self._idle:
                return self._idle.pop()
        manager = self._client.responses.connect(max_retries=0)
        connection = await manager.__aenter__()
        return manager, connection

    async def give_back(self, socket: tuple[Any, Any], healthy: bool) -> None:
        if healthy:
            async with self._lock:
                self._idle.append(socket)
            return
        try:
            await socket[0].__aexit__(None, None, None)
        except Exception:  # noqa: BLE001 - closing a broken socket
            pass


class _Response:
    """One streamed response: what ``responses.create(stream=True)`` returns, read from a pooled socket."""

    def __init__(self, pool: _Pool, http: Any, payload: dict[str, Any]) -> None:
        self._pool, self._http, self._payload = pool, http, payload
        self._socket: tuple[Any, Any] | None = None
        self._fallback: Any = None
        self._done = False

    async def __aenter__(self) -> "_Response":
        body = {k: v for k, v in self._payload.items() if k not in HTTP_ONLY}
        try:
            self._socket = await self._pool.take()
            await self._socket[1].response.create(**body)
        except Exception as error:  # noqa: BLE001 - any failure before the first event goes over HTTP
            logger.warning("Responses socket unavailable (%s: %s); this call goes over HTTP", type(error).__name__, error)
            if self._socket is not None:
                await self._pool.give_back(self._socket, healthy=False)
                self._socket = None
            self._fallback = await self._http.create(**self._payload)
            await self._fallback.__aenter__()
        return self

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._events()

    async def _events(self) -> AsyncIterator[Any]:
        if self._fallback is not None:
            async for event in self._fallback:
                yield event
            return
        connection = self._socket[1]
        while True:
            event = await connection.recv()
            kind = getattr(event, "type", None)
            if kind == "error":
                raise SocketError(str(getattr(event, "error", event)))
            yield event
            if kind in TERMINAL:
                self._done = True
                if kind == "response.failed":
                    raise SocketError(str(getattr(getattr(event, "response", None), "error", event)))
                return

    async def __aexit__(self, *exc: Any) -> None:
        if self._fallback is not None:
            await self._fallback.__aexit__(*exc)
            return
        if self._socket is not None:
            # A response not read to its end leaves events on the socket for the next call: closed, not reused.
            await self._pool.give_back(self._socket, healthy=self._done and exc[0] is None)
            self._socket = None


class _Responses:
    def __init__(self, pool: _Pool, http: Any) -> None:
        self._pool, self._http = pool, http

    async def create(self, **payload: Any) -> Any:
        if not payload.get("stream"):
            return await self._http.create(**payload)
        return _Response(self._pool, self._http, payload)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._http, name)


class SocketClient:
    """An ``AsyncOpenAI`` whose streamed ``responses.create`` goes over pooled WebSockets; everything else is the
    client's own."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.responses = _Responses(_Pool(client), client.responses)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
