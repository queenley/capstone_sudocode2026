"""Stage 3b — what the customer says in the reference transcript goes back into the scenario.

The dialogue writer may end a call with a line the scenario never had: the "đúng rồi em" of a read-back
(``call_kinds.py``, ``order_readback``). ``run_eval.py`` plays ``customer_turns`` and nothing else, so without that
line an agent that reads the order back, as PB-09 asks, waits for a yes that never comes and fails ``order.create``.

Offline, no model. Only a transcript that continues the scenario word for word is taken from.

Writes ``<seed>/scenarios/<id>.json``.
"""
from __future__ import annotations

import json
from typing import Any

from src.utils.dataset import Dataset
from src.utils.io import write_json


def spoken_tail(script: list[str], spoken: list[str]) -> list[str]:
    """The lines *spoken* has after *script*, when *script* is a strict prefix of it; otherwise nothing."""
    return spoken[len(script):] if script and len(spoken) > len(script) and spoken[:len(script)] == script else []


def extend(call: dict[str, Any], spoken: list[str]) -> list[str]:
    """Add to the *call* (raw JSON) the lines missing from its script; the lines added."""
    asr = bool(call.get("customer_turns_asr")) and call.get("input_mode") != "text"
    tail = spoken_tail(call["customer_turns_asr"] if asr else call["customer_turns"], spoken)
    if asr and tail:
        call["customer_turns_asr"] += tail
    if tail:
        # An ASR call's two lists stay aligned, one line for one; the written form of a new line is what ASR heard.
        call["customer_turns"] += tail
    return tail


def main() -> None:
    dataset = Dataset()
    added = 0
    for path in sorted(dataset.scenarios_dir.glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for name, call in scenario["calls"].items():
            transcript = dataset.conversation_path(scenario["scenario_id"], name)
            if not transcript.exists():
                continue
            turns = json.loads(transcript.read_text(encoding="utf-8"))["turns"]
            tail = extend(call, [turn["text"] for turn in turns if turn["speaker"] == "customer"])
            added += len(tail)
            changed = changed or bool(tail)
        if changed:
            write_json(path, scenario)
    print(f"Customer lines taken from the transcripts: {added}")


if __name__ == "__main__":
    main()
