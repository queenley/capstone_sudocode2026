"""Diagnostic: re-extract a closed run's transcripts with the current extractor and score RQR, CCR and HR with BTC's reference_eval.

The agent run is unchanged, only the instrument is. This is not a replacement for `evaluate`: it costs one extractor call per turn
(about 0.0006 USD each) and prints numbers, it writes nothing into the run. The extractor is the one `evaluate` would pin now:
the prompt in config/prompts/evaluation/extractor.txt, shown each turn's agent and tool text and, from the second call of a
scenario, the earlier calls of the same configuration (src/services/extractor.py). facts_used merges what the extractor saw
used with what the agent reported using, exactly as the collector does. Compare these numbers only with another rescoring
by the same extractor version, or with the run's own scored/official-report.json when that run used the same one.

    python docs/evaluation/rescore_with_scoped_extractor.py evaluation/agent-evaluation/runs/<day>-work/<run> [dataset-id]

dataset-id defaults to create-data-diagnostic-v4.
"""
import glob
import importlib.util
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
E = REPO / "evaluation/agent-evaluation"
sys.path.insert(0, str(E))

from src.steps.collect.collector import merged_facts_used  # noqa: E402
from src.services.extractor import attach_history, model_input  # noqa: E402

RUN = Path(sys.argv[1]).resolve()
DATASET = sys.argv[2] if len(sys.argv) > 2 else "create-data-diagnostic-v4"
spec = importlib.util.spec_from_file_location("ref", E / "contracts/sources/btc/eval/reference_eval.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)
config = json.loads((RUN / "inputs/extractor.json").read_text(encoding="utf-8"))["config"]
prompt = (REPO / "config/prompts/evaluation/extractor.txt").read_text(encoding="utf-8")
env = {**os.environ, "PYTHONUTF8": "1"}
PYTHON = REPO / "apps/ai-agent-service/.venv/bin/python"


def extract(document):
    payload = {"config": config, "prompt": prompt + "\n[INPUT DATA]\n" + json.dumps(model_input(document), ensure_ascii=False)}
    done = subprocess.run([str(PYTHON), "-B", "-m", "src.services.agent.extract_command"], cwd=E, input=json.dumps(payload, ensure_ascii=False),
                          text=True, encoding="utf-8", capture_output=True, env=env, timeout=150)
    answer = json.loads(done.stdout.strip().splitlines()[-1])
    if answer.get("raw") is None:
        raise RuntimeError(f"extraction failed: {answer.get('message')}")
    return json.loads(answer["raw"])["items"], answer.get("slots_outside_vocabulary", 0)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


scenarios = {s["scenario_id"]: s for s in map(load, glob.glob(str(E / f"datasets/{DATASET}/scenarios/*.json")))}
in_run = {load(p)["context"]["scenario_id"] for p in glob.glob(str(RUN / "evidence/full/transcripts/*.json"))}
scenarios = {k: v for k, v in scenarios.items() if k in in_run}
results = {}
for name in ("full", "baseline_no_memory"):
    documents = {p: load(p) for p in glob.glob(str(RUN / f"evidence/{name}/transcripts/*.json"))}
    attached = attach_history(documents)
    with ThreadPoolExecutor(6) as pool:
        extracted = dict(zip(attached, pool.map(extract, attached.values())))
    trace = {}
    for path, document in documents.items():
        items, _ = extracted[path]
        context = document["context"]
        trace.setdefault((context["scenario_id"], context["call"]), []).append({
            "turn": context["turn"], "agent_text": document["agent_text"],
            "tool_calls": [{"name": e["request"]["name"], "args": e["request"].get("args", {})} for e in document["tools"]],
            "questions": [{"slot": i["slot_or_field"], "type": i["question_type"], "text": i["quote"]}
                          for i in items if i["kind"] == "question" and i["speaker"] == "agent"],
            "claims": [{"field": i["slot_or_field"], "value": i["value"], "text": i["quote"]}
                       for i in items if i["kind"] == "claim" and i["speaker"] == "agent"],
            "facts_used": merged_facts_used(items, document)})
    for rows in trace.values():
        rows.sort(key=lambda r: r["turn"])
    results[name] = (ref.repeat_question_rate(scenarios, trace), ref.context_carryover_rate(scenarios, trace),
                     ref.hallucination_rate(scenarios, trace), sum(changed for _, changed in extracted.values()))

for name, (rqr, ccr, hr, changed) in results.items():
    price = hr["price_promo_only"]
    print(name, "RQR", rqr["value"], f"{rqr['redundant']}/{rqr['total_questions']}", "| CCR", ccr["value"], f"{ccr['used']}/{ccr['required']}",
          "| HR", hr["value"], f"{hr['wrong']}/{hr['total_claims']}", "| HR price&promo", price["value"], f"{price['wrong']}/{price['total']}",
          "| outside-vocab fixes", changed)
    if name == "full":
        for e in rqr["examples"]:
            print("   ", e["scenario"][-4:], e["call"], e["turn"], e["type"], e["slot"], "|", (e["text"] or "")[:70])
