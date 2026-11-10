"""The loop offline: failures from the grader, versions, review, and the customer simulator's
customer and search. No model call and no database: the models are scripted and the database steps faked."""

import json
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableLambda

from ai_agent_service.agents import qa as qa_module
from ai_agent_service.agents.advisor import shown_passages
from ai_agent_service.agents import simulator as simulator_module
from ai_agent_service.agents.simulator import Customer, Observation, PersonaTurn, Session, SimulatorAgent, faithful
from ai_agent_service.components.improvement import lessons, review, signals, versions
from ai_agent_service.components.improvement.signals import Failure
from ai_agent_service.config.config_manager import Profile, get_models_config
from ai_agent_service.pipeline.improve import cli

def scenario(**calls):
    return {"scenario_id": "SCN-T", "persona": "khach_do_du_hoi_nguoi_nha", "customer_phone": "0900000001",
            "honorific": "chị", "calls": calls}


def failure(code="RQR.room_area_m2", customer="A", scenario_id="S1", call="call_2"):
    return Failure(code=code, route=signals.route(code), scenario_id=scenario_id, call=call, turn=1, customer=customer,
                   persona="khach_so_gia", hard_case=None, lane="CONTINUITY", reason="open question")


# ── the local profile ─────────────────────────────────────────────────────


def test_profile_moves_the_agents_it_lists(monkeypatch):
    models = get_models_config()
    profile = models.profiles["local"]
    monkeypatch.setenv("AGENT_PROFILE", "local")
    for name in models.agents:
        moved = models.agent(name)
        if name in profile.overrides:
            own = profile.overrides[name]
            assert (moved.provider, moved.model) == (own.provider, own.model)
        elif name in profile.agents:
            assert (moved.provider, moved.model) == (profile.provider, profile.model)
        else:
            assert (moved.provider, moved.model) == (models.agents[name].provider, models.agents[name].model)
    assert models.agent("advisor").generation.max_tokens == 2048
    monkeypatch.delenv("AGENT_PROFILE")
    assert models.agent("advisor").provider == "openai"
    monkeypatch.setenv("AGENT_PROFILE", "nowhere")
    with pytest.raises(KeyError):
        models.agent("advisor")


def test_profile_override_gives_an_agent_its_own_model():
    profile = Profile(provider="google_genai", model="a", agents=["advisor"],
                      overrides={"simulator": {"provider": "google_genai", "model": "b"}})
    assert profile.overrides["simulator"].model == "b"
    with pytest.raises(ValueError):
        Profile(provider="google_genai", model="a", agents=["simulator"],
                overrides={"simulator": {"provider": "google_genai", "model": "b"}})


# ── failures ──────────────────────────────────────────────────────────────


def test_failures_are_the_graders_own_and_routed_by_code():
    spec = {"success_if": {"tool_called": "order.create", "args_match": {"sku": "SKU-AP-Y"}},
            "must_not_ask": ["room_area_m2"], "must_carry_over": ["room_area_m2"],
            "ground_truth_facts": {"price_vnd": 4890000, "return_days": 7}}
    rows = [{"turn": 1, "customer_text": "Chị gọi lại", "agent_text": "Phòng chị bao nhiêu m² ạ? Đổi trả 14 ngày.",
             "questions": [{"slot": "room_area_m2", "type": "open", "text": "Phòng chị bao nhiêu m² ạ?"}],
             "claims": [{"field": "return_days", "value": 14}, {"field": "price_vnd", "value": 4690000}],
             "facts_used": [], "tool_calls": []}]
    found = signals.failures(scenario(call_1={"customer_turns": []}, call_2=spec), {"call_2": rows},
                             lanes={("call_2", 1): "CONTINUITY"})
    routed = {f.code: f.route for f in found}
    assert routed == {"TSR.tool_missing:order.create": "product", "RQR.room_area_m2": "behaviour",
                      "CCR.room_area_m2": "product", "HR.return_days": "product", "HR.price_vnd": "product"}
    asked = next(f for f in found if f.code == "RQR.room_area_m2")
    assert (asked.turn, asked.lane, asked.customer) == (1, "CONTINUITY", "0900000001")
    assert asked.agent_text.startswith("Phòng chị")
    assert signals.tsr_code("có lý do mới chưa biết") == "TSR.other"
    assert signals.route("TSR.other") == "review"


# ── the screen, support, consolidation ────────────────────────────────────


# ── versions and review ───────────────────────────────────────────────────


@pytest.fixture
def improvement_home(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPROVEMENT_DIR", str(tmp_path / "improvement"))
    return tmp_path / "improvement"


def kb_line(chunk_id):
    return {"chunk_id": chunk_id, "source": "faq", "title": "Bao lâu thay màng lọc?", "text": "Sau 6 đến 12 tháng."}


def test_publish_rollback_and_revoke_never_rewrite_a_version(tmp_path, improvement_home):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "v0.jsonl").write_text("", encoding="utf-8")
    config = tmp_path / "knowledge.yaml"
    config.write_text("# the pointer\nversion: 0\nretrieval:\n  top_k: 5\n", encoding="utf-8")

    assert versions.publish([kb_line("LP-1")], reviewer="Lan", directory=kb, config_path=config) == 1
    assert versions.active(config) == 1 and "# the pointer" in config.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        versions.publish([kb_line("LP-1")], reviewer="Lan", directory=kb, config_path=config)

    assert versions.rollback(0, reviewer="Lan", reason="R1 fell", directory=kb, config_path=config) == 1
    assert versions.publish([kb_line("LP-3")], reviewer="Lan", directory=kb, config_path=config) == 2
    assert [e["chunk_id"] for e in versions.entries(2, kb)] == ["LP-3"]
    assert [e["chunk_id"] for e in versions.entries(1, kb)] == ["LP-1"]
    assert versions.revoke("LP-3", reviewer="Lan", reason="harmful", directory=kb, config_path=config) == 3
    assert versions.entries(3, kb) == [] and versions.active(config) == 3
    actions = [json.loads(line)["action"] for line in review.log_path().read_text(encoding="utf-8").splitlines()]
    assert actions == ["publish", "rollback", "publish", "revoke"]


def test_review_takes_only_what_a_person_other_than_the_author_approved(improvement_home):
    proposals = [{"proposal_id": f"LP-{n}", "kind": "playbook", "failure_code": "J07", "author": "qa",
                  "entry": kb_line(f"LP-{n}"), "counts": {}, "evidence": [], "flags": flags}
                 for n, flags in enumerate([[], [], [], ["promise"]])]
    path = review.write("r1", proposals)
    assert path.with_suffix(".md").exists()
    with pytest.raises(FileExistsError):
        review.write("r1", proposals)
    data = json.loads(path.read_text(encoding="utf-8"))
    for item, reviewer in zip(data["proposals"], ["Lan", "qa", "", "Lan"]):
        item.update(decision="approved", reviewer=reviewer)
    path.write_text(json.dumps(data), encoding="utf-8")
    taken, refused = review.approved(path)
    assert [item["proposal_id"] for item in taken] == ["LP-0"]
    assert [item["proposal_id"] for item in refused] == ["LP-1", "LP-2", "LP-3"]


# ── the exploration's customer ────────────────────────────────────────────


def customer_for(**call_2):
    spec = {"customer_turns": ["Chị gọi lại vụ máy lọc", "Chốt giúp chị nhé"], "facts_established": {"address": "Q3"},
            "expected_outcome": "chot_don", **call_2}
    data = scenario(call_1={"facts_established": {"room_area_m2": 25}}, call_2=spec)
    return Customer(data, "call_2", seed=0)


def test_customer_loses_patience_when_asked_again_and_ends_at_zero():
    customer = customer_for()
    assert customer.first() == "Chị gọi lại vụ máy lọc" and customer.patience == 3
    line = customer.step(Observation(questions=[{"slot": "room_area_m2", "type": "confirm"}]))
    assert customer.patience == 3 and line == "Chốt giúp chị nhé"
    line = customer.step(Observation(questions=[{"slot": "room_area_m2", "type": "confirm"}]))
    assert customer.patience == 2 and line == "Hôm trước chị nói rồi mà. 25."
    customer.step(Observation(questions=[{"slot": "room_area_m2", "type": "open"}]))
    line = customer.step(Observation(questions=[{"slot": "room_area_m2", "type": "open"}]))
    assert line == "Thôi để chị xem lại." and customer.ended and customer.log()["outcome"] == "tu_choi"
    assert customer.history[-1]["rules"] == [1, 2]


def test_customer_answers_what_it_knows_and_not_what_it_does_not():
    customer = customer_for()
    customer.first()
    assert customer.step(Observation(questions=[{"slot": "address", "type": "open"}])) == "Q3"
    assert customer.step(Observation(questions=[{"slot": "payment_method", "type": "open"}])) == \
        "Chị không rõ. Chốt giúp chị nhé"
    assert customer.step(Observation(questions=[{"slot": "other", "type": "open"}])) is None
    assert customer.log()["ended_by"] == "agent"


def test_customer_notices_a_new_price_agrees_to_a_matching_offer_and_ends_on_a_handoff():
    customer = customer_for()
    customer.first()
    assert customer.step(Observation(prices=[4690000])).startswith("Hôm trước em báo giá khác mà?")
    assert customer.patience == 2 and customer.history[-1]["rules"] == [3]
    assert customer.step(Observation(offer_matches=True)) == "Dạ, chị đồng ý."
    assert customer.committed and customer.outcome == "chot_don"
    other = customer_for()
    other.first()
    assert other.step(Observation(handed_off=True)) is None and other.log()["outcome"] == "chuyen_may"


def test_customer_asks_after_two_silences_and_hangs_up_after_three_or_twelve_turns():
    customer = customer_for()
    customer.first()
    customer.step(Observation(silent=True))
    assert customer.step(Observation(silent=True)) == "Em còn đó không?"
    assert customer.step(Observation(silent=True)) is None and customer.outcome == "tu_choi"
    long = customer_for(customer_turns=[f"câu {n}" for n in range(20)])
    long.first()
    while not long.ended:
        long.step(Observation())
    assert long.ended_by == "timeout" and long.n == 12


def test_the_persona_holds_challenges_or_leaves_only_where_the_outline_would_go_on():
    customer = customer_for()
    customer.first()
    line = customer.step(Observation(reaction="hold", persona_line="Bên kia rẻ hơn mà em.", agent_text="Không giảm được ạ"))
    assert line == "Bên kia rẻ hơn mà em." and customer.upcoming() == "Chốt giúp chị nhé"
    line = customer.step(Observation(reaction="challenge", persona_line="Giảm 700.000 là chương trình gì?",
                                     agent_text="Em giảm 10% cho chị"))
    assert line == "Bên kia rẻ hơn mà em."  # a number the call never had is not said
    assert customer.reactions == ["hold", "challenge"] and customer.history[-1]["reaction"] == "challenge"
    answered = customer.step(Observation(questions=[{"slot": "address", "type": "open"}], reaction="leave"))
    assert answered == "Q3" and not customer.ended  # the rules answered: the persona is not asked
    assert customer.step(Observation(reaction="leave", persona_line="Thôi khỏi.")) is None
    log = customer.log()
    assert (log["outcome"], log["ended_by"], log["reactions"]) == ("tu_choi", "customer", ["hold", "challenge", "leave"])


def test_agreement_is_still_rule_five_and_counts_the_turns_to_it():
    customer = customer_for()
    customer.first()
    customer.step(Observation(reaction="hold", persona_line="Bên kia rẻ hơn mà em."))
    assert customer.step(Observation(offer_matches=True, reaction="leave")) == "Dạ, chị đồng ý."
    assert customer.log()["turns_to_commit"] == 2 and customer.outcome == "chot_don"


def test_a_lost_sale_and_a_challenge_are_failures_of_the_call():
    data = scenario(call_1={"expected_outcome": "chot_don"})
    lost = signals.simulated(data, "call_1", {"outcome": "tu_choi", "ended_by": "customer", "n_turns": 3,
                                             "reactions": ["hold", "challenge"]})
    assert [(f.code, f.route) for f in lost] == [("SIM.lost", "behaviour"), ("SIM.challenged", "behaviour")]
    data = scenario(call_1={"expected_outcome": "tu_choi"})
    assert signals.simulated(data, "call_1", {"outcome": "tu_choi", "reactions": []}) == []


@pytest.mark.asyncio
async def test_the_session_asks_the_persona_and_never_shows_it_the_checks():
    requests = []

    class Model:
        def with_structured_output(self, schema):
            async def answer(request):
                requests.append(request)
                return schema(reaction="follow", line="Thôi chốt luôn cho chị nha")
            return RunnableLambda(answer)

    agent = SimulatorAgent.__new__(SimulatorAgent)
    agent.llm, agent.observer, agent._persona, agent.name = Model(), None, None, "simulator"
    agent.say = lambda customer, line: _same(line)
    data = scenario(call_1={"customer_turns": ["Chị muốn mua máy lọc", "Chốt giúp chị nhé"], "expected_outcome": "chot_don",
                            "success_if": {"tool_called": "order.create"}, "must_not_ask": ["room_area_m2"]})
    session = Session(agent, Customer(data, "call_1", seed=0), set())
    assert await session.opening() == "Chị muốn mua máy lọc"
    line = await session.reply("Dạ máy này bảo hành 24 tháng ạ", [], {"questions": [], "claims": []})
    assert line == "Thôi chốt luôn cho chị nha"
    assert "success_if" not in requests[0] and "must_not_ask" not in requests[0] and "order.create" not in requests[0]
    assert "Dạ máy này bảo hành 24 tháng ạ" in requests[0]
    assert isinstance(PersonaTurn(reaction="hold", line="x"), PersonaTurn)


async def _same(line):
    return line


@pytest.mark.asyncio
async def test_a_failed_persona_call_is_recorded_and_a_spent_quota_is_recognised(monkeypatch):
    monkeypatch.setattr(simulator_module, "RETRY_PAUSE_S", 0)

    class Broken:
        def with_structured_output(self, schema):
            async def answer(request):
                raise RuntimeError("429 RESOURCE_EXHAUSTED: quota")
            return RunnableLambda(answer)

    agent = SimulatorAgent.__new__(SimulatorAgent)
    agent.llm, agent.observer, agent._persona, agent.errors = Broken(), None, None, []
    data = scenario(call_1={"customer_turns": ["Chị muốn mua", "Chốt nhé"], "expected_outcome": "chot_don"})
    reaction, line = await agent.react(Customer(data, "call_1", seed=0), [], "Dạ", "Chốt nhé")
    assert (reaction, line) == ("follow", "Chốt nhé") and agent.errors


def test_a_yes_or_no_fact_is_said_as_words_and_marked_as_an_answer():
    customer = customer_for(facts_established={"has_children": False, "budget_vnd": 5000000})
    customer.first()
    assert customer.step(Observation(questions=[{"slot": "has_children", "type": "open"}])) == "Không."
    assert customer.answering == ["has_children"]
    assert customer.step(Observation(questions=[{"slot": "budget_vnd", "type": "open"}])) == "5000000"
    assert customer.step(Observation()) == "Chốt giúp chị nhé" and customer.answering == []


@pytest.mark.asyncio
async def test_the_session_says_an_answer_in_the_customer_s_words():
    voiced = []

    async def say(customer, line, *, answering=()):
        voiced.append((line, tuple(answering)))
        return "Dạ nhà chị không có trẻ nhỏ đâu em."

    agent = SimulatorAgent.__new__(SimulatorAgent)
    agent.llm, agent.observer, agent._persona, agent.name, agent.errors = None, None, None, "simulator", []
    agent.say = say
    data = scenario(call_1={"customer_turns": ["Chị muốn mua máy lọc", "Chốt giúp chị nhé"], "expected_outcome": "chot_don",
                            "facts_established": {"has_children": False}})
    session = Session(agent, Customer(data, "call_1", seed=0), set())
    voiced.clear()
    session.last_line = "Chị muốn mua máy lọc"
    session.customer.first()
    line = await session.reply("Nhà mình có trẻ nhỏ không ạ?", [],
                               {"questions": [{"slot": "has_children", "type": "open"}], "claims": []})
    assert line == "Dạ nhà chị không có trẻ nhỏ đâu em." and voiced == [("Không.", ("has_children",))]


@pytest.mark.asyncio
async def test_a_failed_call_is_retried_once_but_not_after_a_spent_daily_quota(monkeypatch):
    monkeypatch.setattr(simulator_module, "RETRY_PAUSE_S", 0)
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("503 UNAVAILABLE: the model is overloaded")
        return "ok"

    assert await simulator_module.twice(flaky, "persona") == "ok" and len(calls) == 2

    async def spent():
        calls.append(1)
        raise RuntimeError("429 RESOURCE_EXHAUSTED: GenerateRequestsPerDayPerProjectPerModel-FreeTier")

    calls.clear()
    with pytest.raises(RuntimeError):
        await simulator_module.twice(spent, "persona")
    assert len(calls) == 1


def test_a_rewrite_that_drops_a_number_is_not_said():
    assert faithful("Chị muốn mua 2 máy", "Cho chị lấy 2 cái máy nha")
    assert not faithful("Chị muốn mua 2 máy", "Cho chị lấy máy nha")


# ── the QaAgent and the search ────────────────────────────────────────────


class Scripted:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def with_structured_output(self, schema):
        async def answer(request):
            self.requests.append(request)
            return self.answers.pop(0)
        return RunnableLambda(answer)


class Inner:
    def __init__(self, data):
        self.data_ = data

    def has(self, name):
        return True

    async def call(self, name, /, **args):
        return {"ok": True, "data": dict(self.data_)}


# ── harvest ───────────────────────────────────────────────────────────────


def test_harvest_refuses_until_the_frozen_set_is_written_and_never_learns_from_it(tmp_path, improvement_home):
    run = tmp_path / "run"
    (run / "scenarios").mkdir(parents=True)
    spec = {"must_not_ask": ["room_area_m2"]}
    (run / "scenarios" / "S1.json").write_text(json.dumps({**scenario(call_1=spec), "scenario_id": "S1"}),
                                               encoding="utf-8")
    rows = [{"scenario_id": "S1", "call": "call_1", "turn": 1, "customer_text": "", "agent_text": "Phòng mấy m²?",
             "questions": [{"slot": "room_area_m2", "type": "open"}], "claims": [], "tool_calls": []}]
    (run / "full.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        cli.harvest(run, "learn-1")
    improvement_home.mkdir(parents=True, exist_ok=True)
    (improvement_home / "frozen.json").write_text(json.dumps(["S1"]), encoding="utf-8")
    assert cli.harvest(run, "learn-1") == 2
    (improvement_home / "frozen.json").write_text(json.dumps(["F1"]), encoding="utf-8")
    assert cli.harvest(run, "learn-1") == 0
    found = lessons.read_jsonl(lessons.round_dir("learn-1") / "failures.jsonl")
    assert [f["code"] for f in found] == ["RQR.room_area_m2"]
    assert cli.harvest(run, "learn-1") == 2
