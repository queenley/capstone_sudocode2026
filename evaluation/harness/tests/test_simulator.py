"""The BTC customer simulator: its eight rules, the call-level fix, the voice guard and the session's evidence. No model."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import simulate  # noqa: E402


def spec(**extra):
    base = {"customer_goal": "Mua máy lọc không khí", "facts_established": {"payment": "COD", "delivery_area": "Hà Nội", "product_advised": "SKU-AP-X"},
            "customer_turns": ["Alo, chị muốn mua máy lọc.", "Chị thanh toán COD.", "Giao ở Hà Nội nhé.", "Chị chốt đơn."],
            "must_not_ask": ["product_advised"], "expected_outcome": "chot_don",
            "success_if": {"tool_called": "order.create", "args_match": {"sku": "SKU-AP-X", "payment": "COD"}}}
    base.update(extra)
    return base


def customer(call="call_2", persona="khach_so_gia", prior=("product_advised",), **extra):
    return simulate.Customer("SCN-T", call, persona, spec(**extra), 0, prior)


def step(c, **observed):
    return c.process({"observed": observed})


class Rules(unittest.TestCase):
    def test_1_repeated_open_question_costs_patience_and_complains(self):
        c = customer()
        start = c.patience
        reply = step(c, questions=[{"slot": "product_advised", "type": "open"}])
        self.assertEqual(c.patience, start - 1)
        self.assertEqual(c.irritation, 1)
        self.assertIn("Hôm trước chị nói rồi mà", reply)

    def test_1_first_confirmation_is_free_second_costs(self):
        c = customer()
        start = c.patience
        step(c, questions=[{"slot": "product_advised", "type": "confirm"}])
        self.assertEqual(c.patience, start)
        step(c, questions=[{"slot": "product_advised", "type": "confirm"}])
        self.assertEqual(c.patience, start - 1)

    def test_2_zero_patience_ends_with_tu_choi(self):
        c = customer(call="call_3", persona="khach_goi_lan_3_het_kien_nhan")
        self.assertEqual(c.patience, 1)
        reply = step(c, questions=[{"slot": "product_advised", "type": "open"}])
        self.assertTrue(c.ended)
        self.assertEqual((c.outcome, c.ended_by), ("tu_choi", "customer"))
        self.assertEqual(reply, "Thôi để chị xem lại.")

    def test_3_wrong_price_costs_patience(self):
        c = customer()
        start = c.patience
        self.assertIn("Hôm trước", step(c, wrong_price=True))
        self.assertEqual(c.patience, start - 1)

    def test_4_new_needed_information_is_answered_free(self):
        c = customer()
        start = c.patience
        reply = step(c, questions=[{"slot": "payment", "type": "open"}])
        self.assertEqual(reply, "COD")
        self.assertEqual(c.patience, start)

    def test_5_matching_offer_commits_to_the_expected_outcome(self):
        c = customer()
        self.assertEqual(step(c, offer_matches=True), "Dạ chị đồng ý.")
        self.assertTrue(c.committed)
        self.assertEqual(c.outcome, "chot_don")
        later = customer(expected_outcome="hen_goi_lai")
        self.assertEqual(step(later, offer_matches=True), "Chị hẹn gọi lại nhé.")

    def test_6_two_off_topic_turns_ask_if_present_and_the_third_hangs_up(self):
        c = customer()
        step(c, silent_or_off_topic=True)
        self.assertEqual(step(c, silent_or_off_topic=True), "Em còn đó không?")
        step(c, silent_or_off_topic=True)
        self.assertTrue(c.ended)
        self.assertEqual(c.outcome, "tu_choi")

    def test_7_unknown_slot_is_not_invented(self):
        c = customer()
        self.assertTrue(step(c, questions=[{"slot": "other", "type": "open"}]).startswith("Chị không rõ."))

    def test_8_twelve_customer_turns_time_out(self):
        c = customer(customer_turns=[f"dòng {i}" for i in range(20)])
        for _ in range(40):
            if step(c) is None and c.ended:
                break
        self.assertEqual((c.outcome, c.ended_by), ("timeout", "timeout"))
        self.assertEqual(c.n, 12)

    def test_log_has_the_mandatory_fields_and_a_decreasing_patience_trace(self):
        c = customer()
        step(c, questions=[{"slot": "product_advised", "type": "open"}])
        step(c, questions=[{"slot": "product_advised", "type": "open"}])
        log = c.log()
        for key in ("scenario_id", "call", "persona_id", "seed", "patience_trace", "outcome", "n_turns", "ended_by"):
            self.assertIn(key, log)
        self.assertEqual(log["patience_trace"], sorted(log["patience_trace"], reverse=True))


class TeamPersonas(unittest.TestCase):
    def test_a_persona_the_generator_added_is_read_from_the_teams_file(self):
        c = simulate.Customer("SCN-T", "call_1", "khach_yeu_cau_xoa_du_lieu", spec(), 0)
        self.assertEqual((c.persona_id, c.patience, c.team_persona), ("khach_yeu_cau_xoa_du_lieu", 3, True))
        self.assertIn("xóa thông tin cá nhân", c.prompt)

    def test_a_pinned_persona_is_untouched(self):
        c = simulate.Customer("SCN-T", "call_3", "khach_goi_lan_3_het_kien_nhan", spec(), 0)
        self.assertFalse(c.team_persona)
        self.assertEqual(c.patience, 1)


class Rule7Continues(unittest.TestCase):
    def test_not_knowing_is_followed_by_the_next_planned_line(self):
        c = customer()
        first = step(c)
        reply = step(c, questions=[{"slot": "other", "type": "open"}])
        self.assertEqual(reply, "Chị không rõ. " + spec()["customer_turns"][1])
        self.assertEqual(c.outline_index, 2)
        self.assertEqual(first, spec()["customer_turns"][0])

    def test_the_last_line_is_not_followed_by_anything(self):
        c = customer(customer_turns=["Chỉ một dòng."])
        step(c)
        self.assertEqual(step(c, questions=[{"slot": "other", "type": "open"}]), "Chị không rõ.")


class Rule4SkipsRepeats(unittest.TestCase):
    def test_a_planned_line_that_only_repeats_what_was_just_answered_is_skipped(self):
        c = customer()
        step(c)
        step(c, questions=[{"slot": "payment", "type": "open"}])  # answers COD
        nxt = step(c)
        self.assertEqual(nxt, "Giao ở Hà Nội nhé.")  # "Chị thanh toán COD." is not said again

    def test_bank_in_the_facts_skips_a_line_that_says_chuyen_khoan(self):
        c = customer(facts_established={"payment": "bank"}, customer_turns=["Mở đầu.", "Chị chuyển khoản nhé.", "Chốt đơn."])
        step(c)
        step(c, questions=[{"slot": "payment", "type": "open"}])
        self.assertEqual(step(c), "Chốt đơn.")


class Pronouns(unittest.TestCase):
    def test_the_kernels_own_lines_use_the_scenarios_honorific(self):
        c = simulate.Customer("SCN-T", "call_2", "khach_so_gia", spec(), 0, honorific="anh")
        self.assertEqual(c.speak("Thôi để chị xem lại."), "Thôi để anh xem lại.")
        self.assertEqual(c.speak("Chị không rõ."), "Anh không rõ.")

    def test_planned_lines_are_never_rewritten(self):
        c = simulate.Customer("SCN-T", "call_2", "khach_so_gia", spec(), 0, honorific="anh")
        self.assertEqual(c.speak(spec()["customer_turns"][0]), spec()["customer_turns"][0])


class CallLevel(unittest.TestCase):
    def test_a_slot_this_call_will_establish_is_not_already_answered(self):
        fresh = simulate.Customer("SCN-T", "call_1", "khach_so_gia", spec(), 0, prior_slots=())
        start = fresh.patience
        step(fresh, questions=[{"slot": "payment", "type": "open"}])
        self.assertEqual(fresh.patience, start)


class FakeModel:
    def __init__(self, replies):
        self.replies, self.log = list(replies), []

    def chat(self, system, user, *, seed, schema=None):
        self.log.append((system, user, seed, schema))
        return self.replies.pop(0)


class VoiceGuard(unittest.TestCase):
    def test_paraphrase_that_drops_a_number_is_discarded(self):
        c = customer(customer_turns=["Phòng của chị 40m2.", "Chị chốt đơn."])
        voice = simulate.Voice(FakeModel(["Chị cần máy lọc phòng rộng."]), 0)
        self.assertEqual(voice.say(c, "Phòng của chị 40m2.", 1), "Phòng của chị 40m2.")

    def test_the_kernels_own_words_are_never_rewritten(self):
        c = customer()
        voice = simulate.Voice(FakeModel(["Bên em không lưu à?"]), 0)
        self.assertEqual(voice.say(c, "Chị không rõ.", 1), "Chị không rõ.")

    def test_paraphrase_that_keeps_the_numbers_is_used(self):
        c = customer(customer_turns=["Phòng của chị 40m2.", "Chị chốt đơn."])
        voice = simulate.Voice(FakeModel(["Phòng nhà chị khoảng 40m2 đó em."]), 0)
        self.assertEqual(voice.say(c, "Phòng của chị 40m2.", 1), "Phòng nhà chị khoảng 40m2 đó em.")


class VoiceRole(unittest.TestCase):
    def test_a_reply_that_recites_another_outline_line_is_discarded(self):
        c = customer()
        voice = simulate.Voice(FakeModel(["Alo, chị muốn mua máy lọc. Chị thanh toán COD."]), 0)
        self.assertEqual(voice.say(c, "Giao ở Hà Nội nhé.", 1), "Giao ở Hà Nội nhé.")

    def test_a_reply_that_answers_as_the_shop_is_discarded(self):
        c = customer()
        voice = simulate.Voice(FakeModel(["Dạ bên em có sẵn máy lọc đó ạ, em kiểm tra cho chị nhé."]), 0)
        self.assertEqual(voice.say(c, "Chị thanh toán COD.", 1), "Chị thanh toán COD.")


class VoiceAnswers(unittest.TestCase):
    def test_a_number_keeps_its_value_however_it_is_written(self):
        c = customer()
        c.answering = "price_quoted_vnd"
        voice = simulate.Voice(FakeModel(["Dạ giá em báo là 1.990.000 đồng đó."]), 0)
        self.assertEqual(voice.say(c, "1990000", 1), "Dạ giá em báo là 1.990.000 đồng đó.")

    def test_a_bare_value_becomes_a_sentence_in_the_customers_words(self):
        c = customer()
        c.answering = "payment"
        voice = simulate.Voice(FakeModel(["Chị thanh toán chuyển khoản nhé."]), 0)
        self.assertEqual(voice.say(c, "bank", 1), "Chị thanh toán chuyển khoản nhé.")

    def test_a_sentence_that_changes_the_value_is_discarded(self):
        c = customer()
        c.answering = "payment"
        voice = simulate.Voice(FakeModel(["Chị thanh toán tiền mặt nhé."]), 0)
        self.assertEqual(voice.say(c, "bank", 1), "bank")

    def test_rule_4_marks_the_slot_that_was_answered(self):
        c = customer()
        step(c, questions=[{"slot": "payment", "type": "open"}])
        self.assertEqual(c.answering, "payment")
        step(c)
        self.assertIsNone(c.answering)


class SessionEvidence(unittest.TestCase):
    def make(self, observed_json):
        model = FakeModel([observed_json] * 4)
        c = customer()
        voice = simulate.Voice(FakeModel(["x"] * 9), 0)
        voice.say = lambda customer, line, turn: line  # the rule kernel's own words
        session = simulate.Session(c, simulate.Observer(model, 0), voice, spec(), "full", prior_prices=set())
        return session, model

    def event(self, name, args, result=None):
        return {"request": {"name": name, "args": args}, "result": result or {}}

    def test_offer_is_judged_on_the_real_tool_call_and_prices_on_tool_results(self):
        session, _ = self.make(json.dumps({"questions": [], "stated_prices_vnd": [4890000], "off_topic": False,
                                           "answered_outline_indices": []}))
        session.first()
        events = [self.event("pricing.get_quote", {"sku": "SKU-AP-X"}, {"final_price_vnd": 4890000}),
                  self.event("order.create", {"sku": "SKU-AP-X", "payment": "COD", "price_vnd": 4890000})]
        line = session.reply("Em đã tạo đơn, giá 4.890.000đ", events)
        self.assertEqual(line, "Dạ chị đồng ý.")
        self.assertTrue(session.customer.committed)
        passed, reasons = simulate._reference_eval().check_call(spec(), session.rows)
        self.assertTrue(passed, reasons)

    def test_a_price_no_tool_returned_is_a_wrong_price(self):
        session, _ = self.make(json.dumps({"questions": [], "stated_prices_vnd": [3490000], "off_topic": False,
                                           "answered_outline_indices": []}))
        session.first()
        before = session.customer.patience
        session.reply("Giá 3.490.000đ ạ", [self.event("pricing.get_quote", {}, {"final_price_vnd": 4890000})])
        self.assertEqual(session.customer.patience, before - 1)

    def test_the_agent_only_ever_receives_the_customers_words_and_the_model_never_sees_the_checks(self):
        session, model = self.make(json.dumps({"questions": [], "stated_prices_vnd": [], "off_topic": False,
                                               "answered_outline_indices": []}))
        first = session.first()
        self.assertIsInstance(first, str)
        session.reply("Dạ chào chị", [])
        for system, user, _, _ in model.log:
            self.assertNotIn("success_if", system + user)
            self.assertNotIn("order.create", system + user)

    def test_the_trace_records_what_the_observer_saw_and_which_rules_fired(self):
        session, _ = self.make(json.dumps({"questions": [{"slot": "product_advised", "type": "open"}], "stated_prices_vnd": [],
                                           "off_topic": False, "answered_outline_indices": []}))
        session.first()
        session.reply("Chị chọn sản phẩm nào ạ?", [])
        row = session.trace[-1]
        self.assertEqual(row["rules"], [1])
        self.assertEqual(row["observed"]["questions"], [{"slot": "product_advised", "type": "open"}])
        self.assertIn("patience", row)

    def test_a_completed_handoff_ends_the_call(self):
        session, _ = self.make(json.dumps({"questions": [], "stated_prices_vnd": [], "off_topic": False,
                                           "answered_outline_indices": []}))
        session.first()
        events = [self.event("handoff.transfer", {"brief": {}}, {"ticket_id": "T1"})]
        self.assertIsNone(session.reply("Em chuyển máy cho nhân viên ạ", events))
        self.assertEqual((session.customer.outcome, session.customer.ended_by), ("chuyen_may", "agent"))
        self.assertEqual(session.log()["n_turns"], 1)

    def test_a_refused_handoff_does_not_end_the_call(self):
        session, _ = self.make(json.dumps({"questions": [], "stated_prices_vnd": [], "off_topic": False,
                                           "answered_outline_indices": []}))
        session.first()
        events = [self.event("handoff.transfer", {"brief": {}}, {"error": "x"})]
        self.assertIsNotNone(session.reply("Em chuyển máy ạ", events))

    def test_observer_prompt_tells_offers_from_questions(self):
        self.assertIn("KHÔNG phải câu hỏi thông tin", simulate.OBSERVER_PROMPT)

    def test_observer_ignores_malformed_output(self):
        model = FakeModel(["not json"] * simulate.OBSERVER_ATTEMPTS)
        observer = simulate.Observer(model, 0)
        seen = observer.observe("a", "b", ["payment"], {0: "x"}, 1)
        self.assertEqual((seen["questions"], seen["prices"], seen["answered_outline_indices"]), ([], [], []))
        self.assertEqual((len(model.log), observer.invalid), (simulate.OBSERVER_ATTEMPTS, simulate.OBSERVER_ATTEMPTS))


class Statistics(unittest.TestCase):
    def test_money_in_collects_vnd_fields(self):
        self.assertEqual(simulate.money_in({"a": {"final_price_vnd": 5}, "b": [{"total_vnd": 7}], "c": 3}), {5, 7})


class ObserverOutput(unittest.TestCase):
    """The observer's answer: held to ``Observed``, repaired, asked again with the error, empty at the end."""

    class Model:
        def __init__(self, *answers):
            self.answers, self.users, self.schemas = list(answers), [], []

        def chat(self, system, user, *, seed, schema=None):
            self.users.append(user)
            self.schemas.append(schema)
            return self.answers.pop(0)

    @classmethod
    def setUpClass(cls):
        from agent import launch

        launch.prepare()

    def observe(self, model):
        return simulate.Observer(model, 0).observe("Chị hỏi giá", "Dạ giá 1.990.000đ ạ, chị lấy size nào ạ?",
                                                    ["size"], {0: "Chị lấy size 38."}, 1)

    def test_broken_json_is_repaired(self):
        model = self.Model('{"questions": [{"slot": "size", "type": "open"},], "stated_prices_vnd": [1990000]')
        seen = self.observe(model)
        self.assertEqual((seen["questions"], seen["prices"]), ([{"slot": "size", "type": "open"}], [1990000]))
        self.assertIs(model.schemas[0], simulate.Observed)

    def test_wrong_shape_is_asked_again_with_the_error(self):
        model = self.Model('{"questions": [{"slot": "size", "type": "hỏi"}]}', '{"off_topic": true}')
        seen = self.observe(model)
        self.assertTrue(seen["off_topic"])
        self.assertIn("RETRY:", model.users[1])

    def test_no_valid_answer_observes_nothing(self):
        seen = self.observe(self.Model(*['{"stated_prices_vnd": ["nhiều"]}'] * simulate.OBSERVER_ATTEMPTS))
        self.assertEqual((seen["questions"], seen["prices"], seen["off_topic"]), ([], [], False))


if __name__ == "__main__":
    unittest.main()
