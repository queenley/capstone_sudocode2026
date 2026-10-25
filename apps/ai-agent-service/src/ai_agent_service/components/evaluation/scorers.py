"""The extractor that labels the trace: questions and claims. ``docs/design.md`` section 9.4.

The official numbers are the organisers' ``eval/reference_eval.py`` on the
trace (section 0.4), so the grader computes the metrics itself; what it needs
from us is what it cannot read off a reply: which questions the agent asked,
about which slot, and which verifiable claims it made. :class:`Extractor` is
the design's ``question_classifier`` and ``claim_extractor`` in one model call
per agent turn. ``facts_used`` is not here: it is deterministic, the ``[Bn]``
chain of section 5.5 (``pipeline/eval/trace.py``).

Both vocabularies are fixed, never read from a scenario, so the extractor
cannot learn the answer key (the organisers hand-check 20 turns for exactly
that, ``README`` of their pack): questions are filed under the slots of
section 5.2 (``components.memory.ontology``), claims under
:data:`CLAIM_FIELDS`, the keys the organisers' scenario format uses in
``ground_truth_facts`` plus the few the case catalogue (section 14.6) adds. The grader
compares a claim's value with the truth exactly, type included (``5200000``
is not ``"5.200.000đ"``), so every value is coerced to its field's type in
code, and a claim whose value cannot be is set aside rather than written in a
shape that would count as false. A claim about a named promotion is written
in both forms the scenario format uses, ``promo_<CODE>_active`` and ``promo_active``
(section 9.4).

It is a measuring instrument: temperature 0, labels cached on disk and shared
between runs (Appendix D), so the same reply under the same prompt always
gets the same labels, and no improvement round ever changes it (section 10.1).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ...config.config_manager import load_prompt
from ...llm.structured import Report, StructuredOutput, StructuredOutputError
from ..memory.ontology import CORE, INDUSTRIES
from ..guardrails.hard import HUMAN

logger = logging.getLogger(__name__)
GROUNDING_VERSION = "claim-grounding-v1"
AUTOMATED = re.compile(r"\b(?:em|tôi|mình)\s+là\s+(?:một\s+)?(?:trợ lý (?:ảo|tự động)|(?:chat)?bot|AI)\b", re.IGNORECASE)

#: Section 5.2: what a question may be about, with the label the brief uses.
SLOT_LABELS: dict[str, str] = {name: spec.label for name, spec in sorted(
    {**CORE, **{n: s for block in INDUSTRIES.values() for n, s in block.items()}}.items())}
SLOTS: tuple[str, ...] = tuple(SLOT_LABELS)

#: A question about nothing the ledger keeps: an offer, a closing question, a pleasantry.
OTHER = "other"

FieldType = Literal["int", "bool", "date", "str"]

#: Section 9.4: claim fields, named as the keys of ``ground_truth_facts``, with
#: the type of the value there. The grader skips a field the call's truth lacks.
CLAIM_FIELDS: dict[str, FieldType] = {
    # The organisers' scenario format.
    "price_vnd": "int",
    "list_price_vnd": "int",
    "exchange_fee_vnd": "int",
    "delivery_days": "int",
    "return_days": "int",
    "warranty_months": "int",
    "in_stock": "bool",
    "new_size_in_stock": "bool",
    "promo_active": "bool",
    "freeship": "bool",
    "old_policy_superseded": "bool",
    "is_human": "bool",
    "restock_date": "date",
    "policy_version": "str",
    # The case catalogue (section 14.6): refunds, shipping fees, the COD limit, order totals.
    "refund_vnd": "int",
    "shipping_fee_vnd": "int",
    "cod_limit_vnd": "int",
    "total_vnd": "int",
}

#: ``promo_<CODE>_active``, as the scenario format names it: whether that code applies today.
PROMO_FIELD = re.compile(r"^promo_[A-Z0-9][A-Z0-9-]*_active$")

INSTRUCTIONS = load_prompt("turn_labeller.md")
#: Said after a truncated answer: a turn's labels are short, so a long answer repeats itself.
LENGTH_HINT = ("The previous output exceeded the token limit. Label each statement once; keep value_json to a "
               "single scalar JSON literal and quote only the relevant words. Do not repeat entries or add explanations.")


class Question(BaseModel):
    """One question the agent asks the customer in this reply."""

    slot: str = Field(description='A name from SLOTS, or "other".')
    type: Literal["open", "confirm"] = Field(
        description="confirm: the agent states a value and asks to confirm it; open: it asks for a value it does not state.")
    text: str = Field(description="The question exactly as written in the reply.")


class Claim(BaseModel):
    """One verifiable statement the agent asserts as true now."""

    field: str = Field(description="A name from FIELDS, or promo_<CODE>_active.")
    value_json: str = Field(description='The value as a JSON literal: 5200000, true, "2026-10-20", "2026-10".')
    text: str = Field(description="The words of the reply the claim comes from.")


class TurnLabels(BaseModel):
    """The labels of one agent reply: its questions and its claims."""

    questions: list[Question] = Field(
        default_factory=list, description="Every question the agent asks in the reply, in order; empty when none.")
    claims: list[Claim] = Field(
        default_factory=list, description="Every claim the agent makes in the reply; empty when none.")


def prompt() -> str:
    """The instructions with both vocabularies filled in."""
    return INSTRUCTIONS.format(
        slots="\n".join(f"- {name}: {label}" for name, label in SLOT_LABELS.items()),
        fields=", ".join(CLAIM_FIELDS),
    )


#: Everything the model is shown besides the turn. Part of every cache key, so
#: a change to the instructions, the vocabularies or the schema never reuses
#: labels made under the old ones.
PROMPT_SHA = hashlib.sha256(
    json.dumps([prompt(), TurnLabels.model_json_schema()], ensure_ascii=False, sort_keys=True).encode()
).hexdigest()


class Extractor:
    """``question_classifier`` and ``claim_extractor`` over one agent turn, cached on disk.

    The cache holds the model's raw labels, keyed by the prompt, the model
    and the turn. Coercion runs on every read, so a change to it needs no new
    labels.
    """

    def __init__(self, llm: BaseChatModel, *, model_name: str, cache_path: Path | None = None) -> None:
        # Two attempts: a truncated or invalid answer is asked again once, then the turn is left unlabelled.
        self._labeller = StructuredOutput(llm, TurnLabels, attempts=2, length_hint=LENGTH_HINT)
        self.model_name = model_name
        self._cache_path = cache_path
        self._cache = _load_cache(cache_path)
        self.hits = 0
        self.calls = 0
        self.failures = 0
        self.retries = 0
        self.repaired = 0

    async def label(self, *, customer_text: str, agent_text: str) -> dict[str, Any]:
        """``{"questions", "claims", "set_aside"}`` in the trace's shapes, plus ``error`` when the call failed.

        ``set_aside`` holds the claims whose value could not be coerced to
        their field's type: kept for whoever reads the run, out of the trace.
        """
        if not agent_text.strip():
            return {"questions": [], "claims": [], "set_aside": []}
        key = hashlib.sha256(
            json.dumps([PROMPT_SHA, self.model_name, customer_text, agent_text], ensure_ascii=False).encode()
        ).hexdigest()
        raw = self._cache.get(key)
        if raw is not None:
            self.hits += 1
            return shape(raw, agent_text=agent_text)
        request = f"{prompt()}\n\nCUSTOMER: {customer_text}\nAGENT: {agent_text}"
        try:
            labels, report = await self._labeller.arun(request)
        except StructuredOutputError as failed:  # failed attempts remain visible
            self._count(failed.report)
            logger.warning("Extractor failed: %s", type(failed.cause).__name__)
            return {"questions": [], "claims": [], "set_aside": [], "error": failed.report.errors[-1],
                    "attempt_errors": failed.report.errors}
        self._count(report)
        raw = labels.model_dump()
        if report.errors:
            raw["recovered_errors"] = report.errors
        self._cache[key] = raw
        self._save()
        return shape(raw, agent_text=agent_text)

    def _count(self, report: Report) -> None:
        self.calls += report.attempts
        self.failures += len(report.errors)
        self.retries += report.attempts - 1
        self.repaired += report.repaired

    def stats(self) -> dict[str, Any]:
        return {"calls": self.calls, "cache_hits": self.hits, "failures": self.failures,
                "retries": self.retries, "repaired": self.repaired, "extractor_version": "turn-labels-recovery-v2",
                "normalizer_version": GROUNDING_VERSION}

    def _save(self) -> None:
        """Write the whole cache to a temporary file and swap it in, so a run
        killed mid-write leaves the previous cache whole."""
        if self._cache_path is None:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._cache_path.with_name(self._cache_path.name + ".tmp")
        temporary.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, self._cache_path)


def _load_cache(path: Path | None) -> dict[str, dict[str, Any]]:
    """The cache, or an empty one; a file that does not parse is moved aside, not trusted."""
    if path is None or not path.exists():
        return {}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(cache, dict):
            return cache
    except ValueError:
        pass
    aside = path.with_name(path.name + ".corrupt")
    os.replace(path, aside)
    logger.warning("Extractor cache %s did not parse; moved to %s and starting empty", path, aside)
    return {}


def shape(raw: dict[str, Any], *, agent_text: str | None = None) -> dict[str, Any]:
    """The model's labels in the trace's shapes, every claim value coerced to its field's type."""
    questions = [
        {"slot": q["slot"] if q["slot"] in SLOT_LABELS else OTHER, "type": q["type"], "text": q["text"]}
        for q in raw.get("questions") or []
    ]
    claims: list[dict[str, Any]] = []
    set_aside: list[dict[str, Any]] = []
    for claim in raw.get("claims") or []:
        named = bool(PROMO_FIELD.match(claim["field"]))
        kind = "bool" if named else CLAIM_FIELDS.get(claim["field"])
        if kind is None:
            continue
        ok, value = coerce(kind, claim["value_json"])
        entry = {"field": claim["field"], "value": value, "text": claim["text"]}
        if not ok:
            set_aside.append(entry)
            continue
        quote = claim["text"]
        reason = None
        if agent_text is not None and (not quote or quote not in agent_text):
            reason = "quote_not_in_reply"
        elif claim["field"] == "is_human" and not (HUMAN.search(quote) if value else AUTOMATED.search(quote)):
            reason = "unsupported_human_claim"
        elif claim["field"] == "delivery_days" and "xóa" in quote.lower():
            reason = "deletion_is_not_delivery"
        elif (claim["field"] == "price_vnd" and "phụ thu" in quote.lower()
              and not re.search(r"giá (?:bán|cuối|sau|là)|thanh toán", quote, re.IGNORECASE)):
            reason = "surcharge_is_not_product_price"
        if reason:
            set_aside.append({**entry, "reason": reason})
            continue
        claims.append(entry)
        if named:
            claims.append({**entry, "field": "promo_active"})
    return {"questions": questions, "claims": _unique(claims), "set_aside": set_aside,
            **({"recovered_errors": raw["recovered_errors"]} if raw.get("recovered_errors") else {})}


def _unique(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One claim per field and value in a turn: two promotions both active say ``promo_active`` once."""
    seen: set[tuple[str, str]] = set()
    kept = []
    for claim in claims:
        key = (claim["field"], json.dumps(claim["value"], ensure_ascii=False))
        if key not in seen:
            seen.add(key)
            kept.append(claim)
    return kept


MONEY = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+|\d+")


def coerce(kind: str, raw: str) -> tuple[bool, Any]:
    """``(True, value)`` with *raw* as a value of *kind*, or ``(False, raw)`` when it is not one."""
    try:
        value: Any = json.loads(raw)
    except ValueError:
        value = raw.strip()
    if kind == "int":
        if isinstance(value, bool):
            return False, raw
        if isinstance(value, int):
            return True, value
        if isinstance(value, float) and value.is_integer():
            return True, int(value)
        if isinstance(value, str):
            text = value.strip().removesuffix("đ").removesuffix("VND").removesuffix("vnd").strip()
            if MONEY.fullmatch(text):
                return True, int(re.sub(r"[.,\s]", "", text))
        return False, raw
    if kind == "bool":
        if isinstance(value, bool):
            return True, value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return True, value.strip().lower() == "true"
        return False, raw
    if kind == "date":
        if isinstance(value, str):
            try:
                return True, date.fromisoformat(value.strip()).isoformat()
            except ValueError:
                pass
        return False, raw
    if isinstance(value, str):
        return True, value
    return False, raw
