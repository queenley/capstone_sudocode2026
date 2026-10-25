"""The phone hotline: LiveKit SIP calls answered by the shop's AI agent.

A call to the hotline number reaches LiveKit through the carrier's SIP trunk;
LiveKit's SIP service puts each call in its own room (``hotline-<random>``,
the dispatch rule in ``infra/livekit``). This bridge watches for those rooms,
joins each as the shop, and relays the audio both ways to the agent's voice
channel, the same WebSocket a browser call uses
(``/api/conversations/{id}/voice``):

    caller (SIP) -> LiveKit room -> bridge -> agent voice WS  (float32 PCM up)
    agent voice WS -> bridge -> LiveKit room -> caller        (WAV/MP3 sentences down)

For each call the bridge opens a platform conversation on the hotline channel
(Sales ``POST /api/conversations``) and tells the agent the caller's number
(``sip.phoneNumber``) with ``HOTLINE_BRIDGE_KEY``, so returning customers are
recognised. It speaks the browser client's playback protocol
(``playback_started`` / ``_ended`` / ``_stopped``, ``hangup``) so barge-in and
latency figures work as on the web.

Environment: ``LIVEKIT_URL``, ``LIVEKIT_API_KEY``, ``LIVEKIT_API_SECRET``,
``AGENT_URL`` (http://ai-agent-service:8400), ``SALES_URL``
(http://sales-service:8300), ``HOTLINE_BRIDGE_KEY``, ``ROOM_PREFIX`` (hotline-).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import wave
from dataclasses import dataclass, field

import httpx
import numpy as np
import soxr
import websockets
from livekit import api, rtc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("hotline-bridge")

RATE = 48_000
FRAME = RATE // 100  # 10 ms
IDENTITY = "shop-agent"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


LIVEKIT_URL = env("LIVEKIT_URL", "ws://livekit:7880")
LIVEKIT_KEY = env("LIVEKIT_API_KEY")
LIVEKIT_SECRET = env("LIVEKIT_API_SECRET")
AGENT_URL = env("AGENT_URL", "http://ai-agent-service:8400")
SALES_URL = env("SALES_URL", "http://sales-service:8300")
BRIDGE_KEY = env("HOTLINE_BRIDGE_KEY")
PREFIX = env("ROOM_PREFIX", "hotline-")


# ── audio ────────────────────────────────────────────────────────────────


def decode(data: bytes, mime: str) -> np.ndarray:
    """One sentence of speech as mono int16 at 48 kHz."""
    if "wav" in mime:
        with wave.open(io.BytesIO(data)) as wav:
            rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
            raw = wav.readframes(wav.getnframes())
        dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
        samples = np.frombuffer(raw, dtype=dtype).astype(np.float32)
        if width == 1:
            samples = (samples - 128) / 128
        else:
            samples /= float(np.iinfo(dtype).max)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
    else:  # MP3 and anything else: PyAV
        import av

        with av.open(io.BytesIO(data)) as container:
            stream = container.streams.audio[0]
            rate = stream.rate
            chunks = [frame.to_ndarray().astype(np.float32).mean(axis=0) if frame.to_ndarray().ndim > 1
                      else frame.to_ndarray().astype(np.float32) for frame in container.decode(stream)]
        samples = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
        if samples.size and np.abs(samples).max() > 1.5:  # integer formats
            samples /= 32768.0
    if rate != RATE and samples.size:
        samples = soxr.resample(samples, rate, RATE)
    return (np.clip(samples, -1, 1) * 32767).astype(np.int16)


@dataclass
class Piece:
    turn: str
    seq: int
    pcm: np.ndarray


@dataclass
class Player:
    """Plays the agent's sentences into the room in order, and reports playback as a browser does."""

    source: rtc.AudioSource
    send: object
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    resume: asyncio.Event = field(default_factory=asyncio.Event)
    dropped: set = field(default_factory=set)
    ended: set = field(default_factory=set)
    current: Piece | None = None
    position: int = 0

    def __post_init__(self) -> None:
        self.resume.set()

    async def run(self) -> None:
        started: set[str] = set()
        while True:
            piece: Piece = await self.queue.get()
            if piece.turn in self.dropped:
                continue
            self.current, self.position = piece, 0
            if piece.turn not in started:
                started.add(piece.turn)
                await self.send({"type": "playback_started", "turn": piece.turn})
            while self.position < len(piece.pcm):
                await self.resume.wait()
                if piece.turn in self.dropped:
                    break
                chunk = piece.pcm[self.position:self.position + FRAME]
                if len(chunk) < FRAME:
                    chunk = np.pad(chunk, (0, FRAME - len(chunk)))
                frame = rtc.AudioFrame.create(RATE, 1, FRAME)
                np.frombuffer(frame.data, dtype=np.int16)[:] = chunk
                await self.source.capture_frame(frame)
                self.position += FRAME
            self.current = None
            if piece.turn in self.ended and self.queue.empty() and piece.turn not in self.dropped:
                await self.source.wait_for_playout()
                await self.send({"type": "playback_ended", "turn": piece.turn})

    def stop(self, turn: str) -> dict:
        """The agent was interrupted: drop the rest of *turn* and say how much was heard."""
        self.dropped.add(turn)
        self.source.clear_queue()
        piece = self.current if self.current and self.current.turn == turn else None
        self.resume.set()
        return {"type": "playback_stopped", "turn": turn, "seq": piece.seq if piece else 0,
                "played_ms": (self.position / RATE) * 1000 if piece else 0,
                "duration_ms": (len(piece.pcm) / RATE) * 1000 if piece else 1}


# ── one call ─────────────────────────────────────────────────────────────


async def open_conversation() -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{SALES_URL}/api/conversations", json={"channel": "hotline"})
        response.raise_for_status()
        return response.json()


def caller_number(participant: rtc.RemoteParticipant) -> str:
    attributes = dict(participant.attributes or {})
    return attributes.get("sip.phoneNumber") or attributes.get("phone") or ""


async def handle_room(name: str) -> None:
    token = (api.AccessToken(LIVEKIT_KEY, LIVEKIT_SECRET).with_identity(IDENTITY).with_name("Quivo")
             .with_grants(api.VideoGrants(room_join=True, room=name)).to_jwt())
    room = rtc.Room()
    caller: asyncio.Future = asyncio.get_running_loop().create_future()
    gone = asyncio.Event()

    @room.on("track_subscribed")
    def _track(track: rtc.Track, _pub: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO and not caller.done():
            caller.set_result((track, participant))

    @room.on("participant_disconnected")
    def _left(participant: rtc.RemoteParticipant) -> None:
        if participant.identity != IDENTITY:
            gone.set()

    @room.on("disconnected")
    def _closed(*_args) -> None:
        gone.set()

    await room.connect(LIVEKIT_URL, token)
    logger.info("Joined %s", name)
    try:
        track, participant = await asyncio.wait_for(caller, timeout=30)
    except asyncio.TimeoutError:
        logger.warning("%s: no caller audio within 30 s", name)
        await room.disconnect()
        return

    source = rtc.AudioSource(RATE, 1)
    local = rtc.LocalAudioTrack.create_audio_track("shop-voice", source)
    await room.local_participant.publish_track(local, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))

    conversation = await open_conversation()
    number = caller_number(participant)
    url = AGENT_URL.replace("http", "ws", 1).rstrip("/") + f"/api/conversations/{conversation['conversation_id']}/voice"
    logger.info("%s: caller ···%s on conversation %s", name, number[-4:] if number else "?", conversation["conversation_id"])

    async with websockets.connect(url, max_size=None) as ws:
        async def send(payload: dict) -> None:
            await ws.send(json.dumps(payload))

        await send({"token": conversation["conversation_token"], "sample_rate": RATE,
                    "caller_phone": number, "bridge_key": BRIDGE_KEY})
        player = Player(source, send)

        async def uplink() -> None:
            async for event in rtc.AudioStream(track, sample_rate=RATE, num_channels=1):
                pcm = np.frombuffer(event.frame.data, dtype=np.int16).astype(np.float32) / 32768.0
                try:
                    await ws.send(pcm.tobytes())
                except websockets.ConnectionClosed:
                    return  # the agent ended the call

        async def downlink() -> None:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                message = json.loads(raw)
                kind = message.get("type")
                if kind == "audio":
                    pcm = decode(base64.b64decode(message["data"]), message.get("mime", "audio/wav"))
                    await player.queue.put(Piece(str(message["turn"]), int(message.get("seq", 0)), pcm))
                elif kind == "audio_end":
                    player.ended.add(str(message["turn"]))
                    if player.queue.empty() and player.current is None:
                        await send({"type": "playback_ended", "turn": str(message["turn"])})
                elif kind == "pause":
                    player.resume.clear()
                elif kind == "resume":
                    player.resume.set()
                elif kind == "stop":
                    await send(player.stop(str(message["turn"])))
                elif kind == "error":
                    logger.warning("%s: agent says %s", name, message.get("text"))
                elif kind in ("transcript", "reply"):
                    logger.info("%s %s: %s", name, kind, (message.get("text") or "")[:120])

        tasks = [asyncio.create_task(coro) for coro in (uplink(), downlink(), player.run(), gone.wait())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        # Collect every task's outcome, so a closed socket is not reported as an unhandled error.
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, Exception) and not isinstance(result, websockets.ConnectionClosed):
                logger.warning("%s: %r", name, result)
        try:
            await send({"type": "hangup"})
        except websockets.ConnectionClosed:
            pass
    await room.disconnect()
    logger.info("%s: call ended", name)


# ── the watcher ──────────────────────────────────────────────────────────


async def run_call(name: str) -> None:
    try:
        await handle_room(name)
    except Exception:  # noqa: BLE001 - one call failing must not stop the others
        logger.exception("%s: call failed", name)


async def ensure_dispatch_rule(lk: api.LiveKitAPI) -> None:
    """Every inbound SIP call gets its own room named ``<PREFIX><random>`` (created once)."""
    try:
        rules = (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items
        if any(r.rule.dispatch_rule_individual.room_prefix == PREFIX for r in rules):
            return
        await lk.sip.create_dispatch_rule(api.CreateSIPDispatchRuleRequest(
            name="telesales-hotline",
            rule=api.SIPDispatchRule(dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix=PREFIX)),
        ))
        logger.info("Created SIP dispatch rule: each call -> room %s<random>", PREFIX)
    except Exception as error:  # noqa: BLE001 - without SIP the bridge still serves rooms made another way
        logger.warning("Could not check the SIP dispatch rule: %s", error)


async def main() -> None:
    if not (LIVEKIT_KEY and LIVEKIT_SECRET):
        raise SystemExit("Set LIVEKIT_API_KEY and LIVEKIT_API_SECRET")
    if not BRIDGE_KEY:
        logger.warning("HOTLINE_BRIDGE_KEY is not set: callers will not be identified by their number")
    lk = api.LiveKitAPI(LIVEKIT_URL.replace("ws", "http", 1), LIVEKIT_KEY, LIVEKIT_SECRET)
    await ensure_dispatch_rule(lk)
    handled: set[str] = set()  # a room lingers a few seconds after its call: never join one twice
    logger.info("Watching LiveKit at %s for rooms %s*", LIVEKIT_URL, PREFIX)
    while True:
        try:
            rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
            for room in rooms:
                if room.name.startswith(PREFIX) and room.name not in handled:
                    handled.add(room.name)
                    asyncio.create_task(run_call(room.name))
        except Exception as error:  # noqa: BLE001 - LiveKit restarting: try again
            logger.warning("Listing rooms failed: %s", error)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
