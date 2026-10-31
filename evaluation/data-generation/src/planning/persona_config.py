"""Which personas a run plans, and how each one talks.

Two sets, planned the same way:

* ``btc``: BTC's personas. Targets and level in ``config/personas.yaml``;
  behaviour (style, patience, simulator prompt) in ``data/simulator/personas.json``.
  Scenario ids ``SCN-GEN-xxxx``.
* ``advanced``: the team's personas, everything in ``config/personas_advanced.yaml``.
  Scenario ids ``SCN-ADV-xxxx``.

Every stage that needs a persona's style or patience reads :func:`load_profiles`,
so a persona is described once, whichever set it belongs to.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import yaml

from src.utils.paths import CONFIG_DIR, PERSONAS_JSON

PersonaSource = Literal["btc", "advanced"]
SOURCES: tuple[PersonaSource, ...] = ("btc", "advanced")
BTC_PREFIX = "SCN-GEN"


@dataclass(frozen=True)
class PersonaSet:
    source: PersonaSource
    #: Scenario ids are ``<id_prefix>-0001``, ``-0002``, ...
    id_prefix: str
    #: ``[{"id", "level", "target"}]`` in the order the planner cycles through them.
    targets: list[dict[str, Any]]


def _yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))


def load_persona_set(source: PersonaSource) -> PersonaSet:
    if source == "btc":
        return PersonaSet("btc", BTC_PREFIX, _yaml("personas.yaml")["personas"])
    config = _yaml("personas_advanced.yaml")
    targets = [{"id": p["id"], "level": p.get("level", "M2"), "target": p["target"]} for p in config["personas"]]
    return PersonaSet("advanced", config["id_prefix"], targets)


def load_persona_sets(which: str = "all") -> list[PersonaSet]:
    """``btc``, ``advanced`` or ``all`` (both, BTC's first)."""
    if which not in (*SOURCES, "all"):
        raise ValueError(f"--personas must be btc, advanced or all, not {which!r}")
    return [load_persona_set(s) for s in SOURCES if which in (s, "all")]


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, dict[str, Any]]:
    """persona id -> ``{persona_id, source, level, style, patience_initial, system_prompt}`` for both sets."""
    levels = {p["id"]: p.get("level", "M2") for p in _yaml("personas.yaml")["personas"]}
    profiles = {p["persona_id"]: {**p, "source": "btc", "level": levels.get(p["persona_id"], "M2")}
                for p in json.loads(PERSONAS_JSON.read_text(encoding="utf-8"))["personas"]}
    for p in _yaml("personas_advanced.yaml")["personas"]:
        profiles[p["id"]] = {"persona_id": p["id"], "source": "advanced", "level": p.get("level", "M2"),
                             "style": p["style"], "patience_initial": p["patience_initial"],
                             "system_prompt": p["system_prompt"]}
    return profiles
