"""Team ASR test set (Điều chỉnh đề §8: "≥ 20 file của team") in BTC ``asr/`` format.

Output ``output/asr_test/``::

    ground_truth.json            {description, hypotheses_format, normalization_rule, reference_date,
                                  dialogues: [{id, customer_region, customer_gender, agent_gender, agent_region,
                                               scenario_ref, noisy, note, entities, full_text, n_turns,
                                               turns: [{idx, speaker: A|C, text, entities}]}]}
    audio/<id>.wav               16 kHz mono, agent + customer voices (ElevenLabs)
    audio/<id>.segments.json     {"segments": [{"speaker": "A"|"C", "start": s, "end": s}]}  (M2 diarization)

Every dialogue comes from a reference transcript (one call). Text is converted to
spoken form (``src/asr/spoken.py``: numbers/dates/codes as words, like BTC D01–D04)
and that exact string is sent to TTS, so the reference is correct by construction.
``noisy_fraction`` of the dialogues get telephone-band + packet-loss ("weak_signal")
noise, mirroring BTC's 4/12 noisy dialogues.

    python -m src.pipeline.build_asr_testset --limit 24 --text-only   # ground truth only, no API
    python -m src.pipeline.build_asr_testset --limit 24              # + ElevenLabs audio
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from pathlib import Path
from typing import Any

from src.asr.spoken import to_spoken
from src.schemas.conversation import AgentTurn, Conversation, split_conversation_id
from src.schemas.scenario import Scenario
from src.utils.crm import load_customers
from src.utils.dataset import Dataset
from src.utils.paths import ASR_TEST_DIR, CONFIG_DIR, DATA_DIR
from src.utils.settings import load_settings

ASR_DIR = ASR_TEST_DIR
SAMPLE_RATE = 16000
TURN_GAP_S = 0.35
ENTITY_KEYS = ("price_vnd", "room_area_m2", "budget_vnd", "size", "order_id", "has_children", "payment",
               "child_age_months", "competitor_price_vnd", "restock_date", "refund_vnd")
MALE_HONORIFICS = {"anh", "chú", "ông", "em trai", "bác trai"}


def dialogue_entities(scenario: Scenario, call_name: str) -> dict[str, Any]:
    call = scenario.calls[call_name]
    facts = {**call.facts_established, **call.ground_truth_facts}
    entities = {k: facts[k] for k in ENTITY_KEYS if k in facts and facts[k] is not None}
    sku = call.facts_established.get("variant_sku") or call.facts_established.get("product_advised")
    if sku:
        entities["sku"] = sku
    return entities


def build_dialogue(index: int, scenario: Scenario, conversation: Conversation, customer, noisy: bool) -> dict[str, Any]:
    turns = []
    for idx, turn in enumerate(conversation.turns, start=1):
        item = turn.root
        speaker = "A" if isinstance(item, AgentTurn) else "C"
        entities = {c.field: c.value for c in item.claims if c.field in ENTITY_KEYS} if speaker == "A" else \
            {k: v for k, v in item.facts_stated.items() if k in ENTITY_KEYS}
        turns.append({"idx": idx, "speaker": speaker, "text": to_spoken(item.text), "entities": entities})
    honorific = (customer.honorific if customer else scenario.honorific or "").lower()
    return {
        "id": f"T{index:02d}", "customer_region": scenario.region,
        "customer_gender": "m" if honorific in MALE_HONORIFICS else "f",
        "agent_gender": "f", "agent_region": scenario.region,
        "scenario_ref": f"{scenario.scenario_id} {conversation.call}", "noisy": noisy,
        "note": f"{scenario.persona}; {scenario.hard_case or 'normal'}",
        "entities": dialogue_entities(scenario, conversation.call),
        "full_text": " ".join(t["text"] for t in turns), "n_turns": len(turns), "turns": turns,
    }


def synthesize(dialogue: dict[str, Any], customer_id: str, tts, audio_cfg: dict, out_dir: Path) -> None:
    import numpy as np

    from src.utils.audio_noise import add_noise

    pieces, segments, cursor = [], [], 0.0
    gap = np.zeros(int(TURN_GAP_S * SAMPLE_RATE), dtype=np.float32)
    for turn in dialogue["turns"]:
        if turn["speaker"] == "A":
            voice = tts.pick_voice("agent", "female", dialogue["agent_region"], "adult", "agent")
        else:
            gender = "male" if dialogue["customer_gender"] == "m" else "female"
            voice = tts.pick_voice("customer", gender, dialogue["customer_region"], "adult", customer_id)
        pcm = tts.synthesize_turn(turn["text"], voice, model_id=audio_cfg.get("model_id", "eleven_v4"),
                                  language_code=audio_cfg.get("language_code"))
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        segments.append({"speaker": turn["speaker"], "start": round(cursor, 3),
                         "end": round(cursor + len(samples) / SAMPLE_RATE, 3)})
        pieces += [samples, gap]
        cursor += (len(samples) + len(gap)) / SAMPLE_RATE
    audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)
    seed = int.from_bytes(hashlib.sha256(dialogue["id"].encode()).digest()[:4], "big")
    audio = add_noise(audio, SAMPLE_RATE, "weak_signal" if dialogue["noisy"] else None, 10, seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_dir / f"{dialogue['id']}.wav"), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    (out_dir / f"{dialogue['id']}.segments.json").write_text(
        json.dumps({"segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=24, help="number of dialogues (BTC asks for ≥ 20)")
    parser.add_argument("--noisy-fraction", type=float, default=1 / 3)
    parser.add_argument("--text-only", action="store_true", help="write ground_truth.json without TTS")
    args = parser.parse_args()

    dataset = Dataset()
    conversations = list(dataset.iter_conversations())
    if not conversations:
        sys.exit("No reference transcripts in output/conversations; run generate_dialogue first.")
    customers = {c.customer_id: c for c in load_customers()}
    dialogues = []
    # Prefer variety: interleave hard cases and normal calls by taking every other conversation first.
    ordered = conversations[::2] + conversations[1::2]
    for conversation in ordered:
        if len(dialogues) >= args.limit:
            break
        scenario = dataset.scenario(conversation.scenario_id)
        if scenario is None:
            continue
        index = len(dialogues) + 1
        noisy = (index % round(1 / args.noisy_fraction) == 0) if args.noisy_fraction > 0 else False
        dialogues.append(build_dialogue(index, scenario, conversation, customers.get(conversation.customer_id), noisy))

    btc = json.loads((DATA_DIR / "asr" / "ground_truth.json").read_text(encoding="utf-8"))
    ground_truth = {
        "description": f"Bộ ASR của team: {len(dialogues)} hội thoại đa lượt sinh từ reference transcript + TTS "
                       f"({sum(d['noisy'] for d in dialogues)} hội thoại băng thông điện thoại có nhiễu).",
        "hypotheses_format": btc["hypotheses_format"], "normalization_rule": btc["normalization_rule"],
        "reference_date": btc["reference_date"], "dialogues": dialogues,
    }
    ASR_DIR.mkdir(parents=True, exist_ok=True)
    (ASR_DIR / "ground_truth.json").write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(dialogues)} dialogues -> {ASR_DIR / 'ground_truth.json'}")
    if args.text_only:
        return

    from src.elevenlabs_client import ElevenLabsClient

    settings = load_settings()
    tts = ElevenLabsClient(CONFIG_DIR / "voices.yaml", ASR_DIR / "audio", settings["budget"]["max_elevenlabs_chars_per_run"])
    for dialogue in dialogues:
        customer_id = next((c.customer_id for c in conversations
                            if f"{split_conversation_id(c.conversation_id)[0]} {c.call}" == dialogue["scenario_ref"]), "x")
        synthesize(dialogue, customer_id, tts, settings.get("scenario_audio", {}), ASR_DIR / "audio")
        print(f"  audio {dialogue['id']} ({dialogue['n_turns']} turns, noisy={dialogue['noisy']})", flush=True)
    print(f"ElevenLabs characters sent: {tts.characters_sent}")


if __name__ == "__main__":
    main()
