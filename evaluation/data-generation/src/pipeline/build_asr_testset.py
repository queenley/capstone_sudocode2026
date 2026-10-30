"""Team ASR dialogue set (Điều chỉnh đề §8: "≥ 20 file của team") in BTC ``asr/`` format: whole calls, two speakers.

Like BTC's D01–D04, each item is one call: the shop agent and the customer, each in their own voice, one after the
other, so the set measures what the per-turn clips cannot: a two-person recording and diarization (who spoke when).

Output ``<seed>/asr_test/``::

    ground_truth.json            {description, hypotheses_format, normalization_rule, reference_date, kind: "dialogues",
                                  entity_schema, dialogues: [{id, customer_region, customer_gender, agent_gender,
                                  agent_region, scenario_ref, noisy, note, entities, full_text, n_turns,
                                  turns: [{idx, speaker: A|C, text, entities, reference_source}]}]}
    spoken/scenarios_<id>/call_<n>.json   the model's spoken form of each line (``src/asr/reference.py``), cached
    audio/<id>.wav               16 kHz mono, agent + customer voices (ElevenLabs)
    audio/<id>.segments.json     {"segments": [{"speaker": "A"|"C", "start": s, "end": s}]}  (diarization truth)

Every dialogue comes from a reference transcript (one call). A model writes every line of both speakers in spoken
form (numbers, money, codes and brand names as words) with the entities it states, under the same rules and checks
as the per-turn clips; that exact string is sent to TTS, so the reference is right by construction. A dialogue's
``entities`` are its turns' entities, the last value of a key winning. Calls in typed chat are not speech and are
skipped. ``noisy_fraction`` of the dialogues get telephone-band + packet-loss ("weak_signal") noise, as BTC's 4/12.

    python -m src.pipeline.build_asr_testset --limit 24 --text-only   # spoken forms + ground_truth.json, no TTS
    python -m src.pipeline.build_asr_testset --limit 24              # + ElevenLabs audio and segments
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from pathlib import Path
from typing import Any

from src.asr.reference import AGENT, CUSTOMER, NOT_SPEECH, load_or_build
from src.schemas.asr import entity_schema
from src.schemas.conversation import AgentTurn, Conversation, split_conversation_id
from src.schemas.scenario import Scenario
from src.utils.crm import SourceData, load_customers
from src.utils.dataset import Dataset
from src.utils.paths import ASR_TEST_DIR, CONFIG_DIR, DATA_DIR
from src.utils.quota import stop_on_daily_limit
from src.utils.settings import load_settings, model_client

ASR_DIR = ASR_TEST_DIR
SAMPLE_RATE = 16000
TURN_GAP_S = 0.35
MALE_HONORIFICS = {"anh", "chú", "ông", "em trai", "bác trai"}


def conversation_lines(conversation: Conversation) -> list[dict[str, Any]]:
    """Both speakers' lines of a reference transcript, in order: ``{idx, speaker: A|C, text}``."""
    return [{"idx": idx, "speaker": AGENT if isinstance(turn.root, AgentTurn) else CUSTOMER, "text": turn.root.text}
            for idx, turn in enumerate(conversation.turns, start=1)]


def build_dialogue(index: int, scenario: Scenario, conversation: Conversation, customer, reference: dict[str, Any],
                   noisy: bool) -> dict[str, Any]:
    turns = [{"idx": t["idx"], "speaker": t["speaker"], "text": t["spoken_text"], "entities": t["entities"],
              "reference_source": t["reference_source"]} for t in reference["turns"]]
    entities: dict[str, Any] = {}
    for turn in turns:
        entities.update(turn["entities"])
    honorific = (customer.honorific if customer else scenario.honorific or "").lower()
    return {
        "id": f"T{index:02d}", "customer_region": scenario.region,
        "customer_gender": "m" if honorific in MALE_HONORIFICS else "f",
        "agent_gender": "f", "agent_region": scenario.region,
        "scenario_ref": f"{scenario.scenario_id} {conversation.call}", "noisy": noisy,
        "note": f"{scenario.persona}; {scenario.hard_case or 'normal'}",
        "entities": entities, "full_text": " ".join(t["text"] for t in turns), "n_turns": len(turns), "turns": turns,
    }


def synthesize(dialogue: dict[str, Any], customer_id: str, tts, audio_cfg: dict, out_dir: Path) -> None:
    import numpy as np

    from src.utils.audio_noise import add_noise

    pieces, segments, cursor = [], [], 0.0
    gap = np.zeros(int(TURN_GAP_S * SAMPLE_RATE), dtype=np.float32)
    for turn in dialogue["turns"]:
        if turn["speaker"] == AGENT:
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
    parser.add_argument("--text-only", action="store_true", help="spoken forms and ground_truth.json, without TTS")
    args = parser.parse_args()

    dataset = Dataset()
    conversations = list(dataset.iter_conversations())
    if not conversations:
        sys.exit("No reference transcripts in <seed>/conversations; run generate_dialogue first.")
    settings = load_settings()
    customers = {c.customer_id: c for c in load_customers()}
    names = {product.sku: product.name for product in SourceData.load().catalog.products}
    clients: list = []

    def reference_client():
        if not clients:
            clients.append(model_client("asr_reference", settings))
        return clients[0]

    dialogues, sources = [], {}
    # Prefer variety: interleave hard cases and normal calls by taking every other conversation first.
    for conversation in conversations[::2] + conversations[1::2]:
        if len(dialogues) >= args.limit:
            break
        scenario = dataset.scenario(conversation.scenario_id)
        if scenario is None or conversation.call not in scenario.calls:
            continue
        call = scenario.calls[conversation.call]
        if call.input_mode in NOT_SPEECH:
            continue   # typed chat: nobody says it
        reference = load_or_build(reference_client, scenario, conversation.call, call, names,
                                  root=ASR_DIR / "spoken", lines=conversation_lines(conversation))
        if reference is None:
            continue
        index = len(dialogues) + 1
        noisy = (index % round(1 / args.noisy_fraction) == 0) if args.noisy_fraction > 0 else False
        dialogues.append(build_dialogue(index, scenario, conversation, customers.get(conversation.customer_id), reference, noisy))
        sources[dialogues[-1]["id"]] = conversation

    btc = json.loads((DATA_DIR / "asr" / "ground_truth.json").read_text(encoding="utf-8"))
    sources_by_kind = [t["reference_source"] for d in dialogues for t in d["turns"]]
    ground_truth = {
        "description": f"Bộ ASR hội thoại của team: {len(dialogues)} cuộc gọi hai người nói (agent + khách) sinh từ "
                       f"reference transcript; LLM viết từng câu ở dạng nói rồi TTS đọc đúng câu đó "
                       f"({sources_by_kind.count('llm')} câu LLM, {sources_by_kind.count('rule')} câu theo luật); "
                       f"{sum(d['noisy'] for d in dialogues)} hội thoại băng thông điện thoại có nhiễu.",
        "hypotheses_format": btc["hypotheses_format"], "normalization_rule": btc["normalization_rule"],
        "reference_date": btc["reference_date"], "kind": "dialogues",
        # Not in BTC's file: the entity keys and types, so the evaluator extracts the same ones from what was heard.
        "entity_schema": entity_schema(), "dialogues": dialogues,
    }
    ASR_DIR.mkdir(parents=True, exist_ok=True)
    (ASR_DIR / "ground_truth.json").write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(dialogues)} dialogues -> {ASR_DIR / 'ground_truth.json'}")
    if args.text_only:
        return

    from src.elevenlabs_client import ElevenLabsClient

    tts = ElevenLabsClient(CONFIG_DIR / "voices.yaml", ASR_DIR / "audio", settings["budget"]["max_elevenlabs_chars_per_run"])
    for dialogue in dialogues:
        customer_id = sources[dialogue["id"]].customer_id or split_conversation_id(sources[dialogue["id"]].conversation_id)[0]
        synthesize(dialogue, customer_id, tts, settings.get("scenario_audio", {}), ASR_DIR / "audio")
        print(f"  audio {dialogue['id']} ({dialogue['n_turns']} turns, noisy={dialogue['noisy']})", flush=True)
    print(f"ElevenLabs characters sent: {tts.characters_sent}")


if __name__ == "__main__":
    stop_on_daily_limit(main)()
