"""Stage 3 — generate test scenarios (BTC ``scenario_format.md``).

    plan (deterministic labels) ──► LLM writes customer language ──► check ──► assemble ──► write

Two persona sets (``src/planning/persona_config.py``): BTC's (``SCN-GEN-*``) and
the team's advanced ones (``SCN-ADV-*``). ``--limit`` and ``--advanced-limit``
say how many scenarios of each.

Usage::

    python -m src.pipeline.generate_scenarios --limit 150                     # both sets
    python -m src.pipeline.generate_scenarios --personas advanced             # the team's only
    python -m src.pipeline.generate_scenarios --limit 150 --resume                     # keep what is on disk
    python -m src.pipeline.generate_scenarios --limit 150 --fresh                      # delete old output first
    python -m src.pipeline.generate_scenarios --limit 150 --plan-only                  # labels only, no API calls

``--plan-only`` writes the same layout to ``<seed>/plan_preview/`` with
placeholder customer turns, so every label can be checked before spending API budget.
"""
from __future__ import annotations

import argparse
import json

from src.planning.persona_config import load_persona_set, load_persona_sets, load_profiles
from src.planning.planner import ScenarioPlan, assemble, check_draft, plan_scenarios, writer_context
from src.schemas.scenario import ScenarioDraft, as_draft, draft_schema
from src.utils.crm import SourceData
from src.utils.dataset import Dataset
from src.utils.io import write_json
from src.utils.paths import PLAN_PREVIEW_DIR, PROMPTS_DIR, REPORTS_DIR
from src.utils.quota import DailyLimitReached, stop_on_daily_limit
from src.utils.settings import load_settings, model_client, sampling

MAX_DRAFT_ATTEMPTS = 4
#: Retries are about following the structure, not creativity.
RETRY_TEMPERATURE = 0.3
FAILURES_PATH = REPORTS_DIR / "scenario_failures.json"


class DraftRejected(RuntimeError):
    def __init__(self, scenario_id: str, errors: list[str]):
        super().__init__(f"{scenario_id}: draft still invalid after {MAX_DRAFT_ATTEMPTS} attempts: {errors}")
        self.scenario_id, self.errors = scenario_id, errors


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
        shape = tuple((pc.name, tuple(sorted(pc.customer_must_state)), pc.input_mode != "text") for pc in sp.calls)
        answer = client.generate(prompt, draft_schema(shape), temperature=temperature,
                                 max_output_tokens=params["max_output_tokens"])
        draft = as_draft(answer, shape)
        errors = check_draft(sp, draft)
        if not errors:
            return draft
        print(f"  {sp.scenario_id} draft attempt {attempt} rejected: {errors}", flush=True)
        repair = []
        for pc, dc in zip(sp.calls, draft.calls):
            missing = sorted(set(pc.customer_must_state) - {fact.slot for fact in dc.facts_stated})
            if missing:
                required = {slot: pc.customer_must_state[slot] for slot in missing}
                repair.append(f"{pc.name}: add facts_stated entries exactly for {json.dumps(required, ensure_ascii=False)} and state each value in customer_turns")
            if pc.input_mode != "text":
                repair.append(f"{pc.name}: output exactly {len(dc.customer_turns)} customer_turns_asr strings, one aligned line for each customer_turn")
        feedback = (
            "\n\nYOUR PREVIOUS OUTPUT WAS REJECTED. Fix exactly these problems:\n- " + "\n- ".join(errors)
            + ("\n\nTARGETED REPAIR CHECKLIST:\n- " + "\n- ".join(repair) if repair else "")
            + f"\n\nREQUIRED STRUCTURE: one key per planned call, {_structure(sp)}. "
            "crm_history is the past: never write it as a call."
        )
        temperature = min(temperature, RETRY_TEMPERATURE)
    raise DraftRejected(sp.scenario_id, errors)


def planned(personas: str, limit: int, advanced_limit: int | None, seed: int) -> list[ScenarioPlan]:
    """The plans of each persona set asked for, BTC's first."""
    source, profiles = SourceData.load(), load_profiles()
    counts = {"btc": limit, "advanced": advanced_limit}
    if advanced_limit is None:
        counts["advanced"] = sum(x["target"] for x in load_persona_set("advanced").targets)
    return [sp for persona_set in load_persona_sets(personas)
            for sp in plan_scenarios(counts[persona_set.source], source, persona_set, profiles, seed)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--personas", default="all", choices=("btc", "advanced", "all"))
    parser.add_argument("--limit", type=int, default=150, help="BTC-persona scenarios (each has 1–3 calls)")
    parser.add_argument("--advanced-limit", type=int,
                        help="advanced-persona scenarios (default: the sum of the targets in personas_advanced.yaml)")
    parser.add_argument("--resume", action="store_true", help="keep scenarios already on disk")
    parser.add_argument("--fresh", action="store_true", help="delete every generated scenario and transcript first")
    parser.add_argument("--plan-only", action="store_true", help="write label previews without calling a model")
    args = parser.parse_args()

    settings = load_settings()
    plans = planned(args.personas, args.limit, args.advanced_limit, int(settings["generation"]["seed"]))

    if args.plan_only:
        preview = Dataset(PLAN_PREVIEW_DIR)
        preview.clear()
        for sp in plans:
            preview.write_scenario(assemble(sp, None))
        print(f"Wrote {len(plans)} label previews to {PLAN_PREVIEW_DIR}")
        return

    dataset = Dataset()
    if args.fresh:
        dataset.clear()
    client = model_client("scenario", settings)
    params = sampling(settings)
    template = (PROMPTS_DIR / "scenario_writer.jinja").read_text(encoding="utf-8")
    profiles = load_profiles()
    failures: list[dict] = []
    out_of_budget: DailyLimitReached | None = None
    for sp in plans:
        if args.resume and dataset.has_scenario(sp.scenario_id):
            continue
        context = writer_context(sp, profiles.get(sp.persona_id, {}).get("style", ""))
        try:
            draft = write_draft(client, template, context, sp, params)
        except DailyLimitReached as error:
            out_of_budget = error   # stop asking; what exists is already written
            break
        except DraftRejected as rejected:
            # One stubborn scenario must not cost the others: skip it, record why.
            print(f"  SKIPPED {sp.scenario_id} ({sp.persona_id}): {rejected.errors}", flush=True)
            failures.append({"scenario_id": sp.scenario_id, "persona": sp.persona_id, "errors": rejected.errors})
            continue
        scenario = assemble(sp, draft)
        dataset.write_scenario(scenario)
        print(f"Wrote {sp.scenario_id} ({sp.persona_id}, {len(scenario.calls)} calls, "
              f"focus={','.join(scenario.metric_focus)})", flush=True)

    write_json(FAILURES_PATH, {"failed": failures})
    if failures:
        print(f"{len(failures)} scenario(s) skipped after {MAX_DRAFT_ATTEMPTS} attempts "
              f"({', '.join(f['scenario_id'] for f in failures)}); details in {FAILURES_PATH}. "
              "Rerun with --resume to retry only those.", flush=True)
        if len(failures) == len(plans):
            raise SystemExit("Every scenario failed; check the model and the prompt.")
    if out_of_budget is not None:
        missing = sum(1 for sp in plans if not dataset.has_scenario(sp.scenario_id))
        print(f"{missing} of {len(plans)} scenarios still to write.", flush=True)
        raise out_of_budget  # stop_on_daily_limit prints the advice and exits EXIT_DAILY_LIMIT


if __name__ == "__main__":
    stop_on_daily_limit(main)()
