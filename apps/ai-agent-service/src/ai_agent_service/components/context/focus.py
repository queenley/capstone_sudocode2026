"""What one turn needs in its prompt: the situation's rules and the brief lines it can use.

A guess from the customer's words may only add guidance here or keep it for the turn; it never takes a tool away or
decides anything (``components.orchestration.rules``). So every doubt keeps more, not less:

- a rule pack is loaded by the words of the last few messages *or* by what the call already holds (a product shown, an
  order placed) *or* by a tool called this turn, and all of them when a guard blocked the draft, since its reason may
  name a rule;
- the brief is whole on the call's first turn, on a turn with no recognised topic and after a block. Otherwise it keeps
  what is open and what the topic reads, and drops the history already said. ``must_not_ask`` stays in the lane's
  instruction either way, and a line's number never changes, so ``[Bn]`` still traces back to its facts.

``ADVISOR_CONTEXT=full`` turns all of it off: every rule and every line, the before of a before/after measurement.
"""

from __future__ import annotations

import os
import re
from typing import Any, Collection, Iterable, Mapping, Sequence

from ..intake.text import plain

#: Most brief lines of a focused turn: what is open is kept beyond it, the rest fills it.
MAX_LINES = 6

TOPICS = {
    "purchase": re.compile(r"\b(mua|lay|dat|chot|len don|giao|ship|thanh toan|cod|chuyen khoan|gia|bao nhieu|size|mau)\b"),
    "orders": re.compile(r"\b(don|van don|giao chua|doi size|doi hang|doi san pham|tra hang|hoan tien|doi dia chi)\b"),
    "callback": re.compile(r"\b(goi lai|hen|lien he lai|bao lai|ban voi|hoi y kien|hoi (chong|vo|ong xa|ba xa|nguoi nha|gia dinh|bo me)"
                           r"|suy nghi|can nhac)\b"),
    "objection": re.compile(r"\b(dat|mac|so sanh|ben khac|cho khac|shop khac|re hon|giam gia|bot|khuyen mai|km|het han|gia cu)\b"),
    "account": re.compile(r"\b(gio hang|tai khoan|website|tren web|dang nhap)\b"),
    "second_air": re.compile(r"\b(may loc|loc khong khi|phong thu hai|hai may|2 may|khuyen mai|km)\b"),
    "advice": re.compile(r"\b(tu van|san pham|dang tim|can tim|loai nao|mau nao|phong|ngan sach|phu hop|nen chon|goi y|con hang|het hang"
                         r"|mua|lay|dat|gia|size)\b"),
    "past": re.compile(r"\b(lan truoc|hom truoc|bua truoc|truoc day|da mua|da dat|da tu van|noi roi|bao roi|gia cu|chinh sach cu|nghe noi)\b"),
    "deletion": re.compile(r"\b(xoa|du lieu|thong tin cua|quen so|khong luu)\b"),
}
#: A tool called this turn -> the pack that says how to use what it returned.
TOOL_PACKS = {"pricing_get_quote": "purchase", "delivery_estimate": "purchase", "order_create": "purchase",
              "order_status": "orders", "order_update": "orders", "schedule_callback": "callback",
              "account_cart": "account", "account_orders": "account"}
#: The brief's lines a topic reads, by ``BriefLine.kind``.
LINES_FOR = {"purchase": ("need", "product", "quote"), "advice": ("need", "product", "quote"),
             "objection": ("product", "quote", "need"), "orders": ("order", "product"), "callback": ("product", "quote")}
#: Kept on every turn: what is unfinished, and what must be checked with the customer.
ALWAYS = ("open", "other")


def full() -> bool:
    return os.environ.get("ADVISOR_CONTEXT", "").strip().lower() == "full"


def topics(text: str | None) -> set[str]:
    words = plain(text or "").lower()
    return {name for name, pattern in TOPICS.items() if pattern.search(words)}


def packs(context: Any, known: Iterable[str], called: Collection[str] = ()) -> tuple[str, ...]:
    """The rule packs of this turn, in the file's order."""
    known = tuple(known)
    if full() or context.block_reasons:
        return known
    said = " ".join(text for speaker, text in context.recent if speaker == "customer")
    wanted = topics(f"{said} {context.customer_said or ''}")
    wanted |= {TOOL_PACKS[name] for name in called if name in TOOL_PACKS}
    if context.pending_purchase or context.seen_products or context.quotes or context.placed_lines:
        wanted |= {"purchase", "advice"}
    if context.created_orders or context.updated_orders or context.known_orders:
        wanted.add("orders")
    if context.account_id:
        wanted.add("account")
    if context.brief_lines:
        wanted.add("past")
    if any(line.kind == "open" for line in context.brief_lines):
        wanted |= {"callback", "objection"}
    return tuple(name for name in known if name in wanted)


def lines(brief: Sequence[Any], said: str | None, *, first_turn: bool, blocked: bool) -> list[Any]:
    """The brief lines of this turn, in their order and with their numbers."""
    wanted = [kind for topic in sorted(topics(said)) for kind in LINES_FOR.get(topic, ())]
    if full() or first_turn or blocked or not wanted:
        return list(brief)
    keep = {id(line) for line in brief if line.kind in ALWAYS}
    for kind in dict.fromkeys(wanted):
        for line in brief:
            if line.kind == kind and len(keep) < MAX_LINES:
                keep.add(id(line))
    return [line for line in brief if id(line) in keep]


def stats(prompt_tokens: int, cut: Sequence[str], loaded: Sequence[str], shown: int, held: int) -> Mapping[str, Any]:
    """What a reader of the run needs to see this turn's prompt was whole."""
    return {"tokens": prompt_tokens, "cut": list(cut), "packs": list(loaded), "brief_shown": shown, "brief_held": held}
