"""The ASR reference of the scenario audio: the model's spoken form is checked, and falls back to the rules."""
import json

from src.asr.reference import build, load_or_build, problems, products_of, write_ground_truth
from src.asr.spoken import to_spoken
from src.schemas.asr import SpokenCall, SpokenEntities, SpokenTurn

PRODUCTS = {"SKU-AP-X": "Máy lọc không khí AirPure X"}


class FakeClient:
    """Answers with the given SpokenCall objects in turn and records the prompts."""

    model = "fake"

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def generate(self, prompt, schema, **_):
        assert schema is SpokenCall
        self.prompts.append(prompt)
        if not self.answers:
            raise RuntimeError("no answer left")   # what a client raises when it gives up
        return self.answers.pop(0)


def turn(idx, spoken, **entities):
    return SpokenTurn(idx=idx, spoken_text=spoken, entities=SpokenEntities(**entities))


def test_a_faithful_spoken_form_passes():
    assert problems("Phòng chị 25m2, ngân sách tầm 5 triệu thôi em.",
                    turn(1, "phòng chị hai mươi lăm mét vuông, ngân sách tầm năm triệu thôi em.",
                         room_area_m2=25, budget_vnd=5_000_000), PRODUCTS) == []
    assert problems("Chị lấy con AirPure X nhé", turn(1, "chị lấy con e pia x nhé", sku="SKU-AP-X"), PRODUCTS) == []


def test_rewrites_digits_and_invented_values_are_caught():
    assert "digit_left" in problems("Phòng 25m2", turn(1, "phòng 25 mét vuông"), PRODUCTS)
    assert "words_changed" in problems("Chị muốn hỏi máy lọc cho phòng ngủ",
                                       turn(1, "tôi cần tư vấn thiết bị lọc không khí"), PRODUCTS)
    assert "entity_not_stated:budget_vnd" in problems("Chị muốn hỏi giá", turn(1, "chị muốn hỏi giá", budget_vnd=5_000_000), PRODUCTS)
    assert "entity_unknown:sku" in problems("Chị lấy máy kia", turn(1, "chị lấy máy kia", sku="SKU-NOPE"), PRODUCTS)


def test_a_line_the_model_keeps_getting_wrong_falls_back_to_the_rules(all_scenarios):
    scenario = next(s for s in all_scenarios if s.calls["call_1"].input_mode == "text")
    call = scenario.calls["call_1"].model_copy(update={"customer_turns": ["Alo em ơi", "Phòng chị 25m2 nhé"]})
    bad = SpokenCall(turns=[turn(1, "alo em ơi"), turn(2, "phòng chị 25m2 nhé")])
    still_bad = SpokenCall(turns=[turn(2, "phòng chị 25m2 nhé")])
    client = FakeClient(bad, still_bad)
    record = build(client, scenario, "call_1", call, {})
    first, second = record["turns"]
    assert first["reference_source"] == "llm" and first["spoken_text"] == "alo em ơi"
    assert second["reference_source"] == "rule" and second["spoken_text"] == "phòng chị hai mươi lăm mét vuông nhé"
    assert "digit_left" in second["issues"] and "fix them" in client.prompts[1]


def test_ground_truth_lists_spoken_clips_in_btc_format(tmp_path, all_scenarios):
    from src.utils.dataset import Dataset

    dataset = Dataset(tmp_path / "output")
    scenario = next(s for s in all_scenarios if s.calls["call_1"].input_mode == "text")
    dataset.write_scenario(scenario)
    call = scenario.calls["call_1"]
    client = FakeClient(SpokenCall(turns=[turn(i, to_spoken(text)) for i, text in enumerate(call.customer_turns, start=1)]))
    record = load_or_build(lambda: client, scenario, "call_1", call, PRODUCTS, root=tmp_path / "asr_reference")
    assert {t["reference_source"] for t in record["turns"]} == {"llm"}
    assert load_or_build(lambda: FakeClient(), scenario, "call_1", call, PRODUCTS, root=tmp_path / "asr_reference") == record
    audio = tmp_path / "output" / "audio" / f"scenarios_{scenario.scenario_id}" / "call_1"
    audio.mkdir(parents=True)
    (audio / "turn_1.wav").write_bytes(b"RIFF")
    (audio / "turn_1.json").write_text(json.dumps({
        "scenario_id": scenario.scenario_id, "call": "call_1", "turn": 1, "text": call.customer_turns[0],
        "input_mode": "text", "spoken_text": "câu 1", "entities": {}, "reference_source": "llm",
        "customer_gender": "f", "duration_seconds": 1.5, "noise": None}), encoding="utf-8")
    summary = write_ground_truth(tmp_path / "output" / "audio", tmp_path / "gt.json", dataset)
    truth = json.loads((tmp_path / "gt.json").read_text(encoding="utf-8"))
    assert summary["dialogues"] == 1 and set(truth) == {"description", "hypotheses_format", "normalization_rule",
                                                         "reference_date", "kind", "entity_schema", "dialogues"}
    assert truth["kind"] == "turns" and {"budget_vnd", "price_vnd", "blocker"} <= set(truth["entity_schema"]["properties"])
    dialogue = truth["dialogues"][0]
    assert dialogue["full_text"] == "câu 1" and dialogue["turns"][0]["speaker"] == "C"
    assert dialogue["id"] == f"{scenario.scenario_id}-call_1-t1"


def test_products_of_a_call_come_from_its_labels_or_its_words(all_scenarios):
    call = next(c for s in all_scenarios for c in s.calls.values() if "SKU-" in json.dumps(c.model_dump(mode="json")))
    sku = next(word for word in json.dumps(call.model_dump(mode="json")).replace('"', " ").split() if word.startswith("SKU-"))
    assert sku.strip(",") in products_of(call, {sku.strip(","): "x", "SKU-ZZZ": "y"})
