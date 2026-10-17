"""``after_call``: what the call leaves behind. ``docs/design.md`` sections 4.7 and 5.4.

Memory poisoning is stopped here: facts are written only to a customer the
call confirmed. VERIFIED writes to that customer and confirms the keys seen.
UNKNOWN with a key (a new caller, a Zalo identity, a number they typed that
matched nobody) creates a customer on those keys. A caller who gave a number
that belongs to a customer and never clearly answered the confirming question
is that customer only if the MemoryAgent, reading the whole call, finds they
said so (section 4.2, step 4); otherwise, as for AMBIGUOUS at hang-up,
nothing is written to anyone, since a guess would put one person's facts in
another's file.

A call in which the customer asked to be forgotten (QT-06) writes nothing
either: the request recorded during the call is carried out here, under the
``admin`` role, and the next call is a stranger's.

The steps of section 5.4: ``extract`` (the MemoryAgent), ``gate`` (the win
rule inside the call, then each candidate against the ledger), ``commit``
(through ``memory.commit_facts``, which decides again under the customer's
lock), ``summarize`` (one episode line, the next brief's precomputed part).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Sequence

from ...agents.memory import MemoryAgent
from ...agents.qa import QaAgent
from ...components.memory import gate, ledger
from ...components.memory.ontology import NOTE_SLOT, slot

logger = logging.getLogger(__name__)

#: Opens the ``admin`` role's tools when a call needs them: only to carry out
#: a deletion, so a run without one never starts those servers.
AdminTools = Callable[[], Awaitable[Any]]


async def after_call(
    call: dict[str, Any],
    transcript: Sequence[dict[str, Any]],
    tool_log: Sequence[dict[str, Any]],
    *,
    writer: Any,
    memory: MemoryAgent,
    qa: QaAgent,
    admin: AdminTools | None = None,
) -> dict[str, Any]:
    """Run both branches; what was written, and how the call was tagged.

    ``call`` is ``{call_id, channel, on, tier, customer_id, keys_seen,
    provisional}``;
    ``transcript`` the spoken turns ``{speaker, text, turn}``, tokenised;
    ``tool_log`` every tool call ``{name, args, result, turn}``; ``writer``
    a ``ToolBox`` holding the ``memory_writer`` role; ``admin`` opens the
    ``admin`` role's ``ToolBox`` when a deletion must be carried out.
    """
    candidates = await memory.extract(transcript, tool_log, on=call["on"])
    if requested_deletion(tool_log):
        remembered = await _forget(call, admin)
    else:
        settled = await _settle_identity(call, transcript, writer=writer, memory=memory)
        remembered = await _remember(settled, candidates, writer=writer, memory=memory)
    tags = await qa.tag(candidates, returning=bool(call.get("returning")))
    score = await qa.score(transcript, tool_log)
    return {**remembered, "tags": tags, "qa": score}


def requested_deletion(tool_log: Sequence[dict[str, Any]]) -> bool:
    """Whether the customer asked to be forgotten in this call, and the request was recorded."""
    return any(c.get("name") == "memory.request_deletion" and (c.get("result") or {}).get("ok") for c in tool_log)


async def _forget(call: dict[str, Any], admin: AdminTools | None) -> dict[str, Any]:
    """Carry out a recorded deletion; nothing of this call is written (QT-06)."""
    customer_id = call.get("customer_id") if call.get("tier") == "VERIFIED" else None
    if customer_id is None:
        return {"status": "skipped", "reason": "deletion asked by an unconfirmed caller", "memory_writes": []}
    if admin is None:
        return {"status": "deletion_pending", "customer_id": customer_id, "memory_writes": [],
                "reason": "no admin role here; the recorded request waits for it"}
    deleted = await (await admin()).data("memory_delete_customer", customer_id=customer_id)
    if deleted is None:
        return {"status": "failed", "reason": "the deletion could not be carried out", "memory_writes": []}
    logger.info("after_call %s: customer %s forgotten on request", call["call_id"], customer_id)
    return {"status": "deleted", "customer_id": customer_id, "memory_writes": [], "deleted": deleted.get("deleted")}


async def _settle_identity(call: dict[str, Any], transcript: Sequence[dict[str, Any]], *, writer: Any,
                           memory: MemoryAgent) -> dict[str, Any]:
    """The call as it is remembered: a caller who gave a customer's number and never clearly answered becomes
    that customer when the whole call shows it, and nobody otherwise (section 4.2, step 4).

    Nobody, not a new customer: a new identity on a number that already
    belongs to someone would make every later call from it ambiguous.
    """
    provisional = call.get("provisional")
    if call.get("tier") == "VERIFIED" or not provisional or not provisional.get("customer_id"):
        return call
    profile = await writer.data("memory_get_profile", customer_id=provisional["customer_id"], on=call["on"])
    advised = [str(f.get("value")) for f in (profile or {}).get("facts") or []
               if f.get("slot") in ("product_advised", "order_id") and f.get("status") == "active"]
    who = " ".join(x for x in (provisional.get("honorific"), provisional.get("name")) if x) or "chưa rõ tên"
    described = who + (f"; trước đây: {', '.join(advised)}" if advised else "")
    if await memory.same_person(transcript, profile=described) is True:
        logger.info("after_call %s: the call shows the caller is %s", call["call_id"], provisional["customer_id"])
        return {**call, "tier": "VERIFIED", "customer_id": provisional["customer_id"]}
    return {**call, "tier": "PROBABLE"}


async def _remember(call: dict[str, Any], candidates: list[gate.Candidate], *, writer: Any, memory: MemoryAgent) -> dict[str, Any]:
    tier = call.get("tier") or "UNKNOWN"
    keys = [{"key_type": k["kind"], "key_hash": k["digest"]} for k in call.get("keys_seen") or []]
    if tier in ("PROBABLE", "AMBIGUOUS"):
        return {"status": "skipped", "reason": f"identity still {tier.lower()} at hang-up", "memory_writes": []}
    customer_id = call.get("customer_id") if tier == "VERIFIED" else None
    if customer_id is None and not keys:
        return {"status": "skipped", "reason": "anonymous: no key to remember them by", "memory_writes": []}
    if keys or customer_id is None:
        confirmed = await writer.data("memory_confirm_identity", keys=keys, customer_id=customer_id)
        if not confirmed:
            return {"status": "failed", "reason": "could not confirm the identity", "memory_writes": []}
        customer_id = confirmed["customer_id"]

    profile, history = await asyncio.gather(
        writer.data("memory_get_profile", customer_id=customer_id, on=call["on"]),
        writer.data("memory_get_episodes", customer_id=customer_id, n=10),
    )
    current = list((profile or {}).get("facts") or [])
    number = len((history or {}).get("episodes") or []) + 1
    source = {"call_id": str(call["call_id"]), "call": f"call_{number}", "channel": call.get("channel")}
    decisions = plan_writes(candidates, current, source=source, on=call["on"])
    committed = await writer.data("memory_commit_facts", customer_id=customer_id,
                                  decisions=[d.as_dict() for d in decisions], on=call["on"])
    if committed is None:
        return {"status": "failed", "reason": "the ledger refused the call's facts", "memory_writes": []}
    episode = await memory.summarize(candidates, call_number=number, day=call["on"], channel=call.get("channel") or "web")
    await writer.data("memory_commit_episode", customer_id=customer_id, episode={
        "call_id": str(call["call_id"]), "channel": call.get("channel"), "date": call["on"], **episode,
        "source_turn_span": [min((c.turn for c in candidates), default=0), max((c.turn for c in candidates), default=0)],
    })
    writes = committed.get("memory_writes") or []
    logger.info("after_call %s: %d facts written for %s", call["call_id"], len(writes), customer_id)
    return {"status": "done", "customer_id": customer_id, "memory_writes": writes, "episode": episode["summary"]}


def plan_writes(candidates: Sequence[gate.Candidate], current: list[dict[str, Any]], *, source: dict[str, Any],
                on: str) -> list[ledger.Decision]:
    """The call's candidates through the gate, as ledger decisions (section 5.4, ``gate`` and ``commit``).

    The win rule settles the call first (the newest word, the tool over the
    customer); each survivor is then measured against the ledger, a
    customer's contrary claim about a record becoming a disputed fact. Open
    notes count against the customer's cap as they are added.
    """
    settled = gate.settle(candidates)
    recorded = {c.slot: c for c in settled if c.slot and not _customer_claim(c)}
    notes = sum(1 for f in current if f.get("slot") == NOTE_SLOT and f.get("status") == "active")
    decisions = []
    for candidate in settled:
        verdict = gate.check(candidate, current, open_notes=notes, settled=recorded)
        if not verdict.passed:
            continue
        decision = ledger.plan(candidate, verdict, current, source=source, on=on)
        if decision.operation == "skip":
            continue
        decisions.append(decision)
        if candidate.slot is None:
            notes += 1
    return decisions


def _customer_claim(candidate: gate.Candidate) -> bool:
    spec = slot(candidate.slot or "")
    return bool(spec and spec.kind in gate.RECORDS and candidate.said_by == "customer")
