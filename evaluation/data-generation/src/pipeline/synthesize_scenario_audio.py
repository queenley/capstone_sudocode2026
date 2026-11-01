"""Stage 9 — speak every customer turn of the scenarios, until the audio reaches its target length.

Output: ``<seed>/audio/scenarios_<id>/call_<n>/turn_<k>.wav`` (16 kHz mono) and a
``.json`` beside each with its text, the spoken form the voice read, its entities, voice, noise and duration.

The voice does not read the written turn ("5.200.000đ", "AirPure X"). It reads the spoken form
("năm triệu hai trăm nghìn", "e pia x"). A model writes that form first (``src/asr/reference.py``,
``<seed>/asr_reference/scenarios_<id>/call_<n>.json``), so the ASR reference is exactly what was said.
After the run, ``<seed>/asr_reference/ground_truth.json`` lists every spoken clip in BTC's
``data/asr/ground_truth.json`` format. Typed chat (teencode, no diacritics) is read as written and left out.

Scenarios are taken in id order until the audio on disk reaches
``generation.audio_hours_target`` (BTC M2: ≥ 3 hours) or ``--hours``; ``--limit``
caps the scenarios instead. ElevenLabs characters per run are capped by
``budget.max_elevenlabs_chars_per_run``; ``--resume`` keeps the turns already spoken
with the same words.

    python -m src.pipeline.synthesize_scenario_audio --resume            # up to the target hours
    python -m src.pipeline.synthesize_scenario_audio --hours 1 --clean   # one hour, no background noise
    python -m src.pipeline.synthesize_scenario_audio --reference-only --limit 5   # spoken forms only, no TTS
    python -m src.pipeline.synthesize_scenario_audio --ground-truth-only          # rewrite ground_truth.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import wave
from pathlib import Path

import numpy as np
import yaml

from src.asr.reference import load_or_build, write_ground_truth
from src.utils.audio_noise import NOISE_TYPES, add_noise
from src.utils.crm import SourceData, load_customers
from src.utils.dataset import Dataset, call_folder
from src.utils.paths import AUDIO_DIR, REPORTS_DIR, ROOT
from src.utils.quota import stop_on_daily_limit
from src.utils.settings import model_client

SAMPLE_RATE = 16000
SENIOR = ("cô", "chú", "bác", "ông", "bà")
MALE = ("anh", "chú", "ông", "em trai")


def write_wav(path: Path, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(pcm)


def _spoken_text(wav: Path) -> tuple[str | None, str | None]:
    """``(turn text, what the voice read)`` of a WAV on disk, per the .json beside it."""
    try:
        meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    return meta.get("text"), meta.get("spoken_text") or meta.get("text")


def spoken_seconds(root: Path = AUDIO_DIR) -> float:
    """Seconds of customer audio already on disk (from the .json beside each WAV)."""
    total = 0.0
    for meta in root.glob("scenarios_*/call_*/turn_*.json"):
        try:
            total += float(json.loads(meta.read_text(encoding="utf-8")).get("duration_seconds") or 0)
        except (ValueError, OSError):
            continue
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=float, help="stop once this much audio exists (default: settings target)")
    parser.add_argument("--limit", type=int, help="at most this many scenarios")
    parser.add_argument("--clean", action="store_true", help="Do not add background noise")
    parser.add_argument("--noise-type", choices=NOISE_TYPES, help="Use one noise type for every turn")
    parser.add_argument("--resume", action="store_true", help="Skip turns whose WAV and JSON already exist")
    parser.add_argument("--free-voices-only", action="store_true",
                        help="use only premade voices, the ones a free ElevenLabs plan may call (English voices: "
                             "foreign accent, no regional one)")
    parser.add_argument("--replace-missing-voices", action="store_true",
                        help="Rewrite config/voices.yaml (old one kept as .bak): each voice the key's account lacks becomes "
                             "one of its Vietnamese voices of the same gender, region accent and age band")
    parser.add_argument("--reference-only", action="store_true", help="Write the spoken forms only (model, no TTS)")
    parser.add_argument("--ground-truth-only", action="store_true", help="Rewrite ground_truth.json from the clips on disk")
    args = parser.parse_args()
    if args.ground_truth_only:
        print(f"ASR ground truth: {write_ground_truth()}")
        return
    settings = yaml.safe_load((ROOT / "config/settings.yaml").read_text(encoding="utf-8"))
    target_seconds = 3600 * (args.hours if args.hours is not None else float(settings["generation"]["audio_hours_target"]))
    budget = settings["budget"]["max_elevenlabs_chars_per_run"]
    audio_config = settings.get("scenario_audio", {})
    model_id = audio_config.get("model_id", "eleven_v4")
    language_code = audio_config.get("language_code")
    voice_settings = audio_config.get("voice_settings", {})
    noise_fraction = float(audio_config.get("noise_fraction", 0.5))
    noise_snr_db = int(audio_config.get("noise_snr_db", 6))
    names = {product.sku: product.name for product in SourceData.load().catalog.products}
    clients: list = []

    def reference_client():   # built on first use: a rerun whose spoken forms are on disk makes no model call
        if not clients:
            clients.append(model_client("asr_reference", settings))
        return clients[0]

    if args.reference_only:
        written = 0
        for scenario in Dataset().iter_scenarios(args.limit):
            for call_name, call in scenario.ordered_calls():
                written += load_or_build(reference_client, scenario, call_name, call, names) is not None
        print(f"Spoken forms on disk for {written} calls -> <seed>/asr_reference/")
        return

    from src.providers.elevenlabs_client import ElevenLabsClient

    tts = ElevenLabsClient(ROOT / "config/voices.yaml", AUDIO_DIR, budget)
    if args.replace_missing_voices:
        changes = tts.replace_missing_voices(ROOT / "config/voices.yaml")
        for group, old, new in changes:
            print(f"  voice {group}: {old} -> {new}", flush=True)
        print(f"Replaced {len(changes)} voice entries in config/voices.yaml (previous file: voices.yaml.bak)", flush=True)
    missing = tts.use_available_voices()
    if missing:
        # The voices the key can use speak instead (pick_voice: the nearest group that has one).
        print(f"{len(missing)} voice IDs in config/voices.yaml are not available to this ElevenLabs key and are "
              "skipped (add them to My Voices to use them): " + ", ".join(missing), flush=True)
    if args.free_voices_only:
        free = tts.use_free_voices_only()
        print(f"Free voices only: {len(free)} premade voices (English, so a foreign accent); library voices skipped",
              flush=True)
    by_id = {customer.customer_id: customer for customer in load_customers()}
    seconds = spoken_seconds()
    generated = 0
    for scenario in Dataset().iter_scenarios(args.limit):
        if seconds >= target_seconds:
            break
        # A caller the CRM does not know (khach_chua_co_danh_tinh) is voiced from the scenario's own honorific.
        customer = by_id.get(scenario.customer_id or "")
        honorific = (customer.honorific if customer else scenario.honorific or "chị").lower()
        gender = "male" if honorific in MALE else "female"
        age_band = "senior" if honorific in SENIOR or scenario.persona == "khach_lon_tuoi" else "adult"
        for call_name, call in scenario.ordered_calls():
            voice = tts.pick_voice("customer", gender, scenario.region, age_band, scenario.customer_id or scenario.customer_phone)
            reference = load_or_build(reference_client, scenario, call_name, call, names)
            for turn_index, text in enumerate(call.customer_turns, start=1):
                spoken = reference["turns"][turn_index - 1] if reference else None
                said = spoken["spoken_text"] if spoken else text
                output = AUDIO_DIR / call_folder(scenario.scenario_id) / call_name / f"turn_{turn_index}.wav"
                if args.resume and output.exists() and _spoken_text(output) == (text, said):
                    continue   # a turn whose words changed (a regenerated scenario) is spoken again
                pcm = tts.synthesize_turn(said, voice, model_id=model_id, language_code=language_code,
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
                processed = add_noise(samples, SAMPLE_RATE, noise_type, noise_snr_db, seed)
                pcm = np.clip(processed * 32767, -32768, 32767).astype("<i2").tobytes()
                write_wav(output, pcm)
                duration = round(len(pcm) / 2 / SAMPLE_RATE, 3)
                output.with_suffix(".json").write_text(json.dumps({
                    "scenario_id": scenario.scenario_id, "call": call_name, "turn": turn_index,
                    "speaker": "customer", "text": text, "input_mode": call.input_mode,
                    # The ASR reference: what the voice read, and the values it states (None for typed chat).
                    "spoken_text": spoken["spoken_text"] if spoken else None,
                    "entities": spoken["entities"] if spoken else None,
                    "reference_source": spoken["reference_source"] if spoken else None,
                    "customer_gender": "m" if gender == "male" else "f",
                    "asr_text": call.customer_turns_asr[turn_index - 1] if turn_index <= len(call.customer_turns_asr) else None,
                    "voice_id": voice, "duration_seconds": duration,
                    "model_id": model_id, "language_code": language_code,
                    "speed": voice_settings.get("speed", 1.0),
                    "noise": {"type": noise_type, "snr_db": noise_snr_db} if noise_type else None,
                    "sample_rate": SAMPLE_RATE,
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                seconds += duration
                generated += 1
                print(f"  audio {scenario.scenario_id}/{call_name}/turn_{turn_index}: {duration:.1f}s, "
                      f"voice …{voice[-4:]}, {noise_type or 'clean'} · {generated} clips this run, "
                      f"{seconds / 3600:.2f}/{target_seconds / 3600:.1f} h, {tts.characters_sent} chars sent"
                      f"{f', {tts.cache_hits} from cache' if tts.cache_hits else ''}", flush=True)
    report = REPORTS_DIR / "elevenlabs_usage.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"characters_sent": tts.characters_sent, "budget": budget,
                                  "mode": "scenario_customer_turns", "turns_generated": generated,
                                  "turns_from_tts_cache": tts.cache_hits,
                                  "audio_hours": round(seconds / 3600, 3), "target_hours": round(target_seconds / 3600, 3)},
                                 indent=2), encoding="utf-8")
    print(f"Scenario turn audio generated: {generated}; characters sent: {tts.characters_sent}/{budget} "
          f"({tts.cache_hits} turns from the TTS cache, not paid); "
          f"audio on disk: {seconds / 3600:.2f} h (target {target_seconds / 3600:.1f} h)")
    print(f"ASR ground truth: {write_ground_truth()}")


if __name__ == "__main__":
    stop_on_daily_limit(main)()
