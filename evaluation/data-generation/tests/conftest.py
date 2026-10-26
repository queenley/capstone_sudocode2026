import pytest

from src.planning.persona_config import load_persona_set, load_profiles
from src.planning.planner import assemble, plan_scenarios
from src.utils.crm import SourceData

N_SCENARIOS = 60
SEED = 20261007


def plan(source: str, n: int | None = None):
    persona_set = load_persona_set(source)
    count = n if n is not None else sum(x["target"] for x in persona_set.targets)
    return plan_scenarios(count, SourceData.load(), persona_set, load_profiles(), seed=SEED)


@pytest.fixture(scope="session")
def plans():
    return plan("btc", N_SCENARIOS)


@pytest.fixture(scope="session")
def scenarios(plans):
    return [assemble(sp, None) for sp in plans]


@pytest.fixture(scope="session")
def advanced_plans():
    return plan("advanced")


@pytest.fixture(scope="session")
def advanced_scenarios(advanced_plans):
    return [assemble(sp, None) for sp in advanced_plans]


@pytest.fixture(scope="session")
def all_scenarios(scenarios, advanced_scenarios):
    return scenarios + advanced_scenarios


@pytest.fixture(scope="session")
def by_hard_case(scenarios):
    out = {}
    for s in scenarios:
        out.setdefault(s.hard_case, s)
    return out
