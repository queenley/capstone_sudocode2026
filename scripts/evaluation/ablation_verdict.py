"""The verdict of the 2x2 measurement ``ablation.py`` ran: does each method do what it learned, and do the two together.

    python scripts/evaluation/ablation_verdict.py --name abl-1

No model call. Reads evaluation/runs/<name>/ (``ablation.plan.json`` and the runs ``<config>-<set>-<i>``), grades every
run with the organisers' ``reference_eval.py`` (its functions, never a copy of its formulas), and writes
``ablation.json`` and ``ablation.md`` beside them.

Model noise. The advisor takes no temperature, so every configuration runs k times (k = 3) and is judged against the
spread of the Router's own k runs, never against one number:

  - per set and configuration: TSR, HR, RQR, CCR as the mean of the k runs, with their min and max;
  - per scenario: the share of the k runs it passed in;
  - against the Router: the mean difference of those shares over the set's scenarios, with a 95% interval from a paired
    bootstrap over scenarios (2000 resamples, fixed seed, so the same runs always give the same interval).

Checks:

  control (no harm)   for GapLoop, Reflection, Combined: TSR mean not below the Router's lowest run, HR mean not above
                      its highest, and the interval of the difference not wholly below 0.
  gap-loop            GapLoop and Combined pass every target case in every run; no control case (F11-F13) a Router
                      run passed every time fails in any of theirs. Reported, not required: the Router's share on the
                      targets (what there was to learn).
  budget/warranty/... Reflection and Combined, the same way (controls: the cases whose labels forbid a claim).
  learn/proof apart   no scenario id in both a learning set and its proof set (FAIL), and no customer turn of five
                      words or more in both (WARN, listed: a pleasantry is harmless, the proved question is not).
  interaction         per set, TSR(Combined) - TSR(GapLoop) - TSR(Reflection) + TSR(Router): near 0, the two add up;
                      clearly below 0, they get in each other's way (reported).

Exit 0 PASS, 1 FAIL, 3 WARN (fewer than 3 runs of a configuration).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "apps" / "ai-agent-service" / "data" / "btc" / "eval" / "reference_eval.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verdict import controls  # noqa: E402  the proof sets' control cases, one definition

CONFIGS = ("router", "gaploop", "reflection", "combined")
#: Which configurations must have learned what a set proves.
LEARNERS = {"gap-loop": ("gaploop", "combined")}
REFLECTION_SETS = ("budget", "warranty", "conduct")
for _set in REFLECTION_SETS:
    LEARNERS[_set] = ("reflection", "combined")
#: The learning sets pass under the same rule as their proofs (ablation.py runs them as "<set>-learn").
LEARNERS.update({f"{name}-learn": learners for name, learners in list(LEARNERS.items())})


def set_controls(label: str, path: Path) -> set[str]:
    """A proof set's controls (verdict.controls); in a learning set, the cases whose labels forbid a claim."""
    if not label.endswith("-learn"):
        return controls(label)
    return {f.stem for f in path.glob("*.json") if "forbidden_claims" in f.read_text(encoding="utf-8")}
MIN_RUNS = 3
RESAMPLES = 2000


def reference() -> Any:
    spec = importlib.util.spec_from_file_location("reference_eval", REFERENCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def graded(ref: Any, run: Path) -> dict[str, Any]:
    """The four metrics of one run and whether each scenario passed every one of its calls."""
    scenarios = ref.load_scenarios(str(run / "full.scenarios"))
    trace = ref.load_trace(str(run / "full.jsonl"))
    passed: dict[str, bool] = {}
    for sid, s in scenarios.items():
        ok = True
        for call in sorted(s["calls"]):
            earlier = [r for c in sorted(s["calls"]) if c < call for r in trace.get((sid, c), [])]
            result, _ = ref.check_call(s["calls"][call], trace.get((sid, call), []), ref.created_order_ids(earlier))
            ok = ok and result is not False
        passed[sid] = ok
    tsr = ref.task_success_rate(scenarios, trace)
    hr = ref.hallucination_rate(scenarios, trace)
    rqr = ref.repeat_question_rate(scenarios, trace)
    ccr = ref.context_carryover_rate(scenarios, trace)
    return {"passed": passed, "TSR": tsr["value"], "HR": hr["value"], "RQR": rqr["value"], "CCR": ccr["value"]}


def shares(runs: Sequence[Mapping[str, bool]]) -> dict[str, float]:
    """Per scenario, the share of the runs it passed in."""
    ids = sorted(set().union(*runs)) if runs else []
    return {sid: mean(1.0 if r.get(sid) else 0.0 for r in runs) for sid in ids}


def bootstrap(diffs: Sequence[float], resamples: int = RESAMPLES, seed: int = 0) -> tuple[float, float]:
    """95% interval of the mean of *diffs* by resampling scenarios; the same diffs always give the same interval."""
    if not diffs:
        return 0.0, 0.0
    rng = random.Random(seed)
    means = sorted(mean(rng.choice(diffs) for _ in diffs) for _ in range(resamples))
    return means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def spread(values: Sequence[float | None]) -> dict[str, float | None]:
    vs = [v for v in values if v is not None]
    return {"mean": round(mean(vs), 1) if vs else None, "min": min(vs) if vs else None, "max": max(vs) if vs else None,
            "runs": len(vs)}


def proof_checks(label: str, by_config: Mapping[str, Mapping[str, float]], ctl: set[str]) -> list[dict[str, str]]:
    """Each learner passes every target case in every run; no control case the Router always passed is lost."""
    out = []
    router = by_config.get("router", {})
    targets = sorted(set(router) - ctl) if router else []
    if router:
        learned_from = mean(router[s] for s in targets) if targets else 1.0
        out.append({"set": label, "config": "router", "check": "tỉ lệ đạt ca mục tiêu trước khi học (tham khảo)",
                    "status": "INFO", "detail": f"{learned_from:.2f} trên {len(targets)} ca"})
    for config in LEARNERS.get(label, ()):
        got = by_config.get(config)
        if not got:
            out.append({"set": label, "config": config, "check": "đã đo", "status": "FAIL", "detail": "thiếu run"})
            continue
        missed = sorted(s for s in targets if got.get(s, 0.0) < 1.0)
        out.append({"set": label, "config": config, "check": "ca mục tiêu đạt mọi lần chạy",
                    "status": "PASS" if not missed else "FAIL",
                    "detail": f"{len(targets) - len(missed)}/{len(targets)}" + (f"; trượt: {', '.join(missed)}" if missed else "")})
        lost = sorted(s for s in ctl if router.get(s) == 1.0 and got.get(s, 0.0) < 1.0)
        out.append({"set": label, "config": config, "check": "ca đối chứng không mất",
                    "status": "PASS" if not lost else "FAIL",
                    "detail": f"{len(ctl)} ca đối chứng" + (f"; mất: {', '.join(lost)}" if lost else "")})
    return out


def control_checks(metrics: Mapping[str, Mapping[str, Any]], by_config: Mapping[str, Mapping[str, float]]) -> list[dict[str, str]]:
    """No harm on the data/dev sample, judged against the Router's spread."""
    out = []
    router = metrics.get("router")
    if not router:
        return [{"set": "control", "config": "router", "check": "đã đo", "status": "FAIL", "detail": "thiếu run Router"}]
    for config in CONFIGS[1:]:
        m = metrics.get(config)
        if not m:
            continue
        tsr_ok = m["TSR"]["mean"] is not None and router["TSR"]["min"] is not None and m["TSR"]["mean"] >= router["TSR"]["min"]
        hr_ok = m["HR"]["mean"] is None or router["HR"]["max"] is None or m["HR"]["mean"] <= router["HR"]["max"]
        ids = sorted(set(by_config["router"]) & set(by_config.get(config, {})))
        low, high = bootstrap([by_config[config][s] - by_config["router"][s] for s in ids])
        status = "PASS" if tsr_ok and hr_ok and high >= 0 else "FAIL"
        out.append({"set": "control", "config": config, "check": "không làm hỏng (trong dao động Router)", "status": status,
                    "detail": f"TSR {m['TSR']['mean']} so với Router [{router['TSR']['min']}-{router['TSR']['max']}]; "
                              f"HR {m['HR']['mean']} so với Router tối đa {router['HR']['max']}; "
                              f"chênh tỉ lệ đạt theo kịch bản 95% [{low:+.2f}, {high:+.2f}]"})
    return out


def turns_of(folder: Path) -> tuple[set[str], set[str]]:
    """The scenario ids of a set and its customers' turns of five words or more, lower case, punctuation removed."""
    ids, turns = set(), set()
    for f in folder.glob("*.json"):
        s = json.loads(f.read_text(encoding="utf-8"))
        ids.add(s.get("scenario_id", f.stem))
        for spec in (s.get("calls") or {}).values():
            for text in spec.get("customer_turns") or []:
                words = re.findall(r"\w+", text.lower())
                if len(words) >= 5:
                    turns.add(" ".join(words))
    return ids, turns


def apart(learn: Path, proof: Path) -> dict[str, Any]:
    li, lt = turns_of(learn)
    pi, pt = turns_of(proof)
    shared_ids, shared_turns = sorted(li & pi), sorted(lt & pt)
    # A shared scenario is the same case seen twice: FAIL. A shared turn may be a pleasantry ("đúng rồi đặt đi em")
    # or the very question the set proves: a person reads the list (WARN).
    return {"status": "FAIL" if shared_ids else "WARN" if shared_turns else "PASS",
            "detail": f"{len(shared_ids)} kịch bản chung, {len(shared_turns)} lượt khách chung"
                      + (f": {', '.join(shared_ids[:5])} {'; '.join(shared_turns[:3])}" if shared_ids or shared_turns else "")}


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True)
    args = p.parse_args(argv)
    folder = ROOT / "evaluation" / "runs" / args.name
    plan = json.loads((folder / "ablation.plan.json").read_text(encoding="utf-8"))
    ref = reference()
    checks: list[dict[str, str]] = []
    table: dict[str, dict[str, Any]] = {}
    tsr_means: dict[str, dict[str, float | None]] = {}
    for label in plan["sets"]:
        metrics: dict[str, dict[str, Any]] = {}
        by_config: dict[str, dict[str, float]] = {}
        for config in plan["configs"]:
            runs = sorted(r for r in folder.glob(f"{config}-{label}-*") if (r / "full.jsonl").is_file())
            if not runs:
                continue
            grades = [graded(ref, r) for r in runs]
            by_config[config] = shares([g["passed"] for g in grades])
            metrics[config] = {k: spread([g[k] for g in grades]) for k in ("TSR", "HR", "RQR", "CCR")}
            if len(runs) < MIN_RUNS:
                checks.append({"set": label, "config": config, "check": f"đủ {MIN_RUNS} lần chạy", "status": "WARN",
                               "detail": f"{len(runs)} lần: không tách được dao động"})
        table[label] = metrics
        tsr_means[label] = {c: (metrics.get(c) or {}).get("TSR", {}).get("mean") for c in CONFIGS}
        if label == "control":
            checks += control_checks(metrics, by_config)
        else:
            checks += proof_checks(label, by_config, set_controls(label, ROOT / plan["sets"][label]["path"]))
    for label, learn in plan.get("learn_sets", {}).items():
        if label in plan["sets"]:
            result = apart(ROOT / learn, ROOT / plan["sets"][label]["path"])
            checks.append({"set": label, "config": "-", "check": "bộ học và bộ chứng minh tách rời", **result})
    interaction = {}
    for label, t in tsr_means.items():
        if all(t.get(c) is not None for c in CONFIGS):
            interaction[label] = round(t["combined"] - t["gaploop"] - t["reflection"] + t["router"], 1)
    statuses = {c["status"] for c in checks}
    verdict = "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "PASS"
    result = {"name": args.name, "verdict": verdict, "plan": plan, "metrics": table, "interaction_tsr": interaction,
              "checks": checks}
    (folder / "ablation.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (folder / "ablation.md").write_text(markdown(result), encoding="utf-8")
    print(markdown(result))
    return {"FAIL": 1, "WARN": 3}.get(verdict, 0)


def markdown(result: Mapping[str, Any]) -> str:
    plan = result["plan"]
    lines = [f"# Ablation {result['name']}: {result['verdict']}", "",
             f"GapLoop: kb v{plan['kb_version']} của `{plan['gap_round']}`. Reflection: skills v{plan['skills_version']} "
             f"của `{plan['reflection_round']}`. Combined = cả hai. {plan['runs']} lần chạy mỗi cấu hình mỗi bộ.", ""]
    for label, metrics in result["metrics"].items():
        lines += [f"## {label}", "", "| Cấu hình | TSR TB [min-max] | HR TB [min-max] | RQR TB | CCR TB | Số lần |",
                  "|---|---|---|---|---|---|"]
        for config in CONFIGS:
            m = metrics.get(config)
            if m:
                lines.append(f"| {config} | {m['TSR']['mean']} [{m['TSR']['min']}-{m['TSR']['max']}] | {m['HR']['mean']} "
                             f"[{m['HR']['min']}-{m['HR']['max']}] | {m['RQR']['mean']} | {m['CCR']['mean']} | {m['TSR']['runs']} |")
        if label in result["interaction_tsr"]:
            lines.append(f"\nTương tác TSR (C − G − R + R0): {result['interaction_tsr'][label]:+.1f}")
        lines.append("")
    lines += ["## Kiểm tra", "", "| Bộ | Cấu hình | Kiểm | Kết quả | Chi tiết |", "|---|---|---|---|---|"]
    lines += [f"| {c['set']} | {c['config']} | {c['check']} | {c['status']} | {c['detail']} |" for c in result["checks"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
