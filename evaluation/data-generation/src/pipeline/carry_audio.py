"""Bring a previous revision's clips into this seed, so only the turns that changed are spoken.

Copies ``asr_reference/`` and, for every customer turn, the clip of a previous revision with the same words in the
same call, wherever that turn stood: a line added earlier in the call moves the turns after it, not their audio.
Offline, and nothing on disk is replaced. ``synthesize_scenario_audio --changed-only`` speaks what is left.

    DATAGEN_SEED=dev-r3 python -m src.pipeline.carry_audio --from dev-r2
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from src.schemas.scenario import Scenario
from src.utils.dataset import Dataset, call_folder
from src.utils.paths import ASR_REFERENCE_DIR, AUDIO_DIR, REPO_ROOT


def clips_by_words(folder: Path) -> dict[str, Path]:
    """Turn text -> its clip's metadata, for the clips of one call that have their WAV."""
    found: dict[str, Path] = {}
    for path in sorted(folder.glob("turn_*.json")):
        if path.with_suffix(".wav").exists():
            found.setdefault(json.loads(path.read_text(encoding="utf-8"))["text"], path)
    return found


def carry_call(scenario: Scenario, call_name: str, base: Path, audio_root: Path) -> tuple[int, int]:
    """``(clips carried, turns left to speak)`` of one call; a call the base never spoke counts for neither."""
    folder = audio_root / call_folder(scenario.scenario_id) / call_name
    clips = clips_by_words(base / "audio" / call_folder(scenario.scenario_id) / call_name)
    if not clips:
        return 0, 0
    carried = left = 0
    for turn, text in enumerate(scenario.calls[call_name].customer_turns, start=1):
        target = folder / f"turn_{turn}.wav"
        if target.exists():
            continue
        if text not in clips:
            left += 1
            continue
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(clips[text].with_suffix(".wav"), target)
        meta = json.loads(clips[text].read_text(encoding="utf-8"))
        target.with_suffix(".json").write_text(json.dumps({**meta, "turn": turn}, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
        carried += 1
    return carried, left


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="base", required=True, help="the seed to copy from, a folder under data/")
    args = parser.parse_args()
    base = REPO_ROOT / "data" / args.base
    if (base / "asr_reference").exists() and not ASR_REFERENCE_DIR.exists():
        shutil.copytree(base / "asr_reference", ASR_REFERENCE_DIR)
    carried = left = 0
    for scenario in Dataset().iter_scenarios():
        for call_name, _ in scenario.ordered_calls():
            one, other = carry_call(scenario, call_name, base, AUDIO_DIR)
            carried, left = carried + one, left + other
    print(f"{carried} clips carried from {base.name}; {left} turns of those calls still to speak.")


if __name__ == "__main__":
    main()
