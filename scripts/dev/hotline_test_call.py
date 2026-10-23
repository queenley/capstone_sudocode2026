"""Place a test call to the hotline without a phone line or SIP trunk.

    docker compose --profile hotline up -d
    docker compose --profile hotline run --rm -v "$PWD/scripts/dev:/dev-scripts" hotline-bridge \
        python /dev-scripts/hotline_test_call.py --wav /dev-scripts/question.wav --number +84985003703

It joins LiveKit the way a SIP call does: a new room named ``hotline-test-<n>``
(the bridge watches ``hotline-*``) with a participant whose
``sip.phoneNumber`` attribute is the caller id. It plays a WAV file as the
caller's voice (mono or stereo, any rate; silence when none is given),
records what the shop says into ``answer.wav`` beside this script, and prints
how long the first answer took. The bridge's log shows the transcript and the
reply (``docker compose logs hotline-bridge``).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import time
import wave

import numpy as np
import soxr
from livekit import api, rtc

RATE = 48_000
FRAME = RATE // 100


def load_wav(path: str | None, seconds: float) -> np.ndarray:
    if not path:
        return np.zeros(int(RATE * seconds), dtype=np.int16)
    with wave.open(path) as wav:
        rate, channels = wav.getframerate(), wav.getnchannels()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != RATE:
        samples = soxr.resample(samples, rate, RATE)
    # Some silence after the question so the agent's end-of-turn detector fires.
    samples = np.concatenate([samples, np.zeros(int(RATE * 2), np.float32)])
    return (np.clip(samples, -1, 1) * 32767).astype(np.int16)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--wav", help="The caller's speech (WAV); silence when omitted")
    parser.add_argument("--number", default="+84985003703", help="Caller id, as a carrier would send it")
    parser.add_argument("--listen", type=float, default=40, help="Seconds to stay on the line after speaking")
    parser.add_argument("--wait", type=float, default=10, help="Seconds before speaking: the bridge joins and opens the agent's line")
    args = parser.parse_args()

    url = os.environ.get("LIVEKIT_URL", "ws://livekit:7880")
    key, secret = os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]
    room_name = f"{os.environ.get('ROOM_PREFIX', 'hotline-')}test-{random.randint(1000, 9999)}"
    token = (api.AccessToken(key, secret).with_identity(f"caller-{args.number[-4:]}").with_name("Test caller")
             .with_attributes({"sip.phoneNumber": args.number})
             .with_grants(api.VideoGrants(room_join=True, room=room_name, room_create=True)).to_jwt())

    room = rtc.Room()
    heard: list[np.ndarray] = []
    first_audio: list[float] = []

    @room.on("track_subscribed")
    def _track(track: rtc.Track, _pub, participant: rtc.RemoteParticipant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return

        async def record() -> None:
            async for event in rtc.AudioStream(track, sample_rate=RATE, num_channels=1):
                pcm = np.frombuffer(event.frame.data, dtype=np.int16)
                if not first_audio and np.abs(pcm).max() > 500:
                    first_audio.append(time.monotonic())
                heard.append(pcm.copy())

        asyncio.create_task(record())
        print(f"Shop joined the call as {participant.identity}")

    await room.connect(url, token)
    print(f"Calling: room {room_name}, caller id {args.number}")
    source = rtc.AudioSource(RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("caller", source)
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))

    await asyncio.sleep(args.wait)  # the bridge polls for new rooms each second, then opens the agent's line
    speech = load_wav(args.wav, 3)
    print(f"Speaking {len(speech) / RATE:.1f} s")
    spoke_until = None
    for start in range(0, len(speech), FRAME):
        chunk = speech[start:start + FRAME]
        if len(chunk) < FRAME:
            chunk = np.pad(chunk, (0, FRAME - len(chunk)))
        frame = rtc.AudioFrame.create(RATE, 1, FRAME)
        np.frombuffer(frame.data, dtype=np.int16)[:] = chunk
        await source.capture_frame(frame)
    spoke_until = time.monotonic()
    await asyncio.sleep(args.listen)
    await room.disconnect()

    audio = np.concatenate(heard) if heard else np.zeros(0, np.int16)
    # Beside this script (scripts/dev, mounted from the host), so the recording is easy to find.
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "answer.wav")
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(audio.tobytes())
    loud = float(np.abs(audio).mean()) if audio.size else 0.0
    print(f"Heard {audio.size / RATE:.1f} s from the shop (mean level {loud:.0f}); saved {out}")
    if first_audio and spoke_until:
        print(f"First sound from the shop {first_audio[0] - spoke_until:+.1f} s after the caller stopped")


if __name__ == "__main__":
    asyncio.run(main())
