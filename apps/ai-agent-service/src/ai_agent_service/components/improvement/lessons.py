"""What a Reflection round keeps: what counts as evidence, and what a change may never say. ``docs/design.md`` 10.3.

A failure in one call is one vote, not a rule: a change to a skill needs the same failure with at least
:data:`MIN_SUPPORT` different customers. A change that states an amount, a promotion, a promise or one case, or cites
no existing rule, is flagged, and a flagged change is never published, however it was reviewed.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from ...config.config_manager import btc_data_dir
from ..intake.text import plain
from ..knowledge.corpus import policy_chunks
from .signals import home

#: Different customers who share a failure, before a change to a skill is proposed.
MIN_SUPPORT = 3


#: What only one scenario or product has: a skill holds for any customer.
SPECIFIC = re.compile(r"\b(?:SCN|SKU)-\w+|\bOD\d+|\bkhach_\w+")
#: An amount: "4.890.000", "249k", "5 triệu", "200 nghìn", "10%".
MONEY = re.compile(r"\d[\d.,]*\s*(?:đ|₫|vnd|vnđ|k|nghìn|ngàn|triệu|tr|%)(?!\w)|\b\d{1,3}(?:[.,]\d{3})+\b|\b\d{4,}\b",
                   re.IGNORECASE)
#: Promises the tools must make, never a playbook, on the plain (unaccented) text.
PROMISES = re.compile(
    r"\b(giam gia|giam them|chiet khau|bot cho|tang kem|qua tang|tang (?:chi|anh|em|ban|them)|mien phi|freeship|free ship|"
    r"con hang|het hang|chac chan|cam ket|bao dam|dam bao|bao hanh tron doi|uu dai rieng)\b")


@lru_cache(maxsize=1)
def rule_codes() -> frozenset[str]:
    """The section codes of the organisers' policy corpus a hint may cite: internal notes are not rules."""
    return frozenset(chunk.chunk_id for chunk in policy_chunks(btc_data_dir() / "policy") if not chunk.restricted)


@lru_cache(maxsize=1)
def promo_codes() -> frozenset[str]:
    path = btc_data_dir() / "catalog" / "promotions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(str(p["promo_code"]) for p in data.get("promotions") or [] if p.get("promo_code"))


def screen_patch(text: str, cites: Iterable[str], *, rules: Iterable[str] | None = None,
                 promos: Iterable[str] | None = None) -> list[str]:
    """Why a change to a skill may not go to review as it is: it must cite a rule and promise nothing."""
    flags: list[str] = []
    if MONEY.search(text):
        flags.append("amount")
    if PROMISES.search(plain(text)):
        flags.append("promise")
    if any(code in text for code in (promos if promos is not None else promo_codes())):
        flags.append("promotion_code")
    if SPECIFIC.search(text):
        flags.append("specific")
    known = set(rules if rules is not None else rule_codes())
    cited = [code for code in cites if code]
    if not cited or not set(cited) <= known:
        flags.append("no_rule")
    return flags


def round_dir(name: str) -> Path:
    """``IMPROVEMENT_DIR/rounds/<name>``: one learning round's failures, explorations and cards."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError(f"Round name {name!r}: letters, digits, '.', '_' and '-' only")
    return home() / "rounds" / name


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]], *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
