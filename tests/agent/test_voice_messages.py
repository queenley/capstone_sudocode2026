"""Voice messages in the web chat, as on Zalo (api/routes/conversations.py): each is transcribed on its own
(``/voice-message``), then the client sends them as one turn, each line marked, and the model reads them as speech."""
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

from ai_agent_service.api.routes import conversations as routes

MARK = routes.VOICE_MARK


def test_marked_lines_are_the_customers_words_and_counted():
    said, spoken = routes.unmark_voice(f"{MARK}cho chị hỏi máy lọc\n{MARK}phòng hai lăm mét\ngiá bao nhiêu")
    assert said == "cho chị hỏi máy lọc\nphòng hai lăm mét\ngiá bao nhiêu" and spoken == 2
    assert routes.unmark_voice("chỉ gõ chữ") == ("chỉ gõ chữ", 0)
    assert "2 tin nhắn thoại" in routes.voice_note(2) and "hỏi lại" in routes.voice_note(1)


class _Request:
    def __init__(self, body: bytes):
        self._body = body
        self.app = SimpleNamespace()
        self.headers = {"authorization": "Bearer t"}

    async def stream(self):
        for start in range(0, len(self._body), 4096):
            yield self._body[start:start + 4096]


@pytest.fixture()
def heard(monkeypatch):
    from ai_agent_service.components.intake import lexicon
    from ai_agent_service.components.voice import asr
    from ai_agent_service.runtime import options

    seen = {}

    def transcribe(name, samples, hotwords=None, **_):
        seen.update(name=name, samples=samples)
        return asr.Transcript(name, "  máy lọc   không khí  ", 0.1, samples.size / 16000)

    async def authorize(app, conversation_id, token):
        return SimpleNamespace(id=conversation_id, status=seen.get("status", "open"))

    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(options, "voice", lambda: SimpleNamespace(asr="zipformer-30m"))
    monkeypatch.setattr(lexicon, "lexicon", lambda: SimpleNamespace(hotwords=[], correct=lambda text: (text, [])))
    monkeypatch.setattr(routes.platform, "authorize", authorize)
    monkeypatch.setattr(routes, "bearer", lambda request: "t")
    return seen


@pytest.mark.asyncio
async def test_a_voice_message_is_16_bit_pcm_and_comes_back_as_words(heard):
    pcm = (np.sin(np.linspace(0, 200, 16000)) * 8000).astype("<i2").tobytes()
    result = await routes.voice_message("00000000-0000-0000-0000-000000000001", _Request(pcm))
    assert result == {"text": "máy lọc không khí", "seconds": 1.0}
    assert heard["samples"].dtype == np.float32 and abs(float(heard["samples"].max())) <= 1.0


@pytest.mark.asyncio
async def test_a_voice_message_over_a_minute_or_on_a_closed_chat_is_refused(heard):
    too_long = bytes(int(routes.VOICE_MAX_SECONDS * routes.VOICE_RATE * 2) + 2)
    with pytest.raises(HTTPException) as refused:
        await routes.voice_message("00000000-0000-0000-0000-000000000001", _Request(too_long))
    assert refused.value.status_code == 413
    with pytest.raises(HTTPException) as odd:
        await routes.voice_message("00000000-0000-0000-0000-000000000001", _Request(b"\x00\x01\x02"))
    assert odd.value.status_code == 400
    heard["status"] = "closed"
    with pytest.raises(HTTPException) as closed:
        await routes.voice_message("00000000-0000-0000-0000-000000000001", _Request(bytes(3200)))
    assert closed.value.status_code == 409
