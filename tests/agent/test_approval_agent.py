"""The ApprovalAgent decides a Reflection change against what the people who wrote the learning set expect, one call per
change; in a scripted round its decision stands, the screen's flags still hold. And the warranty set it is proven on.
No model call: the models are scripted."""

import json
from pathlib import Path

import pytest
import yaml

from ai_agent_service.agents.approval import Approval, ApprovalAgent, expectations
from ai_agent_service.components.improvement import gaps, lessons, review, signals
from ai_agent_service.pipeline.eval import scenarios as loader
from tests.agent.test_reflection_changes_skills import (ScriptedPolicy, ScriptedQa, ScriptedReflection, book, home,  # noqa: F401
                                                        learning_round)
from tests.agent.test_reflection_dataset import mock

WARRANTY = Path(__file__).resolve().parents[2] / "data" / "reflection" / "warranty"
EXPECTED = {"after_sale": {"accept": "Hướng dẫn bảo hành."}, "other": {"accept": "Khác."}}


def with_expectations(tmp_path, situation="after_sale"):
    """The learning set's metadata and expectations, beside the scenarios learning_round wrote."""
    (tmp_path / "expected.yaml").write_text(yaml.safe_dump(EXPECTED, allow_unicode=True), encoding="utf-8")
    (tmp_path / "run" / "metadata").mkdir()
    for sid in ("SA", "SB", "SC"):
        (tmp_path / "run" / "metadata" / f"{sid}.json").write_text(json.dumps({"situation": situation}), encoding="utf-8")


class ScriptedApproval:
    def __init__(self, approve=True):
        self.approve, self.seen = approve, []

    async def decide(self, proposal, expected, *, cited_rules):
        self.seen.append((proposal, dict(expected), dict(cited_rules)))
        if not expected:
            return None
        return Approval(approve=self.approve, reason="r")


async def reflected(home, tmp_path, approval, policy=None):
    learning_round(home, tmp_path, {(f"S{c}", c): ["RQR.budget_vnd"] for c in "ABC"})
    with_expectations(tmp_path)
    await cli_score()
    from ai_agent_service.pipeline.improve import cli

    assert await cli.reflect("r", ScriptedReflection(), policy or ScriptedPolicy(), approval) == 0
    return signals.home() / "review" / "r.json"


async def cli_score():
    from ai_agent_service.pipeline.improve import cli

    await cli.score("r", ScriptedQa())


def test_the_agent_reads_only_the_expectations_of_the_situations_its_evidence_is_in():
    found = expectations(WARRANTY / "learn" / "scenarios", ["SCN-WTY-L01", "SCN-WTY-L02"])
    assert list(found) == ["durability_worry"] and "BH-05" in found["durability_worry"]["accept"]
    assert expectations(WARRANTY / "learn" / "scenarios", ["SCN-NOT-THERE"]) == {}


@pytest.mark.asyncio
async def test_a_change_the_agent_approves_is_published_in_a_scripted_round_under_its_name(home, tmp_path, book):
    approval = ScriptedApproval()
    path = await reflected(home, tmp_path, approval)
    proposal, expected, cited = approval.seen[0]
    assert list(expected) == ["after_sale"] and cited == {"BH-03": "Mang tới trung tâm bảo hành."}
    review.approve_scripted(path, gaps.SCRIPTED)
    taken, _ = review.approved(path)
    assert [t["reviewer"] for t in taken] == [review.APPROVAL_AGENT] and taken[0]["approval"]["situations"] == ["after_sale"]
    assert "Approval agent: approve: r" in path.with_suffix(".md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_a_change_the_agent_refuses_is_never_published(home, tmp_path, book):
    path = await reflected(home, tmp_path, ScriptedApproval(approve=False))
    review.approve_scripted(path, gaps.SCRIPTED)
    taken, refused = review.approved(path)
    assert taken == [] and refused[0]["reason"] == "decision is 'rejected'"


@pytest.mark.asyncio
async def test_the_agent_may_approve_over_the_policy_check_but_never_over_the_screen(home, tmp_path, book):
    path = await reflected(home, tmp_path, ScriptedApproval(), ScriptedPolicy(failed=("contradicts_skill",)))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["proposals"][0]["flags"] == ["policy:contradicts_skill"]
    review.approve_scripted(path, gaps.SCRIPTED)
    assert len(review.approved(path)[0]) == 1
    data = json.loads(path.read_text(encoding="utf-8"))
    data["proposals"][0]["flags"].append("amount")
    path.write_text(json.dumps(data), encoding="utf-8")
    assert review.approved(path)[0] == []


@pytest.mark.asyncio
async def test_without_an_expectation_the_change_waits_for_the_gates_as_before(home, tmp_path, book):
    approval = ScriptedApproval()
    learning_round(home, tmp_path, {(f"S{c}", c): ["RQR.budget_vnd"] for c in "ABC"})
    await cli_score()
    from ai_agent_service.pipeline.improve import cli

    await cli.reflect("r", ScriptedReflection(), ScriptedPolicy(), approval)
    path = signals.home() / "review" / "r.json"
    assert json.loads(path.read_text(encoding="utf-8"))["proposals"][0]["approval"] is None
    review.approve_scripted(path, gaps.SCRIPTED)
    assert [t["reviewer"] for t in review.approved(path)[0]] == [gaps.SCRIPTED]


class FakeModel:
    def __init__(self):
        self.requests = []

    def with_structured_output(self, schema):
        model = self

        class Runnable:
            async def ainvoke(self, request):
                model.requests.append(request)
                return schema(approve=True, reason="ok")

        return Runnable()


@pytest.mark.asyncio
async def test_one_call_per_change_with_the_expectation_and_the_change_and_never_without_an_expectation(home, monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_CACHE", str(home / "cache.jsonl"))
    model = FakeModel()
    agent = ApprovalAgent(llm=model)
    proposal = {"entry": {"text": "Khách lo máy hư: giới thiệu bảo hành mở rộng (BH-05).", "cites": ["BH-05"],
                          "where": "objection-handling.body"}, "flags": ["policy:invents"], "policy": ["lý do"]}
    assert await agent.decide(proposal, {}, cited_rules={}) is None and model.requests == []
    found = await agent.decide(proposal, {"durability_worry": EXPECTED["after_sale"]}, cited_rules={"BH-05": "Gói."})
    assert found.approve and len(model.requests) == 1
    request = model.requests[0]
    assert "durability_worry" in request and "BH-05" in request and "lý do" in request and "Khác." not in request


# ── the warranty set ──────────────────────────────────────────────────────


def read(name):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((WARRANTY / name / "scenarios").glob("*.json"))]


@pytest.mark.parametrize("name", ["learn", "frozen"])
def test_the_warranty_set_loads_and_offers_the_extended_warranty_only_where_bh_05_allows_it(name):
    loaded, rejected = loader.load(WARRANTY / name / "scenarios")
    assert rejected == [] and len(loaded) == len(read(name))
    tools = mock()
    for scenario in read(name):
        meta = json.loads((WARRANTY / name / "metadata" / f"{scenario['scenario_id']}.json").read_text(encoding="utf-8"))
        assert meta["situation"] in lessons.situations()
        spec = scenario["calls"]["call_1"]
        truth = spec["ground_truth_facts"]
        price = tools.pricing_get_quote(truth["sku"], spec["call_date"])["final_price_vnd"]
        assert price == truth["price_vnd"]
        offered = "must_say_any" in spec["success_if"]
        assert offered == (meta["target"] == "skill_gap") == (price > 3_000_000)


def test_the_warranty_frozen_set_is_listed_has_as_many_controls_and_shares_no_customer():
    learn, frozen = read("learn"), read("frozen")
    assert json.loads((WARRANTY / "frozen.json").read_text(encoding="utf-8")) == [s["scenario_id"] for s in frozen]
    phones = [s["customer_phone"] for s in learn + frozen]
    assert len(phones) == len(set(phones))
    targets = [json.loads(p.read_text(encoding="utf-8"))["target"] for p in (WARRANTY / "frozen" / "metadata").glob("*.json")]
    assert targets.count("control") >= targets.count("skill_gap") and len(learn) >= lessons.MIN_SUPPORT


# ── the budget set (persona khach_mua_nhieu_mon) ─────────────────────────

BUDGET = WARRANTY.parent / "budget"


@pytest.mark.parametrize("name", ["learn", "frozen"])
def test_the_budget_set_asks_to_hear_of_a_passed_budget_only_when_the_mock_s_total_passes_it(name):
    loaded, rejected = loader.load(BUDGET / name / "scenarios")
    assert rejected == [] and loaded
    tools = mock()
    for path in sorted((BUDGET / name / "scenarios").glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        meta = json.loads((BUDGET / name / "metadata" / path.name).read_text(encoding="utf-8"))
        spec = scenario["calls"]["call_1"]
        truth = spec["ground_truth_facts"]
        quote = tools.pricing_quote_order(lines=[{"sku": s, "qty": 1} for s in truth["skus"]], on=spec["call_date"])
        assert quote["total_vnd"] == truth["total_vnd"]
        assert all(tools.inventory_check(sku, spec["call_date"])["in_stock"] for sku in truth["skus"]), path.name
        passed = truth["total_vnd"] > truth["budget_vnd"]
        assert passed == (meta["target"] == "skill_gap") == ("must_say_any" in spec["success_if"])
        assert meta["situation"] in lessons.situations()


def test_the_budget_frozen_set_is_listed_and_has_as_many_controls():
    frozen = sorted(p.stem for p in (BUDGET / "frozen" / "scenarios").glob("*.json"))
    assert json.loads((BUDGET / "frozen.json").read_text(encoding="utf-8")) == frozen
    targets = [json.loads(p.read_text(encoding="utf-8"))["target"] for p in (BUDGET / "frozen" / "metadata").glob("*.json")]
    assert targets.count("control") >= targets.count("skill_gap")


@pytest.mark.asyncio
async def test_what_was_routed_to_review_reaches_reflection_where_the_set_states_the_lesson_we_accept(home, tmp_path, book):
    from ai_agent_service.pipeline.improve import cli

    folder = learning_round(home, tmp_path, {(f"S{c}", c): ["TSR.must_say"] for c in "ABC"})
    with_expectations(tmp_path)
    assert await cli.score("r", ScriptedQa()) == 0
    rows = lessons.read_jsonl(folder / "diagnoses.jsonl")
    assert sorted(r["scenario_id"] for r in rows) == ["SA", "SB", "SC"] and {r["routed"] for r in rows} == {"review"}


@pytest.mark.asyncio
async def test_without_a_lesson_we_accept_what_was_routed_to_review_waits_for_a_person(home, tmp_path, book):
    from ai_agent_service.pipeline.improve import cli

    folder = learning_round(home, tmp_path, {(f"S{c}", c): ["TSR.must_say"] for c in "ABC"})
    await cli.score("r", ScriptedQa())
    assert lessons.read_jsonl(folder / "diagnoses.jsonl") == []


@pytest.mark.parametrize("evidence, found", [
    ("Dạ AirPure Y giá 5.200.000đ ạ", True), ('"dạ airpure y  giá 5.200.000đ ạ."', True),
    ("Dạ AirPure Y ... bảo hành 24 tháng", True), ("Dạ AirPure Y giá 4.000.000đ", False), ("", False),
    ('Agent nói “AirPure Y giá 4.000.000đ” và giữ xưng hô.', False),
    ('Agent nói “AirPure Y giá 5.200.000đ”, đúng giá công cụ.', True)])
def test_the_qa_agent_reads_a_rubric_quote_as_a_person_would(evidence, found):
    from ai_agent_service.agents.qa import quoted

    words = "Chị hỏi giá AirPure Y\nDạ AirPure Y giá 5.200.000đ ạ, bảo hành 24 tháng."
    assert quoted(evidence, words) is found


def test_the_evaluation_judge_keeps_its_exact_quote():
    from ai_agent_service.components.evaluation.judge import BtcJudge

    judge = BtcJudge(FakeModel())
    assert judge.quoted("giá 5.200.000đ", "Dạ giá 5.200.000đ ạ") and not judge.quoted('"giá 5.200.000đ"', "Dạ giá 5.200.000đ ạ")


#: What the assistant said in real runs (2026-11-10, 2026-11-11), by what it did.
OFFERS = ["Chị có thể mua thêm gói bảo hành 12 tháng trong vòng 15 ngày từ ngày nhận hàng, áp dụng cho sản phẩm này.",
          "Bên em có gói bảo hành mở rộng thêm 12 tháng, phí bằng 8% giá sản phẩm và cần mua trong 15 ngày.",
          "Ngoài ra, chị có thể mua thêm 12 tháng bảo hành với phí bằng 8% giá sản phẩm trong vòng 15 ngày."]
NO_OFFERS = ["Máy được bảo hành 24 tháng cho lỗi kỹ thuật do nhà sản xuất như motor, bo mạch, cảm biến và nguồn.",
             "Mẫu này có bảo hành 12 tháng; giá sản phẩm 1.890.000đ nên chưa thuộc diện mua thêm bảo hành mở rộng của shop."]


@pytest.mark.parametrize("said, offered", [*((text, True) for text in OFFERS), *((text, False) for text in NO_OFFERS)])
def test_the_grader_reads_an_offer_in_the_words_the_assistant_uses_and_a_true_refusal_is_no_offer(said, offered):
    """A call is judged by what was done, not by one wording: on 2026-11-10 the original agent offered the package as
    "mua thêm gói bảo hành 12 tháng" and failed, and a control would have passed with the same words."""
    from ai_agent_service.components.improvement import signals

    rows = [{"turn": 1, "customer_text": "x", "agent_text": said, "tool_calls": []}]
    for scenario in read("frozen"):
        spec = scenario["calls"]["call_1"]
        target = "must_say_any" in spec["success_if"]
        if target and "chưa thuộc diện" in said:
            continue  # a phrase match cannot tell "not eligible" from an offer; only the controls can be asked that
        passed, _ = signals.grader().check_call(spec, rows)
        assert passed == (offered == target), (scenario["scenario_id"], said)


def test_a_pass_needs_no_quote_and_a_fail_without_the_call_s_words_is_dropped_not_the_whole_judgment():
    from ai_agent_service.agents.qa import settled
    from ai_agent_service.components.improvement import signals

    words = "Dạ AirPure Y giá 5.200.000đ ạ\nChị muốn hỏi thêm"
    judged = {"status": "INCOMPLETE", "criteria": ["J02", "J06", "J08"], "verdicts": [
        {"criterion_id": "J02", "verdict": "PASS", "evidence": "Agent nói đúng giá công cụ."},
        {"criterion_id": "J06", "verdict": "FAIL", "evidence": 'Agent nói "AirPure Y giá 5.200.000đ" mà không xưng hô.'},
        {"criterion_id": "J08", "verdict": "FAIL", "evidence": "Agent xác nhận lặp lại nhiều lần."}]}
    kept = settled(judged, words)
    assert kept["status"] == "PARTIAL" and kept["dropped"] == ["J08"]
    assert [v["criterion_id"] for v in kept["verdicts"]] == ["J02", "J06"]
    scenario = {"scenario_id": "S", "customer_phone": "0900000001"}
    assert [f.code for f in signals.rubric_failures(scenario, "call_1", kept)] == ["J.J06"]
    assert settled({**judged, "verdicts": judged["verdicts"][:2]}, words) is None  # a criterion left unanswered
    assert settled({**judged, "error": "TimeoutError"}, words) is None
    only_pass = settled({**judged, "verdicts": [{**v, "verdict": "PASS"} for v in judged["verdicts"]]}, words)
    assert only_pass["status"] == "COMPLETE" and "dropped" not in only_pass
