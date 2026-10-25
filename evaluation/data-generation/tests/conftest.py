import json

import pytest
import yaml

from src.planning.planner import assemble, plan_scenarios
from src.utils.crm import SourceData
from src.utils.paths import CONFIG_DIR, PERSONAS_JSON

N_SCENARIOS = 60


@pytest.fixture(scope="session")
def plans():
    targets = yaml.safe_load((CONFIG_DIR / "personas.yaml").read_text(encoding="utf-8"))["personas"]
    personas = {p["persona_id"]: p for p in json.loads(PERSONAS_JSON.read_text(encoding="utf-8"))["personas"]}
    return plan_scenarios(N_SCENARIOS, SourceData.load(), targets, personas, seed=20261007)


@pytest.fixture(scope="session")
def scenarios(plans):
    return [assemble(sp, None) for sp in plans]


@pytest.fixture(scope="session")
def by_hard_case(scenarios):
    out = {}
    for s in scenarios:
        out.setdefault(s.hard_case, s)
    return out
