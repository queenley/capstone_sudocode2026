"""The hot graph's seven nodes. ``docs/design.md`` section 4.

Each node builds the input a component or an agent declares from
:class:`~.state.HotState`, calls it, and writes the result back into the
keys it owns. What a step *does* is documented where it is done, in the
module each docstring names. Collaborators arrive through
``runtime.context`` (:class:`~.state.HotContext`), never as module globals.
"""

from __future__ import annotations

import json

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Mapping, Sequence

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.runtime import Runtime

from ...agents.advisor import RULE_PACKS, AdvisorFailure, AgentContext, Draft, shown_passages, system_prompt, _seen_in
from ...agents.policy import PolicyInput
from ...components.context import compact, focus
from ...components.context.budget import tokens as count_tokens
from ...components.guardrails import actions, fallback, purchase
from ...components.guardrails.hard import (MAX_SENTENCES, ORDER_SUMMARY, GuardInput, check, clean, moved_callback,
                                           open_amounts)
from ...config.config_manager import review_head_start
from .review import Reviews
from ...components.context import skills as skill_book
from ...components.guardrails.stream import SentenceSplitter
from ...components.identity import resolver
from ...components.intake import honorific, itn, lexicon, pii, signals, text as intake_text
from ...components.knowledge.search import stated_order_day
from ...components.memory import brief as briefs
from ...components.memory import recall
from ...components.memory.brief import BriefLine
from ...observability import stopwatch
from ...components.orchestration.rules import MODEL_FAILURES, RouteInput, decide
from ...config.config_manager import handoff_auto_accept
from ...mcp.servers import btc
from ...mcp.tools import INFRASTRUCTURE_CODES
from . import call_state
from .state import TURN_KEYS, HotContext, HotState

logger = logging.getLogger(__name__)

#: What the PolicyAgent reads of the call's earlier tool results: the last few, short.
CALL_LOG_SIZE = 12
CALL_LOG_CHARS = 500
#: How far back the PolicyAgent reads the customer's words, in messages of the call.
CUSTOMER_WORDS = 12
#: How many of the documents' passages the guards remember for the rest of a call.
PASSAGES_READ = 9
#: Section 4.5: two regenerations, then the safe line.
MAX_REGENERATIONS = 2

#: Below this the recogniser's confidence sends the turn to CLARIFY.
ASR_LOW_CONFIDENCE = 0.45

#: The marks a reply carries: the brief lines it rests on ("[B2]", "[B2, B5]")
#: and, by imitation of the passages it was shown, document codes ("[DT-03]",
#: "[SP-AIR-01]"). The customer hears neither; the brief lines are kept as the
#: ones the reply used (``facts_used`` in the trace).
_CODE = r"(?:B(?:\d+|n)|[A-Z]{2,4}(?:-[A-Z]{2,4})?-\d{2})"
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
    update["pending_purchase"] = purchase.still_open(
        state.get("pending_purchase"), call_id=str(state["call_id"]), channel=state.get("channel") or "web",
        turn_id=state["turn_id"])
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
    agent_said = _last_reply(state)
    called = honorific.self_reference(written, agent_asked=agent_said)
    if called:
        update["honorific_said"] = called
    if agent_said and honorific.ASKED.search(intake_text.plain(agent_said)):
        update["honorific_asked"] = True
    low = context.asr_confidence is not None and context.asr_confidence < ASR_LOW_CONFIDENCE
    update.update(
        input_mode=mode,
        call_facts=call_state.heard(tokenised, state.get("call_facts")),
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
    with stopwatch.span("context"):
        update = await _identify(state, context)
    if state.get("phase") != "opening" and (context.text or "").strip():
        with stopwatch.span("knowledge"):
            found = await _knowledge({**state, **update}, context, _last_customer_text(state) or "")
        if found is not None:
            update["knowledge"] = found
            update["passages_read"] = _passages_after(state.get("passages_read") or {}, _passages({"knowledge": found}))
    return update


async def _knowledge(state: dict[str, Any], context: HotContext, said: str) -> dict[str, Any] | None:
    """``kb.search`` on the customer's words: the passages, and whether the documents cover them."""
    if context.harness is None or not said.strip():
        return None
    order_date, other_orders = _order_days(state, said)
    found = await context.harness.data("kb_search", query=said, k=5, on=state["on"], order_date=order_date,
                                       other_order_dates=list(other_orders),
                                       about=[p["sku"] for p in state.get("seen_products") or [] if p.get("sku")])
    if not found:
        return None
    return {key: found.get(key) for key in ("hits", "top_score", "threshold", "abstain", "reason", "mode",
                                            "changelog", "version", "withheld", "explains", "version_differs")} | {
                                                "order_date": order_date}


#: The turn mentions an order: the knowledge search then picks the policy version in force on that order's day.
#: Not routing (the advisor reads what the turn is about); a hint to retrieval only.
ORDER_TALK = re.compile(
    r"\b(don hang|don cua|ma don|od\d+|dang giao|giao chua|giao den dau|den dau roi|khi nao giao|doi size|"
    r"doi sang|doi mau|doi san pham|tra hang|hoan tien|doi dia chi|sua dia chi|trang thai don|nhan hang|"
    r"van don|chat qua|rong qua|bi loi)\b")


def _order_days(state: dict[str, Any], said: str) -> tuple[str | None, tuple[str, ...]]:
    """The day of the order a question is about, and when it names none, this customer's other order days."""
    orders = [o for o in (state.get("brief") or {}).get("orders") or [] if o.get("order_id")]
    named = next((o for o in orders if o["order_id"] in said), None)
    if named is None:
        # The order named by its product ("cái máy lọc hôm trước"), as origin/main reads it.
        words = intake_text.plain(said)
        named = next((o for o in orders if any(str(o.get(key) or "") and intake_text.plain(str(o[key])) in words
                                               for key in ("product_name", "name", "sku", "variant_sku"))), None)
    if named is not None:
        return _order_day(named) or None, ()
    stated = stated_order_day(said, state.get("on"))
    if stated:
        return stated, ()
    if not orders or not (ORDER_TALK.search(intake_text.plain(said)) or "OD" in said):
        return None, ()
    days = sorted({_order_day(order) for order in orders} - {""})
    return (days[-1], tuple(days[:-1])) if days else (None, ())


def _order_day(order: Mapping[str, Any]) -> str:
    return str(order.get("date") or order.get("created_at") or "")[:10]


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
        if context.account_id and state.get("channel") == "web" and context.caller_phone:
            customer_id = f"web:{context.account_id}"
            update.update(tier="VERIFIED", customer_id=customer_id, customer_name=context.account_name,
                          awaiting=None, provisional=None)
            update["keys_seen"] = [{**key, "customer_ids": [customer_id]} for key in keys_seen
                                   if key["from_connection"]]
            update.update(await _brief({**state, **update, "crm": {}}, context, started))
        return update
    if tier == "AMBIGUOUS":
        # The first words may already carry the name; otherwise the fixed question.
        chosen = resolver.pick_by_name(answer or "", matches) or resolver.pick_by_account(context.account_name, matches)
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
    update.update(customer_id=match.customer_id, customer_name=match.name or (context.account_name if context.account_id else None), honorific=match.honorific,
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
    confirmed = resolver.pick_by_name(answer, [profile]) is not None or await _confirms(state, context, answer)
    if not confirmed or not profile.customer_id:
        return dict(STRANGER)
    return {"tier": "VERIFIED", "awaiting": None, **await _brief(state, context, time.perf_counter())}


async def _confirms(state: HotState, context: HotContext, answer: str) -> bool:
    """Whether the answer to the confirming question confirms who the caller is (section 4.2).

    Read by the PolicyAgent with the question asked; the word list (``resolver.confirms``)
    only when it gives no answer in time. A wrong "yes" would open someone
    else's data, so its threshold is the higher one (``INTENT_THRESHOLDS``).
    """
    if context.policy is not None:
        verdict = await context.policy.judge("identity", {"recent_messages": [
            {"speaker": "assistant", "text": _last_reply(state) or ""}, {"speaker": "customer", "text": answer}]})
        if verdict is not None:
            return verdict
    return resolver.confirms(answer) is True


def _recent(state: HotState, limit: int = 6) -> tuple[tuple[str, str], ...]:
    """The last *limit* messages, ``(speaker, text)``, tokenised as the state holds them."""
    out = []
    for message in (state.get("messages") or [])[-limit:]:
        if isinstance(message, HumanMessage):
            out.append(("customer", str(message.content)))
        elif isinstance(message, AIMessage) and message.content:
            out.append(("assistant", str(message.content)))
    return tuple(out)


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
    if found.get("forgotten"):
        return {"tier": "UNKNOWN", "customer_id": None, "customer_name": None, "known_orders": [],
                "brief": {}, "brief_lines": [], "freshness": [], "crm": {}, "call_brief_latency_ms": None}
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
        asr_low_conf=bool(flags.get("asr_low_conf")),
        tool_failures=int(state.get("tool_failures") or 0),
        model_failures=int(state.get("model_failures") or 0),
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
        with stopwatch.span("compact"):
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
    prompt, cut = system_prompt(agent_context)
    if cut:
        logger.warning("Call %s lost %s from its prompt", state.get("call_id"), ", ".join(cut))
    update["prompt_stats"] = focus.stats(count_tokens(prompt), cut, focus.packs(agent_context, RULE_PACKS),
                                         len(agent_context.brief_lines), len(state.get("brief_lines") or []))
    if state.get("lane") == "HANDOFF":
        # Rule 1: tools or the model keep failing. The model is what may be failing, so the
        # harness puts the call through itself, and the bridging line is said only when it did.
        update.update(await _transfer(state, context, agent_context, [], summary=summary))
        return update
    turn_messages = messages or [HumanMessage(content="(Khách vừa bắt máy.)", id="opening")]
    if (state.get("mode") or "speak") == "speak" and hasattr(context.advisor, "stream"):
        update.update(await _streamed(state, context, turn_messages, agent_context))
        return update
    try:
        with stopwatch.span("advisor"):
            draft = await context.advisor.draft(turn_messages, agent_context, user_id=context.user_id)
    except Exception as error:  # noqa: BLE001 - section 4.9: a failure is never silence
        logger.exception("Advisor failed on call %s", state.get("call_id"))
        produced = list(error.partial.tool_results) if isinstance(error, AdvisorFailure) else []
        update.update(await _model_failed(state, context, agent_context, produced, error, summary=summary))
        return update
    update.update(_absorb(state, draft.tool_results))
    update["draft"] = {"text": draft.text, "model": draft.model, "model_calls": draft.model_calls,
                       "seconds": round(draft.seconds, 3)}
    update["model_failures"] = 0
    return update


async def _model_failed(state: HotState, context: HotContext, agent_context: AgentContext,
                        produced: Sequence[Mapping[str, Any]], error: BaseException, *,
                        summary: str | None) -> dict[str, Any]:
    """Section 4.9: the model gave no draft. Ask again once; a second turn in a row goes to a person.

    Counted like a tool failure (route rule 1), and acted on in the same turn: a
    customer who heard "nhắc lại giúp em" once is not asked a second time.
    """
    failures = int(state.get("model_failures") or 0) + 1
    if failures >= MODEL_FAILURES:
        return await _transfer(state, context, agent_context, produced, summary=summary,
                               detail=f"Trợ lý tự động lỗi {failures} lượt liên tiếp ({_readable(error)}).")
    return {**_absorb(state, produced), "model_failures": failures,
            "draft": {"text": fallback.line("model_error", _who(state)), "fallback": True, "error": _readable(error)}}


async def _transfer(state: HotState, context: HotContext, agent_context: AgentContext,
                    produced: Sequence[Mapping[str, Any]], *, summary: str | None,
                    detail: str | None = None) -> dict[str, Any]:
    """Put the call through to a person by the harness itself, with a Handoff Brief made from the state.

    The bridging line is said only after ``handoff.transfer`` succeeded: a
    line that promises a person must never stand for one that was not called.
    A call already handed over is not handed over twice; a failed transfer
    says the system is slow and promises nothing.
    """
    if state.get("handoff"):
        return {**_absorb(state, produced), "model_failures": 0,
                "draft": {"text": fallback.line("tool_down", _who(state)), "fallback": True}}
    reason = detail or _HANDOFF_DETAIL.get(state.get("route_reason") or "", "Trợ lý tự động không trả lời tiếp được.")
    said = [str(m.content) for m in state.get("messages") or [] if isinstance(m, HumanMessage)]
    story = " ".join(x for x in (reason, (summary or "").strip(),
                                 f"Khách vừa nhắn: \"{said[-1].strip()}\"." if said else "") if x)
    brief = actions.fill_handoff({
        "escalation_reason": "loi_he_thong",
        "escalation_reason_detail": reason,
        "conversation_summary": story[:800],
        "open_questions": [said[-1].strip()[:300]] if said else [],
        "next_action": "Xin lỗi khách vì hệ thống trục trặc rồi trả lời tiếp câu khách đang hỏi.",
    }, agent_context.handoff_defaults)
    if context.harness is None:
        envelope: dict[str, Any] = {"ok": False, "error": {"code": "NO_TOOL", "retryable": False,
                                                            "message": "No harness tools"}}
    else:
        envelope = await context.harness.call("handoff_transfer", brief=brief)
    entry = {"name": "handoff.transfer", "args": {"brief": brief}, "result": envelope, "by": "harness"}
    update = _absorb(state, [*produced, entry])
    update["model_failures"] = 0
    if envelope.get("ok"):
        update["draft"] = {"text": fallback.LINES["bridging"], "model": None, "model_calls": 0, "seconds": 0.0,
                           "fixed": True}
    else:
        logger.warning("Call %s: the harness could not transfer the call: %s", state.get("call_id"),
                       (envelope.get("error") or {}).get("message"))
        update["draft"] = {"text": fallback.line("tool_down", _who(state)), "fallback": True}
    return update


#: Why route rule 1 fired, in the words a consultant reads first.
_HANDOFF_DETAIL = {
    "tools failing": "Hệ thống tra cứu lỗi nhiều lần liên tiếp nên trợ lý tự động không trả lời tiếp được.",
    "the model failing": "Trợ lý tự động lỗi nhiều lượt liên tiếp.",
}


def _agent_context(state: HotState, context: HotContext, summary: str | None) -> AgentContext:
    """The slice of the state the advisor may read (section 3.2), with what the tier withholds left out."""
    tier = state.get("tier") or "UNKNOWN"
    lines = [BriefLine(l["id"], l["text"], l["sensitive"], tuple(l.get("fact_ids") or ()), l.get("kind", "other"))
             for l in state.get("brief_lines") or []]
    if tier == "PROBABLE":
        lines = [line for line in lines if not line.sensitive]
    elif tier != "VERIFIED":
        lines = []
    lines = focus.lines(lines, _last_customer_text(state), first_turn=int(state.get("turn_no") or 1) <= 1
                        or state.get("phase") == "opening", blocked=bool(state.get("block_reasons")))
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
        pending_purchase=state.get("pending_purchase"),
        skills=list(state.get("loaded_skills") or []),
        customer_id=state.get("customer_id") if tier == "VERIFIED" else None,
        account_id=context.account_id,
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
        call_state=call_state.lines(state.get("call_facts"), state.get("quotes"), _last_agent_text(state)),
        block_reasons=tuple(state.get("block_reasons") or []),
        tool_results=tuple(state.get("tool_results") or []),
        quotes=dict(state.get("quotes") or {}),
        known_orders=frozenset(state.get("known_orders") or []),
        placed_lines=tuple(state.get("placed_lines") or []),
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
        trusted_skus=trusted | frozenset(p["sku"] for p in state.get("seen_products") or []),
        seen_products=tuple(state.get("seen_products") or ()),
        earlier_results=reusable_results(state.get("call_log") or []),
        basket_lines=_basket_lines(state.get("basket") or {}, state.get("quotes") or {}),
        created_orders=tuple(state.get("created_orders") or ()),
        updated_orders=tuple(state.get("updated_orders") or ()),
        self_called=None if tier == "VERIFIED" else state.get("honorific_said"),
        honorific_asked=bool(state.get("honorific_asked")),
        flags=dict(state.get("flags") or {}),
        customer_said=_last_customer_text(state),
        last_agent_said=_last_agent_text(state),
        deletion_asked=bool(state.get('deletion_awaiting_for')
                            and state['deletion_awaiting_for'] == state.get('customer_id')),
        recent=_recent(state),
        judge=context.policy.judge if context.policy is not None else None,
    )


def _last_reply(state: HotState) -> str | None:
    """The agent's latest reply, before this turn's words are added."""
    for message in reversed(state.get("messages") or []):
        if isinstance(message, AIMessage):
            return str(message.content)
    return None


#: The products kept for later turns: enough for a conversation, small in the prompt.
SEEN_PRODUCTS = 15


def _passages_after(read: Mapping[str, str], shown: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """*read* with the organisers' passages the advisor was just shown, the latest last, at most PASSAGES_READ."""
    now = dict(read)
    policy, _ = shown_passages(shown)
    for passage in policy:
        if passage.get("text") and not passage.get("restricted") and not passage.get("superseded") and passage.get("chunk_id"):
            now.pop(str(passage["chunk_id"]), None)
            now[str(passage["chunk_id"])] = str(passage["text"])
    return dict(list(now.items())[-PASSAGES_READ:])


def _result_key(result: Mapping[str, Any]) -> str | None:
    """What a tool result is about: a later result about the same thing replaces it."""
    data = (result.get("result") or {}).get("data") or {}
    items = data.get("items") or [{}]
    return data.get("sku") or data.get("order_id") or items[0].get("sku")


def reusable_results(log: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    """The latest result per tool and subject, in the order they came: what the advisor need not ask again."""
    latest = {(entry.get("tool"), entry.get("key")): entry for entry in log}
    return tuple(entry for entry in log if latest.get((entry.get("tool"), entry.get("key"))) is entry)


def _basket_after(basket: Mapping[str, Mapping[str, Any]], results: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """The basket after *results*: a quote that names other products sets it, an order placed empties it."""
    current = {sku: dict(line) for sku, line in basket.items()}
    for result in results:
        envelope = result.get("result") or {}
        if not envelope.get("ok"):
            continue
        asked = result.get("args") or {}
        if result.get("name") == "order.create":
            current = {}
        elif result.get("name") == "pricing.get_quote" and (envelope.get("data") or {}).get("sku"):
            sku = envelope["data"]["sku"]
            others = [s for s in asked.get("basket_skus") or [] if s != sku]
            if others:
                current = {s: current.get(s, {"qty": 1}) for s in [*others, sku]}
            if sku in current:
                current[sku] = {"qty": int(asked.get("qty") or 1)}
    return current


def _basket_lines(basket: Mapping[str, Mapping[str, Any]], quotes: Mapping[str, int]) -> tuple[tuple[str, int, int], ...]:
    """``(sku, unit price, qty)`` per product when two or more are in the basket and all are quoted, else nothing."""
    if len(basket) < 2 or any(sku not in quotes for sku in basket):
        return ()
    return tuple((sku, int(quotes[sku]), int(line.get("qty") or 1)) for sku, line in basket.items())


def _products_in(results: Sequence[Mapping[str, Any]], seen: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """*seen* with the products in *results* added (a product seen again moves last), at most SEEN_PRODUCTS."""
    found = {p["sku"]: dict(p) for p in seen if p.get("sku")}
    for result in results:
        envelope = result.get("result") or {}
        if not envelope.get("ok"):
            continue
        data = envelope.get("data") or {}
        items = data.get("items") if result.get("name") == "catalog.search" else ([data] if data.get("sku") else [])
        for item in items or []:
            sku = item.get("sku")
            if not isinstance(sku, str):
                continue
            entry = found.pop(sku, {"sku": sku})
            if item.get("name"):
                entry["name"] = item["name"]
            price = item.get("final_price_vnd") or item.get("price_vnd") or item.get("list_price_vnd")
            if price:
                entry["price_vnd"] = int(price)
            found[sku] = entry
    return list(found.values())[-SEEN_PRODUCTS:]


def _address_as(state: HotState) -> str | None:
    """"chị Hoa" when the tier allows knowing it."""
    if state.get("tier") != "VERIFIED":
        return None
    return " ".join(x for x in (state.get("honorific"), state.get("customer_name")) if x) or None


def _placed(earlier: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The call's order lines with the ones *results* created, one per order id."""
    lines = {line["order_id"]: dict(line) for line in earlier}
    lines.update({line["order_id"]: line for line in actions.placed_lines(results)})
    return list(lines.values())


#: Tools whose numbers a later turn of the call may repeat: prices, discounts, fees and delivery days.
PRICED_TOOLS = frozenset({"pricing.get_quote", "catalog.search", "delivery.estimate"})


def _absorb(state: HotState, produced: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A run's tool results added to the turn's, with today's quotes, the orders seen and the failure count."""
    new_results = [{**r, "turn": state.get("turn_no") or 0} for r in produced]
    codes, _ = _seen_in({}, new_results)
    quotes = dict(state.get("quotes") or {})
    orders = list(state.get("known_orders") or [])
    created = list(state.get("created_orders") or [])
    deletion_recorded = bool(state.get("deletion_recorded"))
    callback_booked = bool(state.get("callback_booked"))
    pending_purchase = state.get("pending_purchase")
    updated = list(state.get("updated_orders") or [])
    failures = int(state.get("tool_failures") or 0)
    for result in new_results:
        envelope = result.get("result") or {}
        data = envelope.get("data") or {}
        if envelope.get("ok"):
            failures = 0
            if actions.deletion_succeeded(result["name"], envelope) and result["name"] == "memory.request_deletion":
                deletion_recorded = True
            callback_booked = callback_booked or result["name"] == "schedule.callback"
            if result["name"] == "pricing.get_quote" and data.get("sku"):
                quotes[data["sku"]] = int(data["final_price_vnd"])
            if result["name"] == "order.create" and data.get("order_id"):
                created.append({"order_id": data["order_id"], "sku": (result.get("args") or {}).get("sku"),
                                "no_address": not (result.get("args") or {}).get("address")})
                pending_purchase = None
            if result["name"] == "order.update":
                asked = result.get("args") or {}
                updated.append({k: asked.get(k) for k in ("order_id", "action", "new_variant_sku")})
            for order in data.get("orders") or ([data] if data.get("order_id") else []):
                if order.get("order_id") and order["order_id"] not in orders:
                    orders.append(order["order_id"])
        elif result.get("blocked_by") == "guardrail" and (envelope.get("error") or {}).get("code") == "CONFIRMATION_REQUIRED":
            pending_purchase = (envelope["error"].get("details") or {}).get("purchase_draft") or pending_purchase
        elif (envelope.get("error") or {}).get("code") in INFRASTRUCTURE_CODES:
            failures += 1
    log = [{"tool": r.get("name"), "key": _result_key(r),
            "result": json.dumps((r.get("result") or {}).get("data"), ensure_ascii=False, default=str)[:CALL_LOG_CHARS]}
           for r in new_results if (r.get("result") or {}).get("ok")]
    return {"tool_results": list(state.get("tool_results") or []) + new_results, "quotes": quotes,
            "call_log": [*(state.get("call_log") or []), *log][-CALL_LOG_SIZE:],
            "basket": _basket_after(state.get("basket") or {}, new_results),
            "known_orders": orders, "created_orders": created, "updated_orders": updated, "tool_failures": failures,
            "deletion_recorded": deletion_recorded, "callback_booked": callback_booked,
            "pending_purchase": pending_purchase,
            "placed_lines": _placed(state.get("placed_lines") or [], new_results),
            "trusted_skus": sorted(set(state.get("trusted_skus") or []) | codes),
            "seen_products": _products_in(new_results, state.get("seen_products") or [])}


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
    #: The reviews running beside this turn's stream.
    reviews: Reviews = field(default_factory=lambda: Reviews(None))
    #: The sentence stopped had already been said: the next run corrects it.
    correction: bool = False
    #: When the first token of the sentence being put together was generated, in ms of the turn.
    token_at: int | None = None


def _soft_summary(reviews: Sequence[Any]) -> dict[str, Any] | None:
    """The PolicyAgent's verdicts on a streamed answer's sentences, as one record for the trace."""
    if not reviews:
        return None
    questions = {name for review in reviews for name in review.probabilities}
    decided = [review.decided_by for review in reviews]
    return {
        "passed": all(review.passed for review in reviews),
        "reasons": sorted({reason for review in reviews for reason in review.reasons}),
        "decided_by": "decisions" if "decisions" in decided else decided[-1],
        "probabilities": {name: max(review.probabilities.get(name, 0.0) for review in reviews) for name in sorted(questions)},
        "seconds": round(sum(review.seconds for review in reviews), 3),
        "sentences": len(reviews),
    }


async def _streamed(state: HotState, context: HotContext, messages: list[Any], agent_context: AgentContext) -> dict[str, Any]:
    """Say the answer a sentence at a time, each checked before it is said.

    A blocked sentence is a draft blocked: the run is abandoned and
    regenerated with the reasons, at most twice, as the ``guard`` node would.
    What was already said cannot be taken back, so a regeneration after the
    first sentence was said goes on from it: the model is told what the
    customer heard and why the next sentence was stopped, and may call the
    tool it lacked ("gọi inventory_check trước"). Only a draft still blocked
    after that gets the lane's safe line. More than three sentences, unless
    reading an order back, are not said.
    """
    timing: dict[str, int | None] = {"first_token_ms": None, "filler_ms": None}
    blocked_drafts = list(state.get("blocked_drafts") or [])
    earlier = tuple(state.get("tool_results") or [])
    produced: list[dict[str, Any]] = []
    reasons: list[str] = []
    attempt = _Attempt()
    regenerations = 0
    view = agent_context
    #: Sentences said by runs whose next sentence was blocked: the next run goes on after them.
    carried: list[str] = []
    reviews = Reviews(_reviewer(state, context), head_start=review_head_start())
    view = replace(view, review_flags=reviews.flags)
    corrected = False
    try:
        while True:
            # A retry is checked against every tool result of the turn, the abandoned runs' included.
            attempt = _Attempt(said=list(carried), last_spoken=bool(carried), reviews=reviews)
            await _stream_once(state, context, messages, view, earlier + tuple(produced), timing, attempt)
            produced += [r for r in attempt.results if r not in produced]
            if not attempt.reasons:
                # The answer is out: what the reviews still running say comes before the turn ends.
                await reviews.recheck(earlier + tuple(produced))
                _flagged(attempt)
            if not attempt.reasons:
                break
            reasons = attempt.reasons
            blocked_drafts.append({"text": attempt.blocked, "reasons": attempt.reasons})
            if attempt.correction:
                if corrected:
                    attempt.reasons = []  # one correction a turn: a second is logged, not said
                    break
                corrected = True
            if regenerations >= MAX_REGENERATIONS:
                break
            regenerations += 1
            carried = list(attempt.said)
            view = replace(view, block_reasons=tuple(reasons), tool_results=earlier + tuple(produced),
                           already_said=tuple(unmarked(s) for s in carried))
    except Exception as error:  # noqa: BLE001 - section 4.9: a failure is never silence
        logger.exception("Advisor failed on call %s", state.get("call_id"))
        pending = error.partial.tool_results if isinstance(error, AdvisorFailure) else attempt.results
        produced += [r for r in pending if r not in produced]
        if attempt.said:
            # Part of the answer was heard: finish it safely; rule 1 counts the failure for the next turn.
            absorbed = _absorb(state, produced)
            line = _safe_line(state, produced)
            await _say(context, line, timing)
            return {**absorbed, "draft": {"text": " ".join([*attempt.said, line]), "streamed": True, "fallback": True,
                                          "error": _readable(error)},
                    "guard": {"passed": True, "streamed": True, "fallback": True}, "latency": timing,
                    "model_failures": int(state.get("model_failures") or 0) + 1}
        failed = await _model_failed(state, context, agent_context, produced, error,
                                     summary=state.get("working_summary"))
        return {**failed, "latency": timing}
    finally:
        reviews.close()

    update = _absorb(state, produced)
    update["loaded_skills"] = skill_book.after_turn(agent_context.skills, produced)
    draft = attempt.draft
    stats = {"model": getattr(draft, "model", None), "model_calls": getattr(draft, "model_calls", None),
             "seconds": round(getattr(draft, "seconds", 0.0), 3), "streamed": True}
    verdict: dict[str, Any] = {"passed": not attempt.reasons, "streamed": True, "sentences": len(attempt.said),
                               "hard": {"passed": not reasons, "reasons": reasons}}
    soft = _soft_summary(reviews.verdicts)
    if soft is not None:
        verdict["soft"] = soft
    if reviews.flagged:
        verdict["flagged_after_said"] = reviews.flagged
        logger.warning("Call %s: %d said sentence(s) flagged by the PolicyAgent", state.get("call_id"), len(reviews.flagged))
    text = " ".join(attempt.said)
    if attempt.reasons:
        line = _safe_line(state, produced)
        await _say(context, line, timing)
        text = f"{text} {line}".strip()
        verdict["fallback"] = True
        update["safe_lines"] = int(state.get("safe_lines") or 0) + 1
        logger.warning("Call %s: a streamed sentence was blocked after %d said; safe line said",
                       state.get("call_id"), len(attempt.said))
    moved = moved_callback(text, produced)
    if moved:  # Said rather than regenerated: nothing else of the answer was wrong, and LN-02 is the shop's own rule.
        line = fallback.LINES["callback_moved"].format(who=_who(state), moment=moved)
        await _say(context, line, timing)
        text = f"{text} {line}".strip()
    update.update(
        draft={"text": text, **stats, "fallback": bool(attempt.reasons)},
        guard=verdict,
        blocked_drafts=blocked_drafts,
        block_reasons=reasons,
        regen_count=regenerations,
        latency=timing,
        model_failures=0,
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
    waited = _waited(stream)
    try:
        async for event in waited:
            if _flagged(attempt):
                return attempt
            if event.kind == "tool_started":
                if timing["filler_ms"] is None and not attempt.said and context.emit is not None:
                    await context.emit("filler", fallback.LINES["filler"].format(who=_who(state)))
                    timing["filler_ms"] = _since(context)
            elif event.kind == "tools":
                attempt.results = list(event.results)
                pending = _confirmation_draft(attempt.results)
                if pending:
                    # This exact final question, rather than a model paraphrase, is what a later yes authorizes.
                    question = pending["question"]
                    await _say(context, question, timing)
                    attempt.said.append(question)
                    recorded = event.draft or Draft(text="", tool_results=[], model=None, model_calls=0, seconds=0)
                    attempt.draft = replace(recorded, text=question, tool_results=attempt.results)
                    return attempt
                line = view.consent.pop("read_back", None)
                if line and any(r.get("name") == "order.create" and (r.get("result") or {}).get("ok") for r in attempt.results):
                    # The customer agreed in this turn and has not heard the order: PB-09, read back once.
                    await _say(context, line, timing)
                    attempt.said.append(line)
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
                at = _since(context)
                timing["last_token_ms"] = at
                if attempt.token_at is None:
                    attempt.token_at = at
                for sentence in splitter.feed(text):
                    if not await _offer(state, context, sentence, earlier + tuple(attempt.results), attempt, timing):
                        return attempt
                    attempt.token_at = at  # what follows this sentence in the same chunk began here
                if not splitter.holding:
                    attempt.token_at = None
        rest = splitter.flush()
        if rest:
            await _offer(state, context, rest, earlier + tuple(attempt.results), attempt, timing)
        return attempt
    finally:
        await waited.aclose()
        await stream.aclose()


async def _waited(stream: Any) -> Any:
    """*stream*'s events, the wait for each timed as ``advisor``: what the customer waits on, not what runs ahead."""
    events = stream.__aiter__()
    while True:
        with stopwatch.span("advisor"):
            try:
                event = await events.__anext__()
            except StopAsyncIteration:
                return
        yield event


def _flagged(attempt: _Attempt) -> bool:
    """A review flagged what was said: stop the stream, and the next run corrects it (section 4.8)."""
    flag = attempt.reviews.take()
    if flag is None:
        return False
    text, reasons = flag
    attempt.correction = True
    attempt.blocked = text
    attempt.reasons = [f"Câu em vừa nói có lỗi: «{text}». {' '.join(reasons)} Khách nghe sai thì đính chính ngắn một câu; chỉ thiếu tool thì gọi tool, không nói lại câu đó. Không chuyển máy chỉ để sửa lỗi này, không thêm thông tin chưa có nguồn."]
    return True


def _established(state: HotState) -> dict[str, Any]:
    """What this call and the customer's record already show: an earlier turn's stock or order is not unsupported."""
    return {"quotes": dict(state.get("quotes") or {}), "orders_created": list(state.get("created_orders") or []),
            "orders_known": list(state.get("known_orders") or []),
            "orders_of_this_customer": list((state.get("brief") or {}).get("orders") or []),
            "earlier_tool_results": list(state.get("call_log") or []),
            "prices_quoted_before": [p.get("price_quoted_vnd") for p in (state.get("brief") or {}).get("products_advised") or []
                                     if p.get("price_quoted_vnd")]}


def _reviewer(state: HotState, context: HotContext) -> Any:
    """How this turn's sentences reach the PolicyAgent, with what it needs to read them fairly."""
    if context.policy is None:
        return None
    tier = state.get("tier") or "UNKNOWN"
    policy, playbook = shown_passages(_passages(state))
    snippets = tuple(dict.fromkeys((*(state.get("passages_read") or {}).values(),
                                    *(str(p["text"]) for p in (*policy, *playbook) if p.get("text") and not p.get("restricted")))))
    earlier = _established(state)
    said = tuple(str(m.content) for m in (state.get("messages") or [])[-CUSTOMER_WORDS:] if isinstance(m, HumanMessage))
    logger.info("Passages shown for call %s turn %s: %s", state.get("call_id"), state.get("turn_id"),
                [p.get("chunk_id") for p in (*policy, *playbook)])

    async def review(text: str, results: tuple[dict[str, Any], ...]) -> Any:
        # Runs beside the stream (Reviews): its wall time is the stopwatch's "policy", counted once however many overlap.
        with stopwatch.span("policy"):
            view = guard_input(state, context, text, results)
            return await context.policy.review(PolicyInput(text=text, tool_results=results, tier=tier,
                                                           policy_snippets=snippets, earlier=earlier, customer_said=said,
                                                           open_amounts=open_amounts(view)))
    return review


def _confirmation_draft(results: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    for result in reversed(results):
        error = (result.get("result") or {}).get("error") or {}
        if result.get("name") == "order.create" and result.get("blocked_by") == "guardrail" and error.get("code") == "CONFIRMATION_REQUIRED":
            return (error.get("details") or {}).get("purchase_draft")
    return None


def _safe_line(state: HotState, produced: list[dict[str, Any]]) -> str:
    """The line said when no draft could be trusted; one that says so when this turn placed an order."""
    placed = any(r.get("name") == "order.create" and (r.get("result") or {}).get("ok") for r in produced)
    return fallback.line("order_placed", _who(state)) if placed else fallback.safe_line(state.get("lane") or "NEW", _who(state))


def same_sentence(one: str, other: str) -> bool:
    """Whether two sentences say the same thing: equal, or, from five words up, the shorter one's words almost all
    in the longer. A regeneration repeats its last line with a word or two changed, not word for word."""
    a, b = intake_text.plain(one).split(), intake_text.plain(other).split()
    if a == b:
        return True
    short, long = sorted((set(a), set(b)), key=len)
    return len(short) >= 5 and len(short & long) >= 0.9 * len(short)


async def _offer(state: HotState, context: HotContext, sentence: str, results: tuple[dict[str, Any], ...],
                 attempt: _Attempt, timing: dict[str, int | None]) -> bool:
    """Check one sentence and say it; False when it was blocked."""
    spoken = unmarked(sentence)
    if not spoken and attempt.said:
        if attempt.last_spoken:
            attempt.said[-1] += " " + sentence
        return True  # A citation arriving after speech is metadata, not an empty reply.
    if any(same_sentence(spoken, unmarked(said)) for said in attempt.said):
        attempt.last_spoken = False
        return True  # already said in this answer: a regeneration going on from it repeats its last line
    if len(attempt.said) >= MAX_SENTENCES and not ORDER_SUMMARY.search(" ".join([*attempt.said, sentence])):
        attempt.last_spoken = False
        return True  # past the length the rules allow: not said, the stream goes on to its end
    with stopwatch.span("guard"):
        reasons = list(check(guard_input(state, context, spoken, results)).reasons)
    if reasons:
        attempt.reasons, attempt.blocked = reasons, " ".join([*attempt.said, sentence])
        return False
    spoken = clean(spoken)
    attempt.reviews.add(spoken, results)
    await attempt.reviews.head()
    if _flagged(attempt):
        # This sentence stays unsaid. If the flag is on it alone, nothing needs correcting either.
        if attempt.blocked == spoken:
            attempt.correction = False
            attempt.reasons = [reason.split("». ", 1)[-1] for reason in attempt.reasons]
        return False
    await _say(context, spoken, timing, token_at=attempt.token_at)
    attempt.said.append(sentence)
    attempt.last_spoken = True
    return True


async def _say(context: HotContext, text: str, timing: dict[str, int | None], *, token_at: int | None = None) -> None:
    """Hand a checked sentence to the channel.

    ``eval/huong-dan-do-latency.md``: TTFT ends at the first token generated and Total at the last. A sentence that
    was blocked was never said, so its tokens do not count. ``said_first_ms`` is when the customer can see it, after
    the sentence is whole and checked. A line of the harness has no tokens: it counts when it is said.
    """
    now = _since(context)
    if timing["first_token_ms"] is None:
        timing["first_token_ms"] = token_at if token_at is not None else now
        timing["said_first_ms"] = now
    if token_at is None:
        timing["last_token_ms"] = now
    if context.emit is not None:
        await context.emit("sentence", text)


def _since(context: HotContext) -> int:
    """Milliseconds since the turn's request arrived, on the monotonic clock."""
    return int((time.perf_counter() - (context.arrived or time.perf_counter())) * 1000)


def _who(state: HotState) -> str:
    """How the harness's own lines address the customer: the profile's form, else the one they used, else anh/chị."""
    if state.get("tier") == "VERIFIED" and state.get("honorific"):
        return str(state["honorific"])
    return str(state.get("honorific_said") or "anh/chị")


# ── 5. guard ──────────────────────────────────────────────────────────────


async def guard(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.5: the hard check, then ``PolicyAgent``.

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
    with stopwatch.span("guard"):
        view = guard_input(state, context, text, results)
        hard = check(view)
    moved = moved_callback(text, results)
    if moved:
        hard = hard._replace(passed=False, reasons=(*hard.reasons, f"Lịch gọi lại đã dời sang {moved} (LN-02); phải báo khách giờ mới."))
    verdict: dict[str, Any] = {"hard": {"passed": hard.passed, "reasons": list(hard.reasons)}}
    reasons = list(hard.reasons)
    if hard.passed and context.policy is not None:
        with stopwatch.span("policy"):
            soft = await context.policy.review(PolicyInput(
                text=text, tool_results=results, tier=tier, policy_snippets=view.policy_texts,
                earlier=_established(state),
                customer_said=_last_customer_text(state),
                open_amounts=open_amounts(view)))
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
    line = fallback.safe_line(state.get("lane") or "NEW", _who(state))
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
    shown = [p for p in (*policy, *playbook) if p.get("text") and not p.get("restricted")]
    passages = tuple(str(p["text"]) for p in shown)
    return GuardInput(
        text=text,
        tool_results=results,
        tier=tier,
        customer_said=tuple(str(m.content) for m in state.get("messages") or [] if isinstance(m, HumanMessage)),
        policy_texts=(*(state.get("passages_read") or {}).values(), *passages),
        priced_texts=(*(state.get("passages_read") or {}).values(),
                      *(str(p["text"]) for p in shown if (p.get("source") or "policy") == "policy")),
        brief_prices=tuple(int(p["price_quoted_vnd"]) for p in brief.get("products_advised") or [] if p.get("price_quoted_vnd")),
        tokens=frozenset(context.vault.entries),
        quotes={**(state.get("quotes") or {}), **_quoted_in(results)},
        earlier_numbers=_earlier_numbers(state.get("call_log") or []),
        earlier_counts=frozenset(int(n) for entry in state.get("call_log") or [] for n in re.findall(r"\d+", str(entry.get("result") or ""))),
        basket_total=_basket_total(state, results),
        warnings=tuple(state.get("freshness") or []) if tier == "VERIFIED" else (),
        promotions=promotions(),
        on=state.get("on"),
    )


#: The earlier results whose numbers the customer may hear again: what the shop stated, not a search's list prices.
STATED_TOOLS = frozenset({"pricing.get_quote", "delivery.estimate", "order.status", "order.create", "order.update"})


def _earlier_numbers(log: Sequence[Mapping[str, Any]]) -> frozenset[int]:
    return frozenset(int(n) for entry in log if entry.get("tool") in STATED_TOOLS
                     for n in re.findall(r"\d+", str(entry.get("result") or "")))


def _basket_total(state: HotState, results: Sequence[Mapping[str, Any]]) -> int | None:
    quotes = {**(state.get("quotes") or {}), **_quoted_in(results)}
    lines = _basket_lines(_basket_after(state.get("basket") or {}, results), quotes)
    return sum(price * qty for _, price, qty in lines) or None


def _quoted_in(results: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """This turn's quotes, not yet in the state: a basket's total may add them."""
    found = {}
    for result in results:
        data = (result.get("result") or {}).get("data") or {}
        if result.get("name") == "pricing.get_quote" and data.get("sku") and data.get("final_price_vnd") is not None:
            found[str(data["sku"])] = int(data["final_price_vnd"])
    return found


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
        # HANDOFF_AUTO_ACCEPT (test runs): the system accepts at once and the agent goes on answering.
        auto = handoff_auto_accept()
        update["mode"] = "speak" if auto else "copilot"
        update["handoff"] = {
            "status": "accepted" if auto else "pending",
            "accepted_by": AUTO_ACCEPTOR if auto else None,
            "ticket_id": ((handoff.get("result") or {}).get("data") or {}).get("ticket_id"),
            "reason": brief.get("escalation_reason"),
            "brief": brief,
        }
        # A person has the call now: the failures that sent it there are theirs to judge, not rule 1's again.
        update.update(tool_failures=0, model_failures=0, safe_lines=0)
    pending = state.get("pending_purchase")
    if pending and pending.get("status") == "pending" and pending.get("issued_turn_id") == turn_id:
        if not streamed:
            text = pending["question"]
        used = []
    if not streamed and text:
        # Said whole: the harness's own lines, a fallback, a draft that did not stream.
        await _say(context, text, timing)
    update["reply"] = {"text": text, "used_lines": used}
    update["messages"] = [AIMessage(content=text, id=f"agent-{turn_id}")]
    update["latency"] = timing
    return update


#: Who accepts a handoff when ``HANDOFF_AUTO_ACCEPT`` is on: no person, and the record says so.
AUTO_ACCEPTOR = "auto"

# ── 7. persist ────────────────────────────────────────────────────────────


async def persist(state: HotState, runtime: Runtime[HotContext]) -> dict[str, Any]:
    """Section 4.7: the checkpointer has saved working memory by now; this
    writes the transcript row and the ``calls`` projection through the store
    the caller handed in (the API's tables, or the evaluation runner's trace)."""
    store = runtime.context.store
    if store is not None:
        await store.persist(state)
    owner = state.get('customer_id') if state.get('tier') == 'VERIFIED' else None
    pending = state.get('deletion_awaiting_for')
    said = intake_text.plain(_last_customer_text(state) or '')
    if pending != owner or actions.DECLINED.search(said) or actions.AGREED.search(said):
        pending = None
    if owner and actions.ASKED_TO_DELETE.search(intake_text.plain((state.get('reply') or {}).get('text') or '')):
        pending = owner
    if state.get('deletion_recorded'):
        pending = None
    return {'deletion_awaiting_for': pending}


# ── helpers ───────────────────────────────────────────────────────────────


#: Told to the advisor when the turn's words were searched and nothing relevant came back (section 7.3).
NOTHING_RELEVANT = "Tài liệu: không có đoạn nào đủ liên quan tới câu khách vừa nói."


def _passages(state: HotState) -> tuple[dict[str, Any], ...]:
    """The passages the advisor reads this turn: none when the best one is under θ, as nothing is relevant then.

    An internal passage reaches it as the instruction it stands for, never its text. A passage not in force
    never does, but the changelog entry that replaced it comes along, or a customer quoting the old rule
    would hear a different number with no reason for it.
    """
    found = state.get("knowledge") or {}
    if not found.get("hits") or found.get("reason") == "no_match":
        return ()
    explains = set(found.get("explains") or ())
    return (*(hit for hit in found["hits"] if hit.get("chunk_id") not in explains),
            *({**entry, "explains": True} for entry in found.get("changelog") or () if entry.get("chunk_id") in explains))


#: The knowledge search found the documents do not answer the turn (nothing relevant, or a passage
#: saying the documents have no information on it): what the advisor does then, by BTC's answer
#: (DIEU-CHINH-DE 4: a transfer is a success for an out-of-scope question). Said next to the
#: passages, where the model reads them, because a passage that says "phải nói không có thông tin"
#: otherwise outweighs rule 4 (FIX-07, 2026-11-01).
NO_ANSWER = ("Tìm trong tài liệu không thấy đoạn khớp câu khách vừa hỏi; điều này chưa có nghĩa là shop không có. Câu về "
             "sản phẩm, giá, đơn thì xem mục \"Đã tra trong cuộc này\" rồi tra tool phù hợp. Cả hai đều không trả lời được "
             "thì làm theo luật 4.")


#: When the customer's orders fall under different versions of a policy and the question names none.
ORDER_VERSION = ("Đoạn trên đúng cho đơn mới nhất của khách; đơn đặt ngày {days} theo bản chính sách khác. Khách "
                 "chưa nói đơn nào thì hỏi đơn nào trước khi nêu thời hạn hay mức phí.")


def _knowledge_note(state: HotState) -> str | None:
    """What the search says when the documents have no answer: a fact of the retrieval, not of the words."""
    found = state.get("knowledge") or {}
    if not found:
        return None
    if found.get("reason") == "no_match":
        return f"{NOTHING_RELEVANT} {NO_ANSWER}"
    if found.get("abstain") and found.get("reason") == "absence":
        return NO_ANSWER
    if found.get("version_differs"):
        return ORDER_VERSION.format(days=", ".join(found["version_differs"]))
    return None


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
