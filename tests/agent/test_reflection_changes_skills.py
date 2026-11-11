"""Reflection learns only what a skill does not say: the QaAgent scores and diagnoses, the ReflectionAgent writes a
screened card per call and one sentence several customers share, the PolicyAgent checks, a person approves, and going
back is a pointer. No model call: the agents are scripted."""

import json
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from ai_agent_service.agents.qa import Diagnosis, Restated
from ai_agent_service.agents.reflection import LessonCard, SkillPatch
from ai_agent_service.components.context import skills as skill_book
from ai_agent_service.components.improvement import gaps, lessons, review, signals, skill_versions
from ai_agent_service.components.improvement.signals import Failure
from ai_agent_service.pipeline.improve import cli

BOOK = {"place-order": {"description": "Dùng khi khách mua.", "done_on": [], "body": "Câu một. Câu hai."}}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path / "improvement"))
    (tmp_path / "improvement").mkdir()
    return tmp_path


def failure(customer, code="TSR.tool_missing:order.create", route="behaviour"):
    return Failure(code=code, route=route, scenario_id=f"S{customer}", call="call_1", turn=None, customer=customer,
                   persona=None, hard_case=None, lane=None, reason="không có tool call")


def test_a_change_replaces_one_exact_sentence_or_adds_one():
    assert skill_versions.apply(BOOK, {"skill": "place-order", "part": "body", "find": "Câu hai.", "text": "Câu mới."})[
        "place-order"]["body"] == "Câu một. Câu mới."
    assert skill_versions.apply(BOOK, {"skill": "place-order", "part": "body", "text": "Câu ba."})[
        "place-order"]["body"] == "Câu một. Câu hai. Câu ba."
    assert BOOK["place-order"]["body"] == "Câu một. Câu hai."  # never in place


@pytest.mark.parametrize("patch", [
    {"skill": "khac", "part": "body", "text": "x"}, {"skill": "place-order", "part": "done_on", "text": "x"},
    {"skill": "place-order", "part": "body", "find": "Không có.", "text": "x"}, {"skill": "place-order", "part": "body", "text": ""},
    {"skill": "place-order", "part": "body", "text": "x" * 3000},
])
def test_a_change_that_cannot_apply_exactly_is_refused(patch):
    with pytest.raises(ValueError):
        skill_versions.apply(BOOK, patch)


RULES = {"PB-09": "Đọc lại đơn một lần.", "VC-03": "Chấp nhận COD với đơn dưới 10.000.000đ.", "BH-03": "Mang tới trung tâm bảo hành."}


@pytest.mark.parametrize("text,cites,flag", [
    ("Báo khách giá 4.890.000đ.", ["PB-09"], "amount"), ("Đơn COD tối đa 12.000.000đ.", ["VC-03"], "amount"),
    ("Với mẫu SKU-AP-X thì đọc lại.", ["PB-09"], "specific"), ("Như khach_so_gia thì đọc lại.", ["PB-09"], "specific"),
    ("Đọc lại đơn một lần.", ["XX-1"], "no_rule"),
    ("Nhắc mã GIFT-FILTER khi chốt.", ["PB-09"], "promotion_code"),
])
def test_a_change_never_carries_a_case_a_code_a_new_amount_or_a_new_rule(text, cites, flag):
    assert flag in lessons.screen_patch(text, cites, rules=RULES, promos={"GIFT-FILTER"})


@pytest.mark.parametrize("text,cites", [
    ("Đọc lại đơn một lần trước khi tạo.", ["PB-09"]),
    # What not to do is the lesson itself, not a promise: meaning is the PolicyAgent's to read, not a word list's.
    ("Không tự giảm giá, không hứa còn hàng khi chưa tra.", ["PB-09"]),
    # An amount the cited rule states as written is the rule, not an invented number.
    ("Đơn COD từ 10.000.000đ thì đề nghị chuyển khoản.", ["VC-03"]),
])
def test_a_clean_change_passes_the_screen(text, cites):
    assert lessons.screen_patch(text, cites, rules=RULES, promos=()) == []


def card(customer, *, skill="place-order", code="RQR.budget_vnd", situation="after_sale", **extra):
    return {"skill": skill, "failure_code": code, "situation": situation, "customer": customer, "scope": "general",
            "what_happened": "Làm thủ tục trả hàng.", "do": "Giải thích bảo hành.", "dont": "Không tạo yêu cầu trả hàng.",
            "sample_line": "Dạ máy mình còn bảo hành ạ.", "cites": ["BH-03"], "scenario_id": f"S{customer}",
            "call": "call_2", **extra}


def test_a_card_is_screened_before_it_is_stored_and_a_flagged_one_never_is(home):
    clean = {**card("A"), "flags": lessons.screen_card(card("A"), skills=BOOK, rules=RULES, promos=(),
                                                       known_situations={"after_sale"})}
    bad = {**card("B", sample_line="Giá 4.890.000đ ạ."), "flags": []}
    bad["flags"] = lessons.screen_card(bad, skills=BOOK, rules=RULES, promos=(), known_situations={"after_sale"})
    lost = card("C", skill="khong-co", situation="la")
    assert clean["flags"] == [] and bad["flags"] == ["amount"]
    assert set(lessons.screen_card(lost, skills=BOOK, rules=RULES, promos=(), known_situations={"after_sale"})) == {
        "unknown_skill", "unknown_situation"}
    assert lessons.store([clean, bad]) == 1
    assert [c["customer"] for c in lessons.stored()] == ["A"]


def test_three_customers_share_a_lesson_before_it_is_one_one_customer_is_one_vote():
    two = [card("A"), card("A"), card("B")]
    assert lessons.clusters(two) == {}
    assert list(lessons.clusters([*two, card("C")])) == [("place-order", "after_sale")]
    # Another situation or one customer's own preference is another lesson, or none.
    mixed = [card("A"), card("B", situation="bulk_order"), card("C", skill="conversation"), card("D", scope="this_customer")]
    assert lessons.clusters(mixed) == {}


def test_one_lesson_whose_cards_name_different_skills_is_one_lesson_in_the_skill_most_name():
    split = [card("A", skill="objection-handling"), card("B", skill="product-advice"), card("C", skill="objection-handling")]
    assert list(lessons.clusters(split)) == [("objection-handling", "after_sale")]


def test_one_lesson_seen_through_different_checks_is_still_one_lesson():
    symptoms = [card("A"), card("B", code="J.J01_opening_continuity"), card("C", code="TSR.too_many_questions")]
    assert [len(items) for items in lessons.clusters(symptoms).values()] == [3]


def test_not_followed_stands_only_with_a_sentence_that_is_in_the_skill():
    assert lessons.settle_kind("not_followed", "place-order", "Câu   hai.  ", {"place-order": {
        "description": "x", "body": "Câu một dài hơn. Câu   hai."}}) == "unsettled"  # too short to be a sentence
    book = {"place-order": {"description": "Dùng khi khách mua.", "body": "Khách đã đồng ý thì gọi order_create ngay."}}
    assert lessons.settle_kind("not_followed", "place-order", "Khách đã đồng ý thì gọi  order_create ngay.", book) == "not_followed"
    assert lessons.settle_kind("not_followed", "place-order", "Khách đổi ý thì hỏi lại lý do trước.", book) == "unsettled"
    assert lessons.settle_kind("skill_gap", "khong-co", "", book) == "not_a_skill"
    assert lessons.settle_kind("not_a_skill", "place-order", "", book) == "not_a_skill"


def test_the_models_read_what_a_check_means_never_what_the_grader_expected():
    reason = "thiếu must_say_any: trung tâm bảo hành | gửi về shop"
    described = signals.describe(signals.tsr_code(reason))
    assert "trung tâm" not in described and "gửi về" not in described
    assert "order.update" in signals.describe("TSR.forbidden_tool:order.update")
    assert signals.describe("J.J11_budget_transparency").startswith("BTC rubric J11_budget_transparency")
    assert signals.route("J.J02_no_fabrication") == "product" and signals.route("J.J12_out_of_stock") == "product"
    assert signals.route("J.J06_tone_vietnamese") == "behaviour" and signals.route("TSR.tool_missing:order.create") == "product"


def test_publishing_keeps_every_version_and_going_back_is_a_pointer(home, monkeypatch):
    folder = home / "skills"
    monkeypatch.setattr(skill_book, "load_prompt_yaml", lambda name: BOOK)
    patch = {"skill": "place-order", "part": "body", "find": "Câu hai.", "text": "Câu mới.", "cites": ["PB-09"]}
    assert skill_versions.publish([patch], reviewer="scripted-eval", folder=folder) == 1
    assert skill_book.read_book(folder)["place-order"]["body"] == "Câu một. Câu mới."
    first = (folder / "v1.yaml").read_text(encoding="utf-8")
    assert skill_versions.publish([{"skill": "place-order", "part": "body", "text": "Câu ba."}], reviewer="x", folder=folder) == 2
    assert skill_versions.rollback(0, reviewer="x", reason="tụt", folder=folder) == 2
    assert skill_book.read_book(folder) == BOOK and (folder / "v1.yaml").read_text(encoding="utf-8") == first
    with pytest.raises(ValueError):
        skill_versions.rollback(9, reviewer="x", reason="y", folder=folder)


def test_scripted_approval_says_so_and_takes_nothing_flagged(home):
    path = review.write("r", [
        {"proposal_id": "a", "kind": "skill", "failure_code": "c", "author": "qa", "entry": {}, "counts": {}, "evidence": [], "flags": []},
        {"proposal_id": "b", "kind": "skill", "failure_code": "c", "author": "qa", "entry": {}, "counts": {}, "evidence": [], "flags": ["amount"]}])
    review.approve_scripted(path, gaps.SCRIPTED)
    taken, refused = review.approved(path)
    assert [t["proposal_id"] for t in taken] == ["a"] and taken[0]["reviewer"] == "scripted-eval"
    assert [r["proposal_id"] for r in refused] == ["b"]
    assert any(json.loads(line)["action"] == "approve_scripted" for line in review.log_path().read_text(encoding="utf-8").splitlines())


def learning_round(home, tmp_path, calls):
    """A harvested round: a run of *calls* {(scenario, customer): [codes]}, with every call's trace on disk."""
    run = tmp_path / "run"
    (run / "scenarios").mkdir(parents=True)
    rows, found = [], []
    for (sid, customer), codes in calls.items():
        (run / "scenarios" / f"{sid}.json").write_text(json.dumps({"scenario_id": sid, "customer_phone": customer,
                                                                   "calls": {"call_2": {}}}), encoding="utf-8")
        rows.append({"scenario_id": sid, "call": "call_2", "turn": 1, "customer_text": "Máy hỏng rồi em.",
                     "agent_text": "Dạ em làm thủ tục trả hàng ạ.", "tool_calls": [{"name": "order.update", "args": {}}]})
        found += [Failure(code=code, route=signals.route(code), scenario_id=sid, call="call_2", turn=None,
                          customer=customer, persona=None, hard_case=None, lane=None,
                          reason="thiếu must_say_any: trung tâm bảo hành").to_json() for code in codes]
    lessons.write_jsonl(run / "full.jsonl", rows)
    folder = lessons.round_dir("r")
    lessons.write_jsonl(folder / "failures.jsonl", found)
    (folder / "source.json").write_text(json.dumps({"run": str(run), "scenarios": str(run / "scenarios"),
                                                    "skills_version": 0}), encoding="utf-8")
    return folder


class ScriptedQa:
    def __init__(self, kind="skill_gap", quote=""):
        self.kind, self.quote, self.seen = kind, quote, []

    async def score(self, scenario, call, rows):
        return {"status": "COMPLETE", "criteria": [], "verdicts": []}

    async def diagnose(self, code, check, transcript, *, skills, situations, fixed_rules="", policy=None):
        self.seen.append((code, check, transcript))
        return Diagnosis(kind=self.kind, skill="place-order", covering_sentence=self.quote, situation="after_sale", why="w")


class ScriptedReflection:
    def __init__(self, text="Máy hỏng sau thời hạn đổi trả thì hướng dẫn bảo hành, không tạo yêu cầu trả hàng."):
        self.text, self.cards_seen, self.objections, self.revised = text, [], [], None

    async def lesson(self, code, check, transcript, *, skill, skills, rules, situations, fixed_rules="", covering=""):
        return LessonCard(situation="after_sale", what_happened="Làm thủ tục trả hàng cho máy đã quá hạn.",
                          do="Hướng dẫn bảo hành.", dont="Không tạo yêu cầu trả hàng.", sample_line="Dạ máy mình còn bảo hành ạ.",
                          cites=["BH-03"], scope="general")

    async def patch(self, cards, *, skill, skills, rules, fixed_rules="", objection=None):
        self.cards_seen.append(list(cards))
        self.objections.append(objection)
        text = self.revised if objection and self.revised else self.text
        return SkillPatch(part="body", text=text, cites=["BH-03"], why="w")


class ScriptedPolicy:
    def __init__(self, failed=(), refuses=None):
        self.failed = tuple(failed)
        self.refuses = refuses  # the one text it refuses, when given; every other text passes

    async def review_change(self, text, *, cited_rules, skill_now, fixed_rules=""):
        failed = self.failed if self.refuses is None or text == self.refuses else ()
        return SimpleNamespace(failed=failed, reasons=tuple(f"lý do {name}" for name in failed))


@pytest.fixture
def book(monkeypatch):
    monkeypatch.setattr(skill_book, "read_book", lambda folder=None: BOOK)
    monkeypatch.setattr(lessons, "rule_texts", lambda: dict(RULES))
    monkeypatch.setattr(lessons, "promo_codes", lambda: frozenset())
    monkeypatch.setattr(lessons, "situations", lambda: {"after_sale": "x", "other": "y"})
    monkeypatch.setattr(lessons, "fixed_rules", lambda: "Luật cứng: không bao giờ nhận là người thật với khách hàng.")


@pytest.mark.asyncio
async def test_qa_diagnoses_without_the_answer_key_and_a_violated_call_is_no_evidence(home, tmp_path, book):
    folder = learning_round(home, tmp_path, {("S1", "A"): ["RQR.budget_vnd"],
                                             ("S2", "B"): ["RQR.budget_vnd", "HR.price_vnd"]})
    qa = ScriptedQa("not_followed", quote="Không có câu này trong skill.")
    assert await cli.score("r", qa) == 0
    rows = {r["scenario_id"]: r for r in lessons.read_jsonl(folder / "diagnoses.jsonl")}
    assert rows["S2"]["kind"] == "excluded" and rows["S1"]["kind"] == "unsettled"  # the quote is not in the skill
    assert len(qa.seen) == 1 and "trung tâm bảo hành" not in " ".join(qa.seen[0])
    assert await cli.score("r", qa) == 2  # once per round


@pytest.mark.asyncio
async def test_reflection_writes_cards_and_one_change_three_customers_share(home, tmp_path, book):
    learning_round(home, tmp_path, {(f"S{c}", c): ["RQR.budget_vnd"] for c in "ABC"})
    await cli.score("r", ScriptedQa())
    reflection = ScriptedReflection()
    assert await cli.reflect("r", reflection, ScriptedPolicy()) == 0
    assert len(lessons.stored(skills_version=0)) == 3 and len(reflection.cards_seen[0]) == 3
    written = json.loads((signals.home() / "review" / "r.json").read_text(encoding="utf-8"))
    proposal = written["proposals"][0]
    assert proposal["author"] == "reflection" and proposal["flags"] == [] and proposal["counts"]["customers"] == 3
    assert proposal["patch"]["skill"] == "place-order" and written["not_followed"] == []
    # The agent that wrote it can never approve it.
    data = json.loads((signals.home() / "review" / "r.json").read_text(encoding="utf-8"))
    data["proposals"][0].update(decision="approved", reviewer="reflection")
    (signals.home() / "review" / "r.json").write_text(json.dumps(data), encoding="utf-8")
    assert review.approved(signals.home() / "review" / "r.json")[0] == []


@pytest.mark.asyncio
async def test_conduct_a_skill_already_says_but_was_not_followed_is_rewritten_in_that_skill(home, tmp_path, book):
    learning_round(home, tmp_path, {(f"S{c}", c): ["RQR.budget_vnd"] for c in "ABC"})
    BOOK["place-order"]["body"] = "Câu một. Câu hai dài hơn mười hai ký tự."
    try:
        await cli.score("r", ScriptedQa("not_followed", quote="Câu hai dài hơn   mười hai ký tự."))
        assert await cli.reflect("r", ScriptedReflection(), ScriptedPolicy()) == 0
    finally:
        BOOK["place-order"]["body"] = "Câu một. Câu hai."
    written = json.loads((signals.home() / "review" / "r.json").read_text(encoding="utf-8"))
    assert [p["patch"]["skill"] for p in written["proposals"]] == ["place-order"] and written["not_followed"] == []
    assert {c["kind"] for c in lessons.stored()} == {"not_followed"}


@pytest.mark.asyncio
async def test_conduct_a_fixed_rule_already_says_goes_to_the_conduct_skill(home, tmp_path, book, monkeypatch):
    with_conduct = {**BOOK, "conversation": {"description": "Luôn áp dụng.", "done_on": [], "body": "Cách trò chuyện."}}
    monkeypatch.setattr(skill_book, "read_book", lambda folder=None: with_conduct)
    learning_round(home, tmp_path, {(f"S{c}", c): ["RQR.budget_vnd"] for c in "ABC"})
    await cli.score("r", ScriptedQa("not_followed", quote="không bao giờ nhận là người thật"))
    assert await cli.reflect("r", ScriptedReflection(), ScriptedPolicy()) == 0
    written = json.loads((signals.home() / "review" / "r.json").read_text(encoding="utf-8"))
    assert [p["patch"]["skill"] for p in written["proposals"]] == ["conversation"]


@pytest.mark.asyncio
async def test_a_change_the_policy_flags_or_could_not_check_is_never_published(home, tmp_path, book):
    learning_round(home, tmp_path, {(f"S{c}", c): ["RQR.budget_vnd"] for c in "ABC"})
    await cli.score("r", ScriptedQa())
    await cli.reflect("r", ScriptedReflection(), ScriptedPolicy(failed=("unavailable",)))
    path = signals.home() / "review" / "r.json"
    assert json.loads(path.read_text(encoding="utf-8"))["proposals"][0]["flags"] == ["policy:unavailable"]
    review.approve_scripted(path, gaps.SCRIPTED)
    assert review.approved(path)[0] == []


@pytest.mark.asyncio
async def test_a_refused_change_is_written_again_once_with_the_checks_it_failed_and_checked_again(home, tmp_path, book):
    learning_round(home, tmp_path, {(f"S{c}", c): ["RQR.budget_vnd"] for c in "ABC"})
    await cli.score("r", ScriptedQa())
    writer = ScriptedReflection()
    writer.revised = "Khi khách đã nói đủ, đọc lại đơn một lần rồi làm tiếp."
    await cli.reflect("r", writer, ScriptedPolicy(failed=("contradicts_fixed",), refuses=writer.text))
    proposal = json.loads((signals.home() / "review" / "r.json").read_text(encoding="utf-8"))["proposals"][0]
    assert proposal["entry"]["text"] == writer.revised and proposal["flags"] == []
    objection = writer.objections[-1]
    assert objection["text"] == writer.text and objection["checks"][0].startswith("contradicts_fixed:")


@pytest.mark.asyncio
async def test_a_change_the_checker_could_not_read_is_not_rewritten(home, tmp_path, book):
    learning_round(home, tmp_path, {(f"S{c}", c): ["RQR.budget_vnd"] for c in "ABC"})
    await cli.score("r", ScriptedQa())
    writer = ScriptedReflection()
    await cli.reflect("r", writer, ScriptedPolicy(failed=("unavailable",)))
    assert [o for o in writer.objections if o] == []


@pytest.mark.asyncio
async def test_a_sale_won_by_a_false_promise_never_becomes_a_lesson(home, tmp_path, book):
    """Spec 10.4, layer 4: three customers closed after a price the tools never gave; nothing of it is learned."""
    learning_round(home, tmp_path, {(f"S{c}", c): ["RQR.budget_vnd", "HR.price_vnd"] for c in "ABC"})
    await cli.score("r", ScriptedQa())
    await cli.reflect("r", ScriptedReflection(), ScriptedPolicy())
    assert lessons.stored() == []
    assert json.loads((signals.home() / "review" / "r.json").read_text(encoding="utf-8"))["proposals"] == []


@pytest.mark.asyncio
async def test_the_change_check_fails_closed_when_the_policy_api_does_not_answer(monkeypatch):
    from ai_agent_service.agents import policy as policy_module
    from ai_agent_service.llm.decisions import DecisionUnavailable

    async def unavailable(*args, **kwargs):
        raise DecisionUnavailable("TIMEOUT", "no answer")

    monkeypatch.setattr(policy_module.decisions, "evaluate", unavailable)
    agent = policy_module.PolicyAgent.__new__(policy_module.PolicyAgent)
    agent.name = "policy"
    verdict = await agent.review_change("Đọc lại đơn.", cited_rules={"PB-09": "x"}, skill_now="y")
    assert verdict.passed is False and verdict.failed == ("unavailable",)


def vectors(table):
    return lambda texts: np.array([table[t] for t in texts], dtype=float)


@pytest.mark.asyncio
async def test_a_question_is_restated_then_joined_by_meaning(home):
    gaps.record("mua may ve bao lau thay mang z em", call_id="1", turn_id="t", recent=["máy lọc không khí"])
    gaps.record("Bao lâu phải thay màng lọc vậy?", call_id="2", turn_id="t")
    gaps.record("Có lọc được radon không?", call_id="3", turn_id="t")
    said = {}

    async def restate(question, recent):
        said[question] = list(recent)
        text = "Có lọc được radon không?" if "radon" in question else "Bao lâu cần thay màng lọc của máy lọc không khí?"
        return Restated(question=text, variants=["cách hỏi khác"])

    assert await gaps.restate_open(restate) == 3
    assert said["mua may ve bao lau thay mang z em"] == ["máy lọc không khí"]
    table = {"Bao lâu cần thay màng lọc của máy lọc không khí?": [1.0, 0.0], "Có lọc được radon không?": [0.0, 1.0]}
    async def same(a, b):
        return "radon" not in a + b

    assert await gaps.merge_same(vectors(table), same) == 1
    open_gaps = gaps.list_gaps()
    assert len(open_gaps) == 2 and len(open_gaps[0]["occurrences"]) == 2


@pytest.mark.asyncio
async def test_a_scripted_answer_reaches_its_gap_through_the_gate_and_is_marked(home, monkeypatch):
    gaps.record("thay mang khi nao", call_id="1", turn_id="t")

    async def restate(question, recent):
        return Restated(question="Bao lâu cần thay màng lọc?", variants=["Khi nào thay màng?"])

    await gaps.restate_open(restate)
    published = {}
    monkeypatch.setattr(gaps, "resolve", lambda key, **kw: published.update(kw) or 1)
    table = {"Bao lâu cần thay màng lọc?": [1.0, 0.0], "Khi nào thay màng lọc?": [1.0, 0.0], "Giá màng lọc?": [1.0, 0.0], "Lạ?": [0.0, 1.0]}
    async def same(question, answer):
        return answer != "x"

    results = await gaps.answer_from_script([
        {"question": "Lạ?", "answer": "x", "cites": ["BH-04"]},
        {"question": "Giá màng lọc?", "answer": "Giá 990.000đ.", "cites": ["BH-04"]},
        {"question": "Khi nào thay màng lọc?", "answer": "Sau 6 đến 12 tháng tùy môi trường.", "cites": ["BH-04"]},
    ], vectors(table), same)
    assert [r["status"] for r in results] == ["no_gap", "refused", "published"]
    assert published["reviewer"] == gaps.SCRIPTED == "scripted-eval"


def test_the_entry_is_titled_by_the_restated_question_not_the_raw_words(home, tmp_path):
    key = gaps.record("thay mang khi nao", call_id="1", turn_id="t")
    rows = json.loads(gaps._path().read_text(encoding="utf-8"))
    rows[key].update(restated="Bao lâu cần thay màng lọc?", variants=["Khi nào thay màng?"])
    gaps._path().write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    config = tmp_path / "knowledge.yaml"
    config.write_text("version: 0\n", encoding="utf-8")
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "v0.jsonl").write_text("", encoding="utf-8")
    gaps.resolve(key, answer="Sau 6 đến 12 tháng.", cites=["BH-04"], reviewer=gaps.SCRIPTED, directory=kb, config_path=config)
    entry = json.loads((kb / "v1.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["title"] == "Bao lâu cần thay màng lọc? | Khi nào thay màng?" and entry["approved_by"] == "scripted-eval"


@pytest.mark.asyncio
async def test_the_same_request_to_the_same_model_is_paid_for_once_and_a_failure_is_asked_again(home):
    from ai_agent_service.components.improvement import answers

    asked = []

    async def ask():
        asked.append(1)
        return {"kind": "skill_gap"} if len(asked) > 1 else None

    assert await answers.remember("qa.diagnose", "m/medium", "request", ask) is None  # a failure is not stored
    assert await answers.remember("qa.diagnose", "m/medium", "request", ask) == {"kind": "skill_gap"}
    assert await answers.remember("qa.diagnose", "m/medium", "request", ask) == {"kind": "skill_gap"}
    assert len(asked) == 2
    await answers.remember("qa.diagnose", "other/medium", "request", ask)  # another model asks again
    assert len(asked) == 3


def test_the_loop_reads_the_customer_s_earlier_calls_before_the_failed_one():
    by_call = {("S", "call_1"): [{"turn": 1, "customer_text": "Mua nồi chiên.", "agent_text": "Dạ đã tạo đơn.",
                                  "tool_calls": [{"name": "order.create", "args": {}, "result": {"created_on": "2026-09-10"}}]}],
               ("S", "call_2"): [{"turn": 1, "customer_text": "Nồi hỏng rồi.", "agent_text": "Dạ.", "tool_calls": []}],
               ("T", "call_1"): [{"turn": 1, "customer_text": "Khách khác.", "agent_text": "x", "tool_calls": []}]}
    shown = cli.history(by_call, "S", "call_2")
    assert shown.index("2026-09-10") < shown.index("Nồi hỏng rồi.") and "Khách khác." not in shown
    assert "Cuộc trước" not in cli.history(by_call, "S", "call_1")


def test_a_failure_a_fixed_rule_already_covers_is_product_work_whatever_the_skill_says():
    fixed = "Luật cứng: không bao giờ nhận là người thật với khách hàng."
    book = {"place-order": {"description": "Dùng khi khách mua.", "body": "Câu một."}}
    assert lessons.settle_kind("not_followed", "place-order", "không bao giờ nhận là người thật", book, fixed) == "not_followed"
    assert lessons.settle_kind("not_followed", "", "không bao giờ nhận là người thật", book, fixed) == "not_followed"
    assert lessons.settle_kind("not_followed", "place-order", "Một câu không có ở đâu cả.", book, fixed) == "unsettled"


def test_the_fixed_rules_are_the_advisor_s_own_prompt_and_the_history_carries_what_memory_kept():
    rules = lessons.fixed_rules()
    assert "Không bao giờ nhận là người" in rules and len(rules) > 5000
    shown = cli.history({("S", "call_1"): [{"turn": 1, "customer_text": "a", "agent_text": "b", "tool_calls": [],
                                            "memory_writes": [{"key": "budget_vnd", "value": 5000000, "op": "set"}]}],
                         ("S", "call_2"): [{"turn": 1, "customer_text": "c", "agent_text": "d", "tool_calls": []}]}, "S", "call_2")
    assert "budget_vnd=5000000" in shown and shown.index("budget_vnd") < shown.index("Cuộc gọi đang xét")


@pytest.mark.asyncio
async def test_a_gap_answered_once_is_never_answered_again_in_the_same_script(home, monkeypatch):
    gaps.record("giao may lan khong gap", call_id="1", turn_id="t")

    async def restate(question, recent):
        return Restated(question="Giao không gặp khách thì xử lý thế nào?", variants=[])

    await gaps.restate_open(restate)
    published = []
    monkeypatch.setattr(gaps, "resolve", lambda key, **kw: published.append(key) or 1)
    monkeypatch.setattr(gaps, "list_gaps", lambda: [] if published else [
        {"id": "g", "status": "open", "restated": "Giao không gặp khách thì xử lý thế nào?", "occurrences": []}])

    async def same(a, b):
        return True

    table = {"Giao không gặp khách thì xử lý thế nào?": [1.0, 0.0], "Giao hụt thì sao?": [1.0, 0.0],
             "Từ chối nhận hàng có bị phạt không?": [1.0, 0.0]}
    results = await gaps.answer_from_script([
        {"question": "Giao hụt thì sao?", "answer": "Giao tối đa 3 lần.", "cites": ["VC-07"]},
        {"question": "Từ chối nhận hàng có bị phạt không?", "answer": "Lần đầu không phạt.", "cites": ["QT-02"]},
    ], vectors(table), same)
    assert [r["status"] for r in results] == ["published", "no_gap"] and published == ["g"]


def round_args(tmp_path, **extra):
    import argparse
    return argparse.Namespace(name="rt", learn=[tmp_path / "learnset" / "learn" / "scenarios"], frozen=[tmp_path / "frozenset" / "frozen" / "scenarios"],
                              frozen_ids=[], answers=None, r0_runs=2, r1_runs=1, scripted=True, approved=False, deadline_minutes=1, **extra)


@pytest.fixture(autouse=True)
def no_watchdog(monkeypatch):
    """A round's watchdog is a process; the tests check the round, and one test checks the watchdog is required."""
    monkeypatch.setattr(cli, "_watched", lambda minutes: SimpleNamespace(terminate=lambda: None))


@pytest.mark.asyncio
async def test_a_round_refuses_to_start_from_an_agent_that_has_learned_already(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_agent_service.pipeline.eval.cli.runs_dir", lambda: tmp_path / "runs")
    monkeypatch.setattr(skill_versions, "active", lambda folder=None: 1)
    ran = []
    monkeypatch.setattr(cli, "_evaluate", lambda scenarios, out: ran.append(out) or out)
    assert await cli.run_round(round_args(tmp_path)) == 2 and ran == []


@pytest.mark.asyncio
async def test_a_round_measures_learns_measures_again_and_goes_back_to_the_original(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_agent_service.pipeline.eval.cli.runs_dir", lambda: tmp_path / "runs")
    monkeypatch.setattr(skill_versions, "active", lambda folder=None: 0)
    monkeypatch.setattr(cli.versions, "active", lambda *a, **k: 0)
    steps = []
    monkeypatch.setattr(cli, "_evaluate", lambda scenarios, out: steps.append(out.name) or out)

    async def step(name, *rest):
        steps.append(f"{step.kind}:{name}")
        return 0

    def harvest(run, name, **kw):
        steps.append(f"harvest:{name}")
        return 0

    async def score(name):
        steps.append(f"score:{name}")
        return 0

    async def reflect(name):
        steps.append(f"reflect:{name}")
        return 0

    monkeypatch.setattr(cli, "harvest", harvest)
    monkeypatch.setattr(cli, "score", score)
    monkeypatch.setattr(cli, "reflect", reflect)
    monkeypatch.setattr(cli, "publish", lambda path, scripted=False: steps.append("publish") or 0)
    monkeypatch.setattr(cli, "compare", lambda before, after: steps.append(f"compare:{len(before)}>{len(after)}") or 0)
    monkeypatch.setattr(cli, "_back_to_original", lambda folder, reviewer: steps.append(f"back:{reviewer}"))
    review_dir = tmp_path / "runs" / "rt" / "improvement" / "review"
    review_dir.mkdir(parents=True)
    (review_dir / "rt-learnset.json").write_text("{}", encoding="utf-8")
    assert await cli.run_round(round_args(tmp_path)) == 0
    assert steps == ["r0-frozenset-1", "r0-frozenset-2", "learn-learnset", "harvest:rt-learnset", "score:rt-learnset",
                     "reflect:rt-learnset", "publish", "r1-frozenset", "compare:2>1", "back:scripted-eval"]



def test_a_person_s_round_is_never_watched(monkeypatch):
    """The real _watched (the fixture stubs it): only an assistant's own run sets SPEND_SINCE and is watched."""
    import importlib

    real = importlib.reload(importlib.import_module("ai_agent_service.pipeline.improve.cli"))._watched
    monkeypatch.delenv("SPEND_SINCE", raising=False)
    assert real(1) is None


def published_gap(home, tmp_path, question):
    key = gaps.record(question, call_id="1", turn_id="t")
    rows = json.loads(gaps._path().read_text(encoding="utf-8"))
    rows[key].update(restated="Shop có lắp đặt máy lọc nước tại nhà không?", variants=["Có thợ lắp máy không?"])
    gaps._path().write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    config = tmp_path / "knowledge.yaml"
    config.write_text("version: 0\n", encoding="utf-8")
    kb = tmp_path / "kb"
    kb.mkdir(exist_ok=True)
    (kb / "v0.jsonl").write_text("", encoding="utf-8")
    return key, kb, config


def test_a_consultant_answer_needs_no_document_but_is_recorded_as_the_consultant_s(home, tmp_path):
    key, kb, config = published_gap(home, tmp_path, "co tho lap may loc nuoc khong")
    gaps.resolve(key, answer="Dạ bên em có thợ lắp đặt máy lọc nước tại nhà, hẹn lịch sau khi giao hàng ạ.", cites=[],
                 reviewer=gaps.SCRIPTED, source="consultant", directory=kb, config_path=config)
    entry = json.loads((kb / "v1.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["provenance"]["source"] == "consultant" and entry["provenance"]["cites"] == []


@pytest.mark.parametrize("answer,cites,source", [
    ("Dạ có, phí lắp 200.000đ ạ.", [], "consultant"),          # an amount: prices come from tools
    ("Dạ có thợ lắp ạ.", ["XX-99"], "consultant"),              # a citation that does not exist
    ("Dạ có thợ lắp ạ.", [], "documents"),                      # documents claimed, none cited
    ("Dạ có thợ lắp ạ.", [], "rumour"),                         # no such source
])
def test_a_consultant_answer_still_passes_the_gate(home, tmp_path, answer, cites, source):
    key, kb, config = published_gap(home, tmp_path, "co tho lap may loc nuoc khong")
    with pytest.raises(ValueError):
        gaps.resolve(key, answer=answer, cites=cites, reviewer=gaps.SCRIPTED, source=source, directory=kb,
                     config_path=config)


@pytest.mark.asyncio
async def test_qa_records_a_question_the_agent_could_not_answer_even_without_a_transfer(home, tmp_path, book):
    learning_round(home, tmp_path, {("S1", "A"): ["RQR.budget_vnd"]})

    class Reads(ScriptedQa):
        async def unanswered(self, customer, assistant):
            return "trả hàng" in assistant

    await cli.score("r", Reads())
    recorded = gaps.list_gaps()
    assert [g["question"] for g in recorded] == ["Máy hỏng rồi em."]
    assert recorded[0]["occurrences"] == [{"call_id": "S1/call_2", "turn_id": "1"}]


def test_reflection_reads_every_tool_the_assistant_has_and_what_each_does():
    from ai_agent_service.agents.reflection import _tools_block

    block = _tools_block()
    assert "pricing_quote_order: The price of every unit" in block and "handoff_transfer:" in block
    assert "load_skill" not in block and "kb_upsert" not in block  # what the advisor cannot call is not offered


def test_a_line_added_to_a_body_of_lines_is_a_line_and_names_its_situation_in_the_description():
    book = {"objection-handling": {"description": "Dùng khi khách chê đắt.", "done_on": [], "body": "- Một.\n- Hai."}}
    changed = skill_versions.apply(book, {"skill": "objection-handling", "part": "body", "text": "- Ba.",
                                          "when": "Khách lo máy mau hỏng"})["objection-handling"]
    assert changed["body"] == "- Một.\n- Hai.\n- Ba."
    assert changed["description"] == "Dùng khi khách chê đắt. Cả khi khách lo máy mau hỏng."
    assert skill_versions.apply(book, {"skill": "objection-handling", "part": "body", "text": "- Ba."})[
        "objection-handling"]["description"] == "Dùng khi khách chê đắt."
