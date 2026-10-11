"""Stage 3 — generate test scenarios (BTC ``scenario_format.md``).

    plan (deterministic labels) ──► LLM writes customer language ──► check ──► assemble ──► write

Usage::

    python -m src.pipeline.generate_scenarios --limit 48            # generate
    python -m src.pipeline.generate_scenarios --limit 48 --resume   # skip existing files
    python -m src.pipeline.generate_scenarios --limit 48 --plan-only  # labels only, no API calls

``--plan-only`` writes ``output/plans/*.json`` so the team can inspect every
metric label before spending API budget.
"""
from __future__ import annotations

import argparse
import json

import yaml

from src.planning.planner import assemble, check_draft, plan_scenarios, writer_context
from src.schemas.scenario import Scenario, ScenarioDraft
from src.utils.crm import SourceData
from src.utils.io import load_model, write_json
from src.utils.paths import CONFIG_DIR, PERSONAS_JSON, PLANS_DIR, PROMPTS_DIR, REPORTS_DIR, SCENARIOS_DIR, SCENARIOS_INTERNAL_DIR
from src.utils.scenario_export import write_combined_export, write_scenario
from src.utils.settings import load_settings, model_client, sampling
from src.utils.quota import DailyLimitReached, stop_on_daily_limit

MAX_DRAFT_ATTEMPTS = 4
#: Retries are about following the structure, not creativity.
RETRY_TEMPERATURE = 0.3
FAILURES_PATH = REPORTS_DIR / "scenario_failures.json"


class DraftRejected(RuntimeError):
    def __init__(self, scenario_id: str, errors: list[str]):
        super().__init__(f"{scenario_id}: draft still invalid after {MAX_DRAFT_ATTEMPTS} attempts: {errors}")
        self.scenario_id, self.errors = scenario_id, errors


def align_calls(sp, draft: ScenarioDraft) -> ScenarioDraft:
    """Keep the planned calls, matched by their ``call`` label, when the model wrote extra ones.

    A persona with old CRM history ("khách quay lại sau 8 tháng") tempts the
    model to write that old session as one more call. When every planned
    call is present by name, the extras are dropped instead of the draft.
    """
    planned = [pc.name for pc in sp.calls]
    if len(draft.calls) <= len(planned):
        return draft
    by_name = {c.call: c for c in draft.calls if c.call}
    if all(name in by_name for name in planned):
        return draft.model_copy(update={"calls": [by_name[name] for name in planned]})
    return draft


def _structure(sp) -> str:
    return ", ".join(f"{pc.name} ({pc.kind}, ≥{pc.template.min_turns} customer_turns)" for pc in sp.calls)


def write_draft(client, template: str, context: dict, sp, params: dict) -> ScenarioDraft:
    """Ask the LLM for customer language; retry with the deterministic check errors appended."""
    feedback = ""
    temperature = params["temperature"]
    errors: list[str] = []
    for attempt in range(1, MAX_DRAFT_ATTEMPTS + 1):
        # Context is already PII-safe (writer_context redacts CRM history); test CCCD/STK strings must stay verbatim.
        prompt = f"{template}\n\nINPUT:\n{json.dumps(context, ensure_ascii=False)}{feedback}"
        draft = align_calls(sp, client.generate(prompt, ScenarioDraft, temperature=temperature,
                                                max_output_tokens=params["max_output_tokens"]))
        errors = check_draft(sp, draft)
        if not errors:
            return draft
        print(f"  {sp.scenario_id} draft attempt {attempt} rejected: {errors}", flush=True)
        feedback = (
            "\n\nYOUR PREVIOUS OUTPUT WAS REJECTED. Fix exactly these problems:\n- " + "\n- ".join(errors)
            + f"\n\nREQUIRED STRUCTURE: `calls` has exactly {len(sp.calls)} objects, in this order, each with its "
            f"`call` field set: {_structure(sp)}. crm_history is the past: never write it as a call."
        )
        temperature = min(temperature, RETRY_TEMPERATURE)
    raise DraftRejected(sp.scenario_id, errors)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=48, help="number of scenarios (each has 2–3 calls)")
    parser.add_argument("--resume", action="store_true", help="keep scenarios already on disk")
    parser.add_argument("--plan-only", action="store_true", help="write label previews without calling a model")
    args = parser.parse_args()

    settings = load_settings()
    persona_cfg = yaml.safe_load((CONFIG_DIR / "personas.yaml").read_text(encoding="utf-8"))
    personas = {p["persona_id"]: p for p in json.loads(PERSONAS_JSON.read_text(encoding="utf-8"))["personas"]}
    levels = {p["id"]: p.get("level", "M2") for p in persona_cfg["personas"]}
    plans = plan_scenarios(args.limit, SourceData.load(), persona_cfg["personas"], personas,
                           int(settings["generation"]["seed"]))

    if args.plan_only:
        # Full internal scenarios with placeholder customer turns; feed them to
        # `build_ground_truth --scenarios output/plans --out output/plans` to verify every label offline.
        for old in PLANS_DIR.glob("SCN-GEN-*.json"):
            old.unlink()
        for sp in plans:
            write_json(PLANS_DIR / f"{sp.scenario_id}.json", assemble(sp, None, levels[sp.persona_id]))
        print(f"Wrote {len(plans)} label previews to {PLANS_DIR}")
        return

    client = model_client("scenario", settings)
    params = sampling(settings)
    template = (PROMPTS_DIR / "scenario_writer.jinja").read_text(encoding="utf-8")
    failures: list[dict] = []
    out_of_budget: DailyLimitReached | None = None
    for sp in plans:
        path = SCENARIOS_INTERNAL_DIR / f"{sp.scenario_id}.json"
        if args.resume and path.exists():
            try:
                load_model(path, Scenario)
                continue
            except ValueError:
                print(f"  {path.name} uses an old schema; regenerating", flush=True)
        context = writer_context(sp, personas.get(sp.persona_id, {}).get("style", ""))
        try:
            draft = write_draft(client, template, context, sp, params)
        except DailyLimitReached as error:
            # Stop asking, but still write the combined export of what exists.
            out_of_budget = error
            break
        except DraftRejected as rejected:
            # One stubborn scenario must not cost the other 149: skip it, record why.
            print(f"  SKIPPED {sp.scenario_id} ({sp.persona_id}): {rejected.errors}", flush=True)
            failures.append({"scenario_id": sp.scenario_id, "persona": sp.persona_id, "errors": rejected.errors})
            continue
        scenario = assemble(sp, draft, levels[sp.persona_id])
        write_scenario(scenario)
        print(f"Wrote {sp.scenario_id} ({sp.persona_id}, {len(scenario.calls)} calls, "
              f"focus={','.join(scenario.metric_focus)})", flush=True)

    exported = sorted(p for p in SCENARIOS_DIR.glob("SCN-GEN-*.json"))
    count = write_combined_export(exported, SCENARIOS_DIR.parent / "scenarios_all.json")
    print(f"Combined export: {count} scenarios -> output/scenarios_all.json")

    write_json(FAILURES_PATH, {"failed": failures})
    if failures:
        print(f"{len(failures)} scenario(s) skipped after {MAX_DRAFT_ATTEMPTS} attempts "
              f"({', '.join(f['scenario_id'] for f in failures)}); details in {FAILURES_PATH}. "
              "Rerun with --resume to retry only those.", flush=True)
        if len(failures) == len(plans):
            raise SystemExit("Every scenario failed; check the model and the prompt.")
    if out_of_budget is not None:
        missing = sum(1 for sp in plans if not (SCENARIOS_INTERNAL_DIR / f"{sp.scenario_id}.json").exists())
        print(f"{missing} of {len(plans)} scenarios still to write.", flush=True)
        raise out_of_budget  # stop_on_daily_limit prints the advice and exits EXIT_DAILY_LIMIT


if __name__ == "__main__":
    stop_on_daily_limit(main)()
