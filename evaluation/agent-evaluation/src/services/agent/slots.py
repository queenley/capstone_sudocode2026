"""The extractor's vocabulary: the one the agent's own grading path uses, not a second one.

BTC supplies no extractor (``trace_log.schema.json``: extracting ``questions[]`` and ``claims[]`` is the team's job,
described in its report; BTC hand-checks 20 turns for an extractor that cheats). What BTC does fix is the names its
scenarios use. The organisers' command (``run_eval.py --scenarios``) runs ``components/evaluation/scorers.py``, whose
vocabularies are "fixed, never read from a scenario" so the extractor cannot learn the answer key:

- question slots: the memory ontology's slots (``SLOTS``) plus :data:`EXTRA_SLOTS`, a superset of every
  ``must_not_ask`` / ``must_carry_over`` / ``facts_established`` name in BTC's public samples
  (``test_slot_vocabulary`` keeps it so);
- claim fields: ``CLAIM_FIELDS``, the keys of BTC's ``ground_truth_facts``, with each value's type, plus
  ``promo_<CODE>_active``.

The analysis harness's extractor must label exactly like that instrument, so this module takes its vocabularies,
type coercion and grounding rules from it instead of keeping its own. :func:`restrict` applies them to the
harness's items (which carry quotes and spans, unlike the instrument's labels).
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import launch

launch.prepare()

from ai_agent_service.components.evaluation import scorers  # noqa: E402

OTHER = scorers.OTHER

#: Slots BTC's scenarios use that the agent's memory ontology does not keep: ``channel`` is in BTC's
#: ``facts_established`` (SAMPLE-04) and in the handoff brief. Only the extractor knows them, so the product's
#: ontology and memory stay as they are.
EXTRA_SLOTS: frozenset[str] = frozenset({"channel"})


def vocabulary() -> frozenset[str]:
    """Every name a question or fact use may be filed under; ``config/prompts/evaluation/extractor.txt`` lists the same."""
    return frozenset(scorers.SLOTS) | EXTRA_SLOTS


def restrict(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """*items* under the instrument's rules; how many were changed or set aside.

    Questions: a slot outside ``SLOTS`` is ``other``, and a question about nothing in ``SLOTS`` is never a confirm.
    Fact uses outside ``SLOTS`` are dropped. An observation repeated at the same span is kept once. Claims: the field must be in ``CLAIM_FIELDS`` (or a named promotion),
    the value is coerced to the field's type (else set aside), and the instrument's grounding rules apply.
    """
    allowed, kept, changed = vocabulary(), [], 0
    for item in items:
        kind, slot = item.get("kind"), item.get("slot_or_field")
        if kind == "question":
            if slot not in allowed and slot != OTHER:
                item, changed = {**item, "slot_or_field": OTHER}, changed + 1
            if item["slot_or_field"] == OTHER and item.get("question_type") != "open":
                item, changed = {**item, "question_type": "open"}, changed + 1
        elif kind == "fact_usage":
            if slot not in allowed:
                changed += 1
                continue
        elif kind == "claim":
            produced = _claim(item)
            changed += produced is None or produced != [item]
            if produced is None:
                continue
            kept.extend(produced)
            continue
        kept.append(item)
    unique, seen = [], set()
    for item in kept:
        # The same observation twice (a named promotion the model also wrote as promo_active, which the pipeline adds
        # itself) would count twice in the trace and the collector rejects duplicates, losing the whole turn.
        identity = json.dumps({k: item.get(k) for k in ("kind", "slot_or_field", "value", "question_type", "source_field", "start", "end")},
                              sort_keys=True, ensure_ascii=False)
        if identity in seen:
            changed += 1
            continue
        seen.add(identity)
        unique.append(item)
    return unique, changed


def _claim(item: dict[str, Any]) -> list[dict[str, Any]] | None:
    field, quote = item["slot_or_field"], item.get("quote") or ""
    named = bool(scorers.PROMO_FIELD.match(field))
    type_ = "bool" if named else scorers.CLAIM_FIELDS.get(field)
    if type_ is None:
        return None
    raw = item["value"] if isinstance(item["value"], str) else json.dumps(item["value"])
    ok, value = scorers.coerce(type_, raw)
    if not ok:
        return None
    if field == "is_human" and not (scorers.HUMAN.search(quote) if value else scorers.AUTOMATED.search(quote)):
        return None
    if field == "delivery_days" and "xóa" in quote.lower():
        return None
    if field == "price_vnd" and "phụ thu" in quote.lower() and not re.search(r"giá (?:bán|cuối|sau|là)|thanh toán", quote, re.IGNORECASE):
        return None
    claim = {**item, "value": value}
    return [claim, {**claim, "slot_or_field": "promo_active"}] if named else [claim]
