import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.services.agent.extract_command import main, pace
from src.services.agent_settings import product_settings


class ExtractorCommandTest(unittest.TestCase):
    def test_failed_command_preserves_known_usage_and_leaves_unknown_missing(self):
        from openai import LengthFinishReasonError
        from openai.types.chat import ChatCompletion
        from unittest.mock import MagicMock

        class Stream(io.StringIO):
            def reconfigure(self, **kwargs):
                pass

        truncated = LengthFinishReasonError(completion=ChatCompletion(
            id="fixture", model="mock", object="chat.completion", created=0, choices=[],
            usage={"prompt_tokens": 1258, "completion_tokens": 4096, "total_tokens": 5354}))
        for error in [truncated, RuntimeError("unknown billing")]:
            with self.subTest(error=type(error).__name__):
                model = MagicMock()
                model.with_structured_output.return_value.invoke.side_effect = error
                output = Stream()
                with patch("src.services.agent.extract_command.sys.stdin", Stream(json.dumps({
                    "config": {"provider": "openai"}, "prompt": "fixture"}))), \
                     patch("src.services.agent.extract_command.sys.stdout", output), \
                     patch("src.services.agent.extract_command.pace"), \
                     patch("src.services.agent.extract_command.LLMFactory.create_llm", return_value=model):
                    self.assertEqual(main(), 2)
                result = json.loads(output.getvalue())
                self.assertIsNone(result["raw"])
                if error is truncated:
                    self.assertEqual(result["usage"]["output_tokens"], 4096)
                    self.assertEqual(result["usage"]["cost"], 0.0070568)
                else:
                    self.assertIsNone(result["usage"])

    def test_pacing_reuses_file_without_reopening_in_truncate_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent-eval-extractor-test.json"
            path.write_text(json.dumps([0, 99]))
            with patch("src.services.agent.extract_command.tempfile.gettempdir", return_value=directory), \
                 patch("src.services.agent.extract_command.time.time", return_value=100):
                pace({"provider": "test", "rate_limits": {"requests_per_minute": 60}})
            self.assertEqual(json.loads(path.read_text()), [99, 100])

    def test_corrupt_pacing_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent-eval-extractor-test.json"
            path.write_text("broken")
            with patch("src.services.agent.extract_command.tempfile.gettempdir", return_value=directory):
                with self.assertRaisesRegex(RuntimeError, "pacing state"):
                    pace({"provider": "test", "rate_limits": {"requests_per_minute": 60}})
            self.assertEqual(path.read_text(), "broken")

    def test_extractor_override_keeps_agent_output_budget(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test-key"}):
            settings = product_settings("openai:gpt-4.1-mini", "openai:gpt-4.1-mini")
        self.assertEqual(settings["extractor"]["max_tokens"], 4096)


if __name__ == "__main__":
    unittest.main()
