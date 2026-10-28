import json
import tempfile
import unittest
import wave
from pathlib import Path

from src.services.asr import build_set, check_set
from src.services.asr.diarization import roles
from src.services.asr.understanding import MEMORY_TO_BTC, plain


def _wav(path, seconds, rate=16000, channels=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\x01\x00" * int(seconds * rate) * channels)


class AsrSetTest(unittest.TestCase):
    def test_set_pins_data_generation_ground_truth_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            output, datasets = tmp / "output", tmp / "datasets"
            datasets.mkdir()

            def row(turn, *, seconds=1.0):
                return {"id": f"S-call_1-t{turn}", "full_text": f"câu {turn}", "noisy": False, "entities": {"budget_vnd": 5000000},
                        "turns": [], "audio": f"audio/scenarios_S/call_1/turn_{turn}.wav", "duration_seconds": seconds,
                        "source_text": "Ngân sách 5 triệu"}

            _wav(output / "audio/scenarios_S/call_1/turn_1.wav", 1.0)
            _wav(output / "audio/scenarios_S/call_1/turn_2.wav", 1.0, rate=8000)     # wrong format
            truth = {"kind": "turns", "entity_schema": {"properties": {}}, "dialogues": [row(1), row(2), row(3)]}
            source = output / "asr_reference/ground_truth.json"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")

            report = build_set("asr-test", kind="turns", source=source, root=datasets)
            self.assertEqual(report["counts"]["kept"], 1)
            self.assertEqual(report["counts"]["dropped_by_reason"], {"wav_format": 1, "wav_missing": 1})
            kept = json.loads((datasets / "asr-test/ground_truth.json").read_text(encoding="utf-8"))
            self.assertEqual(kept["dialogues"][0]["full_text"], "câu 1")            # taken as it is
            self.assertTrue(kept["dialogues"][0]["number_or_code"])
            registry = json.loads((datasets / "registry.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["asr_sets"][0]["kind"], "turns")
            self.assertEqual(check_set(datasets / "asr-test", "asr-test"), ([], 1))
            with self.assertRaises(ValueError):  # a revision is never overwritten
                build_set("asr-test", kind="turns", source=source, root=datasets)
            _wav(datasets / "asr-test/audio/S-call_1-t1.wav", 2.0)
            self.assertEqual([i["code"] for i in check_set(datasets / "asr-test", "asr-test")[0]], ["ASR_AUDIO_HASH"])

    def test_a_ground_truth_of_the_other_kind_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ground_truth.json"
            source.write_text(json.dumps({"kind": "dialogues", "dialogues": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_set("x", kind="turns", source=source, root=Path(tmp))


class DiarizationAndUnderstandingTest(unittest.TestCase):
    def test_first_speaker_is_the_shop_and_neighbours_merge(self):
        turns = roles([{"speaker": "spk_1", "start": 0.0, "end": 2.0, "text": "dạ shop xin nghe"},
                       {"speaker": "spk_0", "start": 2.3, "end": 4.0, "text": "alo em"},
                       {"speaker": "spk_0", "start": 4.2, "end": 5.0, "text": "chị hỏi chút"},
                       {"speaker": "spk_1", "start": 5.5, "end": 6.0, "text": "dạ"}])
        self.assertEqual([(t["speaker"], t["text"]) for t in turns],
                         [("A", "dạ shop xin nghe"), ("C", "alo em chị hỏi chút"), ("A", "dạ")])

    def test_agent_slots_map_to_btc_keys(self):
        self.assertEqual(MEMORY_TO_BTC["size"], "size_new")
        self.assertEqual(plain("Cần hỏi chồng"), "can hoi chong")
        self.assertEqual(plain("đen"), "den")


if __name__ == "__main__":
    unittest.main()
