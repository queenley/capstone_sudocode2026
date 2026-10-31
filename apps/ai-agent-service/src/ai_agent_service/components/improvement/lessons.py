"""Reflection, first half: what one failed call teaches, and whether it may teach anything. ``docs/design.md`` 10.3.

A **hint** is what the QaAgent proposes for one failure: when it applies,
what to do, what not to, a sample line, and the existing rules it applies
(PB, FAQ, KM codes). Reflection reinforces how a rule is applied; it never
writes a new one.

A **card** is one failure and the best hint the exploration found for it
(``pipeline/improve``), with what that hint did when the call was played
again under it. **A card is one vote, not a rule**: what fixed one call may
be true only for that customer. A playbook entry needs the same failure,
fixed, with at least :data:`MIN_SUPPORT` different customers
(:func:`support`), and a card counts only when it is verified: the grader
found the failure gone and nothing new wrong. A call "won" by a violation
therefore never counts as a win, because the violation is something new.

:func:`screen` is the deterministic half of the guard against learning that
over-promising closes sales: a hint that names an amount, a promotion code,
a discount, a gift, free shipping, stock or a guarantee is flagged, and a
flagged hint is never published, however it was reviewed. The PolicyAgent
checks the rest; neither deletes what it flags.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from ...config.config_manager import btc_data_dir
from ..intake.text import plain
from ..knowledge.corpus import policy_chunks
from .signals import Failure, home

#: Different customers whose call the same failure was fixed in, before an entry is proposed (section 10.3).
MIN_SUPPORT = 3

Scope = Literal["general", "customer"]


@dataclass(frozen=True)
class Hint:
    """A candidate for the advisor's context, in the advisor's language (Vietnamese)."""

    #: When it applies, in what the customer says or what the agent is about to do.
    trigger: str
    do: str
    dont: str
    sample_line: str
    #: Existing rules it applies: PB-09, FAQ-03, KM-02.
    cites: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "cites": list(self.cites)}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Hint":
        return cls(trigger=str(data["trigger"]), do=str(data["do"]), dont=str(data.get("dont") or ""),
                   sample_line=str(data.get("sample_line") or ""), cites=tuple(data.get("cites") or ()))

    def key(self) -> str:
        """The same hint, however it was spaced or capitalised."""
        return " | ".join(plain(part) for part in (self.trigger, self.do, self.dont, self.sample_line))


@dataclass(frozen=True)
class Card:
    """One failure, the hint the exploration settled on, and what the hint did."""

    failure: Failure
    hint: Hint
    #: The failure gone, the call no worse, nothing new wrong (``pipeline/improve``).
    verified: bool
    #: Failure codes of the call played without a hint, and under this one.
    control: tuple[str, ...]
    branch: tuple[str, ...]
    round: str
    scope: Scope = "general"
    #: Why the hint may not be published: :func:`screen`, then the PolicyAgent.
    flags: tuple[str, ...] = ()
    author: str = "qa"
    tried: int = 0

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(failure=self.failure.to_json(), hint=self.hint.to_json(), control=list(self.control),
                    branch=list(self.branch), flags=list(self.flags))
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Card":
        return cls(failure=Failure.from_json(data["failure"]), hint=Hint.from_json(data["hint"]),
                   verified=bool(data["verified"]), control=tuple(data.get("control") or ()),
                   branch=tuple(data.get("branch") or ()), round=str(data["round"]), scope=data.get("scope") or "general",
                   flags=tuple(data.get("flags") or ()), author=str(data.get("author") or "qa"),
                   tried=int(data.get("tried") or 0))

    @property
    def counts(self) -> bool:
        """Whether this card is a vote for its hint: verified, general, unflagged."""
        return self.verified and self.scope == "general" and not self.flags


# ── the deterministic screen ──────────────────────────────────────────────

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


def screen(hint: Hint, *, rules: Iterable[str] | None = None, promos: Iterable[str] | None = None) -> tuple[str, ...]:
    """Why *hint* may not be published; empty when the screen finds nothing.

    The ``dont`` field is not screened for promises: "không tự giảm giá" is
    exactly what a hint against over-promising says.
    """
    known = frozenset(rules) if rules is not None else rule_codes()
    codes = frozenset(promos) if promos is not None else promo_codes()
    said = " ".join((hint.trigger, hint.do, hint.sample_line))
    flags: list[str] = []
    if MONEY.search(said) or MONEY.search(hint.dont):
        flags.append("money")
    if PROMISES.search(plain(said)):
        flags.append("promise")
    if any(code in f"{said} {hint.dont}" for code in codes):
        flags.append("promo_code")
    if not hint.cites:
        flags.append("uncited")
    flags += [f"unknown_rule:{code}" for code in hint.cites if code not in known]
    if not hint.trigger.strip() or not hint.do.strip():
        flags.append("incomplete")
    return tuple(flags)


# ── the cards of a round ──────────────────────────────────────────────────


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


def add(card: Card) -> None:
    """File *card* in its round; a card is one line, never rewritten."""
    write_jsonl(round_dir(card.round) / "cards.jsonl", [card.to_json()], append=True)


def cards(round_name: str) -> list[Card]:
    return [Card.from_json(row) for row in read_jsonl(round_dir(round_name) / "cards.jsonl")]


def support(pool: Sequence[Card], code: str) -> list[Card]:
    """The cards that vote for fixing *code*: one per customer, verified, general, unflagged."""
    chosen: dict[str, Card] = {}
    for card in pool:
        if card.failure.code == code and card.counts:
            chosen.setdefault(card.failure.customer, card)
    return list(chosen.values())


def ready(pool: Sequence[Card]) -> list[str]:
    """The failure codes with enough support for an entry, the best supported first."""
    codes = sorted({card.failure.code for card in pool})
    counted = [(len(support(pool, code)), code) for code in codes]
    return [code for count, code in sorted(counted, key=lambda item: (-item[0], item[1])) if count >= MIN_SUPPORT]
