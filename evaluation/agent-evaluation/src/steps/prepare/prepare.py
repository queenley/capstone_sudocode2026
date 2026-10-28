"""Step 1 — Prepare: copy and pin by hash everything a run needs into ``<run>/inputs/``; calls no model.

:func:`prepare` writes, each pinned by SHA-256 in ``manifest.json``:

- the chosen scenarios of a registered dataset (``datasets/registry.json``), one grading contract per scenario
  (``contracts/fixtures/grading.json``) and the tool labels of every call and configuration;
- the adapter (``src/services/adapter.py``) and ``product-bundle.json``: the interpreter, the module and one
  hash over the whole agent (its ``src``, ``config``, prompts, catalogue and ``src/services/agent``);
- the metrics policy, the synthetic CRM the mock adds, and the extractor (prompt, command, model, call budget).

Then :func:`~src.steps.prepare.preflight.preflight` checks every input and plans one trace row per
(config, scenario, call, turn); its ``execution_gate`` decides whether the run may start.
"""
import hashlib
import os

from src.baseline.configs import CONFIGS, reads_memory
from src.common.assets import Assets, new_output, read_json, write_new
from src.common.contracts import ROOT, checker, validate
from src.datasets.registry import inspect as inspect_data_registry
from src.services.adapter import tree_sha256
from src.services.agent.launch import REPOSITORY, SERVICE, python as agent_python
from src.services.agent_settings import git_state, product_settings
from src.services.extractor import MAX_CALLS
from src.steps.prepare.preflight import call_plan, preflight
from src.steps.run.mock_environment import CRM_EXTENSION

EVALUATION = ROOT.parent
PRODUCT = SERVICE
PYTHON = agent_python()
DATASETS = EVALUATION / "datasets"
#: The dataset a run takes when ``--dataset-id`` is not given.
DEFAULT_DATASET = "create-data-diagnostic-v4"
ADAPTER = EVALUATION / "src/services/adapter.py"
#: Started by the adapter, in the agent's interpreter, from ``evaluation/agent-evaluation``.
BRIDGE = "src.services.agent.bridge"
EXTRACT_COMMAND = "src/services/agent/extract_command.py"
PROMPTS = REPOSITORY / "config" / "prompts"
EXTRACTOR_PROMPT = PROMPTS / "evaluation" / "extractor.txt"
#: The folders that make the agent a run starts: hashed into the bundle.
TREE = {"service/src": SERVICE / "src", "service/config": SERVICE / "config", "service/prompts": PROMPTS / "agent",
        "service/catalog": SERVICE / "data/btc/catalog", "evaluation/agent": EVALUATION / "src/services/agent"}
#: The team's synthetic CRM customers the agent's mock adds (``mcp/servers/btc.py``); a run pins
#: a copy so the harness's mock adds the same ones. ``BTC_SYNTHETIC_CRM=0`` turns both off.
SYNTHETIC_CRM = SERVICE / "data/btc/catalog/crm_seed_synthetic.json"
CAPABILITIES = ["business_tools", "memory_isolation", "memory_read_gate", "after_call_barrier",
                "snapshots", "briefs", "timestamps", "usage"]


def levels(dataset_id, only=None):
    """The levels of a registered set's scenarios (after *only*): one run each, since a run holds one level."""
    groups = [g for g in read_json(DATASETS / "registry.json")["sets"] if g["id"] == dataset_id]
    if len(groups) != 1:
        raise ValueError(f"Unknown dataset {dataset_id!r}; see datasets/registry.json")
    found = {read_json(p)["level"] for p in (DATASETS / groups[0]["path"]).glob("*.json")
             if not only or read_json(p)["scenario_id"] in only}
    return sorted(found) or [None]


def choose(paths, *, only=None, level=None, limit=None):
    """The registered scenarios a run takes: *only* by ID, then one *level*, then the first *limit*."""
    chosen = [p for p in paths if not only or read_json(p)["scenario_id"] in only]
    levels = sorted({read_json(p)["level"] for p in chosen})
    if level is None and len(levels) > 1:
        raise ValueError(f"The selection mixes levels {levels}; pass --level (one run holds one level)")
    chosen = [p for p in chosen if level is None or read_json(p)["level"] == level]
    return chosen[:limit] if limit else chosen


def prepare(out, *, only=None, extractor_calls=None, dataset_id=DEFAULT_DATASET, level=None, limit=None,
            advisor=None, extractor_model=None):
    checker.verify_sources()
    out = new_output(out, Assets(PRODUCT))
    out.mkdir(parents=True, mode=0o700)
    assets = Assets(out)
    agent = product_settings(advisor, extractor_model)

    # The adapter, and the agent it starts.
    (out / "product_adapter.py").write_bytes(ADAPTER.read_bytes())
    tree = {label: str(path) for label, path in TREE.items()}
    write_new(out / "product-bundle.json", {
        "schema_version": "product-bundle-v2", "python": str(PYTHON), "module": BRIDGE, "cwd": str(EVALUATION),
        "tree": tree, "tree_sha256": tree_sha256(tree), "git": git_state(),
        "llm": {"provider": agent["provider"], "model": agent["model"]},
        "notice": "The team's agent (apps/ai-agent-service) through evaluation/agent-evaluation/src/services/agent, with the repository's "
                  ".env; its tables are in the agent_eval schema",
    })
    descriptor = {"kind": "runtime", "entrypoint": "product_adapter:factory",
                  "code": assets.ref("product_adapter.py"), "capabilities": CAPABILITIES}
    write_new(out / "adapter.json", descriptor)

    # Scenarios and their grading contracts, as the diagnostic revision defines them.
    inventory = inspect_data_registry(DATASETS, only=dataset_id)
    if inventory["issues"]:
        raise ValueError("Dataset registry has unresolved validation issues: "
                         + ", ".join(sorted({i["code"] for i in inventory["issues"]})))
    groups = [g for g in read_json(DATASETS / "registry.json")["sets"] if g["id"] == dataset_id]
    if len(groups) != 1 or groups[0]["status"] not in ("approved", "diagnostic") or not groups[0].get("tool_labels"):
        raise ValueError("Choose one registered dataset that has tool labels (approved, or diagnostic)")
    group = groups[0]
    approved = group["status"] == "approved"
    paths = choose(sorted((DATASETS / group["path"]).glob("*.json")), only=only, level=level, limit=limit)
    if not paths:
        raise ValueError("No registered scenario matches")
    imported_labels = read_json(DATASETS / group["tool_labels"])
    conversion = {"report_kind": "registered-dataset-v1", "dataset_id": dataset_id,
                  "split": group["split"], "reviewed_by": group["reviewed_by"], "status": group["status"],
                  "files": [{"scenario_id": read_json(p)["scenario_id"], "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}
    labeller = group["reviewed_by"] if approved else dataset_id + "-success_if-labels-pending-independent-QA"
    write_new(out / "conversion-report.json", conversion)
    (out / "registered-tool-labels.json").write_bytes((DATASETS / group["tool_labels"]).read_bytes())
    (out / "scenarios").mkdir()
    (out / "grading").mkdir()
    (out / "expected-tools").mkdir()
    scenario_refs, grading_refs, tool_refs, scenarios = [], [], [], []
    for path in paths:
        item = read_json(path)
        validate("Scenario", item)
        (out / "scenarios" / path.name).write_bytes(path.read_bytes())
        ref = assets.ref("scenarios/" + path.name)
        scenario_refs.append(ref)
        scenarios.append(item)
        grader = read_json(ROOT / "fixtures/grading.json")
        grader.update(scenario=ref, scenario_id=item["scenario_id"], level=item["level"], calls=[])
        for call in item["calls"]:
            template = read_json(ROOT / "fixtures/grading.json")["calls"][0]
            template.update(call=call, official_success_if={**ref, "pointer": "/calls/" + call + "/success_if"},
                            ground_truth=[ref])
            template["suites"][0]["reason"] = "Generated diagnostic GT pending QA"
            expected = imported_labels[item["scenario_id"]][call]
            for config in CONFIGS:
                label_path = f"expected-tools/{config}/{item['scenario_id']}/{call}.json"
                (out / label_path).parent.mkdir(parents=True, exist_ok=True)
                context = {"run_id": "PRODUCT-" + hashlib.sha256(str(out).encode()).hexdigest()[:16],
                           "config": config, "scenario_id": item["scenario_id"], "call": call, "turn": 1}
                write_new(out / label_path, {"schema_version": "1.0.0",
                       "artifact_id": "/".join((context["run_id"], config, item["scenario_id"], call, "tool-labels")),
                       "run_id": context["run_id"], "evidence_refs": [ref], "context": context,
                       "calls": expected, "allow_extra_read_only": True,
                       "labelled_by": labeller})
                label_ref = assets.ref(label_path)
                tool_refs.append(label_ref)
                template["checks"].append({"check_id": "tool_accuracy_" + config,
                    "kind": "tool_accuracy", "params": {"expected_calls": label_ref},
                    "required_evidence": []})
            grader["calls"].append(template)
        write_new(out / "grading" / path.name, grader)
        grading_refs.append(assets.ref("grading/" + path.name))

    manifest = read_json(ROOT / "fixtures/p6-manifest.json")
    suffix = hashlib.sha256(str(out).encode()).hexdigest()[:16]
    levels = {item["level"] for item in scenarios}
    if len(levels) != 1:
        raise ValueError("One run requires scenarios at one level")
    manifest.update(artifact_id="PRODUCT-Manifest", run_id="PRODUCT-" + suffix, level=levels.pop(), fixture=False,
                    scenarios=scenario_refs, grading_contracts=grading_refs)
    manifest["split"] = group["split"]
    manifest["configuration"].update(model=agent["model"], parameters=agent["parameters"],
                                     hardware="local apps/ai-agent-service, agent_eval schema")
    # A turn may wait on the provider's rate limit; the bridge starts five MCP servers.
    manifest["timeouts_ms"].update(agent=300000, after_call=300000)
    manifest["state_namespaces"] = {key: "product/" + suffix + "/" + key for key in manifest["state_namespaces"]}
    manifest["planned_calls"] = [
        {"config": config, "scenario_id": item["scenario_id"], "call": plan["call"],
         "expected_turns": plan["expected_turns"],
         # The rule preflight checks: a call reads memory when it carries facts over or expects memory writes.
         "memory_required": reads_memory(config) and any(item["calls"][plan["call"]].get(key) for key in
                                                     ("must_carry_over", "seed_history", "memory_expectation"))}
        for config in CONFIGS for item in scenarios
        for plan in call_plan(item, manifest["reference_date"])]

    scope = read_json(ROOT / "fixtures/p1-scope.json")
    scope["notice"] = "Generated diagnostic scenarios; labels pending independent QA; report-only synthetic test"
    scope["source_decisions"] = [
        {**scope["source_decisions"][0], "origin": ref, "run_id": manifest["run_id"],
         "artifact_id": manifest["run_id"] + "/source-decision/" + str(index),
         "source_split": manifest["split"],
         "reason": ("User-provided generated data; report-only diagnostic; GT not approved"
                    if not approved
                    else "Registered dataset reviewed by " + group["reviewed_by"] + "; report-only")}
        for index, ref in enumerate(scenario_refs)]
    if approved:
        scope["pii_review"] = {"status": "approved", "reviewed_by": group["reviewed_by"],
                               "scope": "authorized_redacted"}
    (out / "fixtures").mkdir()
    write_new(out / "fixtures/p1-scope.json", scope)

    resources = []
    for key in ("prompt", "tools", "kb"):
        ref = manifest["configuration"][key]
        target = out / ref["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / ref["path"]).read_bytes())
        resources.append(ref)
    (out / "metrics-policy.json").write_bytes((ROOT / "fixtures/p6-metrics-policy.json").read_bytes())
    extension = []
    if SYNTHETIC_CRM.exists() and os.environ.get("BTC_SYNTHETIC_CRM", "1") != "0":
        (out / CRM_EXTENSION).write_bytes(SYNTHETIC_CRM.read_bytes())
        extension.append(assets.ref(CRM_EXTENSION))

    # The real extractor: the harness's prompt, the product's command, pinned.
    (out / "extractor-prompt.txt").write_bytes(EXTRACTOR_PROMPT.read_bytes())
    (out / "extract_command.py").write_bytes((EVALUATION / EXTRACT_COMMAND).read_bytes())
    # One extraction per agent turn and configuration, unless a smaller budget is asked for.
    planned_turns = sum(plan["expected_turns"] for plan in manifest["planned_calls"])
    extractor = {"kind": "command_model", "version": "product-extractor-v3", "python": str(PYTHON),
                 "backend": str(EVALUATION), "code": assets.ref("extract_command.py"), "files": [],
                 "config": agent["extractor"], "prompt": assets.ref("extractor-prompt.txt"),
                 "max_calls": extractor_calls or max(1, planned_turns)}
    if not 1 <= extractor["max_calls"] <= MAX_CALLS:
        # Refused here, before the agent runs, rather than at collection after paying for every turn.
        raise ValueError(f"{extractor['max_calls']} extraction calls planned; at most {MAX_CALLS} per run. Use --limit.")
    write_new(out / "extractor.json", extractor)
    manifest["configuration"]["extractor_version"] = extractor["version"]

    manifest["sources"] = [assets.ref("fixtures/p1-scope.json"), *resources, *tool_refs, assets.ref("adapter.json"),
                           descriptor["code"], assets.ref("product-bundle.json"), assets.ref("metrics-policy.json"),
                           assets.ref("conversion-report.json"), assets.ref("extractor-prompt.txt"),
                           assets.ref("extract_command.py"), assets.ref("extractor.json"), *extension]
    manifest["sources"].append(assets.ref("registered-tool-labels.json"))
    write_new(out / "manifest.json", manifest)
    write_new(out / "settings.json", {"asset_root": ".", "manifest": "manifest.json",
                                   "scope": "fixtures/p1-scope.json", "adapter": assets.ref("adapter.json")})
    report = preflight(out / "settings.json")
    write_new(out / "preparation-report.json", report)
    return {"settings": str(out / "settings.json"), "run_id": manifest["run_id"],
            "execution_gate": report["execution_gate"], "planned_turns": len(report["coverage_plan"]["expected_trace_ids"])}
