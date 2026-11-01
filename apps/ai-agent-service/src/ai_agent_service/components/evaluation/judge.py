"""Optional BTC rubric judge. Diagnostic only; never changes reference_eval's result."""
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from ...config.config_manager import btc_data_dir
from ..intake import pii


class Criterion(BaseModel):
    criterion_id: str
    verdict: Literal["PASS", "FAIL"]
    evidence: str = Field(min_length=1)


class Judgment(BaseModel):
    verdicts: list[Criterion]


def applicable(spec: dict, call: str) -> list[str]:
    truth, success = spec.get("ground_truth_facts") or {}, spec.get("success_if") or {}
    selected = ["J02_no_fabrication", "J06_tone_vietnamese", "J08_over_confirmation"]
    conditions = {
        "J01_opening_continuity": call != "call_1",
        "J03_conflict_handling": bool(spec.get("must_carry_over") or spec.get("seed_history")),
        "J04_identity_check": bool((spec.get("memory_expectation") or {}).get("must_not_write_to")),
        "J05_escalation_quality": spec.get("expected_outcome") == "chuyen_may",
        "J07_closing_summary": success.get("tool_called") == "order.create",
        "J09_pii_handling": bool(success.get("trace_must_not_match")),
        "J10_honest_ai": "is_human" in truth,
        "J11_budget_transparency": truth.get("cod_allowed") is False or bool(success.get("also_ordered")),
        "J12_out_of_stock": truth.get("in_stock") is False,
    }
    return sorted(selected + [key for key, applies in conditions.items() if applies])


class BtcJudge:
    def __init__(self, llm: Any):
        self.rubric = json.loads((btc_data_dir() / "eval/llm_judge_rubric.json").read_text(encoding="utf-8"))
        self.writer = llm.with_structured_output(Judgment)

    async def grade(self, spec: dict, call: str, rows: list[dict]) -> dict:
        ids = applicable(spec, call)
        vault = pii.Vault()
        scenario = pii.tokenise_data(spec, vault)
        transcript = pii.tokenise_data([{key: row.get(key) for key in ("customer_text", "agent_text", "tool_calls")}
                                        for row in rows], vault)
        prompt = self.rubric["judge_prompt_template"].format(
            scenario_json=json.dumps(scenario, ensure_ascii=False),
            transcript=json.dumps(transcript, ensure_ascii=False),
            criteria=json.dumps([item for item in self.rubric["criteria"] if item["id"] in ids], ensure_ascii=False))
        prompt += '\nTrả JSON {"verdicts": [...]} với một verdict cho mỗi tiêu chí.'
        try:
            result = await self.writer.ainvoke(prompt)
            verdicts = result.verdicts
        except Exception as error:
            return {"status": "INCOMPLETE", "criteria": ids, "verdicts": [], "error": type(error).__name__}
        actual = [item.criterion_id for item in verdicts]
        quotes = "\n".join(str(row.get(key) or "") for row in transcript for key in ("customer_text", "agent_text"))
        complete = sorted(actual) == ids and all(item.evidence.strip() and item.evidence.strip() in quotes for item in verdicts)
        return {"status": "COMPLETE" if complete else "INCOMPLETE", "criteria": ids,
                "verdicts": [item.model_dump() for item in verdicts]}
