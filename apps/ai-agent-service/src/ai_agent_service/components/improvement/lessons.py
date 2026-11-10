"""What Reflection keeps: what counts as evidence, what a lesson or a change may never say. ``docs/design.md`` 10.3.

The brief, C.5: a lesson is "được kiểm tra rồi mới ghi vào bộ nhớ". So each
lesson card is screened here before it is stored (:func:`screen_card`,
:func:`store`), and a change to a skill is screened before review
(:func:`screen_patch`).

A failure in one call is one vote, not a rule: a change to a skill needs the
same lesson, in the same situation, for the same skill and the same failed
check, from at least :data:`MIN_SUPPORT` different customers (:func:`clusters`).

The screens hold only what has a fixed shape: an id of one scenario, product or
order, a promotion code, an amount the cited rule does not state, a missing or
unknown rule. Whether an instruction promises, pressures or contradicts a rule
is meaning, and the PolicyAgent reads it (``PolicyAgent.review_change``).
"""

from __future__ import annotations

from collections import Counter

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from ...config.config_manager import CONFIG_DIR, btc_data_dir, load_prompt, load_prompt_yaml
from ..intake import pii
from ..knowledge.corpus import policy_chunks
from .signals import home
from .storage import locked

#: Different customers who share a lesson, before a change to a skill is drafted.
MIN_SUPPORT = 3
#: Where a lesson about conduct goes when no skill owns the task or the rule broken is a fixed one: a skill always in
#: the prompt (config/prompts/agent/advisor/skills.yaml), grown one reviewed sentence at a time.
CONDUCT_SKILL = "conversation"

#: What only one scenario, product or order has: a skill holds for any customer.
SPECIFIC = re.compile(r"\b(?:SCN|SKU|SAMPLE)-\w+|\bOD\d+|\bkhach_\w+")
#: An amount: "4.890.000", "249k", "5 triệu", "200 nghìn", "10%".
MONEY = re.compile(r"\d[\d.,]*\s*(?:đ|₫|vnd|vnđ|k|nghìn|ngàn|triệu|tr|%)(?!\w)|\b\d{1,3}(?:[.,]\d{3})+\b|\b\d{4,}\b",
                   re.IGNORECASE)
#: The card's fields a screen reads.
CARD_TEXT = ("what_happened", "do", "dont", "sample_line")


@lru_cache(maxsize=1)
def rule_texts() -> dict[str, str]:
    """The organisers' public policy sections a lesson may cite, by code: internal notes are not rules."""
    return {c.chunk_id: c.text for c in policy_chunks(btc_data_dir() / "policy") if not c.restricted}


@lru_cache(maxsize=1)
def promo_codes() -> frozenset[str]:
    path = btc_data_dir() / "catalog" / "promotions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(str(p["promo_code"]) for p in data.get("promotions") or [] if p.get("promo_code"))


@lru_cache(maxsize=1)
def fixed_rules() -> str:
    """The advisor's own fixed instructions, as its prompt carries them: the rules and the lane notes. Reflection never changes them; the loop's models read them so that a failure they already
    cover is not taken for a gap, and a lesson never contradicts them."""
    def texts(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, Mapping):
            return [text for item in value.values() for text in texts(item)]
        if isinstance(value, (list, tuple)):
            return [text for item in value for text in texts(item)]
        return []

    parts = [load_prompt("advisor/rules.md"), *texts(load_prompt_yaml("advisor/notes.yaml"))]
    return "\n\n".join(part.strip() for part in parts if part.strip())


@lru_cache(maxsize=1)
def advisor_tools() -> dict[str, str]:
    """What each tool the advisor may call does, by name: the first paragraph of its docstring, as the model reads it.

    Reflection reads it so that a lesson never tells the assistant to do what no tool does, or to quote a figure no tool
    returns (2026-11-10: a change said to look up an extended warranty's price; no tool gives it)."""
    import importlib
    import inspect

    from ...config.config_manager import get_lanes

    names = sorted({name for tools in get_lanes().values() for name in tools if name != "load_skill"})
    modules = [importlib.import_module(f"ai_agent_service.mcp.servers.{m}")
               for m in ("account", "catalog", "crm", "knowledge", "memory", "order")]
    found: dict[str, str] = {}
    for name in names:
        fn = next((getattr(m, name) for m in modules if callable(getattr(m, name, None))), None)
        if fn is not None:
            found[name] = " ".join((inspect.getdoc(fn) or "").split("\n\n")[0].split())
    return found


@lru_cache(maxsize=1)
def situations() -> dict[str, str]:
    """``config/situations.yaml``: the situations a card and a change are written for."""
    data = yaml.safe_load((CONFIG_DIR / "situations.yaml").read_text(encoding="utf-8")) or {}
    return dict(data.get("situations") or {})


def _known(rules: Mapping[str, str] | Iterable[str] | None) -> dict[str, str]:
    if rules is None:
        return rule_texts()
    return dict(rules) if isinstance(rules, Mapping) else {code: "" for code in rules}


def screen_patch(text: str, cites: Iterable[str], *, rules: Mapping[str, str] | Iterable[str] | None = None,
                 promos: Iterable[str] | None = None) -> list[str]:
    """Why a change may not go to review as it is: it must cite a rule, and name no case, code or new amount.

    An amount is allowed only when a cited rule states it as written (the COD limit of VC-03, say).
    """
    known = _known(rules)
    cited = [code for code in cites if code]
    flags: list[str] = []
    # A lesson about conduct may cite no section; one that cites must cite a real, public one.
    if not set(cited) <= set(known):
        flags.append("no_rule")
    stated = " ".join(known.get(code, "") for code in cited)
    if any(amount.group(0).strip() not in stated for amount in MONEY.finditer(text)):
        flags.append("amount")
    if any(code in text for code in (promos if promos is not None else promo_codes())):
        flags.append("promotion_code")
    if SPECIFIC.search(text):
        flags.append("specific")
    return flags


def screen_card(card: Mapping[str, Any], *, skills: Mapping[str, Any], rules: Mapping[str, str] | Iterable[str] | None = None,
                promos: Iterable[str] | None = None, known_situations: Iterable[str] | None = None) -> list[str]:
    """Why a lesson card may not be stored: the patch screen on its text, plus a skill and a situation that exist."""
    text = " ".join(str(card.get(key) or "") for key in CARD_TEXT)
    flags = screen_patch(text, card.get("cites") or [], rules=rules, promos=promos)
    if not str(card.get("do") or "").strip():
        flags.append("empty")
    if card.get("skill") not in skills:
        flags.append("unknown_skill")
    if card.get("situation") not in set(known_situations if known_situations is not None else situations()):
        flags.append("unknown_situation")
    return flags


def _words(text: str) -> str:
    return " ".join(str(text).split())


def settle_kind(kind: str, skill: str, covering_sentence: str, book: Mapping[str, Mapping[str, Any]],
                rules: str = "") -> str:
    """The diagnosis, checked: ``not_followed`` stands only with a sentence that is, as written, in the skill or in
    the advisor's fixed rules (*rules*, :func:`fixed_rules`): either way it is product work, not a lesson.

    A quote that is not in the skill as written is ``unsettled``: the model says a sentence covers it and cannot show
    which, so a person reads it; it never becomes a lesson. A skill that does not exist means no procedure is at stake.
    """
    quote = _words(covering_sentence)
    if kind == "not_followed" and len(quote) >= 12 and quote in _words(rules):
        return "not_followed"  # a fixed rule already says it, whatever skill the task was in
    if kind == "not_a_skill" or skill not in book:
        return "not_a_skill"
    if kind == "not_followed":
        written = _words(f"{book[skill].get('description', '')} {book[skill].get('body', '')}")
        return "not_followed" if len(quote) >= 12 and quote in written else "unsettled"
    return "skill_gap"


# ── the store of lessons: the memory a lesson is written to ───────────────


def store_path() -> Path:
    """``IMPROVEMENT_DIR/lessons.jsonl``: every card that passed its screen, one line each, never rewritten."""
    return home() / "lessons.jsonl"


def store(cards: Iterable[Mapping[str, Any]]) -> int:
    """Append screened cards; a card with a flag is refused here, whoever calls."""
    clean = [card for card in cards if not card.get("flags")]
    with locked(home()):
        write_jsonl(store_path(), clean, append=True)
    return len(clean)


def stored(*, skills_version: int | None = None) -> list[dict[str, Any]]:
    """The cards in the store, of the skills *skills_version* they were drawn from when given."""
    return [card for card in read_jsonl(store_path())
            if skills_version is None or card.get("skills_version") == skills_version]


def clusters(cards: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    """General cards by situation, where at least :data:`MIN_SUPPORT` customers share one, keyed by (the skill most
    of them would change, situation).

    A lesson is about a situation (the brief, C.5: a structured lesson of what happened in which situation); the
    failed check is its symptom, and one lesson shows as several (asking again, one question too many, a weak
    opening). Where each card would write it is a guess of its own: four cards of one lesson named three skills on
    2026-11-10 and no group reached three customers, so the skill is the one most cards name. A card of one
    customer's own preference is never a rule for others; two cards of the same customer are one vote.
    """
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for card in cards:
        if card.get("scope") != "general":
            continue
        groups.setdefault(str(card.get("situation")), []).append(card)
    shared: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for situation, items in groups.items():
        if len({c.get("customer") for c in items}) < MIN_SUPPORT:
            continue
        skill = Counter(str(c.get("skill")) for c in items).most_common(1)[0][0]
        shared[(skill, situation)] = items
    return shared


# ── what the models read of a call ────────────────────────────────────────


#: A tool result is cut past this many characters: an order's date or a policy's condition must still be in it.
TOOL_RESULT_CHARS = 1500


def _turns(rows: Sequence[Mapping[str, Any]], vault: pii.Vault) -> list[str]:
    lines: list[str] = []
    shown = pii.tokenise_data([{key: row.get(key) for key in ("turn", "customer_text", "agent_text", "tool_calls")}
                               for row in rows], vault)
    for row in sorted(shown, key=lambda r: int(r.get("turn") or 0)):
        lines.append(f"[lượt {row.get('turn')}] khách: {row.get('customer_text') or ''}")
        for tool in row.get("tool_calls") or []:
            result = json.dumps(tool.get("result"), ensure_ascii=False, default=str)[:TOOL_RESULT_CHARS]
            lines.append(f"  tool {tool.get('name')} {json.dumps(tool.get('args') or {}, ensure_ascii=False)} -> {result}")
        lines.append(f"[lượt {row.get('turn')}] trợ lý: {row.get('agent_text') or ''}")
    return lines


def transcript(rows: Sequence[Mapping[str, Any]], earlier: Sequence[tuple[str, Sequence[Mapping[str, Any]]]] = ()) -> str:
    """A call as the models of the loop read it: the customer's earlier calls first, then this one, each side's words
    and every tool called with its result. A lesson about a returning customer needs what they said before (the day
    they bought, the budget they gave), as the advisor had it in its Call Brief.

    Only trace fields: nothing of the scenario's answer key; personal data tokenised as the rubric judge does, with
    one vault for the whole history so a number keeps its token across calls.
    """
    vault = pii.Vault()
    lines: list[str] = []
    for name, rows_before in earlier:
        lines += [f"=== Cuộc trước của cùng khách ({name}) ===", *_turns(rows_before, vault)]
        # What memory kept of that call: the Call Brief of the next call is built from it.
        kept = pii.tokenise_data([{key: w.get(key) for key in ("key", "value", "op")}
                                  for row in rows_before for w in row.get("memory_writes") or []], vault)
        if kept:
            lines.append("Bộ nhớ ghi sau cuộc này (Call Brief của cuộc sau dựng từ đây): " + "; ".join(
                f"{w['key']}={w['value']}" + (" (thay giá trị cũ)" if w.get("op") == "supersede" else "") for w in kept))
    if earlier:
        lines.append("=== Cuộc gọi đang xét ===")
    return "\n".join([*lines, *_turns(rows, vault)])


def round_dir(name: str) -> Path:
    """``IMPROVEMENT_DIR/rounds/<name>``: one learning round's failures, diagnoses and cards."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError(f"Round name {name!r}: letters, digits, '.', '_' and '-' only")
    return home() / "rounds" / name


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]], *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
