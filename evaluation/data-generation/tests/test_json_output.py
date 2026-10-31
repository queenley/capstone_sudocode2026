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
