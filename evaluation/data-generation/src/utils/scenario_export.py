"""Write a generated scenario to its three on-disk forms."""
from __future__ import annotations

import json
from pathlib import Path

from src.schemas.scenario import Scenario
from src.utils.io import write_json
from src.utils.paths import AUDIO_DIR, SCENARIOS_DIR, SCENARIOS_INTERNAL_DIR


def write_scenario(scenario: Scenario) -> Path:
    """Internal file (all fields), BTC export, and one JSON stub per customer turn for TTS."""
    internal = SCENARIOS_INTERNAL_DIR / f"{scenario.scenario_id}.json"
    write_json(internal, scenario)
    write_json(SCENARIOS_DIR / f"{scenario.scenario_id}.json", scenario.btc_export())
    write_turn_artifacts(scenario, AUDIO_DIR)
    return internal


def write_turn_artifacts(scenario: Scenario, audio_root: Path) -> None:
    """``audio/scenarios_<id>/call_<n>/turn_<k>.json`` — text the TTS stage will speak."""
    for call_name, call in scenario.ordered_calls():
        # Audio speaks the clean utterance; the ASR/teencode line is kept as the expected noisy transcript.
        for turn_index, text in enumerate(call.customer_turns, start=1):
            asr = call.customer_turns_asr[turn_index - 1] if turn_index <= len(call.customer_turns_asr) else None
            write_json(audio_root / f"scenarios_{scenario.scenario_id}" / call_name / f"turn_{turn_index}.json", {
                "scenario_id": scenario.scenario_id, "call": call_name, "turn": turn_index,
                "speaker": "customer", "text": text, "asr_text": asr, "input_mode": call.input_mode,
                "customer_goal": call.customer_goal, "expected_outcome": call.expected_outcome,
            })


def write_combined_export(paths: list[Path], destination: Path) -> int:
    """``scenarios_all.json`` in the shape the BTC analysis notebook reads."""
    records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    write_json(destination, records)
    return len(records)
