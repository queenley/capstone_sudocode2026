"""Step 2 — Run: the real agent talks through every scenario, once as ``full`` and once as ``baseline_no_memory``.

:func:`run_fixed` starts the agent per scenario and configuration (``src/services/adapter.py`` → the agent's bridge,
in its own process) and calls its hooks in order: ``open_scenario`` → per call ``start_call``, one ``run_turn`` per
customer line, ``end_call`` (after-call barrier) → ``close_scenario``. Business tools are answered by BTC's mock
(:mod:`.mock_environment`); memory and knowledge go through the agent's own MCP servers on schema ``agent_eval``.
No retry: a failure is recorded where it happened and the scenario's later calls are not run. No extraction, trace
export or verdict here: ``raw/`` is the input of the Collect step.
"""
import asyncio
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import json
import multiprocessing
from pathlib import Path
import sys
import time

from src.baseline.configs import CONFIGS, reads_memory
from src.common.assets import Assets
from src.common.progress import say, short
from src.common.contracts import ROOT, checker
from src.steps.run.mock_environment import CRM_EXTENSION, MockEnvironment
from src.steps.prepare.preflight import ADAPTER_CAPABILITIES, call_plan, preflight

HOOKS = {"open_scenario": 1, "start_call": 1, "run_turn": 1,
         "end_call": 0, "close_scenario": 0}


class ToolOutcomeUnknown(RuntimeError):
    reconciliation_required = True


def now():
    return datetime.now(timezone.utc).isoformat()


def _send(connection, data):
    # JSON IPC: adapter results cannot introduce pickle objects into the parent.
    connection.send_bytes(json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _recv(connection):
    return json.loads(connection.recv_bytes().decode("utf-8"))


def _adapter_worker(connection, code_path, code_hash, entrypoint, declared, log_path):
    """Trusted adapter, isolated for cancellation; this is not a security sandbox."""
    sys.dont_write_bytecode = True
    log = open(log_path, "x", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        path = Path(code_path)
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != code_hash:
            raise ValueError("Adapter code changed before binding")
        name, factory = entrypoint.split(":")
        # Execute the verified bytes, never an installed module of the same name.
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        exec(compile(payload, str(path), "exec"), module.__dict__)
        adapter = getattr(module, factory)()
        actual = adapter.capabilities
        if (not isinstance(actual, (list, tuple, set, frozenset))
                or any(not isinstance(item, str) for item in actual)
                or not set(declared) <= set(actual)
                or not ADAPTER_CAPABILITIES <= set(actual)):
            raise ValueError("Bound adapter lacks declared capabilities")
        if adapter.retry != {"agent": 0, "tool": 0}:
            raise ValueError("Adapter must expose retry agent=0/tool=0, including SDK")
        for hook, count in HOOKS.items():
            function = getattr(adapter, hook)
            if not callable(function):
                raise ValueError(f"Missing callable hook: {hook}")
            inspect.signature(function).bind(*([{}] * count))

        def tool(name, args):
            _send(connection, {"type": "tool", "name": name, "args": args})
            reply = _recv(connection)
            if "error" in reply:
                if reply.get("reconciliation_required"):
                    raise ToolOutcomeUnknown(reply["error"])
                raise RuntimeError(reply["error"])
            return reply["result"]

        def emit(event):
            _send(connection, {"type": "event", "event": event})

        _send(connection, {"type": "bound", "capabilities": sorted(actual),
                           "retry": adapter.retry, "code_sha256": code_hash,
                           "pid": multiprocessing.current_process().pid})
        while True:
            command = _recv(connection)
            hook, args = command["hook"], command["args"]
            if hook == "open_scenario":
                args[0].update(call_tool=tool, emit=emit)
            result = None
            try:
                result = getattr(adapter, hook)(*args)
                if inspect.isawaitable(result):
                    result = loop.run_until_complete(result)
                _send(connection, {"type": "result", "hook": hook, "result": result})
            except Exception as exception:
                _send(connection, {"type": "error", "hook": hook,
                                   "error": f"{type(exception).__name__}: {exception}",
                                   "invalid_result_repr": repr(result)})
                # Parent may only close after this; it never retries failed hooks.
            if hook == "close_scenario":
                break
    except Exception as exception:
        _send(connection, {"type": "error", "error": f"{type(exception).__name__}: {exception}"})
    finally:
        loop.close()
        connection.close()
        log.close()


class AdapterProcess:
    def __init__(self, descriptor, assets, environment, record, tool_record, log_path):
        self.environment, self.record, self.tool_record = environment, record, tool_record
        self.context, self.on, self.closed = None, None, False
        self.scope = {"run_id": environment.run_id, "config": environment.config,
                      "scenario_id": environment.scenario_id}
        self.phase = "binding"
        self.tool_count = self.audit_count = 0
        self.tool_timeout = environment.timeout
        code = assets.resolve(descriptor["code"], json_content=False)
        if not isinstance(code, Path) or descriptor["code"]["pointer"]:
            raise ValueError("Adapter code must reference a whole Python file")
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_adapter_worker, args=(
            child, str(code), descriptor["code"]["sha256"], descriptor["entrypoint"], descriptor["capabilities"], str(log_path)))
        self.process.start()
        child.close()

    def receive(self, timeout, hook=None):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.connection.poll(max(0, remaining)):
                raise TimeoutError(f"Adapter timeout at {hook or 'binding'}; no retry")
            message = _recv(self.connection)
            self.record("adapter_message", message, self.context, phase=hook or "binding")
            kind = message["type"]
            if kind == "event":
                continue  # Persist even malformed emitted evidence; P3 validates role/content.
            if kind == "tool":
                if self.context is None or hook not in ("start_call", "run_turn", "end_call"):
                    raise ValueError("Business tool invoked outside a call")
                self.record("tool_request", message, self.context)  # Before invoke.
                self.environment.timeout = min(self.tool_timeout, max(0.001, deadline - time.monotonic()))
                try:
                    before_events=len(self.environment.events)
                    result = self.environment.call_tool(message["name"], message["args"],
                        call=self.context["call"], turn=self.context["turn"], on=self.on)
                except ValueError as exception:
                    _send(self.connection, {"error": str(exception)})
                else:
                    recent=self.environment.events[before_events:]
                    if len(recent)!=1:raise RuntimeError("Exactly one tool outcome required")
                    if recent[0]["outcome"] in ("success","business_error"):
                        _send(self.connection, {"result": result})  # Filtered result ONLY.
                    else:
                        _send(self.connection, {"error": "Tool outcome unknown; do not retry",
                                                "reconciliation_required":True})
                finally:
                    for audit in self.environment.audit[self.audit_count:]:
                        self.record("tool_audit", audit, self.context)
                    self.audit_count = len(self.environment.audit)
                    for event in self.environment.events[self.tool_count:]:
                        self.tool_record(event)
                    self.tool_count = len(self.environment.events)
                    for failure in self.environment.failures:
                        self.record("tool_failure", failure, self.context)
                continue
            if kind == "error":
                raise RuntimeError(message["error"])
            if hook is None and kind == "bound":
                return message
            if kind != "result" or message["hook"] != hook:
                raise ValueError("Out-of-order adapter protocol")
            return message["result"]

    def invoke(self, hook, args, timeout):
        self.phase = hook
        self.record("hook_request", {"hook": hook, "args": args}, self.context, phase=hook)
        _send(self.connection, {"hook": hook, "args": args})
        return self.receive(timeout, hook)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.process.join(timeout=0.2)  # Let a healthy close hook finish process cleanup.
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=2)
        self.connection.close()
        self.process.close()


def _resource(assets, ref):
    content = assets.resolve(ref, json_content=False)
    return content.read_text(encoding="utf-8") if isinstance(content, Path) else content


def run_fixed(settings_path, out, *, config=None, scenarios_dir=None, round_name=None, simulator=None):
    """Run pinned M1 fixed turns. Returned evaluation status intentionally stays incomplete.

    With *simulator* (``simulate.Simulation``) the customer's lines come from it instead of the
    scenario's ``customer_turns``: ``simulator.session(scenario, call, spec, config)`` returns an object
    with ``first()``, ``reply(agent_text, tool_events)`` and ``log()``. The number of turns is then
    decided by the customer, so coverage of the planned turn ids is not required.
    """
    report = preflight(settings_path, scenarios_dir)
    assets = Assets(report["asset_root"])
    manifest = assets.resolve(report["manifest"])
    if config is not None and config not in CONFIGS:
        raise ValueError("Unknown configuration")
    if round_name is not None and round_name != f"R{manifest['round']}":
        raise ValueError("--round must match pinned manifest.round")
    out = new_output(out, assets)
    configs = [config] if config else list(CONFIGS)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_new(out / "preflight.json", report)
    write_new(out / "manifest.json", manifest)
    # Snapshot verified input bytes for P3 replay; never pass this directory to Agent.
    input_root = out / "inputs"
    input_root.mkdir()
    refs = manifest["sources"] + manifest["scenarios"] + manifest["grading_contracts"]
    refs += [report["scope"], report["manifest"]]
    refs += [manifest["configuration"][key] for key in ("prompt", "tools", "kb")]
    if report["execution_gate"]["allowed"]:
        related = [assets.resolve(report["scope"])] + [assets.resolve(ref) for ref in manifest["grading_contracts"]]
        refs += [item for item in checker.walk(related) if isinstance(item, dict)
                 and {"path", "sha256", "pointer"} <= set(item)]
    for ref in refs if report["execution_gate"]["allowed"] else []:
        # Snapshot whole files even when a ref selects a JSON subtree.
        payload = assets.path(ref["path"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != ref["sha256"]:
            raise ValueError("Input changed after preflight")
        target = input_root / ref["path"]
        if not target.resolve().is_relative_to(input_root.resolve()):
            raise ValueError("Input path cannot be replayed safely inside snapshot root")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(payload)
    source_lock = checker.read("sources.lock.json")
    if report["execution_gate"]["allowed"]:
        for name, digest in source_lock["files"].items():
            payload = (ROOT / name).read_bytes()
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError("BTC source changed during input snapshot")
            target = input_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != payload:
                    raise ValueError("Input BTC snapshot differs from evaluator worker source")
            else:
                with target.open("xb") as stream:
                    stream.write(payload)
    write_new(out / "sources.lock.json", source_lock)
    plans = report["coverage_plan"]["calls"]
    expected = [f"{manifest['run_id']}/{c}/{p['scenario_id']}/{p['call']}/{t}"
                for c in configs for p in plans for t in range(1, p["expected_turns"] + 1)]
    write_new(out / "execution-plan.json", {"configs": configs, "expected_ids": expected,
                                          "calls": plans, "trace_export": "PENDING_P3"})
    observed, calls, bindings, errors = [], [], [], []
    allowed = report["execution_gate"]["allowed"]
    progress = {"done": 0, "total": len(expected), "cost": 0.0}
    if allowed:
        assets = Assets(input_root)  # Bind/read snapshotted bytes, not mutable originals.
    if not allowed:
        errors.append({"code": "INPUT_GATE_BLOCKED", "blocking_codes": report["execution_gate"]["blocking_codes"]})
    scenarios = [assets.resolve(ref) for ref in manifest["scenarios"]] if allowed else []
    # Customers the run adds to the BTC mock's CRM, pinned among its sources (``product.prepare``).
    extension = [ref for ref in manifest["sources"] if ref["path"] == CRM_EXTENSION] if allowed else []
    customers = [c for ref in extension for c in assets.resolve(ref)["customers"]]
    times = manifest["timeouts_ms"]
    for current_config in configs:
        folder = out / current_config
        folder.mkdir()
        with (folder / "raw-execution.jsonl").open("x", encoding="utf-8") as raw, \
                (folder / "tools.jsonl").open("x", encoding="utf-8") as tools:
            def record(kind, data, context=None, *, phase=None):
                raw.write(json.dumps({"recorded_at": now(), "kind": kind, "context": context,
                                      "scope": {"run_id": manifest["run_id"], "config": current_config,
                                                "scenario_id": sid}, "phase": phase or current_phase[0],
                                      "data": data}, ensure_ascii=False, allow_nan=False) + "\n")
                raw.flush()  # Partial survives worker cancellation; never rewrite raw.

            turn_tools = []

            def tool_record(event):
                turn_tools.append(event)
                tools.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                tools.flush()

            for scenario_index, scenario in enumerate(scenarios):
                sid = scenario["scenario_id"]
                say(f"[{current_config}] scenario {scenario_index + 1}/{len(scenarios)} {sid}: starting the agent")
                current_phase = ["binding"]
                environment = adapter = None
                phase, context = "binding", None
                try:
                    environment = MockEnvironment(manifest["run_id"], sid, current_config, timeout=times["tool"] / 1000,
                                                  customers=customers)
                    adapter = AdapterProcess(report["adapter"], assets, environment, record, tool_record,
                                             folder / f"adapter-{scenario_index}.log")
                    binding = adapter.receive(times["agent"] / 1000)
                    bindings.append({"config": current_config, "scenario_id": sid, **binding})
                    seeds = [{"call": name, "history": copy.deepcopy(spec["seed_history"]),
                              "source": {**ref, "pointer": ref["pointer"] + "/calls/" + name + "/seed_history"}}
                             for ref in manifest["scenarios"] if assets.resolve(ref)["scenario_id"] == sid
                             for name, spec in scenario["calls"].items() if "seed_history" in spec]
                    runtime = {"run_id": manifest["run_id"], "config": current_config, "scenario_id": sid,
                               "namespace": f"{manifest['state_namespaces'][current_config]}/{manifest['run_id']}/{sid}",
                               "reference_date": manifest["reference_date"], "timezone": manifest["timezone"],
                               "memory_read_previous": reads_memory(current_config), "seed_history": seeds,
                               "configuration": {key: manifest["configuration"][key] for key in
                                                 ("model", "parameters", "hardware", "prompt", "tools", "kb")},
                               "resources": {key: _resource(assets, manifest["configuration"][key])
                                             for key in ("prompt", "tools", "kb")},
                               "retry": {"agent": 0, "tool": 0}}
                    phase = "open_scenario"
                    current_phase[0] = phase
                    adapter.invoke(phase, [runtime], times["agent"] / 1000)
                    record("business_snapshot", {"phase": "seeded", "state": environment.snapshot()})
                    for plan in call_plan(scenario, manifest["reference_date"]):
                        name, spec = plan["call"], scenario["calls"][plan["call"]]
                        context = {"run_id": manifest["run_id"], "config": current_config,
                                   "scenario_id": sid, "call": name, "turn": 1}
                        adapter.context, adapter.on = context, plan["on"]
                        environment.timeout = times["tool"] / 1000
                        call_status = {"context": copy.deepcopy(context), "attempted": True, "completed": False,
                                       "barrier_complete": False, "failed": False}
                        calls.append(call_status)
                        call_context = {**context, "on": plan["on"], "timezone": manifest["timezone"],
                                        "memory_read_previous": reads_memory(current_config),
                                        "input_mode": spec.get("input_mode", plan["input_field"]),
                                        **{key: scenario[key] for key in ("customer_phone", "customer_name", "honorific")},
                                        **{key: spec[key] for key in ("channel", "channel_identity") if key in spec}}
                        phase = "start_call"
                        current_phase[0] = phase
                        before = adapter.invoke(phase, [call_context], times["agent"] / 1000)
                        if (not isinstance(before, dict) or not isinstance(before.get("memory_snapshot"), dict)
                                or "call_brief" not in before):
                            raise ValueError("start_call must return raw memory_snapshot and call_brief (object or null)")
                        record("business_snapshot", {"phase": "before_call", "state": environment.snapshot()}, context)
                        say(f"[{current_config}] {sid} {name} ({plan['on']}): {plan['expected_turns']} turns")
                        session = simulator.session(scenario, name, spec, current_config) if simulator else None
                        scripted = iter(spec[plan["input_field"]])
                        text = session.first() if session else next(scripted, None)
                        turn = 0
                        while text is not None:
                            turn += 1
                            context["turn"] = turn
                            phase = "run_turn"
                            current_phase[0] = phase
                            turn_tools.clear()
                            record("customer_input", {"text": text, "input_field": plan["input_field"],
                                                      **({"simulated": True} if session else {})}, context)
                            started = time.monotonic()
                            result = adapter.invoke(phase, [text], times["agent"] / 1000)
                            if not isinstance(result, dict) or not isinstance(result.get("agent_text"), str):
                                raise ValueError("run_turn must return actual agent_text; preserve invalid raw for P3")
                            progress["done"] += 1
                            spent = (result.get("usage") or {}).get("cost")
                            progress["cost"] += spent if isinstance(spent, (int, float)) else 0.0
                            say(f"  turn {progress['done']}/{progress['total']} {name}#{turn} "
                                f"({time.monotonic() - started:.1f}s"
                                + (f", ${spent:.4f}, total ${progress['cost']:.3f}" if isinstance(spent, (int, float)) else "")
                                + ")")
                            say(f"      khách: {short(text)}")
                            say(f"      agent: {short(result['agent_text'], 110)}")
                            observed.append(f"{manifest['run_id']}/{current_config}/{sid}/{name}/{turn}")
                            text = session.reply(result["agent_text"], list(turn_tools)) if session else next(scripted, None)
                        if session:
                            record("simulator_log", session.log(), context)
                        phase = "end_call"
                        current_phase[0] = phase
                        after = adapter.invoke(phase, [], times["after_call"] / 1000)
                        if (not isinstance(after, dict) or after.get("completed") is not True
                                or after.get("barrier_complete") is not True
                                or not isinstance(after.get("memory_snapshot"), dict)):
                            raise ValueError("Call not complete: lifecycle + after-call barrier/snapshot required")
                        call_status.update(completed=True, barrier_complete=True)
                        record("business_snapshot", {"phase": "after_call", "state": environment.snapshot()}, context)
                    phase = "close_scenario"
                    current_phase[0] = phase
                    adapter.context = None
                    adapter.invoke(phase, [], times["agent"] / 1000)
                except Exception as exception:
                    error = {"code": "EXECUTION_ERROR", "config": current_config, "scenario_id": sid,
                             "context": copy.deepcopy(context), "phase": phase,
                             "error": f"{type(exception).__name__}: {exception}",
                             "reconciliation_required": phase in ("start_call", "run_turn", "end_call")
                                 or isinstance(exception, (TimeoutError, EOFError, BrokenPipeError)),
                             "retry": 0}
                    errors.append(error)
                    say(f"  ERROR [{current_config}] {sid} at {phase}: {short(error['error'], 200)}")
                    record("execution_error", error, context)
                    if context is not None and calls and not calls[-1]["completed"]:
                        calls[-1]["failed"] = True
                    # Do not start the next call in this scenario after a failed barrier/turn.
                    if (adapter is not None and adapter.process.is_alive()
                            and phase not in ("binding", "close_scenario")
                            and not isinstance(exception, (TimeoutError, EOFError, BrokenPipeError))):
                        try:
                            adapter.context = None
                            adapter.invoke("close_scenario", [], times["agent"] / 1000)
                        except Exception as cleanup_error:
                            record("cleanup_error", {"error": str(cleanup_error)}, context)
                finally:
                    if adapter is not None:
                        adapter.close()
                    if environment is not None:
                        environment.close()
    checker.verify_sources()
    counts = Counter(observed)
    coverage = {"expected_ids": expected, "observed_ids": observed,
                "missing_ids": sorted(set(expected) - set(observed)),
                "duplicate_ids": sorted(key for key, count in counts.items() if count > 1),
                "unknown_ids": sorted(set(observed) - set(expected))}
    execution_complete = not errors and (simulator is not None or not any(
        coverage[key] for key in ("missing_ids", "duplicate_ids", "unknown_ids")))
    summary = {"notice": "P2 execution only; not BTC trace, scorer, runtime isolation proof or quality acceptance",
               "run_id": manifest["run_id"], "fixture": manifest["fixture"], "configs": configs,
               "execution_complete": execution_complete, "bindings": bindings, "calls": calls,
               "attempted_calls": len(calls), "completed_calls": sum(c["completed"] for c in calls),
               "failed_calls": sum(c["failed"] for c in calls), "errors": errors, "coverage": coverage,
               "validation_status": report["validation"]["status"],
               "evaluation_status": {"verdict": "UNDETERMINED", "completeness": "INCOMPLETE",
                                     "reason_codes": ["P3_EVIDENCE_AND_TRACE_PENDING"]},
               "deferred": report["deferred"], "btc_full_readiness": "INCOMPLETE"}
    write_new(out / "runner-report.json", summary)
    # Hash only closed files, including partial runs. Lock is not itself evidence.
    write_new(out / "artifacts.lock.json", {"files": {
        path.relative_to(out).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(out.rglob("*")) if path.is_file()}})
    return summary
