"""The extractor is shown the earlier calls of the same scenario and configuration, and nothing else."""
import io
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from src.services.agent import extract_command  # noqa: E402
from src.steps.collect.collector import extraction_inputs  # noqa: E402
from src.steps.collect.extraction import FixtureExtractor, digest, extractor_input  # noqa: E402
from src.services.extractor import ModelExtractor, attach_history, model_input  # noqa: E402

PROMPT = HERE.parents[1] / "config/prompts/evaluation/extractor.txt"
SHOWN = {"agent_text", "tool_texts", "consultant_texts", "previous_sessions"}


def turn(config, scenario, call, number):
    context = {"run_id": "r", "config": config, "scenario_id": scenario, "call": call, "turn": number}
    return f"r/{config}/{scenario}/{call}/{number}", {
        "context": context, "customer_text": f"{config} {scenario} {call} khach {number}",
        "agent_text": f"{config} {scenario} {call} agent {number}", "tool_texts": ["{}"], "consultant_texts": [],
        # Everything else a collected document carries, none of which may reach the model.
        "customer_id": "C-1", "agent_facts_used": ["blocker"], "tools": [{"result": "oracle"}], "evidence_refs": ["x"]}


def documents():
    # Deliberately out of order: the history must be ordered by call and turn, not by arrival.
    rows = [("full", "S1", "call_2", 2), ("full", "S1", "call_1", 2), ("full", "S1", "call_3", 1), ("full", "S1", "call_1", 1),
            ("full", "S1", "call_2", 1), ("baseline_no_memory", "S1", "call_2", 1), ("baseline_no_memory", "S1", "call_1", 1),
            ("full", "S2", "call_1", 1), ("full", "S2", "call_2", 1)]
    return dict(turn(*row) for row in rows)


class PreviousSessions(unittest.TestCase):
    def setUp(self):
        self.docs = documents()
        self.attached = attach_history(self.docs)

    def history(self, config, scenario, call, number):
        return self.attached[f"r/{config}/{scenario}/{call}/{number}"].get("previous_sessions")

    def test_the_first_call_has_no_earlier_session(self):
        self.assertIsNone(self.history("full", "S1", "call_1", 1))
        self.assertIsNone(self.history("full", "S1", "call_1", 2))

    def test_a_later_call_sees_every_turn_of_each_earlier_call_in_order(self):
        sessions = self.history("full", "S1", "call_3", 1)
        self.assertEqual([s["call"] for s in sessions], ["call_1", "call_2"])
        self.assertEqual([t["customer"] for t in sessions[0]["turns"]], ["full S1 call_1 khach 1", "full S1 call_1 khach 2"])
        self.assertEqual([t["agent"] for t in sessions[1]["turns"]], ["full S1 call_2 agent 1", "full S1 call_2 agent 2"])

    def test_every_turn_of_a_call_sees_the_same_history_even_the_first(self):
        self.assertEqual(self.history("full", "S1", "call_2", 1), self.history("full", "S1", "call_2", 2))
        self.assertEqual([s["call"] for s in self.history("full", "S1", "call_2", 1)], ["call_1"])

    def test_the_configurations_and_scenarios_never_mix(self):
        baseline = self.history("baseline_no_memory", "S1", "call_2", 1)
        self.assertEqual([t["agent"] for t in baseline[0]["turns"]], ["baseline_no_memory S1 call_1 agent 1"])
        other = self.history("full", "S2", "call_2", 1)
        self.assertEqual([t["agent"] for t in other[0]["turns"]], ["full S2 call_1 agent 1"])

    def test_the_originals_are_not_changed(self):
        self.assertTrue(all("previous_sessions" not in d for d in self.docs.values()))

    def test_the_model_sees_the_turn_and_the_earlier_calls_and_nothing_else(self):
        for document in self.attached.values():
            data = model_input(document)
            self.assertLessEqual(set(data), SHOWN)
            self.assertLessEqual({"agent_text", "tool_texts", "consultant_texts"}, set(data))
            for session in data.get("previous_sessions", []):
                self.assertEqual(set(session), {"call", "turns"})
                for item in session["turns"]:
                    self.assertEqual(set(item), {"customer", "agent"})
        blob = json.dumps([model_input(d) for d in self.attached.values()])
        for secret in ("oracle", "C-1", "blocker"):
            self.assertNotIn(secret, blob)

    def test_a_first_call_is_shown_exactly_what_it_was_before(self):
        document = self.attached["r/full/S1/call_1/1"]
        self.assertEqual(model_input(document), extractor_input(document))

    def test_the_pinned_fixture_input_ignores_the_history(self):
        document = self.attached["r/full/S1/call_2/1"]
        self.assertEqual(extractor_input(document), extractor_input(self.docs["r/full/S1/call_2/1"]))
        self.assertNotEqual(model_input(document), extractor_input(document))

    def test_the_collector_keys_the_model_extractor_by_the_full_input(self):
        self.assertIs(ModelExtractor.input_of, model_input)

    def test_the_request_the_command_receives_round_trips_to_the_same_input(self):
        document = self.attached["r/full/S1/call_2/1"]
        prompt = PROMPT.read_text(encoding="utf-8") + extract_command.MARKER + json.dumps(model_input(document), ensure_ascii=False)
        self.assertEqual(json.loads(prompt.split(extract_command.MARKER, 1)[1]), model_input(document))

    def test_an_earlier_call_can_never_be_an_items_evidence(self):
        source = model_input(self.attached["r/full/S1/call_2/1"])
        for name in ("previous_sessions", "previous_sessions/0", "customer_text", "consultant_texts/3"):
            self.assertIsNone(extract_command.field_text(source, name))
        items, dropped = extract_command.spanned(
            [{"source_field": "previous_sessions/0", "quote": "khach"}], source)
        self.assertEqual((items, dropped), ([], 1))



class CollectorWiring(unittest.TestCase):
    """``collect`` hands the extractor its inputs through ``extraction_inputs``; the cache is keyed by the same input."""

    def setUp(self):
        self.docs = documents()
        self.model = object.__new__(ModelExtractor)
        self.fixture = object.__new__(FixtureExtractor)
        self.key = "r/full/S1/call_2/1"

    def test_no_extractor_means_no_inputs_to_prepare(self):
        inputs, input_of = extraction_inputs(None, self.docs)
        self.assertIs(inputs, self.docs)
        self.assertIs(input_of, extractor_input)

    def test_the_model_extractor_is_keyed_by_what_it_is_shown(self):
        inputs, input_of = extraction_inputs(self.model, self.docs)
        self.assertEqual(set(inputs), set(self.docs))
        self.assertEqual(input_of(inputs[self.key]), model_input(inputs[self.key]))
        self.assertIn("previous_sessions", input_of(inputs[self.key]))
        self.assertNotIn("previous_sessions", input_of(inputs["r/full/S1/call_1/1"]))

    def test_the_pinned_fixture_extractor_is_keyed_exactly_as_before(self):
        inputs, input_of = extraction_inputs(self.fixture, self.docs)
        for key, document in self.docs.items():
            self.assertEqual(digest(input_of(inputs[key])), digest(extractor_input(document)))

    def test_the_same_turn_after_a_different_earlier_call_gets_a_different_key(self):
        changed = dict(self.docs)
        key = "r/full/S1/call_1/1"
        changed[key] = {**changed[key], "agent_text": "another reply in call_1"}
        before, input_of = extraction_inputs(self.model, self.docs)
        after, _ = extraction_inputs(self.model, changed)
        self.assertNotEqual(digest(input_of(before[self.key])), digest(input_of(after[self.key])))
        # A turn with no earlier call is unaffected by what a later call said.
        self.assertEqual(digest(input_of(before["r/full/S1/call_1/2"])), digest(input_of(after["r/full/S1/call_1/2"])))


class ModelExtractorRequest(unittest.TestCase):
    """The request ``ModelExtractor.replay`` sends to the command, with the process call stood in."""

    def extractor(self, max_calls=2):
        extractor = object.__new__(ModelExtractor)
        extractor.assets = MagicMock()
        extractor.assets.resolve.return_value = MagicMock(read_text=lambda encoding: "INSTRUCTIONS\n")
        extractor.descriptor = {"prompt": {}, "config": {"provider": "openai"}, "python": "python", "max_calls": max_calls}
        extractor.backend, extractor.recorder, extractor.calls = Path("."), lambda attempt, raw: None, 0
        extractor._lock = threading.Lock()
        return extractor

    def answer(self, items):
        return MagicMock(returncode=0, stderr="", stdout=json.dumps({"raw": json.dumps({"items": items})}))

    def test_the_command_is_sent_the_instructions_then_the_turn_and_the_earlier_calls(self):
        document = attach_history(documents())["r/full/S1/call_2/1"]
        with patch("src.services.extractor.subprocess.run", return_value=self.answer([])) as run:
            self.assertEqual(self.extractor().replay(document), [])
        sent = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(sent["config"], {"provider": "openai"})
        instructions, shown = sent["prompt"].split(extract_command.MARKER, 1)
        self.assertEqual(instructions, "INSTRUCTIONS\n")
        self.assertEqual(json.loads(shown), model_input(document))
        self.assertEqual([s["call"] for s in json.loads(shown)["previous_sessions"]], ["call_1"])

    def test_the_first_call_is_sent_no_history(self):
        document = attach_history(documents())["r/full/S1/call_1/1"]
        with patch("src.services.extractor.subprocess.run", return_value=self.answer([])) as run:
            self.extractor().replay(document)
        shown = json.loads(json.loads(run.call_args.kwargs["input"])["prompt"].split(extract_command.MARKER, 1)[1])
        self.assertEqual(set(shown), {"agent_text", "tool_texts", "consultant_texts"})

    def test_a_run_cannot_make_more_calls_than_it_pinned(self):
        document = documents()["r/full/S1/call_1/1"]
        extractor = self.extractor(max_calls=1)
        with patch("src.services.extractor.subprocess.run", return_value=self.answer([])):
            extractor.replay(document)
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                extractor.replay(document)


class CommandWithHistory(unittest.TestCase):
    """``extract_command.main`` on a request that carries ``previous_sessions``, the model standing in."""

    @staticmethod
    def item(kind, slot, quote, source="agent_text", value=None, qtype=None, start=0, purpose=""):
        return {"kind": kind, "slot_or_field": slot, "value": value, "question_type": qtype,
                "speaker": "agent", "source_field": source, "quote": quote, "start": start, "end": start + len(quote),
                "purpose": purpose}

    def run_main(self, document, items):
        class Stream(io.StringIO):
            def reconfigure(self, **kwargs):
                pass

        prompt = "INSTRUCTIONS" + extract_command.MARKER + json.dumps(model_input(document), ensure_ascii=False)
        model = MagicMock()
        model.with_structured_output.return_value.invoke.return_value = {"items": items}
        output = Stream()
        with patch("src.services.agent.extract_command.sys.stdin", Stream(json.dumps({"config": {"provider": "openai"}, "prompt": prompt}))), \
             patch("src.services.agent.extract_command.sys.stdout", output), patch("src.services.agent.extract_command.pace"), \
             patch("src.services.agent.extract_command.LLMFactory.create_llm", return_value=model):
            self.assertEqual(extract_command.main(), 0)
        return json.loads(output.getvalue())

    def test_items_are_kept_from_the_turn_and_never_from_the_earlier_calls(self):
        document = attach_history(documents())["r/full/S1/call_2/1"]
        agent = document["agent_text"]
        earlier = document["previous_sessions"][0]["turns"][0]["agent"]
        result = self.run_main(document, [
            self.item("question", "room_area_m2", "agent 1", start=999, qtype="open"),       # offset wrong, quote found
            self.item("fact_usage", "product_advised", earlier, source="previous_sessions/0", purpose="x"),
            self.item("fact_usage", "channel", "call_2", purpose="the channel is carried over"),
            self.item("question", "shoe_colour", "full", qtype="confirm"),                  # not a slot
            self.item("fact_usage", "date", "S1", purpose="not a slot")])
        items = json.loads(result["raw"])["items"]
        self.assertEqual(result["dropped_items"], 1)
        self.assertEqual([(i["kind"], i["slot_or_field"]) for i in items],
                         [("question", "room_area_m2"), ("fact_usage", "channel"), ("question", "other")])
        first = items[0]
        self.assertEqual(agent[first["start"]:first["end"]], "agent 1")
        self.assertEqual(items[2]["question_type"], "open")
        # An unknown slot made "other", that question made "open", and the unknown fact use set aside.
        self.assertEqual(result["slots_outside_vocabulary"], 3)

    def test_a_named_promotion_the_model_also_wrote_as_promo_active_is_one_claim_each(self):
        document = attach_history(documents())["r/full/S1/call_2/1"]
        text = document["agent_text"]
        named = self.item("claim", "promo_RUN-10_active", "call_2", value=True, purpose="promotion")
        plain = self.item("claim", "promo_active", "call_2", value=True, purpose="promotion")
        items = json.loads(self.run_main(document, [named, plain])["raw"])["items"]
        self.assertEqual([i["slot_or_field"] for i in items], ["promo_RUN-10_active", "promo_active"])
        self.assertTrue(all(text[i["start"]:i["end"]] == i["quote"] for i in items))


if __name__ == "__main__":
    unittest.main()
