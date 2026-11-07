"""The rubric judge over a finished run, and its agreement with people.

The organisers' rubric (``data/btc/eval/llm_judge_rubric.json``) asks for:
"Chọn ngẫu nhiên ≥20 (call, criterion) có cả verdict LLM và verdict người;
báo Cohen's kappa hoặc % đồng thuận; kappa < 0.6 → rubric/judge chưa tin cậy,
phải phân tích lỗi." Three steps, each its own command::

    python run_eval.py --judge-run evaluation/runs/<run> --out evaluation/runs/<run>-judge   # model calls, budget ledger
    python run_eval.py --judge-sample evaluation/runs/<run>-judge                         # no model; writes human-review/
    python run_eval.py --judge-agreement evaluation/runs/<run>-judge/human-review          # after people fill sheet.csv

``--judge-sample`` draws the pairs at random with a fixed seed, from the
``full`` configuration when the run has it. The sheet people fill holds no
LLM verdict: those are in ``judge-key.json`` beside it, which graders must
not open before they finish. ``calls.md`` shows each drawn call as the judge
saw it (scenario, earlier calls, transcript) and the criteria to grade.
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any, Iterable, Mapping

from ...components.evaluation import judge as rubric
from . import relabel, scenarios, trace

#: Fixed so the same judged run always gives the same sheet.
SEED = 20261107
#: The rubric's minimum number of graded pairs, and its kappa threshold.
MINIMUM = 20
THRESHOLD = 0.6
SHEET_FIELDS = ("sample_id", "scenario_id", "call", "criterion_id", "criterion", "human_verdict", "human_note")


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def judge_run(run: Path, out: Path, judge: Any) -> int:
    """Judge every call of *run*'s traces into *out*; the run itself is not changed. 0 when every call was judged."""
    from .cli import Layout, _write_json, prepare_output

    try:
        traces, scenarios_dir = relabel.locate(run)
        if out.resolve().is_relative_to(run.resolve()) or run.resolve().is_relative_to(out.resolve()):
            raise ValueError("Judge output must be separate from the source run")
        cohort, _ = scenarios.load(scenarios_dir)
        prepare_output(Layout(out, {}))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(error)
        return 2
    _write_json(out / "judge-run.json", {"source": str(run), "scenarios": str(scenarios_dir), "status": "INCOMPLETE"})
    everything = []
    for config, path in traces.items():
        judgments = await rubric.judge_calls(judge, cohort, _rows(path), config)
        trace.write_jsonl(out / f"{config}.judge.jsonl", judgments)
        everything += judgments
    summary = rubric.summarise(everything)
    _write_json(out / "judge-summary.json", summary)
    (out / "judge-table.txt").write_text(rubric.table(summary) + "\n", encoding="utf-8")
    complete = all(item.get("status") == "COMPLETE" for item in everything)
    _write_json(out / "judge-run.json", {"source": str(run), "scenarios": str(scenarios_dir),
                                        "status": "COMPLETE" if complete else "INCOMPLETE", "summary": summary})
    print(rubric.table(summary))
    return 0 if complete else 1


def _source(judged: Path) -> tuple[dict[str, Path], Path]:
    """The traces and scenarios a judged directory was made from: itself, or the run ``judge-run.json`` names."""
    try:
        return relabel.locate(judged)
    except ValueError:
        record = judged / "judge-run.json"
        if not record.is_file():
            raise
        return relabel.locate(Path(json.loads(record.read_text(encoding="utf-8"))["source"]))


def pool(judged: Path) -> list[dict[str, Any]]:
    """Every (call, criterion) the judge graded completely, from ``full`` when the run has it."""
    files = sorted(judged.glob("*.judge.jsonl"))
    preferred = [path for path in files if path.name == "full.judge.jsonl"] or files
    pairs = []
    for path in preferred:
        for item in _rows(path):
            if item.get("status") != "COMPLETE":
                continue
            for verdict in item["verdicts"]:
                pairs.append({"config": item["config"], "scenario_id": item["scenario_id"], "call": item["call"],
                              "criterion_id": verdict["criterion_id"], "verdict": verdict["verdict"],
                              "evidence": verdict["evidence"]})
    return sorted(pairs, key=lambda p: (p["config"], p["scenario_id"], p["call"], p["criterion_id"]))


def draw(judged: Path, out: Path, *, size: int = MINIMUM) -> int:
    """Write a blind grading sheet of *size* random pairs into *out*: 0, or 1 when fewer than the rubric's 20 exist."""
    try:
        traces, scenarios_dir = _source(judged)
        cohort = {item.scenario_id: item for item in scenarios.load(scenarios_dir)[0]}
        pairs = pool(judged)
        if not pairs:
            raise ValueError(f"{judged} holds no complete judgment (*.judge.jsonl)")
        out.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError, KeyError) as error:
        print(error)
        return 2
    chosen = random.Random(SEED).sample(pairs, min(size, len(pairs)))
    chosen.sort(key=lambda p: (p["scenario_id"], p["call"], p["criterion_id"]))
    criteria = _criteria()
    for number, pair in enumerate(chosen, start=1):
        pair["sample_id"] = f"S{number:02d}"
    with (out / "sheet.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        for pair in chosen:
            writer.writerow({"sample_id": pair["sample_id"], "scenario_id": pair["scenario_id"], "call": pair["call"],
                             "criterion_id": pair["criterion_id"], "criterion": criteria.get(pair["criterion_id"], ""),
                             "human_verdict": "", "human_note": ""})
    (out / "judge-key.json").write_text(json.dumps(
        {pair["sample_id"]: {key: pair[key] for key in ("config", "scenario_id", "call", "criterion_id", "verdict", "evidence")}
         for pair in chosen}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = {config: _rows(path) for config, path in traces.items()}
    config = chosen[0]["config"]
    (out / "calls.md").write_text(_calls_page(chosen, cohort, rows.get(config, []), criteria), encoding="utf-8")
    print(f"{len(chosen)} pairs from {len(pairs)} in {out}: fill sheet.csv (human_verdict PASS or FAIL) from calls.md, "
          f"without opening judge-key.json, then run --judge-agreement {out}")
    if len(chosen) < MINIMUM:
        print(f"Only {len(chosen)} pairs: the rubric asks for at least {MINIMUM}. Judge more calls first.")
        return 1
    return 0


def _criteria() -> dict[str, str]:
    from ...config.config_manager import btc_data_dir

    data = json.loads((btc_data_dir() / "eval/llm_judge_rubric.json").read_text(encoding="utf-8"))
    return {item["id"]: item["pass_if"] for item in data["criteria"]}


def _calls_page(chosen: list[dict], cohort: Mapping[str, Any], rows: list[dict], criteria: Mapping[str, str]) -> str:
    lines = ["# Phiếu chấm tay rubric BTC", "",
             "Chấm từng dòng của `sheet.csv`: điền `human_verdict` là PASS hoặc FAIL theo đúng `pass_if` của tiêu chí, "
             "chỉ dựa vào nội dung dưới đây. **Không mở `judge-key.json`** trước khi chấm xong.", ""]
    calls: dict[tuple[str, str], list[dict]] = {}
    for pair in chosen:
        calls.setdefault((pair["scenario_id"], pair["call"]), []).append(pair)
    for (scenario_id, call), pairs in calls.items():
        scenario = cohort.get(scenario_id)
        lines += [f"## {scenario_id} · {call}", ""]
        if scenario is not None:
            lines += ["Kịch bản như judge thấy:", "", "```json",
                      json.dumps(rubric.context(scenario.data, call), ensure_ascii=False, indent=2), "```", ""]
        lines += ["Transcript:", ""]
        for row in sorted((r for r in rows if r["scenario_id"] == scenario_id and r["call"] == call), key=lambda r: r["turn"]):
            tools = ", ".join(tool.get("name", "") for tool in row.get("tool_calls") or [])
            lines.append(f"- **Khách ({row['turn']}):** {row.get('customer_text', '')}")
            lines.append(f"- **Trợ lý ({row['turn']}):** {row.get('agent_text', '')}" + (f" _(tool: {tools})_" if tools else ""))
        lines += ["", "Tiêu chí cần chấm:", ""]
        lines += [f"- `{pair['sample_id']}` {pair['criterion_id']}: {criteria.get(pair['criterion_id'], '')}" for pair in pairs]
        lines.append("")
    return "\n".join(lines)


def kappa(pairs: Iterable[tuple[str, str]]) -> float | None:
    """Cohen's kappa of two raters over PASS/FAIL; None when chance agreement is total (one label only)."""
    pairs = list(pairs)
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    expected = sum((sum(a == label for a, _ in pairs) / n) * (sum(b == label for _, b in pairs) / n)
                   for label in ("PASS", "FAIL"))
    return None if expected == 1 else round((observed - expected) / (1 - expected), 3)


def report(sheet_dir: Path) -> int:
    """Agreement between the people's verdicts in ``sheet.csv`` and the judge's in ``judge-key.json``."""
    try:
        with (sheet_dir / "sheet.csv").open(encoding="utf-8-sig", newline="") as handle:
            sheet = list(csv.DictReader(handle))
        key = json.loads((sheet_dir / "judge-key.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(error)
        return 2
    graded, skipped = [], []
    for row in sheet:
        human = (row.get("human_verdict") or "").strip().upper()
        if human not in ("PASS", "FAIL") or row["sample_id"] not in key:
            skipped.append(row["sample_id"])
            continue
        graded.append({"sample_id": row["sample_id"], "criterion_id": row["criterion_id"], "human": human,
                       "judge": key[row["sample_id"]]["verdict"], "note": row.get("human_note", "")})
    if not graded:
        print("No row of sheet.csv has human_verdict PASS or FAIL yet")
        return 2
    agree = sum(item["human"] == item["judge"] for item in graded)
    value = kappa((item["judge"], item["human"]) for item in graded)
    per = {}
    for item in graded:
        counts = per.setdefault(item["criterion_id"], {"graded": 0, "agree": 0})
        counts["graded"] += 1
        counts["agree"] += int(item["human"] == item["judge"])
    status = ("TOO_FEW" if len(graded) < MINIMUM
              else "UNRELIABLE" if value is None or value < THRESHOLD else "RELIABLE")
    result = {"graded": len(graded), "skipped": skipped, "agreement_pct": round(100 * agree / len(graded), 1),
              "cohen_kappa": value, "threshold": THRESHOLD, "minimum": MINIMUM, "status": status,
              "per_criterion": dict(sorted(per.items())),
              "disagreements": [item for item in graded if item["human"] != item["judge"]]}
    (sheet_dir / "agreement.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(graded)} pairs graded: agreement {result['agreement_pct']}%, Cohen's kappa {value} -> {status}")
    if status == "TOO_FEW":
        print(f"The rubric asks for at least {MINIMUM} graded pairs.")
    elif status == "UNRELIABLE":
        print(f"kappa < {THRESHOLD}: the judge is not reliable yet; analyse the {len(result['disagreements'])} disagreements in agreement.json.")
    return 0
