"""``after_call``: what the call leaves behind. ``docs/design.md`` sections 4.7 and 5.4.

Memory poisoning is stopped here: facts are written only to a customer the
call confirmed. VERIFIED writes to that customer and confirms the keys seen.
UNKNOWN with a key (a new caller, a Zalo identity, a number they typed that
matched nobody) creates a customer on those keys. A caller who gave a number
that belongs to a customer and never clearly answered the confirming question
stays unconfirmed: what they said is kept for that customer as
*unconfirmed*, beside their facts and never over them, and the next call the
customer makes themselves settles it (their own facts win; it becomes theirs
unless they say the contact was not them). So a chat that leaves a number and
goes is remembered when that number calls (Case 2, one customer across channels), and
a stranger typing someone's number writes nothing of theirs. As for AMBIGUOUS
at hang-up, nothing is written to anyone: a model opinion cannot grant
permission to update another person's memory.

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
import re
from typing import Any, Awaitable, Callable, Sequence

from ...agents.memory import MemoryAgent
from ...agents.qa import QaAgent
from ...components.memory import gate, ledger
from ...components.memory.ontology import NOTE_SLOT, slot

logger = logging.getLogger(__name__)

#: Opens the ``admin`` role's tools when a call needs them: only to carry out
#: a deletion, so a run without one never starts those servers.
AdminTools = Callable[[], Awaitable[Any]]

#: The customer saying an earlier contact under their number was not theirs.
NOT_ME = re.compile(r"(không phải (?:tôi|em|anh|chị|mình|tui)\b|(?:tôi|em|anh|chị|mình|tui) (?:có )?(?:không|chưa) "
                    r"(?:hề )?(?:nhắn|hỏi|gọi|liên hệ)\b|nhầm (?:số|người)\b|ai (?:đó )?(?:nhắn|gọi) (?:bằng|lấy) số)",
                    re.IGNORECASE)


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
    if requested_deletion(tool_log):
        candidates = []
        remembered = await _forget(call, admin)
    else:
        candidates = await memory.extract(transcript, tool_log, on=call["on"])
        settled = _settle_identity(call)
        claimed = (call.get("provisional") or {}).get("customer_id")
        if settled.get("tier") == "PROBABLE" and claimed:
            remembered = await _hold(claimed, settled, candidates, writer=writer)
        else:
            remembered = await _remember(settled, candidates, writer=writer, memory=memory)
            if remembered.get("status") == "done" and settled.get("tier") == "VERIFIED":
                denied = any(NOT_ME.search(str(line.get("text") or "")) for line in transcript
                             if line.get("speaker") == "customer")
                await writer.data("memory_settle_unconfirmed", customer_id=remembered["customer_id"],
                                  confirm=not denied, on=call["on"])
    tags = await qa.tag(candidates, returning=bool(call.get("returning")))
    return {**remembered, "tags": tags}


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


async def _hold(customer_id: str, call: dict[str, Any], candidates: list[gate.Candidate], *, writer: Any) -> dict[str, Any]:
    """What a caller who stated *customer_id*'s number said, kept for them as unconfirmed; nothing is theirs yet."""
    profile = await writer.data("memory_get_profile", customer_id=customer_id, on=call["on"])
    current = [f for f in (profile or {}).get("facts") or [] if f.get("status") == "active"]
    source = {"call_id": str(call["call_id"]), "call": "unconfirmed", "channel": call.get("channel")}
    decisions = [{**d.as_dict(), "operation": "add", "unconfirmed": True}
                 for d in plan_writes(candidates, current, source=source, on=call["on"]) if d.operation in ("add", "update")]
    if not decisions:
        return {"status": "skipped", "reason": "identity still probable at hang-up; nothing to keep", "memory_writes": []}
    held = await writer.data("memory_commit_facts", customer_id=customer_id, decisions=decisions, on=call["on"])
    if held is None:
        return {"status": "failed", "reason": "the ledger refused the unconfirmed facts", "memory_writes": []}
    logger.info("after_call %s: %d facts kept unconfirmed for %s", call["call_id"], len(decisions), customer_id)
    return {"status": "unconfirmed", "customer_id": customer_id, "held": len(decisions), "memory_writes": []}


def _settle_identity(call: dict[str, Any]) -> dict[str, Any]:
    """Only the identity flow may verify a caller; an extraction model cannot grant write access."""
    if call.get("tier") != "VERIFIED" and (call.get("provisional") or {}).get("customer_id"):
        return {**call, "tier": "PROBABLE", "customer_id": None}
    return call


async def _remember(call: dict[str, Any], candidates: list[gate.Candidate], *, writer: Any, memory: MemoryAgent, episode: bool = True) -> dict[str, Any]:
    tier = call.get("tier") or "UNKNOWN"
    if tier in ("PROBABLE", "AMBIGUOUS"):
        return {"status": "skipped", "reason": f"identity still {tier.lower()} at hang-up", "memory_writes": []}
    customer_id = call.get("customer_id") if tier == "VERIFIED" else None
    eligible = []
    for key in call.get("keys_seen") or []:
        matches = key.get("customer_ids") or []
        if (customer_id is not None and customer_id not in matches) or (customer_id is None and matches):
            continue
        eligible.append(key)
    if customer_id is None:
        eligible = [key for key in eligible if key.get("from_connection")] or eligible[:1]
    keys = [{"key_type": key["kind"], "key_hash": key["digest"]} for key in eligible]
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
    decisions = [d._replace(source={**d.source, "observed_at": call["turn_times"][d.source["turn"]]})
                 if d.source.get("turn") in call.get("turn_times", {}) else d for d in decisions]
    committed = await writer.data("memory_commit_facts", customer_id=customer_id,
                                  decisions=[d.as_dict() for d in decisions], on=call["on"])
    if committed is None:
        return {"status": "failed", "reason": "the ledger refused the call's facts", "memory_writes": []}
    if not episode:
        return {"status": "done", "customer_id": customer_id, "memory_writes": committed.get("memory_writes") or []}
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
        if candidate.slot == "order_ids" and candidate.said_by == "tool":
            previous = next((f["value"] for f in current if f["slot"] == "order_ids" and f["status"] == "active"), [])
            candidate = candidate._replace(value=list(dict.fromkeys([*previous, *candidate.value])))
        verdict = gate.check(candidate, current, open_notes=notes, settled=recorded)
        if not verdict.passed:
            continue
        decision = ledger.plan(candidate, verdict, current, source=source, on=on)
        if decision.operation == "skip":
            continue
        decisions.append(decision)
        if candidate.slot is None:
            notes += 1
    # A fresh quote is one snapshot: missing promotion fields must not survive from an older one.
    snapshot = {c.slot: c for c in settled if c.said_by == "tool"}
    if all(s in snapshot for s in ("product_advised", "price_quoted_vnd", "quoted_on")):
        quoted = snapshot["quoted_on"]
        for name in ("promo_code", "promo_expiry"):
            if name in snapshot:
                continue
            for held in current:
                if held["slot"] == name and held["status"] == "active":
                    origin = {**source, "turn": quoted.turn, "said_by": "tool", "extractor_version": quoted.extractor}
                    decisions.append(ledger.Decision("invalidate", name, held["value"], held["kind"], origin,
                                                     replaces=held["fact_id"]))
        old_product = next((f["value"] for f in current if f["slot"] == "product_advised" and f["status"] == "active"), None)
        if old_product != snapshot["product_advised"].value and "variant_sku" not in snapshot:
            for held in current:
                if held["slot"] == "variant_sku" and held["status"] == "active":
                    origin = {**source, "turn": quoted.turn, "said_by": "tool", "extractor_version": quoted.extractor}
                    decisions.append(ledger.Decision("invalidate", "variant_sku", held["value"], held["kind"], origin,
                                                     replaces=held["fact_id"]))
    return decisions


def _customer_claim(candidate: gate.Candidate) -> bool:
    spec = slot(candidate.slot or "")
    return bool(spec and spec.kind in gate.RECORDS and candidate.said_by == "customer")
