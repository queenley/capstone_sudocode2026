"""Reflection changes a skill one sentence at a time, a person approves, and going back is a pointer."""

import json
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from ai_agent_service.agents.qa import Restated, SkillPatch
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


@pytest.mark.parametrize("text,cites,flag", [
    ("Báo khách giá 4.890.000đ.", ["PB-09"], "amount"), ("Hứa với khách miễn phí giao hàng.", ["PB-09"], "promise"),
    ("Với mẫu SKU-AP-X thì đọc lại.", ["PB-09"], "specific"), ("Như khach_so_gia thì đọc lại.", ["PB-09"], "specific"),
    ("Đọc lại đơn một lần.", [], "no_rule"), ("Đọc lại đơn một lần.", ["XX-1"], "no_rule"),
])
def test_a_change_never_carries_a_number_a_promise_a_case_or_a_new_rule(text, cites, flag):
    assert flag in lessons.screen_patch(text, cites, rules={"PB-09"}, promos=())


def test_a_clean_change_passes_the_screen():
    assert lessons.screen_patch("Đọc lại đơn một lần trước khi tạo.", ["PB-09"], rules={"PB-09"}, promos=()) == []


def test_only_behaviour_failures_many_customers_share_are_reflected_on():
    found = [failure("A"), failure("A"), failure("B")]
    assert cli.shared_failures(found) == {}
    assert list(cli.shared_failures([*found, failure("C")])) == ["TSR.tool_missing:order.create"]
    assert cli.shared_failures([failure(c, "HR.price_vnd", "product") for c in "ABC"]) == {}


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


@pytest.mark.asyncio
async def test_reflect_writes_a_review_with_its_flags(home, tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "full.jsonl").write_text(json.dumps({"scenario_id": "SA", "call": "call_1", "turn": 1, "customer_text": "x", "agent_text": "y"}) + "\n", encoding="utf-8")
    folder = lessons.round_dir("r")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source.json").write_text(json.dumps({"run": str(run)}), encoding="utf-8")
    lessons.write_jsonl(folder / "failures.jsonl", [failure(c).to_json() for c in "ABC"])

    async def patch_skill(code, calls, *, skills, rules):
        assert calls[0]["transcript"][0]["text"] == "x"
        return SkillPatch(skill=next(iter(skills)), part="body", text="Báo giá 100.000đ.", cites=["PB-09"], why="w")

    async def review_change(text, *, kind):
        return SimpleNamespace(reasons=("hứa",))

    assert await cli.reflect("r", SimpleNamespace(patch_skill=patch_skill), SimpleNamespace(review_change=review_change)) == 0
    written = json.loads((signals.home() / "review" / "r.json").read_text(encoding="utf-8"))["proposals"][0]
    assert "amount" in written["flags"] and written["policy"] == ["hứa"] and written["counts"]["customers"] == 3


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
    assert gaps.merge_same(vectors(table)) == 1
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
    results = gaps.answer_from_script([
        {"question": "Lạ?", "answer": "x", "cites": ["BH-04"]},
        {"question": "Giá màng lọc?", "answer": "Giá 990.000đ.", "cites": ["BH-04"]},
        {"question": "Khi nào thay màng lọc?", "answer": "Sau 6 đến 12 tháng tùy môi trường.", "cites": ["BH-04"]},
    ], vectors(table))
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
