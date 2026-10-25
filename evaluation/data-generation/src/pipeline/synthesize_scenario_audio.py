from __future__ import annotations

import argparse
import hashlib
import json
import wave
from pathlib import Path

import numpy as np
import yaml

from src.elevenlabs_client import ElevenLabsClient
from src.schemas.scenario import Scenario
from src.utils.audio_noise import NOISE_TYPES, add_noise
from src.utils.crm import load_customers
from src.utils.io import iter_models
from src.utils.paths import AUDIO_DIR, ROOT, SCENARIOS_INTERNAL_DIR

INTERNAL = SCENARIOS_INTERNAL_DIR


def write_wav(path: Path, pcm: bytes, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(pcm)


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize each scenario customer turn as an individual Vietnamese WAV")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--clean", action="store_true", help="Do not add background noise")
    parser.add_argument("--noise-type", choices=NOISE_TYPES, help="Use one noise type for every turn")
    parser.add_argument("--resume", action="store_true", help="Skip turns whose WAV and JSON already exist")
    args = parser.parse_args()
    settings = yaml.safe_load((ROOT / "config/settings.yaml").read_text(encoding="utf-8"))
    budget = settings["budget"]["max_elevenlabs_chars_per_run"]
    audio_config = settings.get("scenario_audio", {})
    model_id = audio_config.get("model_id", "eleven_v4")
    language_code = audio_config.get("language_code")
    voice_settings = audio_config.get("voice_settings", {})
    noise_fraction = float(audio_config.get("noise_fraction", 0.5))
    noise_snr_db = int(audio_config.get("noise_snr_db", 6))
    tts = ElevenLabsClient(ROOT / "config/voices.yaml", AUDIO_DIR, budget)
    missing = tts.missing_voices()
    if missing:
        raise SystemExit("These voice IDs in config/voices.yaml are not available to this ElevenLabs key "
                         "(add them to My Voices or remove them):\n  " + "\n  ".join(missing))
    by_id = {customer.customer_id: customer for customer in load_customers()}
    generated = 0
    for _, scenario in iter_models(sorted(INTERNAL.glob("SCN-GEN-*.json"))[:args.limit], Scenario):
        customer = by_id.get(scenario.customer_id or "")
        if customer is None:
            raise RuntimeError(f"Customer not found for {scenario.scenario_id}")
        gender = "male" if customer.honorific.lower() in ("anh", "chú", "ông", "em trai") else "female"
        age_band = "senior" if customer.honorific.lower() in ("cô", "chú", "bác", "ông", "bà") else "adult"
        for call_name, call in scenario.ordered_calls():
            voice = tts.pick_voice("customer", gender, scenario.region, age_band, customer.customer_id)
            for turn_index, text in enumerate(call.customer_turns, start=1):
                output = AUDIO_DIR / f"scenarios_{scenario.scenario_id}" / call_name / f"turn_{turn_index}.wav"
                if args.resume and output.exists() and output.with_suffix(".json").exists():
                    continue
                pcm = tts.synthesize_turn(text, voice, model_id=model_id, language_code=language_code,
                                          stability=voice_settings.get("stability", .35),
                                          similarity_boost=voice_settings.get("similarity_boost", .8),
                                          style=voice_settings.get("style", .35),
                                          rate_hint=voice_settings.get("speed", 1.0))
                seed = int.from_bytes(hashlib.sha256(
                    f"{scenario.scenario_id}:{call_name}:{turn_index}".encode()
                ).digest()[:4], "big")
                rng = np.random.default_rng(seed)
                noise_type = None
                if not args.clean and (args.noise_type or rng.random() < noise_fraction):
                    noise_type = args.noise_type or NOISE_TYPES[seed % len(NOISE_TYPES)]
                samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
                processed = add_noise(samples, 16000, noise_type, noise_snr_db, seed)
                pcm = np.clip(processed * 32767, -32768, 32767).astype("<i2").tobytes()
                write_wav(output, pcm)
                output.with_suffix(".json").write_text(json.dumps({
                    "scenario_id": scenario.scenario_id, "call": call_name, "turn": turn_index,
                    "speaker": "customer", "text": text, "input_mode": call.input_mode,
                    "asr_text": call.customer_turns_asr[turn_index - 1] if turn_index <= len(call.customer_turns_asr) else None,
                    "voice_id": voice, "duration_seconds": round(len(pcm) / 2 / 16000, 3),
                    "model_id": model_id, "language_code": language_code,
                    "speed": voice_settings.get("speed", 1.0),
                    "noise": {"type": noise_type, "snr_db": noise_snr_db} if noise_type else None,
                    "sample_rate": 16000,
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                generated += 1
    report = ROOT / "output/reports/elevenlabs_usage.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"characters_sent": tts.characters_sent, "budget": budget,
                                  "mode": "scenario_customer_turns", "turns_generated": generated}, indent=2), encoding="utf-8")
    print(f"Scenario turn audio generated: {generated}; characters sent: {tts.characters_sent}/{budget}")


if __name__ == "__main__":
    main()