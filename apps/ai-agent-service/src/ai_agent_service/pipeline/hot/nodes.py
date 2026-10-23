"""The hot graph's seven nodes. ``docs/design.md`` section 4.

Each node builds the input a component or an agent declares from
:class:`~.state.HotState`, calls it, and writes the result back into the
keys it owns. What a step *does* is documented where it is done, in the
module each docstring names. Collaborators arrive through
``runtime.context`` (:class:`~.state.HotContext`), never as module globals.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Mapping, Sequence

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.runtime import Runtime

from ...agents.advisor import AdvisorFailure, AgentContext, shown_passages, _seen_in
from ...agents.policy import PolicyInput, needs_review
from ...components.context import compact
from ...components.guardrails import fallback
from ...components.guardrails.hard import MAX_SENTENCES, ORDER_SUMMARY, GuardInput, check
from ...components.guardrails.stream import SentenceSplitter
from ...components.identity import resolver
from ...components.intake import itn, lexicon, pii, signals, text as intake_text
from ...components.memory import brief as briefs
from ...components.memory import recall
from ...components.memory.brief import BriefLine
from ...components.orchestration.rules import ORDER_TALK, RouteInput, decide
from ...mcp.servers import btc
from ...mcp.tools import INFRASTRUCTURE_CODES
from .state import TURN_KEYS, HotContext, HotState

logger = logging.getLogger(__name__)

#: Section 4.5: two regenerations, then the safe line.
MAX_REGENERATIONS = 2

#: Below this the recogniser's confidence sends the turn to CLARIFY.
ASR_LOW_CONFIDENCE = 0.45

#: The marks a reply carries: the brief lines it rests on ("[B2]", "[B2, B5]")
#: and, by imitation of the passages it was shown, document codes ("[DT-03]",
#: "[SP-AIR-01]"). The customer hears neither; the brief lines are kept as the
#: ones the reply used (``facts_used`` in the trace).
_CODE = r"(?:B\d+|[A-Z]{2,4}(?:-[A-Z]{2,4})?-\d{2})"
_MARK = rf"\[{_CODE}(?:\s*[,;]\s*{_CODE})*\]"
#: One run of marks, with the commas between them ("[DT-01], [CL-01]").
MARKS = re.compile(rf"\s*{_MARK}(?:\s*[,;]?\s*{_MARK})*")
BRIEF_LINE = re.compile(r"\bB\d+\b")


def unmarked(text: str) -> str:
    """*text* as the customer hears it: without marks, spaces closed up."""
    return re.sub(r"\s+([,.;!?…])", r"\1", re.sub(r"\s{2,}", " ", MARKS.sub("", text))).strip()


def lines_used(text: str) -> list[str]:
    """The brief lines a reply cites, in order, once each."""
    return list(dict.fromkeys(line for mark in MARKS.finditer(text) for line in BRIEF_LINE.findall(mark.group(0))))


# ── 1. perceive ───────────────────────────────────────────────────────────


async def perceive(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.1, ``components.intake``: clean, NFC, ITN, tokenise.

    Writes the tokenised utterance to ``messages`` under ``customer-<turn_id>``
    (a retried turn replaces its first copy), the input mode, and
    ``flags.new_key`` when the words carry a phone number the call has not
    seen; clears the previous turn's keys. The opening turn has no words.
    """
    context = runtime.context
    if context.arrived is None:
        context.arrived = time.perf_counter()
    update: dict[str, Any] = {**TURN_KEYS, "flags": {"asr_low_conf": False, "new_key": False}}
    raw = (context.text or "").strip()
    if state.get("phase") == "opening" or not raw:
        return update

    if state.get("input_mode") == "asr_transcript" or context.asr_confidence is not None:
        # Recognised speech: the product-name dictionary first (section 4.1, step 3).
        raw = lexicon.correct(raw)
    cleaned, teencode = intake_text.clean(raw)
    written = itn.normalise(cleaned, state["now"])
    tokenised = pii.tokenise(written, context.vault)
    seen = {k["digest"] for k in state.get("keys_seen") or []}
    # A phone number in the words the call has not seen yet is a new key.
    new_phones = [
        token for token in dict.fromkeys(m.group(0) for m in pii.TOKEN.finditer(tokenised) if m.group(1) == "PHONE")
        if resolver.digest("phone", context.vault.get(token) or "", context.identity_secret) not in seen
    ]
    mode = state.get("input_mode") or ("chat_teencode" if teencode else "clean")
    low = context.asr_confidence is not None and context.asr_confidence < ASR_LOW_CONFIDENCE
    update.update(
        input_mode=mode,
        messages=[HumanMessage(content=tokenised, id=f"customer-{state['turn_id']}")],
        flags={"asr_low_conf": low, "new_key": bool(new_phones), "new_phone_tokens": new_phones,
               **signals.read(written).as_flags()},
    )
    return update


# ── 2. load_context: resolve, retrieve, refresh ───────────────────────────


async def load_context(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.2: who is speaking, what the shop knows about them, and what the documents say.

    Identity works on the first turn of a call (keys from the connection),
    whether the agent opened it or the customer spoke first, as in the
    evaluation runner; on a turn that brings a new key; and on the answer to
    a confirming question. The Call Brief's latency runs from the
    identification event to the brief being ready, ``refresh`` included.

    Then, on every turn with words, the knowledge base is searched for them
    (section 7.3), after identity, because a question about an order already
    placed is answered by the policy of the day it was placed (CL-01).
    """
    context = runtime.context
    update = await _identify(state, context)
    if state.get("phase") != "opening" and (context.text or "").strip():
        found = await _knowledge({**state, **update}, context, _last_customer_text(state) or "")
        if found is not None:
            update["knowledge"] = found
    return update


async def _knowledge(state: dict[str, Any], context: HotContext, said: str) -> dict[str, Any] | None:
    """``kb.search`` on the customer's words: the passages, and whether the documents cover them."""
    if context.harness is None or not said.strip():
        return None
    order_date = _order_date(state, said)
    found = await context.harness.data("kb_search", query=said, k=5, on=state["on"], order_date=order_date)
    if not found:
        return None
    return {key: found.get(key) for key in ("hits", "top_score", "threshold", "abstain", "reason", "mode",
                                            "changelog", "version")} | {"order_date": order_date}


def _order_date(state: dict[str, Any], said: str) -> str | None:
    """The day the order a question is about was placed, when it is about one this customer has."""
    orders = [o for o in (state.get("brief") or {}).get("orders") or [] if o.get("order_id")]
    if not orders or not (ORDER_TALK.search(intake_text.plain(said)) or "OD" in said):
        return None
    named = next((o for o in orders if o["order_id"] in said), None)
    chosen = named or max(orders, key=lambda o: str(o.get("date") or o.get("created_at") or ""))
    day = str(chosen.get("date") or chosen.get("created_at") or "")[:10]
    return day or None


async def _identify(state: HotState, context: HotContext) -> dict[str, Any]:
    """Who is speaking: the tier, the profile and its brief (section 4.2)."""
    flags = state.get("flags") or {}
    opening = state.get("phase") == "opening"
    # No key seen yet: the connection's keys (caller id, channel identity)
    # have not been looked up. True on every turn of a web chat that has none,
    # which is harmless: there is nothing to look up until the words bring one.
    unidentified = opening or not state.get("keys_seen")
    tier = state.get("tier") or "UNKNOWN"
    answer = _last_customer_text(state)

    if not unidentified and not flags.get("new_key"):
        if state.get("awaiting") and answer:
            return await _settle(state, context, answer)
        return {}

    started = time.perf_counter()
    keys = _keys(state, context, connection=unidentified)
    if not keys:
        return {}
    if tier == "VERIFIED":
        return {}  # A number mentioned for shipping or another person is not a newly confirmed identity.
    matches, crm_by_customer, key_matches = await _look_up(keys, context)
    keys_seen = list(state.get("keys_seen") or []) + [
        {"kind": k.kind, "digest": k.digest, "last4": k.last4, "from_connection": k.from_connection,
         "customer_ids": key_matches.get(k.digest, [])} for k in keys
    ]
    from_connection = any(k.from_connection and key_matches.get(k.digest) for k in keys)
    tier = resolver.decide(matches, from_connection=from_connection)
    phone = next((k.value for k in keys if k.kind == "phone"), None)
    update: dict[str, Any] = {"keys_seen": keys_seen, "tier": tier}
    if phone:
        update["phone_last4"] = phone[-4:]
        update["phone_token"] = context.vault.put("PHONE", phone)

    if tier == "UNKNOWN":
        return update
    if tier == "AMBIGUOUS":
        # The first words may already carry the name; otherwise the fixed question.
        chosen = resolver.pick_by_name(answer or "", matches)
        if chosen is None:
            update.update(candidates=[m._asdict() | {"phone": None} for m in matches], awaiting="name",
                          customer_id=None, brief=None, brief_lines=[])
            return update
        matches, tier = [chosen], "VERIFIED"
        update["tier"] = tier

    match = matches[0]
    if match.phone and not phone:
        update["phone_token"] = context.vault.put("PHONE", match.phone)
        update["phone_last4"] = match.phone[-4:]
    update.update(customer_id=match.customer_id, customer_name=match.name, honorific=match.honorific,
                  awaiting="confirm" if tier == "PROBABLE" else None)
    if tier == "PROBABLE":
        # Kept whatever the answer: if the call ends unsure, after_call asks the
        # MemoryAgent whether the whole call showed it is them (section 4.2, step 4).
        update["provisional"] = {"customer_id": match.customer_id, "name": match.name, "honorific": match.honorific}
        if context.harness is not None:
            for key in keys:
                if match.customer_id not in key_matches.get(key.digest, []):
                    continue
                await context.harness.call("identity_link_provisional", customer_id=match.customer_id,
                                           key_type=key.kind, key_hash=key.digest)
    merged = {**state, **update, "crm": crm_by_customer.get(match.customer_id) or {}}
    update.update(await _brief(merged, context, started))
    return update


#: A caller who did not confirm: a new customer on this key, and nothing of the other's.
STRANGER: dict[str, Any] = {
    "tier": "UNKNOWN", "customer_id": None, "customer_name": None, "honorific": None, "awaiting": None,
    "brief": None, "brief_lines": [], "freshness": [], "known_orders": [],
    "phone_token": None, "phone_last4": None, "quotes": {}, "provisional": None,
}


async def _settle(state: HotState, context: HotContext, answer: str) -> dict[str, Any]:
    """The answer to the one confirming question (section 4.2). Either way, it is not asked again."""
    if state.get("awaiting") == "name":
        chosen = resolver.pick_by_name(answer, [resolver.Match(**c) for c in state.get("candidates") or []])
        if chosen is None:
            # No one named: general advice, nothing private, the name not asked again.
            return {"awaiting": None}
        bound = {"customer_id": chosen.customer_id, "customer_name": chosen.name, "honorific": chosen.honorific,
                 "tier": "VERIFIED", "awaiting": None, "candidates": []}
        return {**bound, **await _brief({**state, **bound}, context, time.perf_counter())}

    profile = resolver.Match(str(state.get("customer_id") or ""), state.get("customer_name"), state.get("honorific"))
    confirmed = resolver.confirms(answer) is True or resolver.pick_by_name(answer, [profile]) is not None
    if not confirmed or not profile.customer_id:
        return dict(STRANGER)
    return {"tier": "VERIFIED", "awaiting": None, **await _brief(state, context, time.perf_counter())}


def _keys(state: HotState, context: HotContext, *, connection: bool) -> list[resolver.Key]:
    """The connection's keys while none has been seen, then any number the words brought."""
    secret = context.identity_secret
    keys = []
    if connection:
        if context.caller_phone:
            keys.append(resolver.make_key("phone", context.caller_phone, secret, from_connection=True))
        if context.zalo_id:
            keys.append(resolver.make_key("zalo_id", context.zalo_id, secret, from_connection=True))
        if context.fb_id:
            keys.append(resolver.make_key("fb_id", context.fb_id, secret, from_connection=True))
    seen = {(k.kind, k.digest) for k in keys}
    for token in (state.get("flags") or {}).get("new_phone_tokens") or []:
        value = context.vault.get(token)
        if not value:
            continue
        key = resolver.make_key("phone", value, secret, from_connection=False)
        if (key.kind, key.digest) not in seen:
            seen.add((key.kind, key.digest))
            keys.append(key)
    return keys


async def _look_up(keys: list[resolver.Key], context: HotContext) -> tuple[list[resolver.Match], dict[str, dict], dict[str, list[str]]]:
    """The organisers' CRM and the ledger's identities, in parallel."""
    harness = context.harness
    if harness is None:
        return [], {}, {}
    lookups = []
    for key in keys:
        lookups.append(harness.data("crm_get_customer", **{key.kind: key.value}))
        lookups.append(harness.data("identity_find", key_type=key.kind, key_hash=key.digest))
    answers = await asyncio.gather(*lookups)
    matches: dict[str, resolver.Match] = {}
    crm: dict[str, dict] = {}
    key_matches: dict[str, list[str]] = {k.digest: [] for k in keys}
    for index, answer in enumerate(answers):
        if not answer:
            continue
        if index % 2 == 0:
            for match in resolver.matches_from_crm(answer):
                key_matches[keys[index // 2].digest].append(match.customer_id)
                matches[match.customer_id] = match
                if not answer.get("ambiguous"):
                    crm[match.customer_id] = answer
                else:
                    candidate = next((c for c in answer.get("candidates") or [] if c["customer_id"] == match.customer_id), {})
                    crm[match.customer_id] = candidate
        else:
            for row in answer.get("matches") or []:
                if row.get("status") != "confirmed":
                    continue
                key_matches[keys[index // 2].digest].append(row["customer_id"])
                matches.setdefault(row["customer_id"], resolver.Match(row["customer_id"], source="ledger"))
    return list(matches.values()), crm, key_matches


async def _brief(state: dict[str, Any], context: HotContext, started: float) -> dict[str, Any]:
    """Retrieve (the memory switch), refresh, render: the brief and its latency."""
    harness = context.harness
    customer_id = state.get("customer_id")
    if harness is None or not customer_id:
        return {}
    memory_on = bool((state.get("switches") or {}).get("memory", True))
    crm = state.get("crm")
    if crm is None and memory_on:
        phone = context.vault.get(state.get("phone_token") or "")
        crm = await harness.data("crm_get_customer", phone=phone) if phone else {}
        if crm and crm.get("ambiguous"):
            crm = next((c for c in crm.get("candidates") or [] if c["customer_id"] == customer_id), {})
    found = await recall.retrieve(customer_id, state["on"], harness, crm=crm, memory_on=memory_on)
    phone = context.vault.get(state.get("phone_token") or "")
    products, orders, warnings = [], [], []
    if memory_on:
        products = recall.advised(found["facts"], found["orders"])
        products, orders, warnings = await recall.refresh(
            products, found["orders"], found["episodes"], state["on"], harness, customer_phone=phone,
            channel=state.get("channel"),
        )
    latency_ms = int((time.perf_counter() - started) * 1000)
    brief, lines = briefs.render(
        customer={"customer_id": customer_id, "name": state.get("customer_name"), "honorific": state.get("honorific"),
                  "phone_last4": state.get("phone_last4")},
        facts=found["facts"], episodes=found["episodes"], orders=orders, products=products,
        warnings=warnings, now=state["now"], latency_ms=latency_ms, channel=state.get("channel"),
    )
    # PB-11: contacts in a row, newest first, that ended without an order.
    brief["sessions_without_close"] = next(
        (i for i, e in enumerate(found["episodes"]) if e.get("outcome") == "chot_don"), len(found["episodes"]))
    return {
        "brief": pii.tokenise_data(brief, context.vault),
        "brief_lines": pii.tokenise_data([line.as_dict() for line in lines], context.vault),
        "freshness": pii.tokenise_data(warnings, context.vault),
        "call_brief_latency_ms": latency_ms if brief["is_returning"] else None,
        "known_orders": [o.get("order_id") for o in orders if o.get("order_id")],
    }


# ── 3. route ──────────────────────────────────────────────────────────────


async def route(state: HotState) -> dict[str, Any]:
    """Section 4.3, ``components.orchestration.rules``: the lane, by rules, and its notes."""
    flags = state.get("flags") or {}
    decision = decide(RouteInput(
        tier=state.get("tier") or "UNKNOWN",
        has_brief=bool(state.get("brief_lines")),
        has_order=bool(state.get("known_orders")),
        asr_low_conf=bool(flags.get("asr_low_conf")),
        tool_failures=int(state.get("tool_failures") or 0),
        safe_lines=int(state.get("safe_lines") or 0),
        customer_said=_last_customer_text(state),
        must_transfer=bool(flags.get("must_transfer")),
        impatient=bool(flags.get("impatient")),
        sessions_without_close=int((state.get("brief") or {}).get("sessions_without_close") or 0),
        awaiting_identity=bool(state.get("awaiting")),
    ))
    return {"lane": decision.lane, "route_rule": decision.rule, "route_reason": decision.reason,
            "route_notes": list(decision.notes)}


# ── 4. advisor ────────────────────────────────────────────────────────────


async def advisor(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.4, ``AdvisorAgent``: the draft, from the slice of section 3.2.

    Folds old turns into ``working_summary`` once the call grows long. Below
    VERIFIED the model is not shown a brief line carrying a price, an address
    or an order code: withheld here, not merely forbidden in the prompt.

    Speaking to the customer, the answer streams and is said a sentence at a
    time, each checked first (section 4.8, :func:`_streamed`); the ``guard``
    node then has nothing left to check. A suggestion for a consultant is
    drafted whole, and ``guard`` checks it as one.
    """
    context = runtime.context
    update: dict[str, Any] = {}
    messages = list(state.get("messages") or [])
    summary = state.get("working_summary")
    folded, kept = compact.split(messages)
    if folded:
        summary = await compact.fold_with(context.compactor, folded, summary)
        update["working_summary"] = summary
        update["messages"] = [RemoveMessage(id=m.id) for m in folded if m.id]
        messages = kept

    if state.get("lane") == "CONFIRM_IDENTITY" and state.get("awaiting") == "name":
        # Section 4.2: on a shared number the question is the harness's, word for word, not a model's.
        update["draft"] = {"text": fallback.AMBIGUOUS_QUESTION, "model": None, "model_calls": 0, "seconds": 0.0,
                           "fixed": True}
        return update

    agent_context = _agent_context(state, context, summary)
    turn_messages = messages or [HumanMessage(content="(Khách vừa bắt máy.)", id="opening")]
    if (state.get("mode") or "speak") == "speak" and hasattr(context.advisor, "stream"):
        update.update(await _streamed(state, context, turn_messages, agent_context))
        return update
    try:
        draft = await context.advisor.draft(turn_messages, agent_context, user_id=context.user_id)
    except Exception as error:  # noqa: BLE001 - section 4.9: a failure is never silence
        logger.exception("Advisor failed on call %s", state.get("call_id"))
        if isinstance(error, AdvisorFailure):
            update.update(_absorb(state, error.partial.tool_results))
        update["draft"] = {"text": fallback.LINES["model_error"], "fallback": True, "error": _readable(error)}
        return update
    update.update(_absorb(state, draft.tool_results))
    update["draft"] = {"text": draft.text, "model": draft.model, "model_calls": draft.model_calls,
                       "seconds": round(draft.seconds, 3)}
    return update


def _agent_context(state: HotState, context: HotContext, summary: str | None) -> AgentContext:
    """The slice of the state the advisor may read (section 3.2), with what the tier withholds left out."""
    tier = state.get("tier") or "UNKNOWN"
    lines = [BriefLine(l["id"], l["text"], l["sensitive"], tuple(l.get("fact_ids") or ())) for l in state.get("brief_lines") or []]
    if tier == "PROBABLE":
        lines = [line for line in lines if not line.sensitive]
    elif tier != "VERIFIED":
        lines = []
    brief = state.get("brief") or {}
    phone = context.vault.get(state.get("phone_token") or "")
    products = brief.get("products_advised") or []
    # Codes the brief stands behind; codes in this turn's tool results are
    # trusted by the before-write check itself (section 4.4, "mã tin cậy").
    trusted = frozenset(state.get("trusted_skus") or []) | (frozenset(
        [p["sku"] for p in products if p.get("sku")]
        + [o[key] for o in brief.get("orders") or [] for key in ("variant_sku", "sku") if o.get(key)]
    ) if tier == "VERIFIED" else frozenset())
    return AgentContext(
        call_id=str(state["call_id"]),
        customer_id=state.get("customer_id") if tier == "VERIFIED" else None,
        address_as=_address_as(state),
        tier=tier,
        lane=state.get("lane") or "NEW",
        mode=state.get("mode") or "speak",
        phase=state.get("phase") or "turn",
        channel=state.get("channel") or "web",
        now=state.get("now"),
        on=state.get("on"),
        brief_lines=tuple(lines),
        warnings=tuple(state.get("freshness") or []) if tier == "VERIFIED" else (),
        must_not_ask=tuple(brief.get("must_not_ask") or []) if tier == "VERIFIED" else (),
        working_summary=summary,
        block_reasons=tuple(state.get("block_reasons") or []),
        tool_results=tuple(state.get("tool_results") or []),
        quotes=dict(state.get("quotes") or {}),
        known_orders=frozenset(state.get("known_orders") or []),
        customer_phone=phone,
        vault=context.vault,
        shared_phone=any(k.get("kind") == "phone" and len(set(k.get("customer_ids") or [])) > 1
                         for k in state.get("keys_seen") or []),
        addresses={token: value for token, (kind, value) in context.vault.entries.items() if kind == "ADDR"},
        handoff_defaults={
            "customer_phone": phone or "",
            "customer_name": state.get("customer_name"),
            "customer_id": state.get("customer_id"),
            "channel": {"web": "web_chat", "hotline": "hotline", "zalo": "zalo_oa", "facebook": "chat_fanpage"}.get(state.get("channel") or "web", "other"),
            "product_advised": products[0]["sku"] if products else None,
            "price_quoted_vnd": products[0].get("price_quoted_vnd") if products else None,
            "generated_at": state["now"].isoformat(),
        },
        switches=dict(state.get("switches") or {}),
        turn_id=state.get("turn_id"),
        knowledge=_passages(state),
        knowledge_note=_knowledge_note(state),
        confirm_reason="probable" if state.get("awaiting") == "confirm" else None,
        notes=tuple(state.get("route_notes") or ()),
        trusted_skus=trusted,
        flags=dict(state.get("flags") or {}),
        customer_said=_last_customer_text(state),
        last_agent_said=_last_agent_text(state),
    )


def _address_as(state: HotState) -> str | None:
    """"chị Hoa" when the tier allows knowing it."""
    if state.get("tier") != "VERIFIED":
        return None
    return " ".join(x for x in (state.get("honorific"), state.get("customer_name")) if x) or None


def _absorb(state: HotState, produced: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A run's tool results added to the turn's, with today's quotes, the orders seen and the failure count."""
    new_results = [{**r, "turn": state.get("turn_no") or 0} for r in produced]
    codes, _ = _seen_in({}, new_results)
    quotes = dict(state.get("quotes") or {})
    orders = list(state.get("known_orders") or [])
    failures = int(state.get("tool_failures") or 0)
    for result in new_results:
        envelope = result.get("result") or {}
        data = envelope.get("data") or {}
        if envelope.get("ok"):
            failures = 0
            if result["name"] == "pricing.get_quote" and data.get("sku"):
                quotes[data["sku"]] = int(data["final_price_vnd"])
            for order in data.get("orders") or ([data] if data.get("order_id") else []):
                if order.get("order_id") and order["order_id"] not in orders:
                    orders.append(order["order_id"])
        elif (envelope.get("error") or {}).get("code") in INFRASTRUCTURE_CODES:
            failures += 1
    return {"tool_results": list(state.get("tool_results") or []) + new_results, "quotes": quotes,
            "known_orders": orders, "tool_failures": failures,
            "trusted_skus": sorted(set(state.get("trusted_skus") or []) | codes)}


# ── 4b. the streamed answer, section 4.8 ──────────────────────────────────


@dataclass
class _Attempt:
    """One streamed run: what was said, what the tools returned, and why it stopped, if a sentence was blocked."""

    said: list[str] = field(default_factory=list)
    last_spoken: bool = False
    results: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    blocked: str = ""
    draft: Any = None


async def _streamed(state: HotState, context: HotContext, messages: list[Any], agent_context: AgentContext) -> dict[str, Any]:
    """Say the answer a sentence at a time, each checked before it is said.

    A sentence blocked before anything was said is a draft blocked: the run
    is abandoned and regenerated with the reasons, at most twice, as the
    ``guard`` node would. Blocked after the first sentence was said, the
    stream stops there and the lane's safe line follows, since what was said
    cannot be taken back. More than three sentences, unless reading an order
    back, are not said.
    """
    timing: dict[str, int | None] = {"first_token_ms": None, "filler_ms": None}
    blocked_drafts = list(state.get("blocked_drafts") or [])
    earlier = tuple(state.get("tool_results") or [])
    produced: list[dict[str, Any]] = []
    reasons: list[str] = []
    attempt = _Attempt()
    regenerations = 0
    view = agent_context
    try:
        while True:
            # A retry is checked against every tool result of the turn, the abandoned runs' included.
            attempt = _Attempt()
            await _stream_once(state, context, messages, view, earlier + tuple(produced), timing, attempt)
            produced += [r for r in attempt.results if r not in produced]
            if not attempt.reasons:
                break
            reasons = attempt.reasons
            blocked_drafts.append({"text": attempt.blocked, "reasons": attempt.reasons})
            if attempt.said or regenerations >= MAX_REGENERATIONS:
                break
            regenerations += 1
            view = replace(view, block_reasons=tuple(reasons), tool_results=earlier + tuple(produced))
    except Exception as error:  # noqa: BLE001 - section 4.9: a failure is never silence
        logger.exception("Advisor failed on call %s", state.get("call_id"))
        pending = error.partial.tool_results if isinstance(error, AdvisorFailure) else attempt.results
        produced += [r for r in pending if r not in produced]
        absorbed = _absorb(state, produced)
        if attempt.said:
            line = fallback.safe_line(state.get("lane") or "NEW")
            await _say(context, line, timing)
            return {**absorbed, "draft": {"text": " ".join([*attempt.said, line]), "streamed": True, "fallback": True,
                                          "error": _readable(error)},
                    "guard": {"passed": True, "streamed": True, "fallback": True}, "latency": timing}
        return {**absorbed, "draft": {"text": fallback.LINES["model_error"], "fallback": True, "error": _readable(error)},
                "latency": timing}

    update = _absorb(state, produced)
    draft = attempt.draft
    stats = {"model": getattr(draft, "model", None), "model_calls": getattr(draft, "model_calls", None),
             "seconds": round(getattr(draft, "seconds", 0.0), 3), "streamed": True}
    verdict: dict[str, Any] = {"passed": not attempt.reasons, "streamed": True, "sentences": len(attempt.said),
                               "hard": {"passed": not reasons, "reasons": reasons}}
    text = " ".join(attempt.said)
    if attempt.reasons:
        line = fallback.safe_line(state.get("lane") or "NEW")
        await _say(context, line, timing)
        text = f"{text} {line}".strip()
        verdict["fallback"] = True
        update["safe_lines"] = int(state.get("safe_lines") or 0) + 1
        logger.warning("Call %s: a streamed sentence was blocked after %d said; safe line said",
                       state.get("call_id"), len(attempt.said))
    update.update(
        draft={"text": text, **stats, "fallback": bool(attempt.reasons)},
        guard=verdict,
        blocked_drafts=blocked_drafts,
        block_reasons=reasons,
        regen_count=regenerations,
        latency=timing,
    )
    return update


async def _stream_once(
    state: HotState, context: HotContext, messages: list[Any], view: AgentContext,
    earlier: tuple[dict[str, Any], ...], timing: dict[str, int | None],
    attempt: _Attempt,
) -> _Attempt:
    splitter = SentenceSplitter()
    streamed_text = False
    # Text written after a tool round is a new model message: it must not run on
    # into the last sentence before the tools ("…chờ chút nhé.Dạ đơn hàng…").
    new_message = False
    stream = context.advisor.stream(messages, view, user_id=context.user_id)
    try:
        async for event in stream:
            if event.kind == "tool_started":
                if timing["filler_ms"] is None and not attempt.said and context.emit is not None:
                    await context.emit("filler", fallback.LINES["filler"].format(who=_who(state)))
                    timing["filler_ms"] = _since(context)
            elif event.kind == "tools":
                attempt.results = list(event.results)
                new_message = True
            elif event.kind == "done":
                attempt.draft = event.draft
                attempt.results = list(event.draft.tool_results)
                if not streamed_text and event.draft.text:
                    # Nothing came through as it was written: the answer is the draft's, whole.
                    for sentence in splitter.feed(event.draft.text + " "):
                        if not await _offer(state, context, sentence, earlier + tuple(attempt.results), attempt, timing):
                            return attempt
            else:
                streamed_text = True
                text = (" " + event.text) if new_message else event.text
                new_message = False
                for sentence in splitter.feed(text):
                    if not await _offer(state, context, sentence, earlier + tuple(attempt.results), attempt, timing):
                        return attempt
        rest = splitter.flush()
        if rest:
            await _offer(state, context, rest, earlier + tuple(attempt.results), attempt, timing)
        return attempt
    finally:
        await stream.aclose()


async def _offer(state: HotState, context: HotContext, sentence: str, results: tuple[dict[str, Any], ...],
                 attempt: _Attempt, timing: dict[str, int | None]) -> bool:
    """Check one sentence and say it; False when it was blocked."""
    spoken = unmarked(sentence)
    if not spoken and attempt.said:
        if attempt.last_spoken:
            attempt.said[-1] += " " + sentence
        return True  # A citation arriving after speech is metadata, not an empty reply.
    if len(attempt.said) >= MAX_SENTENCES and not ORDER_SUMMARY.search(" ".join([*attempt.said, sentence])):
        attempt.last_spoken = False
        return True  # past the length the rules allow: not said, the stream goes on to its end
    view = guard_input(state, context, spoken, results)
    reasons = list(check(view).reasons)
    if not reasons and context.policy is not None and needs_review(spoken):
        soft = await context.policy.review(PolicyInput(text=spoken, tool_results=results, tier=view.tier,
                                                       policy_snippets=view.policy_texts))
        reasons += list(soft.reasons)
    if reasons:
        attempt.reasons, attempt.blocked = reasons, " ".join([*attempt.said, sentence])
        return False
    await _say(context, spoken, timing)
    attempt.said.append(sentence)
    attempt.last_spoken = True
    return True


async def _say(context: HotContext, text: str, timing: dict[str, int | None]) -> None:
    """Hand a checked sentence to the channel; the first one is the turn's first token (section 4.8)."""
    if timing["first_token_ms"] is None:
        timing["first_token_ms"] = _since(context)
    if context.emit is not None:
        await context.emit("sentence", text)


def _since(context: HotContext) -> int:
    """Milliseconds since the turn's request arrived, on the monotonic clock."""
    return int((time.perf_counter() - (context.arrived or time.perf_counter())) * 1000)


def _who(state: HotState) -> str:
    return state.get("honorific") if state.get("tier") == "VERIFIED" and state.get("honorific") else "anh/chị"


# ── 5. guard ──────────────────────────────────────────────────────────────


async def guard(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.5: the hard check, then ``PolicyAgent`` on Jev.

    Blocked with regenerations left: back to the advisor with the reasons.
    Blocked with none left: the lane's safe line, counted (two in a call send
    the next turn to HANDOFF). In copilot mode nothing is regenerated: the
    verdict travels with the suggestion as a warning for the consultant.
    """
    context = runtime.context
    draft = state.get("draft") or {}
    if draft.get("streamed"):
        return {}  # every sentence was checked before it was said (section 4.8)
    if draft.get("fallback"):
        return {"guard": {"passed": True, "fallback": True}}
    text = unmarked(draft.get("text") or "")
    results = tuple(state.get("tool_results") or [])
    tier = state.get("tier") or "UNKNOWN"
    view = guard_input(state, context, text, results)
    hard = check(view)
    verdict: dict[str, Any] = {"hard": {"passed": hard.passed, "reasons": list(hard.reasons)}}
    reasons = list(hard.reasons)
    if hard.passed and context.policy is not None and needs_review(text):
        soft = await context.policy.review(PolicyInput(text=text, tool_results=results, tier=tier,
                                                       policy_snippets=view.policy_texts))
        verdict["soft"] = {"passed": soft.passed, "reasons": list(soft.reasons), "decided_by": soft.decided_by,
                           "probabilities": soft.probabilities, "seconds": soft.seconds}
        reasons += list(soft.reasons)
    passed = not reasons
    verdict["passed"] = passed
    if passed or state.get("mode") == "copilot":
        return {"guard": verdict}

    blocked = list(state.get("blocked_drafts") or []) + [{"text": draft.get("text"), "reasons": reasons}]
    regenerations = int(state.get("regen_count") or 0)
    if regenerations < MAX_REGENERATIONS:
        return {"guard": verdict, "block_reasons": reasons, "blocked_drafts": blocked, "regen_count": regenerations + 1}
    line = fallback.safe_line(state.get("lane") or "NEW")
    logger.warning("Call %s: draft blocked %d times, safe line said", state.get("call_id"), regenerations + 1)
    return {
        "guard": {**verdict, "fallback": True},
        "blocked_drafts": blocked,
        "draft": {**draft, "text": line, "fallback": True},
        "safe_lines": int(state.get("safe_lines") or 0) + 1,
    }


def guard_input(state: HotState, context: HotContext, text: str, results: tuple[dict[str, Any], ...]) -> GuardInput:
    """What the hard check reads of a draft, or of one sentence of a streamed one (section 4.5)."""
    brief = state.get("brief") or {}
    tier = state.get("tier") or "UNKNOWN"
    policy, playbook = shown_passages(_passages(state))
    passages = tuple(str(p["text"]) for p in (*policy, *playbook) if p.get("text") and not p.get("restricted"))
    return GuardInput(
        text=text,
        tool_results=results,
        tier=tier,
        customer_said=tuple(str(m.content) for m in state.get("messages") or [] if isinstance(m, HumanMessage)),
        policy_texts=passages,
        brief_prices=tuple(int(p["price_quoted_vnd"]) for p in brief.get("products_advised") or [] if p.get("price_quoted_vnd")),
        tokens=frozenset(context.vault.entries),
        quotes=dict(state.get("quotes") or {}),
        warnings=tuple(state.get("freshness") or []) if tier == "VERIFIED" else (),
        promotions=promotions(),
        on=state.get("on"),
    )


@lru_cache(maxsize=1)
def promotions() -> dict[str, tuple[str, str]]:
    """Every promotion the shop runs, code to its first and last day: what KM-02 checks against."""
    return {p["promo_code"]: (str(p["start"]), str(p["end"])) for p in btc.mock().PROMOS}


def after_guard(state: HotState) -> str:
    """Regenerate while the guard blocks and regenerations are left, else respond."""
    verdict = state.get("guard") or {}
    if verdict.get("passed") or verdict.get("fallback") or state.get("mode") == "copilot":
        return "respond"
    return "advisor"


# ── 6. respond ────────────────────────────────────────────────────────────


async def respond(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.6: say it, or hand it to the consultant.

    The ``[Bn]`` marks are stripped and kept as the lines used. In speak
    mode the reply joins ``messages``, tokenised; the API restores the
    customer's own tokens when it sends it. A streamed reply was said as it
    was checked; any other is said here, whole. A successful
    ``handoff.transfer`` this turn adds the bridging line once and turns the
    call to copilot. In copilot mode the draft becomes a suggestion for the
    consultant, with the guard's warnings, and nothing is said to the customer.
    """
    draft = state.get("draft") or {}
    raw = draft.get("text") or ""
    used = lines_used(raw)
    text = unmarked(raw)
    turn_id = state["turn_id"]

    if state.get("mode") == "copilot":
        verdict = state.get("guard") or {}
        warnings = list((verdict.get("hard") or {}).get("reasons") or []) + list((verdict.get("soft") or {}).get("reasons") or [])
        if fallback.is_bridging(text):
            return {"suggestion": None}
        return {"suggestion": {"text": text, "used_lines": used, "warnings": warnings, "turn_id": turn_id}}

    context = runtime.context
    timing: dict[str, Any] = {"first_token_ms": None, "filler_ms": None, **(state.get("latency") or {})}
    streamed = bool(draft.get("streamed"))
    update: dict[str, Any] = {}
    handoff = next(
        (r for r in state.get("tool_results") or [] if r.get("name") == "handoff.transfer" and (r.get("result") or {}).get("ok")),
        None,
    )
    if handoff is not None:
        if not fallback.is_bridging(text):
            text = f"{text} {fallback.LINES['bridging']}".strip()
            if streamed:
                await _say(context, fallback.LINES["bridging"], timing)
        brief = (handoff.get("args") or {}).get("brief") or {}
        update["mode"] = "copilot"
        update["handoff"] = {
            "status": "pending",
            "ticket_id": ((handoff.get("result") or {}).get("data") or {}).get("ticket_id"),
            "reason": brief.get("escalation_reason"),
            "brief": brief,
        }
    if not streamed and text:
        # Said whole: the harness's own lines, a fallback, a draft that did not stream.
        await _say(context, text, timing)
    update["reply"] = {"text": text, "used_lines": used}
    update["messages"] = [AIMessage(content=text, id=f"agent-{turn_id}")]
    update["latency"] = timing
    return update


# ── 7. persist ────────────────────────────────────────────────────────────


async def persist(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.7: the checkpointer has saved working memory by now; this
    writes the transcript row and the ``calls`` projection through the store
    the caller handed in (the API's tables, or the evaluation runner's trace)."""
    store = runtime.context.store
    if store is not None:
        await store.persist(state)
    return {}


# ── helpers ───────────────────────────────────────────────────────────────


#: Told to the advisor when the turn's words were searched and nothing relevant came back (section 7.3).
NOTHING_RELEVANT = "Tài liệu: không có đoạn nào đủ liên quan tới câu khách vừa nói."


def _passages(state: HotState) -> tuple[dict[str, Any], ...]:
    """The passages the advisor reads this turn: none when the best one is under θ, as nothing is relevant then.

    An internal passage reaches it as the instruction it stands for, never its text.
    """
    found = state.get("knowledge") or {}
    if not found.get("hits") or found.get("reason") == "no_match":
        return ()
    return tuple(found["hits"])


def _knowledge_note(state: HotState) -> str | None:
    found = state.get("knowledge") or {}
    return NOTHING_RELEVANT if found and found.get("reason") == "no_match" else None


def _last_customer_text(state: HotState) -> str | None:
    for message in reversed(state.get("messages") or []):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return None


def _last_agent_text(state: HotState) -> str | None:
    """What the agent said last, before this turn's customer words."""
    seen_customer = False
    for message in reversed(state.get("messages") or []):
        if isinstance(message, HumanMessage):
            seen_customer = True
        elif isinstance(message, AIMessage) and seen_customer:
            return str(message.content)
    return None


def _readable(error: Exception) -> str:
    if isinstance(error, AdvisorFailure):
        error = error.error
    text = f"{type(error).__name__}: {error}".lower()
    if any(m in text for m in ("429", "rate limit", "quota", "resource_exhausted")):
        return "The model hit its rate limit."
    if "timeout" in text or "timed out" in text:
        return "The model did not answer in time."
    if "api key" in text or "not set" in text or "401" in text:
        return "The model is not configured on this server."
    return f"{type(error).__name__}"
