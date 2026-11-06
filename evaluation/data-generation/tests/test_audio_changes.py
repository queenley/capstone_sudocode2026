import json

from src.asr.reference import unchanged_lines
from src.pipeline.carry_audio import carry_call
from src.pipeline.synthesize_scenario_audio import turns_to_speak


class Call:
    def __init__(self, turns):
        self.customer_turns = turns


class Scene:
    scenario_id = "S"

    def __init__(self, **calls):
        self.calls = {name: Call(turns) for name, turns in calls.items()}

    def ordered_calls(self):
        return list(self.calls.items())


def clip(root, call, turn, text):
    folder = root / "scenarios_S" / call
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"turn_{turn}.wav").write_bytes(text.encode())
    (folder / f"turn_{turn}.json").write_text(json.dumps({"text": text, "turn": turn}), encoding="utf-8")


def test_a_clip_follows_its_words_when_a_line_is_added_before_it(tmp_path):
    base, audio = tmp_path / "base", tmp_path / "audio"
    clip(base / "audio", "call_1", 1, "chào em")
    clip(base / "audio", "call_1", 2, "cảm ơn em")
    scene = Scene(call_1=["chào em", "đúng rồi em", "cảm ơn em"])
    assert carry_call(scene, "call_1", base, audio) == (2, 1)
    moved = audio / "scenarios_S" / "call_1" / "turn_3"
    assert moved.with_suffix(".wav").read_bytes() == "cảm ơn em".encode()
    assert json.loads(moved.with_suffix(".json").read_text(encoding="utf-8"))["turn"] == 3


def test_only_the_changed_turn_is_spoken_and_a_silent_call_stays_silent(tmp_path):
    clip(tmp_path, "call_1", 1, "chào em")
    scene = Scene(call_1=["chào em", "đúng rồi em"], call_2=["alo"])
    assert turns_to_speak(scene, root=tmp_path) == [("call_1", 2, "đúng rồi em")]


def test_a_named_new_scenario_is_spoken_from_nothing(tmp_path):
    assert turns_to_speak(Scene(call_1=["alo"]), {"S"}, tmp_path) == [("call_1", 1, "alo")]


def test_a_line_keeps_its_spoken_form_wherever_it_moved():
    record = {"turns": [{"idx": 2, "speaker": "C", "text": "cảm ơn em", "spoken_text": "cảm ơn em"}]}
    lines = [{"idx": 1, "speaker": "C", "text": "mới"}, {"idx": 3, "speaker": "C", "text": "cảm ơn em"}]
    assert unchanged_lines(record, lines) == {3: {**record["turns"][0], "idx": 3}}
