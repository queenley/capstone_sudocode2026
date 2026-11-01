"""The generated dataset on disk. This module is the only one that knows where a file goes.

Each fact is stored once, under the seed folder (``data/seed-<name>/`` at the repository root,
``src/utils/paths.py``)::

    <seed>/
      scenarios/<id>.json                          the test case, BTC sample format (Scenario.btc_export)
      metadata/<id>.json                           the pipeline's fields: customer id, region, tags, call kinds
      call_brief/scenarios_<id>/call_<n>.json      expected CallBrief at the start of a call the agent has context for
      handoff_brief/scenarios_<id>/call_<n>.json   expected HandoffBrief of a call that ends with chuyen_may
      tools/scenarios_<id>/call_<n>.json           the ideal agent's tool calls, run on mock_tools: [{name, args, result}]
      trace_log/scenarios_<id>/call_<n>.jsonl      the ideal agent's trace_log rows, one per customer turn
      conversations/scenarios_<id>/call_<n>.json   reference transcript (generate_dialogue)
      judgments/scenarios_<id>/call_<n>.json       LLM-judge verdict on that transcript (llm_judge)
      audio/scenarios_<id>/call_<n>/turn_<k>.wav   the customer's turn, spoken (+ .json beside it)

:meth:`Dataset.write_scenario` splits a :class:`Scenario` into the first five;
:meth:`Dataset.load_scenario` puts it back together for the later stages.
``Dataset(root)`` writes the same layout elsewhere (``--plan-only`` uses ``<seed>/plan_preview``).
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

from pydantic import ValidationError

from src.schemas import keys
from src.schemas.conversation import Conversation, split_conversation_id
from src.schemas.scenario import CallSpec, Scenario
from src.utils.io import load_model, write_json
from src.utils.paths import OUTPUT_DIR

#: Folders of one file per call, written with the scenario.
SCENARIO_CALL_ARTIFACTS = ("call_brief", "handoff_brief", "tools")
#: Every folder this module owns, removed by :meth:`Dataset.clear`.
FOLDERS = ("scenarios", "metadata", *SCENARIO_CALL_ARTIFACTS, "trace_log", "conversations", "judgments")


def call_folder(scenario_id: str) -> str:
    """``scenarios_<id>``: the per-scenario folder name, as the audio and BTC's ASR set name it."""
    return f"scenarios_{scenario_id}"


class Dataset:
    def __init__(self, root: Path = OUTPUT_DIR) -> None:
        self.root = root
        self.scenarios_dir = root / "scenarios"
        self.metadata_dir = root / "metadata"
        self._loaded: dict[str, Scenario | None] = {}

    # -- paths ------------------------------------------------------------------------
    def call_path(self, artifact: str, scenario_id: str, call: str, suffix: str = ".json") -> Path:
        return self.root / artifact / call_folder(scenario_id) / f"{call}{suffix}"

    def conversation_path(self, scenario_id: str, call: str) -> Path:
        return self.call_path("conversations", scenario_id, call)

    def judgment_path(self, scenario_id: str, call: str) -> Path:
        return self.call_path("judgments", scenario_id, call)

    def conversation_file(self, conversation_id: str) -> Path:
        """The transcript of ``<scenario_id>__<call>``."""
        return self.conversation_path(*split_conversation_id(conversation_id))

    def judgment_file(self, conversation_id: str) -> Path:
        return self.judgment_path(*split_conversation_id(conversation_id))

    def trace_path(self, scenario_id: str, call: str) -> Path:
        return self.call_path("trace_log", scenario_id, call, ".jsonl")

    # -- scenarios ----------------------------------------------------------------------
    def write_scenario(self, scenario: Scenario) -> Path:
        sid = scenario.scenario_id
        for artifact in SCENARIO_CALL_ARTIFACTS:   # a regenerated scenario may have lost a brief
            shutil.rmtree(self.root / artifact / call_folder(sid), ignore_errors=True)
        exported = scenario.btc_export()
        # Every key, type and value as contracts/scenario/scenario-keys.yaml allows: a new key is added there first.
        errors = keys.check_scenario(exported)
        if errors:
            raise ValueError(f"{sid} breaks {keys.KEYS_FILE.name}: " + "; ".join(errors[:8])
                             + (f" (+{len(errors) - 8} more)" if len(errors) > 8 else ""))
        write_json(self.scenarios_dir / f"{sid}.json", exported)
        write_json(self.metadata_dir / f"{sid}.json", scenario.metadata())
        for name, call in scenario.ordered_calls():
            for artifact, value in (("call_brief", call.expected_call_brief),
                                    ("handoff_brief", call.expected_handoff_brief),
                                    ("tools", call.oracle_tool_calls)):
                if value:
                    write_json(self.call_path(artifact, sid, name), value)
        return self.scenarios_dir / f"{sid}.json"

    def scenario_ids(self) -> list[str]:
        return sorted(p.stem for p in self.scenarios_dir.glob("*.json") if not p.name.startswith("_"))

    def has_scenario(self, scenario_id: str) -> bool:
        return (self.scenarios_dir / f"{scenario_id}.json").exists() and (self.metadata_dir / f"{scenario_id}.json").exists()

    def load_scenario(self, scenario_id: str) -> Scenario:
        exported = _read(self.scenarios_dir / f"{scenario_id}.json")
        meta = _read(self.metadata_dir / f"{scenario_id}.json")
        calls: dict[str, CallSpec] = {}
        previous: date | None = None
        for name, payload in exported["calls"].items():
            on = date.fromisoformat(payload["call_date"]) if "call_date" in payload else previous + timedelta(
                days=payload["days_later"])
            extra = dict(meta["calls"].get(name, {}))
            # BTC's file says "khac" for the pipeline's finer outcomes; the metadata keeps which one.
            payload = {**payload, "expected_outcome": extra.pop("outcome_detail", None) or payload["expected_outcome"]}
            detail = extra.pop("input_mode_detail", None)
            if detail and detail != "text":
                payload["input_mode"] = detail
            calls[name] = CallSpec(
                **{k: v for k, v in payload.items() if k not in {"call_date"}}, call_date=on,
                expected_call_brief=self._optional("call_brief", scenario_id, name),
                expected_handoff_brief=self._optional("handoff_brief", scenario_id, name),
                oracle_tool_calls=self._optional("tools", scenario_id, name) or [],
                **extra)
            previous = on
        header = {k: v for k, v in exported.items() if k != "calls"}
        return Scenario(**header, **{k: v for k, v in meta.items() if k not in {"scenario_id", "calls"}}, calls=calls)

    def scenario(self, scenario_id: str) -> Scenario | None:
        """:meth:`load_scenario`, once per id; ``None`` when it is missing or unreadable."""
        if scenario_id not in self._loaded:
            try:
                self._loaded[scenario_id] = self.load_scenario(scenario_id)
            except (ValidationError, ValueError, KeyError, FileNotFoundError):
                self._loaded[scenario_id] = None
        return self._loaded[scenario_id]

    def iter_scenarios(self, limit: int | None = None) -> Iterator[Scenario]:
        """Every scenario on disk, in id order; a file of an older schema is reported once and skipped."""
        for sid in self.scenario_ids()[:limit]:
            try:
                yield self.load_scenario(sid)
            except (ValidationError, ValueError, KeyError, FileNotFoundError) as error:
                print(f"[skip] {sid}: {type(error).__name__}: {str(error).splitlines()[0]}", file=sys.stderr)

    def _optional(self, artifact: str, scenario_id: str, call: str) -> Any:
        path = self.call_path(artifact, scenario_id, call)
        return _read(path) if path.exists() else None

    # -- per-call outputs of later stages -------------------------------------------------
    def conversation_paths(self) -> list[Path]:
        return sorted((self.root / "conversations").glob("scenarios_*/call_*.json"))

    def judgment_paths(self) -> list[Path]:
        return sorted((self.root / "judgments").glob("scenarios_*/call_*.json"))

    def iter_conversations(self, limit: int | None = None) -> Iterator[Conversation]:
        for path in self.conversation_paths()[:limit]:
            try:
                yield load_model(path, Conversation)
            except (ValidationError, ValueError) as error:
                print(f"[skip] {path}: {str(error).splitlines()[0]}", file=sys.stderr)

    def write_trace(self, scenario_id: str, call: str, rows: list[dict[str, Any]]) -> None:
        path = self.trace_path(scenario_id, call)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), encoding="utf-8")

    def clear(self) -> None:
        """Remove every generated scenario, artifact, transcript and verdict (not audio, not reports)."""
        for folder in FOLDERS:
            shutil.rmtree(self.root / folder, ignore_errors=True)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))
