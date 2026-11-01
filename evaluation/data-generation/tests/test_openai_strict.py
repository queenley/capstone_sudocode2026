"""OpenAI answers are asked in strict Structured Outputs, the shape enforced; a schema the API refuses goes non-strict."""
import json

import httpx
import openai
import pytest

from src.providers.openai_client import OpenAIClient, _shape_only
from src.schemas.scenario import ScenarioDraft

ANSWER = ('{"calls": [{"call": "call_1", "customer_goal": "Hỏi giày chạy", "customer_turns": ["Chào em", "Giá sao em"],'
          ' "customer_turns_asr": [], "facts_stated": []}], "tags": []}')


class _Response:
    usage = None

    def __init__(self, content):
        self.choices = [type("Choice", (), {"message": type("Message", (), {"content": content})()})()]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    return OpenAIClient("gpt-4o-mini", tmp_path / "cache", tmp_path / "log.jsonl", retries=3, rpm_limit=10_000)


def test_the_shape_is_strict_and_value_limits_stay_with_pydantic(client):
    schema = client._strict_schema(ScenarioDraft)
    text = json.dumps(schema)
    assert schema["additionalProperties"] is False and '"minItems"' not in text and '"default"' not in text


def test_a_field_named_like_a_keyword_keeps_its_definition():
    schema = {"type": "object", "properties": {"format": {"type": "string", "minLength": 1}}, "required": ["format"]}
    _shape_only(schema)
    assert schema == {"type": "object", "properties": {"format": {"type": "string"}}, "required": ["format"]}


def test_a_schema_the_api_refuses_in_strict_mode_is_sent_again_non_strict(client, monkeypatch):
    sent = []

    def create(**kwargs):
        sent.append(kwargs["response_format"]["json_schema"]["strict"])
        if len(sent) == 1:
            raise openai.BadRequestError("Invalid schema", body=None,
                                         response=httpx.Response(400, request=httpx.Request("POST", "http://test")))
        return _Response(ANSWER)

    monkeypatch.setattr(client.client.chat.completions, "create", create)
    draft = client.generate("prompt", ScenarioDraft)
    assert sent == [True, False] and draft.calls[0].customer_turns == ["Chào em", "Giá sao em"]
    assert "ScenarioDraft" in client._not_strict
