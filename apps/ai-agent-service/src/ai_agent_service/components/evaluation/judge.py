"""Optional BTC rubric judge. Diagnostic only; never changes reference_eval's result.

The organisers' rubric (``data/btc/eval/llm_judge_rubric.json``) is used as it is:
its prompt template, its twelve criteria, PASS or FAIL with a one-sentence quote.
Two things the rubric leaves to the team are decided here:

* **What the judge reads.** The rubric's ``[KỊCH BẢN]`` is "the customer's goal,
  what is known from earlier sessions, the ground truth". So the judge gets the
  scenario's header (persona, hard case, name, honorific, notes), every earlier
  call's goal, channel, established facts and outcome, and this call's spec.
  Without the earlier calls it could not grade J01 or J03, nor J06 without the
  honorific.
* **Which criteria apply to a call** (:func:`applicable`), from the rubric's
  ``applies_to`` read against the scenario, its hard case and what the trace
  shows the agent did (an order created, a transfer, a stock result).

Agreement with people (the rubric's ``agreement_protocol``) is
``pipeline/eval/judge_agreement.py``.
"""
import json
import re
from typing import Callable, Any, Literal, Mapping

from pydantic import BaseModel, Field

from ...config.config_manager import btc_data_dir
from ..intake import pii


class Criterion(BaseModel):
    criterion_id: str
    verdict: Literal["PASS", "FAIL"]
    evidence: str = Field(min_length=1)


class Judgment(BaseModel):
    verdicts: list[Criterion]


#: Hard cases (the scenarios' ``hard_case``) that put a conflict, a change of mind or a price
#: that differs between channels or sessions in front of the agent: J03.
CONFLICT_CASES = frozenset({"doi_khuyen_mai_het_han", "ba_kenh_bao_gia_lech", "teencode_da_kenh",
                            "ba_phien_doi_thong_tin", "phien_ban_chinh_sach_cu", "quay_lai_8_thang_ttl_trade_in"})
#: A shared phone number or a profile that does not match: J04.
IDENTITY_CASES = frozenset({"chung_sdt_memory_poisoning"})
#: The customer asks whether a person or a machine is speaking: J10.
HUMAN_CASES = frozenset({"hoi_ai_va_xoa_du_lieu"})
#: An order over the customer's budget or over the COD limit: J11.
COD_CASES = frozenset({"16_luot_4_san_pham_vuot_cod"})
#: A product out of stock when the customer decides: J12.
STOCK_CASES = frozenset({"het_hang_luc_khach_quyet"})

#: A customer asking "person or machine?": J10 applies even when the scenario did not plan it.
ASKS_HUMAN = re.compile(r"người thật|người hay máy|máy hay người|\brobot\b|\bbot\b|\bAI\b|trí tuệ nhân tạo", re.IGNORECASE)
#: A run of 9 to 14 digits that is not a 10-digit phone number: an ID card or bank account (J09).
ID_NUMBER = re.compile(r"(?<!\d)\d{9,14}(?!\d)")

ALWAYS = ("J02_no_fabrication", "J06_tone_vietnamese", "J08_over_confirmation")
#: The fields of a scenario's header the judge reads.
HEADER = ("scenario_id", "level", "persona", "hard_case", "customer_name", "honorific", "notes")
#: What the judge reads of an earlier call: what was sought, where, what became known, how it ended.
EARLIER = ("channel", "customer_goal", "facts_established", "expected_outcome")


def _calls(scenario: Mapping[str, Any]) -> list[str]:
    return sorted(scenario.get("calls") or {}, key=lambda name: (len(name), name))


def _tools(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [tool for row in rows for tool in (row.get("tool_calls") or [])]


def context(scenario: Mapping[str, Any], call: str) -> dict[str, Any]:
    """What the judge is told about the scenario: its header, the earlier calls and this call."""
    order = _calls(scenario)
    earlier = order[:order.index(call)] if call in order else []
    calls = scenario.get("calls") or {}
    return {
        "scenario": {key: scenario.get(key) for key in HEADER if scenario.get(key) is not None},
        "previous_calls": [{"call": name, **{key: calls[name][key] for key in EARLIER if key in calls[name]}}
                           for name in earlier],
        "this_call": {"call": call, **(calls.get(call) or {})},
    }


def _budget(scenario: Mapping[str, Any], call: str) -> int | None:
    """The budget the customer stated in this call or an earlier one, if any."""
    order = _calls(scenario)
    seen = order[:order.index(call) + 1] if call in order else []
    budget = None
    for name in seen:
        spec = (scenario.get("calls") or {})[name]
        for facts in (spec.get("facts_established") or {}, spec.get("memory_expectation") or {}):
            if isinstance(facts.get("budget_vnd"), (int, float)):
                budget = int(facts["budget_vnd"])
    return budget


def applicable(scenario: Mapping[str, Any], call: str, rows: list[Mapping[str, Any]]) -> list[str]:
    """The rubric's criteria that apply to *call*, from each one's ``applies_to``.

    The scenario says what was planned (its hard case, ground truth, expected
    outcome); the trace says what happened (an order created, a transfer, a
    product reported out of stock). A criterion applies when either does.
    """
    calls = scenario.get("calls") or {}
    spec = calls.get(call) or {}
    truth, success = spec.get("ground_truth_facts") or {}, spec.get("success_if") or {}
    memory = spec.get("memory_expectation") or {}
    case = scenario.get("hard_case")
    order = _calls(scenario)
    first = not order or call == order[0]
    previous = calls.get(order[order.index(call) - 1]) if call in order and not first else None
    tools = _tools(rows)
    names = {tool.get("name") for tool in tools}
    said = " ".join(str(row.get("customer_text") or "") for row in rows)
    forbidden = {item.get("field") for item in success.get("forbidden_claims") or [] if isinstance(item, dict)}
    # An order of several units carries its prices in lines (the organisers' update of 11/2026).
    ordered = sum(int(line.get("price_vnd") or 0) * int(line.get("qty") or 1)
                  for tool in tools if tool.get("name") == "order.create"
                  for line in ((tool.get("args") or {}).get("lines") or [tool.get("args") or {}]))
    budget = _budget(scenario, call)
    out_of_stock = any(isinstance(tool.get("result"), dict) and tool["result"].get("in_stock") is False
                       for tool in tools if tool.get("name") == "inventory.check")
    conditions = {
        "J01_opening_continuity": not first,
        "J03_conflict_handling": (not first and case in CONFLICT_CASES) or "superseded" in memory
        or (previous is not None and previous.get("channel") and spec.get("channel")
            and previous.get("channel") != spec.get("channel")),
        "J04_identity_check": case in IDENTITY_CASES or bool(memory.get("must_not_write_to")),
        "J05_escalation_quality": spec.get("expected_outcome") == "chuyen_may"
        or success.get("tool_called") == "handoff.transfer" or "handoff.transfer" in names,
        "J07_closing_summary": "order.create" in names,
        "J09_pii_handling": bool(success.get("trace_must_not_match"))
        or any(len(number) != 10 or not number.startswith("0") for number in ID_NUMBER.findall(said)),
        "J10_honest_ai": "is_human" in truth or "is_human" in forbidden or case in HUMAN_CASES
        or bool(ASKS_HUMAN.search(said)),
        "J11_budget_transparency": truth.get("cod_allowed") is False or case in COD_CASES
        or (budget is not None and ordered > budget),
        "J12_out_of_stock": truth.get("in_stock") is False or truth.get("new_size_in_stock") is False
        or truth.get("product_available") is False or case in STOCK_CASES or out_of_stock,
    }
    return sorted(list(ALWAYS) + [key for key, applies in conditions.items() if applies])


class BtcJudge:
    def __init__(self, llm: Any, quoted: Callable[[str, str], bool] | None = None):
        """*quoted* says whether a verdict's evidence is in the call's words; the evaluation keeps the exact match."""
        self.rubric = json.loads((btc_data_dir() / "eval/llm_judge_rubric.json").read_text(encoding="utf-8"))
        self.writer = llm.with_structured_output(Judgment)
        self.quoted = quoted or (lambda evidence, words: evidence.strip() in words)

    async def grade(self, scenario: Mapping[str, Any], call: str, rows: list[dict]) -> dict:
        ids = applicable(scenario, call, rows)
        vault = pii.Vault()
        told = pii.tokenise_data(context(scenario, call), vault)
        transcript = pii.tokenise_data([{key: row.get(key) for key in ("customer_text", "agent_text", "tool_calls")}
                                        for row in rows], vault)
        prompt = self.rubric["judge_prompt_template"].format(
            scenario_json=json.dumps(told, ensure_ascii=False),
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
        complete = sorted(actual) == ids and all(item.evidence.strip() and self.quoted(item.evidence, quotes) for item in verdicts)
        return {"status": "COMPLETE" if complete else "INCOMPLETE", "criteria": ids,
                "verdicts": [item.model_dump() for item in verdicts]}


async def judge_calls(judge: BtcJudge, scenarios: list[Any], rows: list[dict], config: str) -> list[dict]:
    """One judgment per call of each scenario that has turns in *rows* (one configuration's trace)."""
    judgments = []
    for scenario in scenarios:
        for call in _calls(scenario.data):
            turns = sorted((row for row in rows if row["scenario_id"] == scenario.scenario_id and row["call"] == call),
                           key=lambda row: row["turn"])
            if turns:
                judgments.append({"config": config, "scenario_id": scenario.scenario_id, "call": call,
                                  **await judge.grade(dict(scenario.data), call, turns)})
    return judgments


def summarise(judgments: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Per configuration: calls judged, complete, and PASS/FAIL per criterion over complete calls only."""
    out: dict[str, Any] = {}
    for item in judgments:
        config = out.setdefault(item["config"], {"calls": 0, "complete": 0, "incomplete": 0, "criteria": {}})
        config["calls"] += 1
        if item.get("status") != "COMPLETE":
            config["incomplete"] += 1
            continue
        config["complete"] += 1
        for verdict in item["verdicts"]:
            counts = config["criteria"].setdefault(verdict["criterion_id"], {"PASS": 0, "FAIL": 0})
            counts[verdict["verdict"]] += 1
    for config in out.values():
        config["criteria"] = dict(sorted(config["criteria"].items()))
        for counts in config["criteria"].values():
            counts["pass_rate"] = round(100 * counts["PASS"] / (counts["PASS"] + counts["FAIL"]), 1)
    return out


def table(summary: Mapping[str, Any]) -> str:
    """The summary as lines a person reads: one row per criterion, one column per configuration."""
    configs = list(summary)
    criteria = sorted({key for config in summary.values() for key in config["criteria"]})
    lines = ["Rubric judge (diagnostic, BTC rubric; % PASS over complete calls)",
             f"{'Criterion':<26}" + "".join(f"{name:>22}" for name in configs)]
    for key in criteria:
        cells = []
        for name in configs:
            counts = summary[name]["criteria"].get(key)
            cells.append(f"{counts['pass_rate']}% ({counts['PASS']}/{counts['PASS'] + counts['FAIL']})" if counts else "-")
        lines.append(f"{key:<26}" + "".join(f"{cell:>22}" for cell in cells))
    lines.append(f"{'Calls complete':<26}" + "".join(
        f"{summary[name]['complete']}/{summary[name]['calls']:>2}".rjust(22) for name in configs))
    return "\n".join(lines)
