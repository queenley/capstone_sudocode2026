"""The key registry (contracts/scenario/scenario-keys.yaml): BTC's samples and every planned scenario comply,
a key outside it is refused, and its own entries follow the naming rules they state."""
import json
import re

import pytest

from src.schemas import keys
from src.schemas.slots import SLOTS
from src.utils.dataset import Dataset
from src.utils.paths import SAMPLE_DIR

ORIGINS = {"btc_sample", "btc_format", "team"}
#: rules.naming: the type a suffix implies.
SUFFIX_TYPES = [(r"_vnd$", {"int"}), (r"_m2$|_days$|_months$|_hours$|_percent$", {"int"}),
                (r"_date$|_expiry$", {"date"}), (r"_at$", {"datetime"}), (r"_sku$", {"sku"})]


def entries():
    reg = keys.registry()
    for section in ("scenario", "call", "slots", "memory_expectation", "success_if", "ground_truth_facts"):
        yield from ((section, name, spec) for name, spec in reg[section].items())
    for group in ("team_tools", "team_tool_args"):
        for tool, args in reg[group].items():
            yield from ((f"{group}.{tool}", name, spec) for name, spec in args.items())


@pytest.mark.parametrize("path", sorted(SAMPLE_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_btc_samples_comply(path):
    assert keys.check_scenario(json.loads(path.read_text(encoding="utf-8"))) == []


def test_every_planned_scenario_complies(all_scenarios):
    errors = [e for s in all_scenarios for e in keys.check_scenario(s.btc_export())]
    assert errors == []


def test_entries_are_documented_and_named_by_the_rules():
    for section, name, spec in entries():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), f"{section}.{name}: not snake_case"
        assert spec.get("origin") in ORIGINS, f"{section}.{name}: origin"
        keys.is_type("x", spec["type"])   # raises on a type the checker does not know
        for suffix, allowed in SUFFIX_TYPES:
            if re.search(suffix, name):
                assert spec["type"] in allowed, f"{section}.{name}: {spec['type']} breaks rules.naming"
        if spec["origin"] == "team":
            assert spec.get("description"), f"{section}.{name}: a team key needs a description"


def test_slot_vocabulary_is_the_registrys():
    assert set(SLOTS) == set(keys.registry()["slots"])


def test_an_unregistered_key_is_refused(tmp_path, all_scenarios):
    scenario = all_scenarios[0].model_copy(deep=True)
    call = next(iter(scenario.calls.values()))
    call.ground_truth_facts = {**call.ground_truth_facts, "gia_ban": 1}
    call.facts_established = {**call.facts_established, "room_area_m2": "25m2"}
    errors = keys.check_scenario(scenario.btc_export())
    assert any("ground_truth_facts.gia_ban: not in" in e for e in errors)
    assert any("room_area_m2: '25m2' is not int" in e for e in errors)
    with pytest.raises(ValueError, match="scenario-keys.yaml"):
        Dataset(tmp_path).write_scenario(scenario)


def test_patterns_check_the_code():
    assert keys.ground_truth_spec("promo_GIFT-FILTER_active")["type"] == "bool"
    assert keys.ground_truth_spec("promo_KHONG-CO_active") is None
    assert keys.ground_truth_spec("price_vnd:SKU-AP-X")["type"] == "int"
