"""PolicyAgent: the soft guardrail, on OpenAI's Decisions API. ``docs/design.md`` sections 4.5 and 12.

Runs after the hard check passes and catches what a regular expression
cannot: a promise outside policy, a rule no longer in force, a remark on a
competitor's price, pressure the stock does not justify.

It reads :class:`PolicyInput` and nothing else: **no brief and no
messages**, on purpose (section 12). The advisor has the old brief, the
customer's pleading and the new price all in view, which is what makes it
soften; this agent sees only the draft, the tool results and the policy, so
an old price standing next to a new one is plain.

The model is ``evaluators.policy`` in ``config/models.yaml``: one request, one
predicate per question, each answered independently with a probability. A
draft is blocked when any probability passes its threshold. **The thresholds
were set on another model (Jev) and have not been set again on this one**: they
are provisional until labelled examples from this application set them, as the
Decisions guide asks.

When the API gives no answer in time (no key, throttled, timed out) the draft
passes on the hard check alone and the verdict says so: a late answer costs
the customer more than a skipped soft check, and the hard check has already
held the numbers to the tools.

It also reads **what the customer means** where an action depends on it
(:meth:`PolicyAgent.judge`, :data:`INTENTS`): whether a transfer to a person
is warranted, whether the customer agreed to a deletion, wants one more
order, or confirmed who they are. Those were word lists matched against the
customer's message, which read "cho chị nói chuyện với người hiểu chuyện
này" as no request for a person and "đang cho con bú, muốn mua máy hút sữa"
as a medical question (2026-11-01). The model is asked only when the action is
about to happen, so an ordinary turn costs nothing more.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, Mapping

from ..components.intake.itn import format_vnd
from ..components.intake.text import plain
from ..config.config_manager import load_prompt
from ..llm import decisions
from ..llm.decisions import DecisionUnavailable, Predicate
from .base import BaseAgent

logger = logging.getLogger(__name__)

#: A review runs beside the stream and holds nothing back, so it can wait longer than a check that delays a reply.
REVIEW_TIMEOUT = 5.0
#: A change to a skill is checked off the hot path, a few times a round: it waits as long as the API needs and asks
#: once more before it says the check did not run (2026-11-12: at 5 s it gave no answer and the round stopped there).
CHANGE_TIMEOUT = 45.0

#: What is a violation and what is not, and what the customer means: the developer message of every request.
RULES = load_prompt("policy_rules.md")
RULES_SHA = hashlib.sha256(RULES.encode("utf-8")).hexdigest()


def _ask(instructions: str) -> Predicate:
    return Predicate(instructions=instructions, rules_sha=RULES_SHA)


#: One short sentence each: the rule that decides is in :data:`RULES`.
QUESTIONS = {
    "over_promise": _ask("Câu đang xét có vi phạm luật over_promise không?"),
    "stale_policy": _ask("Câu đang xét có vi phạm luật stale_policy không?"),
    "competitor": _ask("Câu đang xét có vi phạm luật competitor không?"),
    "unsupported_absence": _ask("Câu đang xét có vi phạm luật unsupported_absence không?"),
    "false_pressure": _ask("Câu đang xét có vi phạm luật false_pressure không?"),
    "unsupported_fact": _ask("Câu đang xét có vi phạm luật unsupported_fact không?"),
    "false_transfer": _ask("Câu đang xét có vi phạm luật false_transfer không?"),
    "unbacked_action": _ask("Câu đang xét có vi phạm luật unbacked_action không?"),
    "claims_human": _ask("Câu đang xét có vi phạm luật claims_human không?"),
    "unquoted_price": _ask("Câu đang xét có vi phạm luật unquoted_price không?"),
}

#: ``unsupported_fact`` and ``false_transfer``: set 2026-11-07 on 36 written cases and five real scenarios, where a
#: wrong correction heard by the customer cost more than a missed one.
#: Per question, from the lab's leave-one-out choice. ``unsupported_absence`` came later and is set
#: on four hand-written cases only (2026-10-31: 0.87 for a claim with no search, 0.93 against a search
#: that found the product, 0.50 after one that found nothing): set it again on the team's labelled set.
#: ``unquoted_price`` (2026-11-01) starts at 0.8, between the lab's true cases (from 0.92) and its
#: false alarms (under 0.66); it replaced a word list that blocked correct sentences (SAMPLE-05).
THRESHOLDS = {"over_promise": 0.8, "stale_policy": 0.9, "competitor": 0.9, "unsupported_absence": 0.8,
              "false_pressure": 0.9, "unquoted_price": 0.8, "unsupported_fact": 0.9, "false_transfer": 0.65, "unbacked_action": 0.8,
              "claims_human": 0.8}

REASONS = {
    "over_promise": "Hứa điều chính sách và kết quả tool không xác nhận.",
    "stale_policy": "Nói theo giá, khuyến mãi hoặc chính sách đã hết hiệu lực.",
    "competitor": "Bình luận giá hoặc sản phẩm của cửa hàng khác.",
    "unsupported_absence": "Nói shop không có, không còn bán hoặc không có thông tin về sản phẩm mà tool chưa cho thấy vậy; "
                           "tra catalog_search trước.",
    "false_pressure": "Tạo áp lực khan hiếm hoặc gấp mà tool không xác nhận.",
    "unsupported_fact": "Khẳng định tồn kho, trạng thái đơn, đơn đã tạo hay đã đổi, thời gian giao, thời hạn, hoặc đã xóa "
                        "dữ liệu mà kết quả tool và tài liệu không xác nhận; gọi tool trước khi nói.",
    "false_transfer": "Nói đang chuyển máy cho nhân viên mà chưa gọi handoff_transfer; gọi handoff_transfer trước rồi mới báo khách.",
    "unbacked_action": "Nói đã làm hoặc sẽ làm một việc mà chưa gọi tool của việc đó; gọi tool ngay trong lượt, không gọi được thì nói rõ chưa làm.",
    "claims_human": "Không được nhận hay ám chỉ là người thật; nói rõ em là trợ lý ảo.",
    "unquoted_price": "Nói một số tiền như giá, mức giảm hoặc phí của shop mà kết quả tool không có (số khách nói "
                      "chỉ được nhắc như lời của khách); dùng đúng số đã có, chưa có thì gọi tool, không tự tính.",
}


#: Section 10.3: what a change to a skill may not teach. Its own definitions, read against the change, the rules it
#: cites and the skill it changes.
#: Read when first asked, off the hot path: a reply's review never needs them.
#: "contradicts" asked of each source apart: a writer told only that its change contradicts something cannot tell what
#: to fix (two rounds, 2026-11-10, refused the same lesson twice). One request still asks them all.
CHANGE_CHECKS = ("promise", "pressure", "contradicts_cited", "contradicts_fixed", "contradicts_skill", "invents",
                 "one_case")


def change_rule(name: str) -> str:
    """The text of one change check, as the PolicyAgent reads it: what a writer must fix when it fails."""
    for line in change_rules()[0].splitlines():
        if line.startswith(f"- {name}:"):
            return line[2:].strip()
    return CHANGE_REASONS.get(name, name)


@lru_cache(maxsize=1)
def change_rules() -> tuple[str, dict[str, Predicate]]:
    rules = load_prompt("policy_change_rules.md")
    sha = hashlib.sha256(rules.encode("utf-8")).hexdigest()
    return rules, {name: Predicate(instructions=f"Chỉ dẫn đang xét có vi phạm luật {name} không?", rules_sha=sha)
                   for name in CHANGE_CHECKS}

#: Provisional, not set on labelled changes yet: no round has produced any. Set it on the first rounds' reviewed changes.
CHANGE_THRESHOLD = 0.8
CHANGE_REASONS = {
    "promise": "Dạy trợ lý hứa, giảm giá, tặng hoặc cam kết điều chính sách được trích không cho phép.",
    "pressure": "Dạy trợ lý tạo áp lực hay khan hiếm để khách chốt.",
    "contradicts_cited": "Trái với chính sách được trích.",
    "contradicts_fixed": "Trái với một luật cố định của trợ lý.",
    "contradicts_skill": "Trái với một câu khác của skill.",
    "invents": "Đặt ra quy định mà chính sách được trích không có.",
    "one_case": "Chỉ đúng cho một khách, một sản phẩm hay một cuộc gọi.",
    "unavailable": "Kiểm tra chính sách không trả lời.",
}

#: Section 4.4: actions whose condition is what the customer means, read in context. Each is
#: asked alone, only when its action is about to run; the state is the last few messages,
#: tokenised (no raw personal data reaches the model).
INTENTS = {
    "handoff": _ask("Theo luật handoff, có nên chuyển cuộc này cho người ngay không?"),
    "delete": _ask("Theo luật delete, khách đã đồng ý xóa dữ liệu chưa?"),
    "one_more": _ask("Theo luật one_more, khách có muốn thêm một đơn của sản phẩm này không?"),
    "change": _ask("Theo luật change, khách đã yêu cầu hoặc đồng ý việc này chưa?"),
    "purchase": _ask("Theo luật purchase, khách đã đồng ý đặt đơn này chưa?"),
    "identity": _ask("Theo luật identity, khách có nói mình là người được nêu tên không?"),
}

#: Provisional, set on Jev (2026-11-01), the model before this one, with no labelled set yet: 0.5 where a wrong "no"
#: costs the customer a person or an order; higher where a wrong "yes" opens private data or deletes
#: it. The identity probe put "Ừ đúng rồi em" at 0.72 and "Đúng, chị đây" at 0.98, every refusal at
#: 0.06 or less (asked as a list of messages; asked as two fields it gave 0.38): hence 0.6.
#: Set again on the FIX scenarios and the team's labels. On the Decisions API a clear yes to a deletion read 0.63 and 0.87,
#: and a postponement 0.00 (2026-11-07), hence 0.6 for delete.
INTENT_THRESHOLDS = {"handoff": 0.5, "delete": 0.6, "one_more": 0.5, "change": 0.5, "identity": 0.6, "purchase": 0.7}


@dataclass(frozen=True)
class PolicyInput:
    """What the Policy may read (section 3.2)."""

    text: str
    tool_results: tuple[dict[str, Any], ...]
    tier: Literal["VERIFIED", "PROBABLE", "AMBIGUOUS", "UNKNOWN"]
    #: Policy passages the advisor read this turn.
    policy_snippets: tuple[str, ...] = ()
    #: What this call established before this turn: quotes, orders created. An old quote is not unquoted.
    earlier: Mapping[str, Any] = field(default_factory=dict)
    #: What the customer said in this call, the latest last: their own figure is not the shop's, and repeating
    #: their words is not a claim. Only their words: the advisor's would bring back what makes it soften (section 12).
    customer_said: tuple[str, ...] = ()
    #: The reply's amounts with no source, when the hard check already traced the others; None when it did not run.
    open_amounts: tuple[int, ...] | None = None


@dataclass(frozen=True)
class PolicyVerdict:
    passed: bool
    reasons: tuple[str, ...] = ()
    #: The questions behind *reasons*, in the same order.
    failed: tuple[str, ...] = ()
    #: "decisions", or "skipped:<code>" when the API gave no answer.
    decided_by: str = "decisions"
    probabilities: dict[str, float] = field(default_factory=dict)
    seconds: float = 0.0


def _plain(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False, default=str))


def review_input(view: PolicyInput) -> list[dict[str, Any]]:
    """A sentence against its evidence, and not the conversation, on purpose (section 12): the advisor has the old
    brief, the customer's pleading and the new price all in view, which is what makes it soften.

    Most of the evidence stays the same through a turn, so it ends a prefix; this turn's tool results grow, then the text.
    """
    settled = {
        "identity_tier": view.tier,
        "policy": list(view.policy_snippets) or ["(no policy passage was read this turn)"],
        "earlier_this_call": dict(view.earlier),
        "customer_said": view.customer_said,
        # The hard check traced the reply's other amounts to a source: only these are left to judge (unquoted_price).
        **({} if view.open_amounts is None else {"amounts_without_source": [format_vnd(a) for a in view.open_amounts]}),
    }
    # A refusal is evidence too: "chưa tạo đơn" is true when the tool said so.
    results = {"tool_results": [{"tool": r.get("name"), "ok": bool((r.get("result") or {}).get("ok")),
                                 "result": (r.get("result") or {}).get("data"), "error": (r.get("result") or {}).get("error")}
                                for r in view.tool_results]}
    return [
        decisions.rules_message(RULES),
        decisions.evidence_message(_plain(settled), note="Bằng chứng của lượt này.", reusable=True),
        decisions.evidence_message(_plain(results), note="Kết quả tool của lượt này đến giờ."),
        {"role": "user", "content": f"Câu đang xét:\n{view.text}"},
    ]


def intent_input(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What the customer means, in context: the facts about the action, then the conversation ending on the customer.

    The last message must be the customer's: with the facts last, a clear "lên đơn đi" read 0.00 and with them first
    0.98 (2026-11-07, real calls).
    """
    conversation = [{"role": "user" if m.get("speaker") == "customer" else "assistant", "content": str(m.get("text"))}
                    for m in state.get("recent_messages") or [] if m.get("text")]
    facts = {key: value for key, value in state.items() if key != "recent_messages"}
    about = [decisions.evidence_message(_plain(facts), note="Thông tin về việc sắp làm; hội thoại ở dưới.")] if facts else []
    return [decisions.rules_message(RULES), *about, *conversation]


class PolicyAgent(BaseAgent):
    """Reviews a draft against the shop's policy."""

    def __init__(self) -> None:
        super().__init__("policy")

    async def review(self, view: PolicyInput) -> PolicyVerdict:
        try:
            decision = await decisions.evaluate(self.name, review_input(view), QUESTIONS, timeout=REVIEW_TIMEOUT, wait=True)
        except DecisionUnavailable as unavailable:
            logger.info("Policy check skipped: %s", unavailable)
            return PolicyVerdict(True, decided_by=f"skipped:{unavailable.code}")
        probabilities = {name: float(answer.probability or 0.0) for name, answer in decision.answers.items()}
        failed = [name for name, p in probabilities.items() if p >= THRESHOLDS[name]]
        if view.open_amounts == () and "unquoted_price" in failed:  # every amount has a source: nothing to judge
            failed.remove("unquoted_price")
        logger.info("Review %s: %s (cached %d of %d tokens)", failed or "passed",
                    {k: round(v, 2) for k, v in probabilities.items() if v >= 0.3}, decision.cached_tokens, decision.input_tokens)
        return PolicyVerdict(
            passed=not failed,
            reasons=tuple(REASONS[name] for name in failed),
            failed=tuple(failed),
            probabilities=probabilities,
            seconds=round(decision.seconds, 3),
        )

    async def review_change(self, text: str, *, cited_rules: Mapping[str, str], skill_now: str,
                            fixed_rules: str = "") -> PolicyVerdict:
        """Check a change to a skill before a person sees it (section 10.3), against its own rules (:data:`CHANGE_RULES`).

        A reply's questions do not fit here: an instruction names tools and states no tool result, so it would read as
        an unbacked action. A failure flags the change, which is then never published; the person still sees it with
        the reason, because this agent can be wrong too. No answer flags it as well (``unavailable``): a check that
        did not run is not a check that passed.
        """
        evidence = {"change": text, "cited_rules": dict(cited_rules) or {"(none)": "no rule was cited"}, "skill_now": skill_now,
                    "fixed_rules": fixed_rules or "(not given)"}
        rules, questions = change_rules()
        messages = [decisions.rules_message(rules),
                    decisions.evidence_message(_plain(evidence), note="Chỉ dẫn đang xét và căn cứ của nó.")]
        decision, skipped = None, ""
        for attempt in (1, 2):
            try:
                decision = await decisions.evaluate(self.name, messages, questions, timeout=CHANGE_TIMEOUT, wait=True)
                break
            except DecisionUnavailable as unavailable:
                logger.info("Change check unavailable (attempt %d): %s", attempt, unavailable)
                skipped = unavailable.code
        if decision is None:
            return PolicyVerdict(False, reasons=("The policy check did not answer.",), failed=("unavailable",),
                                 decided_by=f"skipped:{skipped}")
        probabilities = {name: float(answer.probability or 0.0) for name, answer in decision.answers.items()}
        declined = [name for name, answer in decision.answers.items() if answer.probability is None]
        failed = [name for name, p in probabilities.items() if p >= CHANGE_THRESHOLD and name not in declined]
        failed += [f"{name}:declined" for name in declined]
        return PolicyVerdict(passed=not failed, reasons=tuple(CHANGE_REASONS.get(name.split(":")[0], name) for name in failed),
                             failed=tuple(failed), probabilities=probabilities, seconds=round(decision.seconds, 3))

    async def judge(self, intent: str, state: Mapping[str, Any]) -> bool | None:
        """What the customer means for one action (:data:`INTENTS`); None when the API gave no answer in time.

        The caller decides what None means: its word list as a fallback, or, for a transfer, letting
        the advisor's decision stand.
        """
        try:
            decision = await self.evaluate(intent_input(state), {intent: INTENTS[intent]})
        except DecisionUnavailable as unavailable:
            logger.info("Intent check %s skipped: %s", intent, unavailable)
            return None
        probability = decision.answers[intent].probability
        if probability is None:  # the model declined: the same as no answer
            logger.info("Intent check %s skipped: declined", intent)
            return None
        logger.info("Intent check %s: %.2f (threshold %.2f)", intent, probability, INTENT_THRESHOLDS[intent])
        return probability >= INTENT_THRESHOLDS[intent]
