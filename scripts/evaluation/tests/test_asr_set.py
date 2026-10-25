import json
import tempfile
import unittest
import wave
from pathlib import Path

from eval_harness.asr_eval import build_set, check_set


def _wav(path, seconds, rate=16000, channels=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\x01\x00" * int(seconds * rate) * channels)


class AsrSetTest(unittest.TestCase):
    def test_filter_keeps_only_current_spoken_turns_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            scenarios, audio = tmp / "scenarios", tmp / "audio"
            scenarios.mkdir()
            (scenarios / "SCN-T-1.json").write_text(json.dumps({"scenario_id": "SCN-T-1", "region": "bac", "calls": {
                "call_1": {"input_mode": "text", "customer_turns": ["Ngân sách chị 5 triệu.", "Phòng 25m² nhé.",
                                                                    "Thanh toán COD.", "Câu mới", "ko dc"]}}}),
                encoding="utf-8")

            def clip(turn, text, *, seconds=1.0, mode="text", noise=None, wav=True, **wav_args):
                folder = audio / "scenarios_SCN-T-1" / "call_1"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"turn_{turn}.json").write_text(json.dumps({
                    "scenario_id": "SCN-T-1", "call": "call_1", "turn": turn, "text": text, "input_mode": mode,
                    "duration_seconds": seconds, "noise": noise}), encoding="utf-8")
                if wav:
                    _wav(folder / f"turn_{turn}.wav", seconds, **wav_args)

            clip(1, "Ngân sách chị 5 triệu.", noise={"type": "cafe", "snr_db": 6})
            clip(2, "Phòng 25m² nhé.")
            clip(3, "Thanh toán COD.", wav=False)          # the voice was never synthesised
            clip(4, "Câu cũ đã đổi")                         # the scenario was regenerated since
            clip(5, "ko dc", mode="chat_teencode")          # typed slang
            clip(6, "Không còn lượt này")                    # the call has fewer turns now
            clip(7, "x", rate=8000)                          # cannot be in range either; never reached
            out = tmp / "set"
            report = build_set(out, audio_root=audio, scenarios_dir=scenarios, set_id="asr-test")
            self.assertEqual(report["counts"]["kept"], 2)
            self.assertEqual(report["counts"]["dropped_by_reason"],
                             {"turn_out_of_range": 2, "wav_missing": 1, "text_changed": 1, "not_speech": 1})
            truth = {d["id"]: d for d in json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))["dialogues"]}
            first = truth["SCN-T-1-call_1-t1"]
            self.assertEqual(first["full_text"], "ngân sách chị năm triệu.")
            self.assertEqual(first["entities"], {"budget_vnd": 5000000})
            self.assertTrue(first["noisy"])
            self.assertEqual(truth["SCN-T-1-call_1-t2"]["entities"], {"room_area_m2": 25})
            self.assertEqual(check_set(out, "asr-test"), ([], 2))
            with self.assertRaises(ValueError):  # a revision is never overwritten
                build_set(out, audio_root=audio, scenarios_dir=scenarios, set_id="asr-test")
            _wav(out / "audio" / "SCN-T-1-call_1-t2.wav", 2.0)
            issues, _ = check_set(out, "asr-test")
            self.assertEqual([i["code"] for i in issues], ["ASR_AUDIO_HASH"])
            _wav(out / "audio" / "SCN-T-1-call_1-t2.wav", 1.0, rate=8000)
            issues, _ = check_set(out, "asr-test")
            self.assertEqual(issues[0]["reason"], "wav_format")


if __name__ == "__main__":
    unittest.main()
