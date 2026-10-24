"""The extractor's vocabulary: the one the agent's own grading path uses, not a second one.

BTC supplies no extractor (``trace_log.schema.json``: extracting ``questions[]`` and ``claims[]`` is the team's job,
described in its report; BTC hand-checks 20 turns for an extractor that cheats). What BTC does fix is the names its
scenarios use. The organisers' command (``run_eval.py --scenarios``) runs ``components/evaluation/scorers.py``, whose
vocabularies are "fixed, never read from a scenario" so the extractor cannot learn the answer key:

- question slots: the memory ontology's slots (``SLOTS``), a superset of every ``must_not_ask`` /
  ``must_carry_over`` name in BTC's public samples (``test_slot_vocabulary`` keeps it so);
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


def vocabulary() -> frozenset[str]:
    return frozenset(scorers.SLOTS)


def prompt_block() -> str:
    """The sentence block ``extractor-prompt.txt`` carries; a test keeps the file equal to this."""
    slots = "\n".join(f"- {name}: {label}" for name, label in scorers.SLOT_LABELS.items())
    return (
        "SLOT VOCABULARY. For kind=question and kind=fact_usage, slot_or_field must be exactly one of these names, "
        "or \"other\" for a question about none of them:\n"
        f"{slots}\n"
        "A question is a question the agent asks the customer; its slot is the name it asks about. question_type "
        "is \"confirm\" only when the agent states the value itself and asks the customer to confirm it "
        "(\"vẫn là phòng 25 m² đúng không ạ?\"); otherwise \"open\". An offer, a request for permission or a "
        "closing question (\"có muốn em ... không\", \"cần hỗ trợ gì thêm\") has slot \"other\" and question_type "
        "\"open\". A fact_usage is the agent reusing one of these values in its reply or a tool argument; if the item "
        "concerns anything else, do not emit it.\n"
        "CLAIM FIELDS. For kind=claim, slot_or_field is one of: "
        f"{', '.join(scorers.CLAIM_FIELDS)}, or promo_<CODE>_active for a named promotion code. Skip a claim no "
        "field fits. value is an integer for money, days and months, true or false for yes/no facts, "
        "\"YYYY-MM-DD\" for dates. A value named only to say it is outdated or wrong is not a claim of that value."
    )


def restrict(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """*items* under the instrument's rules; how many were changed or set aside.

    Questions: a slot outside ``SLOTS`` is ``other``, and a question about nothing in ``SLOTS`` is never a confirm.
    Fact uses outside ``SLOTS`` are dropped. Claims: the field must be in ``CLAIM_FIELDS`` (or a named promotion),
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
    return kept, changed


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
