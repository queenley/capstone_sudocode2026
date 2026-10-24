"""The team's agent in this harness: :func:`evaluate` runs every stage, :func:`prepare` the first.

``run_eval.py evaluate --out runs/<name>`` calls :func:`evaluate`, which writes
one folder per stage under ``--out`` and never overwrites one:

| Folder | Stage | What to read |
|---|---|---|
| ``inputs/`` | :func:`prepare`: pinned scenarios, grading, manifest, adapter | ``preparation-report.json`` |
| ``raw/`` | P2 ``run_fixed``: the agent's hooks, every tool event | ``runner-report.json``, ``full/adapter-*.log`` |
| ``evidence/`` | P3 ``collect``: transcripts, extraction, memory, briefs, the BTC trace | ``full.jsonl``, ``baseline.jsonl``, ``validation.json`` |
| ``scored/`` | P4 ``score``: the organisers' grader and this harness's own checks | ``scorer.stdout.txt``, ``official-report.json``, ``supplemental-report.json`` |

``execution-report.json`` at the top sums up every stage. P6 (``report``) is
not run: it implements level M1, and these scenarios are M2.

:func:`prepare` calls no model. It writes into a new directory what ``run_fixed`` needs, each input pinned by
hash in the manifest: the five scenarios of ``datasets/output1-btc-diagnostic-v2``
(their provenance from ``output (1)`` checked against ``normalize_output1``),
one grading contract per scenario from ``fixtures/grading.json``, the scope,
the adapter (``product_adapter.py``) and the bundle naming the agent it
starts, the metrics policy, and the real extractor (``extractor-prompt.txt``
and the product's extraction command). The agent's model and parameters are
read from the agent's own ``config/models.yaml``, as the agent reads them.

In this repository the agent is ``apps/ai-agent-service`` (run under its
``.venv``, or ``AGENT_PYTHON``), driven through ``agent/`` beside this file.
Models: the advisor is ``config/models.yaml``'s unless ``advisor`` names
``provider:model``; the extractor is ``extractor``, else OpenAI
``gpt-4.1-mini`` when ``OPENAI_API_KEY`` is set, else the advisor's model.

With ``dataset_id``, a registered set is used instead: an approved one with
its reviewed labels, or a diagnostic one (``normalize_create_data.py``) whose
labels come from its own ``success_if``, pending QA. ``only``, ``level`` and
``limit`` choose its scenarios; a run holds one level.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from eval_harness.assets import Assets, read_json
from eval_harness.case_trace import write as write_case_trace
from eval_harness.collector import collect
from eval_harness.contracts import ROOT, checker, validate
from eval_harness.datasets import close_output
from eval_harness.environment import CRM_EXTENSION
from eval_harness.preflight import call_plan, preflight
from eval_harness.runner import _output_path, _write, run_fixed
from eval_harness.scoring import score
from normalize_output1 import convert
from product_adapter import tree_sha256
from tool_expectations import labels_for
from eval_harness.data_registry import inspect as inspect_data_registry
from eval_harness.progress import say
from agent.launch import SERVICE, python as agent_python

EVALUATION = ROOT.parent
PRODUCT = SERVICE
PYTHON = agent_python()
BRIDGE = "agent.bridge"
DATASET = EVALUATION / "datasets/output1-btc-diagnostic-v2/scenarios"
DATASETS = EVALUATION / "datasets"
COMMAND = "agent/extract_command.py"
#: The folders that make the agent a run starts: hashed into the bundle.
TREE = {"service/src": SERVICE / "src", "service/config": SERVICE / "config",
        "service/catalog": SERVICE / "data/btc/catalog", "evaluation/agent": EVALUATION / "agent"}
#: The team's synthetic CRM customers the agent's mock adds (``mcp/servers/btc.py``); a run pins
#: a copy so the harness's mock adds the same ones. ``BTC_SYNTHETIC_CRM=0`` turns both off.
SYNTHETIC_CRM = SERVICE / "data/btc/catalog/crm_seed_synthetic.json"
CAPABILITIES = ["business_tools", "memory_isolation", "memory_read_gate", "after_call_barrier",
                "snapshots", "briefs", "timestamps", "usage"]
DEFAULT_EXTRACTOR = "openai:gpt-4.1-mini"
#: What the agent's interpreter reports about the agent it would run.
QUERY = """
import json, os
from agent.bridge import parameters
from ai_agent_service.config.config_manager import get_models_config, has_api_key
m = get_models_config()
def pick(spec, fallback):
    provider, _, model = (spec or fallback).partition(":")
    if not has_api_key(provider):
        raise SystemExit(f"No API key for provider {provider!r} (model {model!r}); set it in .env")
    return provider, model
a = m.agent("advisor")
provider, model = pick(os.environ.get("EVAL_ADVISOR"), a.provider + ":" + a.model)
default = os.environ.get("EVAL_EXTRACTOR") or ("openai:gpt-4.1-mini" if has_api_key("openai") else provider + ":" + model)
xp, xm = pick(default, default)
print(json.dumps({"provider": provider, "model": model, "parameters": parameters(provider, model),
                  "extractor": m.llm_config(xp, xm, agent="extractor")}))
"""


def product_settings(advisor=None, extractor=None):
    env = {**os.environ, "PYTHONUTF8": "1"}
    for key, value in (("EVAL_ADVISOR", advisor), ("EVAL_EXTRACTOR", extractor)):
        if value:
            env[key] = value
    result = subprocess.run([str(PYTHON), "-B", "-c", QUERY], cwd=EVALUATION, capture_output=True, text=True,
                            encoding="utf-8", timeout=120, env=env)
    if result.returncode:
        raise RuntimeError("The agent's settings could not be read: " + (result.stderr.strip().splitlines() or ["?"])[-1])
    return json.loads(result.stdout.strip().splitlines()[-1])


def git_state():
    def git(*args):
        return subprocess.run(["git", *args], cwd=PRODUCT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def levels(dataset_id, only=None):
    """The levels of a registered set's scenarios (after *only*): one run each, since a run holds one level."""
    if dataset_id is None:
        return [None]
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


def scenarios_with_provenance(source, only):
    """The five derived scenarios, each proved to be normalize_output1's output for its pinned original."""
    paths = sorted(source.glob("*.json"))
    report = read_json(source.parent / "conversion-report.json")
    if len(paths) != 5 or report.get("official_gt_approved") is not False or len(report.get("files", [])) != 5:
        raise ValueError("Require the five diagnostic revision files and their conversion report")
    for path, record in zip(paths, report["files"]):
        original = ROOT.parent / record["source"]
        if (record["derived"] != "scenarios/" + path.name or not original.is_file()
                or hashlib.sha256(original.read_bytes()).hexdigest() != record["source_sha256"]
                or read_json(path) != convert(read_json(original))[0]):
            raise ValueError(f"Scenario provenance changed: {path.name}")
    chosen = [p for p in paths if not only or read_json(p)["scenario_id"] in only]
    if not chosen:
        raise ValueError("No scenario matches --only")
    return report, chosen


def prepare(out, *, only=None, extractor_calls=None, dataset_id=None, level=None, limit=None,
            advisor=None, extractor_model=None):
    checker.verify_sources()
    out = _output_path(out, Assets(PRODUCT))
    out.mkdir(parents=True, mode=0o700)
    assets = Assets(out)
    agent = product_settings(advisor, extractor_model)

    # The adapter, and the agent it starts.
    (out / "product_adapter.py").write_bytes((ROOT.parent / "product_adapter.py").read_bytes())
    tree = {label: str(path) for label, path in TREE.items()}
    _write(out / "product-bundle.json", {
        "schema_version": "product-bundle-v2", "python": str(PYTHON), "module": BRIDGE, "cwd": str(EVALUATION),
        "tree": tree, "tree_sha256": tree_sha256(tree), "git": git_state(),
        "llm": {"provider": agent["provider"], "model": agent["model"]},
        "notice": "The team's agent (apps/ai-agent-service) through scripts/evaluation/agent, with the repository's "
                  ".env; its tables are in the agent_eval schema",
    })
    descriptor = {"kind": "runtime", "entrypoint": "product_adapter:factory",
                  "code": assets.ref("product_adapter.py"), "capabilities": CAPABILITIES}
    _write(out / "adapter.json", descriptor)

    # Scenarios and their grading contracts, as the diagnostic revision defines them.
    imported_labels = None
    if dataset_id is None:
        conversion, paths = scenarios_with_provenance(DATASET, only)
    else:
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
    _write(out / "conversion-report.json", conversion)
    if imported_labels is not None:
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
            expected = (labels_for(item["scenario_id"], call, item["calls"][call]["success_if"])
                        if imported_labels is None else imported_labels[item["scenario_id"]][call])
            for config in ("full", "baseline_no_memory"):
                label_path = f"expected-tools/{config}/{item['scenario_id']}/{call}.json"
                (out / label_path).parent.mkdir(parents=True, exist_ok=True)
                context = {"run_id": "PRODUCT-" + hashlib.sha256(str(out).encode()).hexdigest()[:16],
                           "config": config, "scenario_id": item["scenario_id"], "call": call, "turn": 1}
                _write(out / label_path, {"schema_version": "1.0.0",
                       "artifact_id": "/".join((context["run_id"], config, item["scenario_id"], call, "tool-labels")),
                       "run_id": context["run_id"], "evidence_refs": [ref], "context": context,
                       "calls": expected, "allow_extra_read_only": True,
                       "labelled_by": ("output1-diagnostic-tool-labels-pending-independent-QA" if imported_labels is None else labeller)})
                label_ref = assets.ref(label_path)
                tool_refs.append(label_ref)
                template["checks"].append({"check_id": "tool_accuracy_" + config,
                    "kind": "tool_accuracy", "params": {"expected_calls": label_ref},
                    "required_evidence": []})
            grader["calls"].append(template)
        _write(out / "grading" / path.name, grader)
        grading_refs.append(assets.ref("grading/" + path.name))

    manifest = read_json(ROOT / "fixtures/p6-manifest.json")
    suffix = hashlib.sha256(str(out).encode()).hexdigest()[:16]
    levels = {item["level"] for item in scenarios}
    if len(levels) != 1:
        raise ValueError("One run requires scenarios at one level")
    manifest.update(artifact_id="PRODUCT-Manifest", run_id="PRODUCT-" + suffix, level=levels.pop(), fixture=False,
                    scenarios=scenario_refs, grading_contracts=grading_refs)
    if imported_labels is not None:
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
         "memory_required": config == "full" and any(item["calls"][plan["call"]].get(key) for key in
                                                     ("must_carry_over", "seed_history", "memory_expectation"))}
        for config in ("full", "baseline_no_memory") for item in scenarios
        for plan in call_plan(item, manifest["reference_date"])]

    scope = read_json(ROOT / "fixtures/p1-scope.json")
    scope["notice"] = "Generated diagnostic scenarios; labels pending independent QA; report-only synthetic test"
    scope["source_decisions"] = [
        {**scope["source_decisions"][0], "origin": ref, "run_id": manifest["run_id"],
         "artifact_id": manifest["run_id"] + "/source-decision/" + str(index),
         "source_split": manifest["split"],
         "reason": ("User-provided generated data; report-only diagnostic; GT not approved"
                    if imported_labels is None or not approved
                    else "Registered dataset reviewed by " + group["reviewed_by"] + "; report-only")}
        for index, ref in enumerate(scenario_refs)]
    if imported_labels is not None and approved:
        scope["pii_review"] = {"status": "approved", "reviewed_by": group["reviewed_by"],
                               "scope": "authorized_redacted"}
    (out / "fixtures").mkdir()
    _write(out / "fixtures/p1-scope.json", scope)

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
    (out / "extractor-prompt.txt").write_bytes((ROOT.parent / "extractor-prompt.txt").read_bytes())
    (out / "extract_command.py").write_bytes((EVALUATION / COMMAND).read_bytes())
    # One extraction per agent turn and configuration, unless a smaller budget is asked for.
    planned_turns = sum(plan["expected_turns"] for plan in manifest["planned_calls"])
    extractor = {"kind": "command_model", "version": "product-extractor-v2", "python": str(PYTHON),
                 "backend": str(EVALUATION), "code": assets.ref("extract_command.py"), "files": [],
                 "config": agent["extractor"], "prompt": assets.ref("extractor-prompt.txt"),
                 "max_calls": extractor_calls or max(1, planned_turns)}
    from eval_harness.model_extractor import MAX_CALLS
    if not 1 <= extractor["max_calls"] <= MAX_CALLS:
        # Refused here, before the agent runs, rather than at collection after paying for every turn.
        raise ValueError(f"{extractor['max_calls']} extraction calls planned; at most {MAX_CALLS} per run. Use --limit.")
    _write(out / "extractor.json", extractor)
    manifest["configuration"]["extractor_version"] = extractor["version"]

    manifest["sources"] = [assets.ref("fixtures/p1-scope.json"), *resources, *tool_refs, assets.ref("adapter.json"),
                           descriptor["code"], assets.ref("product-bundle.json"), assets.ref("metrics-policy.json"),
                           assets.ref("conversion-report.json"), assets.ref("extractor-prompt.txt"),
                           assets.ref("extract_command.py"), assets.ref("extractor.json"), *extension]
    if imported_labels is not None:
        manifest["sources"].append(assets.ref("registered-tool-labels.json"))
    _write(out / "manifest.json", manifest)
    _write(out / "settings.json", {"asset_root": ".", "manifest": "manifest.json",
                                   "scope": "fixtures/p1-scope.json", "adapter": assets.ref("adapter.json")})
    report = preflight(out / "settings.json")
    _write(out / "preparation-report.json", report)
    return {"settings": str(out / "settings.json"), "run_id": manifest["run_id"],
            "execution_gate": report["execution_gate"], "planned_turns": len(report["coverage_plan"]["expected_trace_ids"])}


def log_spend(run, *, force=False):
    """Log *run*'s spend and scores to MLflow (``agent/mlflow_log.py``), with the
    agent's interpreter, which has MLflow. Never fails the evaluation."""
    command = [str(PYTHON), "-B", "-m", "agent.mlflow_log", str(Path(run).resolve())] + (["--force"] if force else [])
    try:
        result = subprocess.run(command, cwd=EVALUATION, capture_output=True, text=True, encoding="utf-8",
                                timeout=300, env={**os.environ, "PYTHONUTF8": "1"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"MLflow logging failed: {type(exc).__name__}: {exc}"
    lines = (result.stdout or "").strip().splitlines()
    if result.returncode or not lines:
        return "MLflow logging failed: " + ((result.stderr or "").strip().splitlines() or ["no output"])[-1]
    return lines[-1]


def evaluate(out, *, only=None, extractor_calls=None, dataset_id=None, level=None, limit=None,
             advisor=None, extractor_model=None):
    """Prepare, run, collect and score; ``execution-report.json`` sums it up."""
    out = _output_path(out, Assets(PRODUCT))
    out.mkdir(parents=True, mode=0o700)
    stages, failure = [], None
    say(f"1/4 Prepare: checking inputs into {out}")
    try:
        prepared = prepare(out / "inputs", only=only, extractor_calls=extractor_calls, dataset_id=dataset_id,
                           level=level, limit=limit, advisor=advisor, extractor_model=extractor_model)
        stages.append({"stage": "prepare", **prepared})
        if not prepared["execution_gate"]["allowed"]:
            raise ValueError("Prepared inputs did not pass the execution gate")
        turns = prepared["planned_turns"]
        scenarios = len(list((out / "inputs/scenarios").glob("*.json")))
        # Measured on Windows: ~75 s to start the agent per scenario and
        # configuration, ~3 s per agent turn, ~8 s per extraction call.
        minutes = (scenarios * 2 * 75 + turns * 3 + turns * 8) // 60 + 1
        say(f"2/4 Run: {scenarios} scenario(s) x 2 configs = {turns} agent turns; whole evaluation ~{minutes} min")
        raw = run_fixed(out / "inputs/settings.json", out / "raw")
        stages.append({"stage": "run", "execution_complete": raw["execution_complete"],
                       "completed_calls": raw["completed_calls"], "failed_calls": raw["failed_calls"],
                       "errors": raw["errors"]})
        say(f"   calls completed {raw['completed_calls']}, failed {raw['failed_calls']}")
        say(f"3/4 Collect: one extraction call per turn ({turns})")
        evidence = collect(out / "raw", out / "evidence", extractor_path="extractor.json")
        stages.append({"stage": "collect", "status": evidence["status"], "trace_rows": evidence["trace_rows"],
                       "trace_wire_complete": evidence["trace_wire_complete"]})
        say("4/4 Score: BTC reference_eval and this harness's checks")
        scored = score(out / "evidence", out / "scored")
        stages.append({"stage": "score", "status": scored["status"],
                       "official_report_available": scored["official_report_available"]})
    except (OSError, ValueError, KeyError, TypeError, AssertionError, RuntimeError) as exc:
        failure = f"{type(exc).__name__}: {exc}"
        say(f"Stopped: {failure}")
    report = {"report_kind": "product-evaluate-v1", "stages": stages, "pipeline_error": failure,
              "quality_accepted": False, "table": "scored/scorer.stdout.txt",
              "notice": "The team's agent on generated diagnostic scenarios whose labels await QA; "
                        "not BTC acceptance. P6 (report) is not run."}
    try:
        write_case_trace(out, report)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report["pipeline_error"] = (report["pipeline_error"] + "; " if report["pipeline_error"] else "") + f"Case trace: {type(exc).__name__}: {exc}"
    _write(out / "execution-report.json", report)
    close_output(out)
    say("Logging spend to MLflow")
    report["mlflow"] = log_spend(out)
    say(report["mlflow"])
    return report
