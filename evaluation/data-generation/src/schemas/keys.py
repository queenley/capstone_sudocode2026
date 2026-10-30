"""The scenario key registry, ``contracts/scenario/scenario-keys.yaml``: every key a scenario may carry.

:func:`check_scenario` lists what a scenario in BTC's file shape (``Scenario.btc_export``) has that the
registry does not allow: an unknown key, a wrong type, a value outside a closed list, an empty section.
:meth:`Dataset.write_scenario` refuses a scenario with any, so a new key is added to the registry first.

Tool names and their arguments come from BTC's ``schemas/tools.schema.json`` (plus the registry's
``team_tools`` and ``team_tool_args``), policy section ids from the ``## [XX-nn]`` headings of ``policy/``,
promotion codes from ``catalog/promotions.json``: the registry does not copy them.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from functools import lru_cache
from typing import Any

import yaml

from src.utils.paths import CATALOG_DIR, DATA_DIR, KEYS_FILE

#: Sections whose keys are themselves listed in the registry.
KEYED = ("scenario", "call", "expected_outcome", "slots", "memory_expectation", "success_if", "ground_truth_facts")
PATTERN = re.compile(r"^(?P<prefix>[^<]*)<(?P<code>[A-Z]+)>(?P<suffix>.*)$")


@lru_cache(maxsize=1)
def registry() -> dict[str, Any]:
    data = yaml.safe_load(KEYS_FILE.read_text(encoding="utf-8"))
    missing = [section for section in KEYED if section not in data]
    if missing:
        raise ValueError(f"{KEYS_FILE}: missing sections {missing}")
    return data


@lru_cache(maxsize=1)
def tool_args() -> dict[str, frozenset[str]]:
    """BTC's tools and the names of their arguments, with the team's optional ones."""
    schema = json.loads((DATA_DIR / "schemas" / "tools.schema.json").read_text(encoding="utf-8"))
    tools = {t["name"]: set(t.get("input") or {}) | {"on"} for t in schema["tools"] if " " not in t["name"]}
    for name, args in (registry().get("team_tools") or {}).items():
        tools[name] = set(args)
    for name, extra in (registry().get("team_tool_args") or {}).items():
        tools.setdefault(name, {"on"}).update(extra)
    return {name: frozenset(args) for name, args in tools.items()}


@lru_cache(maxsize=1)
def promo_codes() -> frozenset[str]:
    promos = json.loads((CATALOG_DIR / "promotions.json").read_text(encoding="utf-8"))
    return frozenset(p["promo_code"] for p in (promos["promotions"] if isinstance(promos, dict) else promos))


@lru_cache(maxsize=1)
def policy_sections() -> frozenset[str]:
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted((DATA_DIR / "policy").glob("*.md")))
    return frozenset(re.findall(r"^## \[([A-Z0-9-]+)\]", text, re.M))


def is_type(value: Any, kind: str) -> bool:
    if "|" in kind:
        return any(is_type(value, k) for k in kind.split("|"))
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "str":
        return isinstance(value, str)
    if kind == "sku":
        return isinstance(value, str) and value.startswith("SKU-")
    if kind == "list":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    if kind in ("date", "datetime"):
        if not isinstance(value, str):
            return False
        try:
            (date if kind == "date" else datetime).fromisoformat(value)
        except ValueError:
            return False
        return kind == "datetime" or len(value) == 10
    raise ValueError(f"unknown type {kind!r} in {KEYS_FILE.name}")


def ground_truth_spec(key: str) -> dict[str, Any] | None:
    """The registry entry of a ground truth key, directly or through a pattern (``promo_<CODE>_active``)."""
    reg = registry()
    if key in reg["ground_truth_facts"]:
        return reg["ground_truth_facts"][key]
    for pattern, spec in (reg.get("ground_truth_patterns") or {}).items():
        parts = PATTERN.match(pattern)
        prefix, suffix = parts["prefix"], parts["suffix"]
        if key.startswith(prefix) and key.endswith(suffix) and len(key) > len(prefix) + len(suffix):
            code = key[len(prefix):len(key) - len(suffix) if suffix else None]
            if spec.get("code") == "promotions" and code not in promo_codes():
                return None
            if spec.get("code") == "sku" and not code.startswith("SKU-"):
                return None
            return spec
    return None


def _value(where: str, value: Any, spec: dict[str, Any], errors: list[str]) -> None:
    if value is None:
        if not spec.get("nullable"):
            errors.append(f"{where}: null is not allowed")
        return
    if not is_type(value, spec["type"]):
        errors.append(f"{where}: {value!r} is not {spec['type']}")
    allowed = spec.get("values")
    if isinstance(allowed, list) and value not in allowed:
        errors.append(f"{where}: {value!r} is not one of {allowed}")


def _section(where: str, payload: dict[str, Any], specs: dict[str, Any], errors: list[str]) -> None:
    for key, value in payload.items():
        spec = specs.get(key)
        if spec is None:
            errors.append(f"{where}.{key}: not in {KEYS_FILE.name}")
        else:
            _value(f"{where}.{key}", value, spec, errors)


def _success_if(where: str, si: dict[str, Any], errors: list[str]) -> None:
    reg, tools = registry(), tool_args()
    _section(where, {k: v for k, v in si.items() if k not in ("tool_called", "args_match")}, reg["success_if"], errors)
    tool = si.get("tool_called")
    if tool is not None and tool not in tools:
        errors.append(f"{where}.tool_called: {tool!r} is not a tool of tools.schema.json")
    for name in si.get("must_not_call_tools") or []:
        if name not in tools:
            errors.append(f"{where}.must_not_call_tools: {name!r} is not a tool of tools.schema.json")
    for sku in si.get("also_ordered") or []:
        if not is_type(sku, "sku"):
            errors.append(f"{where}.also_ordered: {sku!r} is not a sku")
    args = si.get("args_match") or {}
    if args and tool is None:
        errors.append(f"{where}.args_match: given without tool_called")
    for arg in args if tool in tools else ():
        if arg not in tools[tool]:
            errors.append(f"{where}.args_match.{arg}: not an argument of {tool}")
    for claim in si.get("forbidden_claims") or []:
        if isinstance(claim, dict) and ground_truth_spec(str(claim.get("field"))) is None:
            errors.append(f"{where}.forbidden_claims: field {claim.get('field')!r} is not a ground_truth_facts key")


def check_scenario(payload: dict[str, Any]) -> list[str]:
    """What *payload* (BTC's file shape) has that the registry does not allow; empty when it complies."""
    reg = registry()
    sid = payload.get("scenario_id", "?")
    errors: list[str] = []
    _section(sid, {k: v for k, v in payload.items() if k != "calls"}, reg["scenario"], errors)
    slots = reg["slots"]
    for name, call in (payload.get("calls") or {}).items():
        where = f"{sid}.{name}"
        for key, value in call.items():
            spec = reg["call"].get(key)
            if spec is None:
                errors.append(f"{where}.{key}: not in {KEYS_FILE.name}")
                continue
            if value in ({}, []) and key not in ("customer_turns",):
                errors.append(f"{where}.{key}: empty; leave it out")
                continue
            if key == "expected_outcome":
                if value not in reg["expected_outcome"]:
                    errors.append(f"{where}.expected_outcome: {value!r} is not one of {list(reg['expected_outcome'])}")
            elif key not in ("facts_established", "memory_expectation", "success_if", "ground_truth_facts"):
                _value(f"{where}.{key}", value, spec, errors)
        _section(f"{where}.facts_established", call.get("facts_established") or {}, slots, errors)
        _section(f"{where}.memory_expectation", call.get("memory_expectation") or {},
                 {**slots, **reg["memory_expectation"]}, errors)
        for sid in call.get("relevant_policy_ids") or []:
            if sid not in policy_sections():
                errors.append(f"{where}.relevant_policy_ids: {sid!r} is not a section of policy/")
        for key in ("must_carry_over", "must_not_ask"):
            for slot in call.get(key) or []:
                if slot not in slots:
                    errors.append(f"{where}.{key}: {slot!r} is not a slot")
        _success_if(f"{where}.success_if", call.get("success_if") or {}, errors)
        for key, value in (call.get("ground_truth_facts") or {}).items():
            spec = ground_truth_spec(key)
            if spec is None:
                errors.append(f"{where}.ground_truth_facts.{key}: not in {KEYS_FILE.name}")
            else:
                _value(f"{where}.ground_truth_facts.{key}", value, spec, errors)
    return errors
