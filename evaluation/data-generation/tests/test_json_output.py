"""Model answers: strict JSON first, json_repair only for broken syntax, schema errors left for the retry."""
import pytest
from pydantic import ValidationError

from src.schemas.review import JudgeOutput
from src.utils.json_output import parse_output


def test_valid_json_is_not_marked_repaired():
    value, repaired = parse_output('{"verdicts": [{"criterion_id": "J01", "verdict": "PASS", "evidence": "Dạ"}]}', JudgeOutput)
    assert value.verdicts[0].verdict == "PASS" and not repaired


def test_broken_json_is_repaired():
    value, repaired = parse_output('{"verdicts": [{"criterion_id": "J01", "verdict": "FAIL", "evidence": "x",},]', JudgeOutput)
    assert value.verdicts[0].verdict == "FAIL" and repaired


def test_wrong_values_still_raise_for_the_client_to_ask_again():
    with pytest.raises(ValidationError):
        parse_output('{"verdicts": [{"criterion_id": "J01", "verdict": "MAYBE", "evidence": "x"}]}', JudgeOutput)


def test_a_key_the_schema_lacks_is_dropped_not_retried():
    # gpt-4o-mini wrote the scenario's tags inside each call: nothing reads them, the rest is kept as written.
    from src.schemas.scenario import ScenarioDraft

    text = ('{"calls": [{"call": "call_1", "customer_goal": "Hỏi giày chạy", "customer_turns": ["Chào em", "Giá sao em"],'
            ' "tags": ["giay"]}], "tags": ["chay"]}')
    value, repaired = parse_output(text, ScenarioDraft)
    assert repaired and value.tags == ["chay"] and value.calls[0].customer_turns == ["Chào em", "Giá sao em"]


def test_an_extra_key_beside_a_wrong_value_still_raises():
    with pytest.raises(ValidationError):
        parse_output('{"verdicts": [{"criterion_id": "J01", "verdict": "MAYBE", "evidence": "x", "note": "y"}]}', JudgeOutput)
