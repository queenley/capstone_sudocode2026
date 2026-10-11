from __future__ import annotations
import hashlib, os
from pathlib import Path
import httpx, yaml
from dotenv import load_dotenv

class ElevenLabsClient:
    def __init__(self, voices_path: Path, output_dir: Path, char_budget: int):
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.voices = yaml.safe_load(voices_path.read_text(encoding="utf-8"))["voices"]
        self.output_dir, self.char_budget, self.characters_sent = output_dir, char_budget, 0
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")

    def pick_voice(self, speaker_role: str, gender: str, region: str, age_band: str, customer_id: str) -> str:
        role_config = self.voices.get(speaker_role, {})
        regional = role_config.get(region, {})
        by_gender = regional.get(gender, {}) if isinstance(regional, dict) else {}
        candidates = by_gender.get(age_band, []) if isinstance(by_gender, dict) else by_gender
        if not candidates:
            default = role_config.get("default", {})
            candidates = default.get(gender, []) if isinstance(default, dict) else default
        if not candidates:
            raise RuntimeError(f"No ElevenLabs voice ID configured for {speaker_role}/{gender}/{region}/{age_band}; set it in config/voices.yaml")
        index = int.from_bytes(hashlib.sha256(customer_id.encode()).digest()[:8], "big") % len(candidates)
        return candidates[index]

    def missing_voices(self) -> list[str]:
        """Configured voice IDs this API key cannot use (not added to the account's My Voices)."""
        def walk(node):
            if isinstance(node, dict):
                for value in node.values():
                    yield from walk(value)
            elif isinstance(node, list):
                yield from node
        missing = []
        for voice_id in sorted(set(walk(self.voices))):
            response = httpx.get(f"https://api.elevenlabs.io/v1/voices/{voice_id}",
                                 headers={"xi-api-key": self.api_key}, timeout=30)
            if response.is_error:
                missing.append(voice_id)
        return missing

    def synthesize_turn(self, text: str, voice_id: str, *, stability: float = .5,
                        similarity_boost: float = .75, style: float = .2, rate_hint: float = 1.0,
                        model_id: str = "eleven_v4", language_code: str | None = "vi") -> bytes:
        if self.characters_sent + len(text) > self.char_budget:
            raise RuntimeError("ElevenLabs character budget exceeded")
        payload = {"text": text, "model_id": model_id,
                   "voice_settings": {"stability": stability, "similarity_boost": similarity_boost, "style": style,
                                       "speed": rate_hint, "use_speaker_boost": True}}
        if language_code:
            payload["language_code"] = language_code
        response = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": self.api_key, "Accept": "audio/pcm;rate=16000", "Content-Type": "application/json"},
            params={"output_format": "pcm_16000"}, json=payload, timeout=90)
        if response.is_error:
            detail = response.text.strip() or "no response body"
            raise RuntimeError(
                f"ElevenLabs TTS failed ({response.status_code}) for voice "
                f"{voice_id}: {detail}"
            )
        self.characters_sent += len(text)
        return response.content
