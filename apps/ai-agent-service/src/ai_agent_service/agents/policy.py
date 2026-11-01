"""PolicyAgent: the soft guardrail, on Jev. ``docs/design.md`` sections 4.5 and 12.

Runs after the hard check passes and catches what a regular expression
cannot: a promise outside policy, a rule no longer in force, a remark on a
competitor's price, pressure the stock does not justify.

It reads :class:`PolicyInput` and nothing else: **no brief and no
messages**, on purpose (section 12). The advisor has the old brief, the
customer's pleading and the new price all in view, which is what makes it
soften; this agent sees only the draft, the tool results and the policy, so
an old price standing next to a new one is plain.

The model is Jev (``evaluators.policy`` in ``config/models.yaml``): one
request, one Boolean per question, each answered independently with a
probability. A draft is blocked when any probability passes its threshold;
the lab of 2026-09-23 found 0.9 right for policy questions (architecture
notes 8.5), to be set again on the team's own labelled set.

When Jev gives no answer in time (no key, throttled, timed out) the draft
passes on the hard check alone and the verdict says so: a late answer costs
the customer more than a skipped soft check, and the hard check has already
held the numbers to the tools.

It also reads **what the customer means** where an action depends on it
(:meth:`PolicyAgent.judge`, :data:`INTENTS`): whether a transfer to a person
is warranted, whether the customer agreed to a deletion, wants one more
order, or confirmed who they are. Those were word lists matched against the
customer's message, which read "cho chị nói chuyện với người hiểu chuyện
này" as no request for a person and "đang cho con bú, muốn mua máy hút sữa"
as a medical question (2026-11-01). Jev is asked only when the action is
about to happen, so an ordinary turn costs nothing more.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from ..components.intake.text import plain
from ..llm.jev import Boolean, JevUnavailable
from .base import BaseAgent

logger = logging.getLogger(__name__)

#: Section 4.5: what makes a sentence worth the soft check. Money, a
#: promotion, stock or scarcity, another shop, a promise. Matched on text
#: without diacritics, so "mien phi" and "miễn phí" are the same word. A
#: greeting or a clarifying question carries none and costs no Jev call.
RISK = re.compile(
    r"\d"
    r"|\b(trieu|nghin|ngan|dong|k)\b"
    r"|khuyen mai|\bkm\b|\bgiam\b|\btang\b|qua tang|freeship|mien phi|uu dai|voucher"
    r"|con hang|het hang|chi con|sap het|co han|duy nhat|cuoi cung"
    r"|ben kia|shop khac|cho khac|cua hang khac|doi thu|re hon|dat hon"
    r"|chac chan|cam ket|dam bao|\bhua\b|bao hanh|doi tra|hoan tien"
    r"|kinh doanh|ngung ban|ngung san xuat|khong ban|chua ban|thong tin ve"
)


def needs_review(text: str) -> bool:
    """Whether a sentence carries a risk signal and goes to the PolicyAgent."""
    return bool(RISK.search(plain(text)))

QUESTIONS = {
    "over_promise": Boolean(
        instructions=(
            "Does the reply promise something the shop policy and the tool results do not support, such as "
            "free shipping, easier returns, a delivery date, or a discount?"
        ),
    ),
    "stale_policy": Boolean(
        instructions="Does the reply state a rule, price or promotion that the tool results or the policy show has ended or changed?",
    ),
    "competitor": Boolean(
        instructions="Does the reply comment on, disparage or match another shop's price or product?",
    ),
    "unsupported_absence": Boolean(
        instructions=(
            "Does the reply say the shop does not sell a product, no longer sells it, does not have it, or has "
            "no information about it, when the tool results do not show that (no catalogue search, or a search "
            "that found it)?"
        ),
    ),
    "false_pressure": Boolean(
        instructions=(
            "Does the reply pressure the customer with scarcity or urgency (only a few left, price rising "
            "soon) that the tool results do not confirm?"
        ),
    ),
    "unquoted_price": Boolean(
        instructions=(
            "Does the reply state, as this shop's own current price, discount, fee or refund, an amount of "
            "money that is not in the tool results?"
        ),
        criteria={
            "true": "An amount given as what this shop charges, discounts or refunds now, and the tool results "
                    "do not contain it.",
            "false": "Every such amount is in the tool results, or the amount is clearly someone else's: the "
                     "customer's budget, another shop's price, a price the customer remembers, an offer said "
                     "to have ended.",
        },
    ),
}

#: Per question, from the lab's leave-one-out choice. ``unsupported_absence`` came later and is set
#: on four hand-written cases only (2026-10-31: 0.87 for a claim with no search, 0.93 against a search
#: that found the product, 0.50 after one that found nothing): set it again on the team's labelled set.
#: ``unquoted_price`` (2026-11-01) starts at 0.8, between the lab's true cases (from 0.92) and its
#: false alarms (under 0.66); it replaced a word list that blocked correct sentences (SAMPLE-05).
THRESHOLDS = {"over_promise": 0.9, "stale_policy": 0.9, "competitor": 0.9, "unsupported_absence": 0.8,
              "false_pressure": 0.9, "unquoted_price": 0.8}

REASONS = {
    "over_promise": "Hứa điều chính sách và kết quả tool không xác nhận.",
    "stale_policy": "Nói theo giá, khuyến mãi hoặc chính sách đã hết hiệu lực.",
    "competitor": "Bình luận giá hoặc sản phẩm của cửa hàng khác.",
    "unsupported_absence": "Nói shop không có, không còn bán hoặc không có thông tin về sản phẩm mà tool chưa cho thấy vậy; "
                           "tra catalog_search trước.",
    "false_pressure": "Tạo áp lực khan hiếm hoặc gấp mà tool không xác nhận.",
    "unquoted_price": "Nói một số tiền như giá, mức giảm hoặc phí của shop mà kết quả tool không có (số khách nói "
                      "chỉ được nhắc như lời của khách); gọi tool để lấy số đúng.",
}


#: Section 4.4: actions whose condition is what the customer means, read in context. Each is
#: asked alone, only when its action is about to run; the state is the last few messages,
#: tokenised (no raw personal data reaches Jev).
INTENTS = {
    "handoff": Boolean(
        instructions=(
            "Should this conversation be handed to a human colleague now? Read the customer's recent "
            "messages, the assistant's replies, the reason the assistant gives for the transfer and the "
            "shop documents it found."
        ),
        criteria={
            "true": "The customer asks to speak to a person; or asks for medical, medicine, pregnancy, "
                    "breastfeeding-safety, child-safety or legal advice; or makes a serious complaint; or asks "
                    "something the shop documents and the assistant's tools do not answer, so a person must answer it.",
            "false": "The customer asks about products, prices, stock, delivery, orders or policies that the "
                     "documents or tools answer, including a product for mothers or babies (a breast pump, a "
                     "bottle) when they ask for the product, its specifications or its price rather than for "
                     "health advice.",
        },
    ),
    "delete": Boolean(
        instructions=(
            "The assistant asked the customer to confirm that their personal data should be deleted. Has the "
            "customer clearly agreed?"
        ),
        criteria={
            "true": "The customer says yes to the deletion.",
            "false": "The customer declines, hesitates, postpones, asks something else, or was never asked.",
        },
    ),
    "one_more": Boolean(
        instructions=(
            "An order for this product was already created in this conversation. Does the customer want to "
            "buy it again as an additional order?"
        ),
        criteria={
            "true": "The customer asks for one more, another unit or a second order of it.",
            "false": "The customer adds or corrects details of the order already placed (address, payment, size, "
                     "colour, quantity of that same order) or only confirms it.",
        },
    ),
    "change": Boolean(
        instructions=(
            "The assistant is about to change an order the customer already has (the change is given). Has "
            "the customer asked for this change or agreed to it?"
        ),
        criteria={
            "true": "The customer asked for this change (\"đổi sang size L\", \"giao về quận 3\") or said yes "
                    "when the assistant proposed it.",
            "false": "The customer only described a problem (too tight, faulty, late) without choosing what to do, "
                     "is still asking about the options, or declined.",
        },
    ),
    "identity": Boolean(
        instructions=(
            "The assistant asked whether the customer is the person named, the one who contacted the shop "
            "before. Does the customer answer yes, that it is them?"
        ),
        criteria={
            "true": "The customer says yes, it is them.",
            "false": "The customer says no, says it is someone else or that they call for another person, or "
                     "does not answer.",
        },
    ),
}

#: Provisional (2026-11-01), from a first probe of Jev, no labelled set yet: 0.5 where a wrong "no"
#: costs the customer a person or an order; higher where a wrong "yes" opens private data or deletes
#: it. The identity probe put "Ừ đúng rồi em" at 0.72 and "Đúng, chị đây" at 0.98, every refusal at
#: 0.06 or less (asked as a list of messages; asked as two fields it gave 0.38): hence 0.6.
#: Set again on the FIX scenarios and the team's labels.
INTENT_THRESHOLDS = {"handoff": 0.5, "delete": 0.7, "one_more": 0.5, "change": 0.5, "identity": 0.6}


@dataclass(frozen=True)
class PolicyInput:
    """What the Policy may read (section 3.2)."""

    text: str
    tool_results: tuple[dict[str, Any], ...]
    tier: Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN"]
    #: Policy passages the advisor read this turn.
    policy_snippets: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyVerdict:
    passed: bool
    reasons: tuple[str, ...] = ()
    #: "jev", or "skipped:<code>" when Jev gave no answer.
    decided_by: str = "jev"
    probabilities: dict[str, float] = field(default_factory=dict)
    seconds: float = 0.0


class PolicyAgent(BaseAgent):
    """Reviews a draft against the shop's policy."""

    def __init__(self) -> None:
        super().__init__("policy")

    async def review(self, view: PolicyInput) -> PolicyVerdict:
        state = {
            "reply": view.text,
            "identity_tier": view.tier,
            "tool_results": [
                {"tool": r.get("name"), "result": (r.get("result") or {}).get("data")} for r in view.tool_results
            ],
            "policy": list(view.policy_snippets) or ["(no policy passage was read this turn)"],
        }
        try:
            decision = await self.evaluate(json.loads(json.dumps(state, ensure_ascii=False, default=str)), QUESTIONS)
        except JevUnavailable as unavailable:
            # The message, not only the code: the gateway's codes hide the cause
            # (``no_providers_available`` is its answer to a free-tier account).
            logger.info("Policy check skipped: %s", unavailable)
            return PolicyVerdict(True, decided_by=f"skipped:{unavailable.code}")
        probabilities = {name: float(answer.probability or 0.0) for name, answer in decision.answers.items()}
        failed = [name for name, p in probabilities.items() if p >= THRESHOLDS[name]]
        return PolicyVerdict(
            passed=not failed,
            reasons=tuple(REASONS[name] for name in failed),
            probabilities=probabilities,
            seconds=round(decision.seconds, 3),
        )

    async def review_change(self, text: str, *, kind: str, policy_snippets: tuple[str, ...] = ()) -> PolicyVerdict:
        """Check a lesson or a playbook entry before QA sees it (section 10.3).

        A failure is a tag, not a rejection: the change still reaches QA with
        the reason, because this agent can be wrong too.
        """
        return await self.review(PolicyInput(text=text, tool_results=(), tier="VERIFIED", policy_snippets=policy_snippets))

    async def judge(self, intent: str, state: Mapping[str, Any]) -> bool | None:
        """What the customer means for one action (:data:`INTENTS`); None when Jev gave no answer in time.

        The caller decides what None means: its word list as a fallback, or, for a transfer, letting
        the advisor's decision stand.
        """
        try:
            decision = await self.evaluate(json.loads(json.dumps(dict(state), ensure_ascii=False, default=str)),
                                           {intent: INTENTS[intent]})
        except JevUnavailable as unavailable:
            logger.info("Intent check %s skipped: %s", intent, unavailable)
            return None
        probability = float(decision.answers[intent].probability or 0.0)
        logger.info("Intent check %s: %.2f (threshold %.2f)", intent, probability, INTENT_THRESHOLDS[intent])
        return probability >= INTENT_THRESHOLDS[intent]
