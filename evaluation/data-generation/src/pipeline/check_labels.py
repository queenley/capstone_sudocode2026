"""Stage 7c — do the labels agree with what the customer says?

``oracle_perfect`` proves little: the oracle's trace is built from the labels, so it always passes. Three checks that
can fail, offline:

* ``truncated``: the reference transcript has customer lines after the scenario's last one.
* ``no_consent``: ``success_if`` wants ``order.create`` and no line of the customer's, in the last two, is a yes. An
  agent that reads the order back (PB-09) has nothing to act on, and one that orders anyway orders without consent.
* ``reference_fails``: the reference transcript, an agent that was written, not derived from the labels, fails BTC's
  ``check_call`` (``reports/reference_report.json``, from ``build_ground_truth``). Listed for a person to read.

Writes ``<seed>/reports/label_check.json``. Exit 0 always: a finding is for a reviewer, not a reason to stop the run.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from src.pipeline.sync_customer_turns import spoken_tail
from src.utils.dataset import Dataset
from src.utils.io import write_json
from src.utils.paths import OUTPUT_DIR

#: What a customer's yes sounds like, without diacritics (the agent's own, stricter rule: ``purchase.agrees``).
YES = re.compile(r"\b(dung roi|dong y|xac nhan|chinh xac|len don|chot|dat (don|hang)|lam don|ghi don|vang|u)\b")


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def has_consent(turns: list[str]) -> bool:
    return any(YES.search(_plain(turn)) for turn in turns[-2:])


def check(scenario: dict[str, Any], dataset: Dataset) -> list[dict[str, Any]]:
    found = []
    for name, call in scenario["calls"].items():
        where = {"scenario_id": scenario["scenario_id"], "call": name}
        script = call.get("customer_turns_asr") if call.get("input_mode") != "text" and call.get("customer_turns_asr") else call["customer_turns"]
        path = dataset.conversation_path(scenario["scenario_id"], name)
        if path.exists():
            spoken = [t["text"] for t in json.loads(path.read_text(encoding="utf-8"))["turns"] if t["speaker"] == "customer"]
            if spoken_tail(script, spoken):
                found.append({**where, "check": "truncated", "missing": spoken_tail(script, spoken)})
        if (call.get("success_if") or {}).get("tool_called") == "order.create" and not has_consent(script):
            found.append({**where, "check": "no_consent", "last_line": script[-1]})
    return found


def main() -> None:
    dataset = Dataset()
    found = [item for path in sorted(dataset.scenarios_dir.glob("*.json"))
             for item in check(json.loads(path.read_text(encoding="utf-8")), dataset)]
    reference = OUTPUT_DIR / "reports" / "reference_report.json"
    if reference.exists():
        failures = (json.loads(reference.read_text(encoding="utf-8")).get("task_success_rate") or {}).get("failures") or []
        found += [{"scenario_id": f["scenario"], "call": f["call"], "check": "reference_fails", "reasons": f["reasons"]} for f in failures]
    write_json(OUTPUT_DIR / "reports" / "label_check.json", found)
    counts: dict[str, int] = {}
    for item in found:
        counts[item["check"]] = counts.get(item["check"], 0) + 1
    print(f"Label check: {counts or 'nothing found'}")


if __name__ == "__main__":
    main()
