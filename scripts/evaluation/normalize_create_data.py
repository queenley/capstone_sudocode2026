"""Create a diagnostic revision of ``scripts/create_data`` output; never edit its source.

    python normalize_create_data.py [--source ../create_data/output/scenarios] [--name create-data-diagnostic-v3]

Writes ``datasets/<name>/`` (refusing to overwrite) and registers it in
``datasets/registry.json`` with status ``diagnostic``:

- ``scenarios/``: every source scenario the harness can run, converted only
  where the team ``Scenario`` contract differs from the generator's output;
- ``tool-labels.json``: the positive tool label of each call, taken from its
  own ``success_if.tool_called``/``args_match`` (the registry's rule);
- ``conversion-report.json``: source hashes, every changed field, and every
  excluded scenario with its reason.

Conversions (each recorded per call):

- ``expected_outcome`` outside BTC's five values becomes ``khac``, as
  ``normalize_output1.py`` does (``cap_nhat_don``, ``thong_tin``, ...);
- a list ``success_if.agent_must_say`` becomes one string: BTC's
  ``reference_eval.check_call`` reads only that the key is present;
- a missing scenario ``hard_case`` becomes ``null``; a missing ``notes`` ``""``.

Exclusions, never silent drops (``datasets/ground-truth-review/SKILL.md``):

- ``CUSTOMER_NOT_IN_PINNED_CRM``: a ``customer_id`` neither in the organisers'
  ``crm_seed.json`` nor in the synthetic CRM the agent and the harness's mock
  add (``apps/ai-agent-service/data/btc/catalog/crm_seed_synthetic.json``,
  pinned by each run), so CRM-derived GT would not hold. The report records
  that file's hash: a synthetic scenario holds only with the file it was made from.
- ``SCHEMA_INVALID``: anything else the contract still rejects.

The labels are the generator's, not a human's: ``official_gt_approved`` is
``false`` and the set stays ``diagnostic`` until reviewed.
"""
import os
import subprocess
import sys

# Windows reads files as cp1252 unless told otherwise; the BTC files are UTF-8.
if __name__ == "__main__" and not sys.flags.utf8_mode:
    raise SystemExit(subprocess.call([sys.executable, "-X", "utf8", *sys.argv], env={**os.environ, "PYTHONUTF8": "1"}))

import argparse  # noqa: E402
import copy  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

from eval_harness.contracts import ROOT as CONTRACTS, validate  # noqa: E402

ROOT = Path(__file__).resolve().parent
DATASETS = ROOT / "datasets"
SOURCE = ROOT.parent / "create_data" / "output" / "scenarios"
OUTCOMES = {"hen_goi_lai", "chot_don", "chuyen_may", "tu_choi", "khac"}
SYNTHETIC_CRM = ROOT.parent.parent / "apps/ai-agent-service/data/btc/catalog/crm_seed_synthetic.json"


def official_customers():
    """The customers a run's mock knows: the organisers' 50, then the synthetic ones."""
    customers = json.loads((CONTRACTS / "sources/btc/catalog/crm_seed.json").read_text(encoding="utf-8"))["customers"]
    if SYNTHETIC_CRM.exists():
        customers += json.loads(SYNTHETIC_CRM.read_text(encoding="utf-8"))["customers"]
    return {c["customer_id"] for c in customers}


def convert(source, customers):
    """``(scenario, changes, None)``, or ``(None, [], reason)`` when it cannot run."""
    scenario = copy.deepcopy(source)
    sid = scenario.get("scenario_id")
    if scenario.get("customer_id") and scenario["customer_id"] not in customers:
        return None, [], {"code": "CUSTOMER_NOT_IN_PINNED_CRM", "customer_id": scenario["customer_id"]}
    changes = []
    for key, default in (("hard_case", None), ("notes", "")):
        if key not in scenario:
            scenario[key] = default
            changes.append({"call": None, "field": key, "before": "<missing>", "after": default})
    for name, spec in scenario["calls"].items():
        outcome = spec.get("expected_outcome")
        if outcome is not None and outcome not in OUTCOMES:
            spec["expected_outcome"] = "khac"
            changes.append({"call": name, "field": "expected_outcome", "before": outcome, "after": "khac"})
        success = spec.get("success_if") or {}
        if isinstance(success.get("agent_must_say"), list):
            joined = " | ".join(success["agent_must_say"])
            changes.append({"call": name, "field": "success_if/agent_must_say",
                            "before": success["agent_must_say"], "after": joined})
            success["agent_must_say"] = joined
    try:
        validate("Scenario", scenario)
    except ValueError as error:
        return None, [], {"code": "SCHEMA_INVALID", "message": str(error)[:300]}
    if sid is None:
        return None, [], {"code": "SCHEMA_INVALID", "message": "no scenario_id"}
    return scenario, changes, None


def tool_labels(scenario):
    """Per call, the required tool of its ``success_if``, as ``data_registry`` checks it."""
    labels = {}
    for name, spec in scenario["calls"].items():
        success = spec.get("success_if") or {}
        tool = success.get("tool_called")
        labels[name] = ([{"name": tool, "args_match": success.get("args_match", {}), "required": True}]
                        if tool else [])
    return labels


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--name", default="create-data-diagnostic-v3")
    args = parser.parse_args(argv)
    source, target = args.source.resolve(), DATASETS / args.name
    registry_path = DATASETS / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if target.exists() or any(group["id"] == args.name for group in registry["sets"]):
        # A revision is never overwritten: a run may already depend on it.
        print(f"Dataset {args.name!r} already exists in {target.relative_to(ROOT)}; nothing to do.")
        print(f"Use it:  run_eval.py evaluate --dataset-id {args.name} --level M2 --limit 5")
        print(f"Or build a new revision:  normalize_create_data.py --name {args.name.rsplit('-v', 1)[0]}-v2")
        return

    customers = official_customers()
    prepared, labels, files, excluded = {}, {}, [], []
    for path in sorted(source.glob("*.json")):
        raw = path.read_bytes()
        scenario, changes, reason = convert(json.loads(raw), customers)
        record = {"source": path.relative_to(ROOT.parent).as_posix() if path.is_relative_to(ROOT.parent) else str(path),
                  "source_sha256": hashlib.sha256(raw).hexdigest()}
        if reason:
            excluded.append({**record, "scenario_id": json.loads(raw).get("scenario_id"), "reason": reason})
            continue
        prepared[path.name] = json.dumps(scenario, ensure_ascii=False, indent=2) + "\n"
        labels[scenario["scenario_id"]] = tool_labels(scenario)
        files.append({**record, "derived": "scenarios/" + path.name, "level": scenario["level"],
                      "turns": sum(len(c["customer_turns"]) for c in scenario["calls"].values()),
                      "changes": changes, "gt_status": "generated_pending_qa"})
    if not prepared:
        raise SystemExit("No scenario can run; see the exclusion reasons by running with a smaller source")

    (target / "scenarios").mkdir(parents=True)
    for name, payload in prepared.items():
        (target / "scenarios" / name).write_text(payload, encoding="utf-8", newline="\n")
    (target / "tool-labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8", newline="\n")
    (target / "conversion-report.json").write_text(json.dumps({
        "schema_version": "create-data-diagnostic-v1", "official_gt_approved": False,
        "scope": f"{len(files)} of {len(files) + len(excluded)} generated scenarios; JSON only; labels from the generator",
        "tool_labels": "success_if.tool_called/args_match of each call; pending independent QA",
        "synthetic_crm": ({"path": SYNTHETIC_CRM.relative_to(ROOT.parent.parent).as_posix(),
                           "sha256": hashlib.sha256(SYNTHETIC_CRM.read_bytes()).hexdigest()}
                          if SYNTHETIC_CRM.exists() else None),
        "files": files, "excluded": excluded,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    registry["sets"].append({"id": args.name, "split": "development", "path": f"{args.name}/scenarios",
                             "reviewed_by": None, "status": "diagnostic",
                             "tool_labels": f"{args.name}/tool-labels.json"})
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    reasons = {}
    for item in excluded:
        reasons[item["reason"]["code"]] = reasons.get(item["reason"]["code"], 0) + 1
    levels = {}
    for item in files:
        levels[item["level"]] = levels.get(item["level"], 0) + 1
    print(f"Created {target.relative_to(ROOT)}: {len(files)} scenarios {levels}; excluded {len(excluded)} {reasons}")


if __name__ == "__main__":
    main()
