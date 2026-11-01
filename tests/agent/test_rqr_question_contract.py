"""Synthetic RQR contract: evidence/projection regressions, without a model call.

Semantic expectations in the JSON are review fixtures. Passing these tests
must never be reported as a measurement of the model's Vietnamese accuracy.
"""
import json
from pathlib import Path

import pytest

from ai_agent_service.components.evaluation import scorers
from ai_agent_service.components.memory.ontology import CORE, INDUSTRIES


CASES_PATH = Path(__file__).resolve().parents[2] / "docs/evaluation/question-classification-cases.json"
CONTRACT = json.loads(CASES_PATH.read_text(encoding="utf-8"))
CASES = CONTRACT["cases"]
BOUNDARIES = [case for case in CASES if case["execution"] == "label_items"]


def test_contract_preserves_the_user_supplied_30_plus_4_slots():
    core = CONTRACT["ontology"]["core"]
    industry = CONTRACT["ontology"]["industries"]
    assert len(core) == len({row["name"] for row in core}) == 30
    assert len(industry) == len({row["name"] for row in industry}) == 4
    assert {row["name"] for row in core} == set(CORE)
    assert {row["name"] for row in industry} == {name for block in INDUSTRIES.values() for name in block}
    for row in core + industry:
        spec = CORE.get(row["name"])
        if spec is None:
            spec = INDUSTRIES[row["industry"]][row["name"]]
        assert row["value_type"] == spec.value_type
        assert row["meaning_vi"]
    extensions = {row["name"] for row in CONTRACT["btc_extensions"]}
    assert extensions == {"channel"} and not extensions & (set(CORE) | {row["name"] for row in industry})
    assert all(row["memory_slot"] is False for row in CONTRACT["btc_extensions"])


def test_every_ontology_slot_has_both_authored_question_types():
    coverage = {}
    for case in CASES:
        if "slot-coverage" in case["tags"]:
            for question in case["expected_questions"]:
                coverage.setdefault(question["slot"], set()).add(question["type"])
    assert coverage == {row["name"]: {"open", "confirm"}
                        for group in CONTRACT["ontology"].values() for row in group}


def test_fixture_provenance_and_unresolved_cases_remain_explicit():
    assert CONTRACT["status"] == "ready"
    assert CONTRACT["official_gt_approved"] is False
    assert len({case["id"] for case in CASES}) == len(CASES)
    unresolved = []
    allowed = {row["name"] for group in CONTRACT["ontology"].values() for row in group} | {"other", "channel"}
    for case in CASES:
        assert case["reason"] and case["preconditions"] and case["sources"]
        assert set(case["sources"]) <= CONTRACT["source_catalog"].keys()
        assert case["execution"] in {"semantic_review", "label_items"}
        assert set(case["data"]) <= {"agent_text", "tool_texts", "consultant_texts", "previous_sessions"}
        if case["review_status"] == "unresolved":
            unresolved.append(case["id"])
            assert case["expected_questions"] is None and len(case["alternatives"]) >= 2
            assert case["execution"] == "semantic_review"
            continue
        assert case["review_status"] == "specified"
        for question in case["expected_questions"]:
            assert question["slot"] in allowed
            assert question["type"] in {"open", "confirm"}
            assert question["text"] and question["text"] in case["data"]["agent_text"]
            if case["execution"] == "semantic_review":
                if question["type"] == "open":
                    assert question["candidate_value"] is None
                else:
                    assert question["candidate_value"] is not None
    assert unresolved == CONTRACT["unresolved_ids"]
    assert "btc-demo-blocker-disagreement" in unresolved


@pytest.mark.parametrize("case", BOUNDARIES, ids=lambda case: case["id"])
def test_public_question_projection_boundaries(case):
    labels = scorers.label_items(case["raw_items"], case["data"])
    assert labels["questions"] == case["expected_questions"]
    assert labels["claims"] == [] and labels["facts_used"] == []
    for item in labels["items"]:
        assert item["source_field"] == "agent_text" and item["speaker"] == "agent"
        assert case["data"]["agent_text"][item["start"]:item["end"]] == item["quote"]
