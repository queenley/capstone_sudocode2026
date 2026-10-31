"""MemoryAgent: what to remember about this customer. ``docs/design.md`` section 5.4.

Runs after verified web turns and in ``after_call`` under the ``memory_writer``
role, the only path into the ledger. Of the five steps, two are judgements and live here; the gate and
the commit decision are code (``src/components/memory``, ``after_call``):

- ``extract``: candidates in the organisers' flat slot names.

  - **Business facts are read from the tool log by code**, never from what
    anyone said: the product and price of each quote (and its promotion with
    the day it ends), the variant, size and colour a quote or an order names,
    the order, the callback, the handover, and so the call's outcome. When
    several products were quoted, the one ordered (else the first) is
    ``product_advised`` and the last other one ``alt_suggested``.
  - **The customer's words go through one structured-output model call**
    (temperature 0; the schema and the instructions below): each slot with
    what it means and how customers say it ("phòng ngủ 5x5" is 25 m²; "để
    bàn với bà xã" is a blocker and a decision maker), plus open notes, the
    objection, what the agent promised, the customer's mood. The model rates
    its own confidence, and a joke or a hypothetical stays below the gate's
    floor.
  - **The rules are the fallback** when no model is configured, its key is
    missing or the call fails: deterministic patterns for the same slots.

- ``summarize``: one episode line, "Cuộc 1 (15/10, hotline): tư vấn
  SKU-AP-Y 5.200.000đ kèm GIFT-FILTER, khách cần hỏi chồng", precomputed for
  the next call's brief.

Every candidate carries the extractor that proposed it, part of the ledger's
idempotency key: a replay of the same call with the same extractor writes
nothing twice, and a change of prompt is a new extractor.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Literal, Sequence

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from ..components.clock import day_label
from ..components.intake.itn import format_vnd, money_spans
from ..components.memory import gate
from ..components.memory.gate import Candidate
from ..components.memory.ontology import FROM_WORDS, NOTE_SLOT, SENTIMENTS, coerce, slot
from ..config.config_manager import load_prompt
from ..llm.structured import StructuredOutput
from ..mcp.servers import btc
from .base import BaseAgent

logger = logging.getLogger(__name__)

RULES_VERSION = "rules-0.3"


# ── the model's part ──────────────────────────────────────────────────────


class Observation(BaseModel):
    """One thing the call established about the customer, as the model read it."""

    slot: str = Field(description=f'A name from SLOTS, or "{NOTE_SLOT}" for a lasting fact about the customer no slot holds.')
    value: str | int | bool = Field(description="The value in the slot's type: integer VND for money, true or false, a code from its choices.")
    said_by: Literal["customer", "agent"] = Field(description="customer for their words; agent only for commitments and objection_handling.")
    turn: int = Field(ge=1, description="The turn number the value was said in; the latest when it was said several times.")
    confidence: float = Field(ge=0, le=1, description="1 when stated plainly; below 0.5 for a joke, a hypothetical or someone else's need.")


class CallMemory(BaseModel):
    """What one call established about the customer, for the shop to remember next time."""

    observations: list[Observation] = Field(
        default_factory=list,
        description="One Observation per slot the call settled, at its final value; empty when it settled none.")
    sentiment: Literal["binh_thuong", "hai_long", "kho_chiu", "gian"] = Field(
        "binh_thuong", description="The customer's mood by the end of the call: binh_thuong (neutral), hai_long "
                                   "(pleased), kho_chiu (annoyed) or gian (angry).")


INSTRUCTIONS = load_prompt("memory_extractor.md")


def _slot_lines() -> str:
    lines = []
    for name in FROM_WORDS:
        spec = slot(name)
        if spec is None:
            continue
        kind = spec.value_type + (f" one of {', '.join(spec.choices)}" if spec.choices else "")
        lines.append(f"- {name} ({kind}): {spec.label}. {spec.hint}".rstrip())
    return "\n".join(lines)


PROMPT = INSTRUCTIONS.format(slots=_slot_lines())
PROMPT_SHA = hashlib.sha256(
    json.dumps([PROMPT, CallMemory.model_json_schema()], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


# ── the rules: the fallback ───────────────────────────────────────────────

ROOM = re.compile(r"(\d{1,3})\s*(m2|m²|mét vuông|met vuong|mét)", re.IGNORECASE)
ROOM_SIDES = re.compile(r"(\d{1,2})\s*[x×]\s*(\d{1,2})")
CHILDREN_YES = re.compile(r"(có (bé|con|em bé|trẻ)|bé nhỏ|con nhỏ|trẻ nhỏ|em bé|nhà có bé)", re.IGNORECASE)
CHILDREN_NO = re.compile(r"(không có (bé|con|trẻ)|chưa có (bé|con))", re.IGNORECASE)
BUDGET_CUE = re.compile(r"(ngân sách|tầm|khoảng|dưới|tối đa|không quá|budget|trong vòng)", re.IGNORECASE)
ASK_FAMILY = re.compile(r"(hỏi|bàn với|bàn) (ý kiến )?(ông xã|chồng|vợ|bà xã|người nhà|gia đình|bố mẹ|anh nhà)", re.IGNORECASE)
THINK = re.compile(r"(suy nghĩ thêm|cân nhắc thêm|để (chị|anh|em|mình) (xem|nghĩ|tính))", re.IGNORECASE)
COMPARE = re.compile(r"(so sánh|bên khác|chỗ khác|shop khác|bên kia)", re.IGNORECASE)
TOO_DEAR = re.compile(r"(đắt quá|mắc quá|hơi đắt|giá cao|đắt hơn)", re.IGNORECASE)
SIZE = re.compile(r"\bsize\s*([0-9]{2}|[smlx]{1,3})\b", re.IGNORECASE)
COLOUR = re.compile(r"\bmàu\s+(trắng|đen|xanh|đỏ|hồng|xám|be|nâu|vàng|kem)\b", re.IGNORECASE)
TRANSFER = re.compile(r"(chuyển khoản|ck qua|banking)", re.IGNORECASE)
COD = re.compile(r"(\bcod\b|nhận hàng (rồi )?trả tiền|thanh toán khi nhận)", re.IGNORECASE)
UNHAPPY = re.compile(r"(bực|chán|mất thời gian|lâu quá|hỏi rồi mà|nói rồi mà)", re.IGNORECASE)
CALL_BACK = re.compile(r"(gọi lại|liên hệ lại|báo lại)", re.IGNORECASE)
#: The customer ends without buying; "thôi để chị xem lại" is the organisers' own (simulator spec, rule 2).
DECLINE = re.compile(
    r"(thôi khỏi|khỏi đi|thôi,? (không (mua|lấy|đặt|cần)|bỏ đi)|thôi,? để (chị|anh|em|mình|tôi) xem lại"
    r"|không (mua|lấy|đặt|cần) (nữa|đâu)|để (dịp|khi) khác|không quan tâm)",
    re.IGNORECASE,
)
#: Where to deliver, district and province only (never the house number).
AREA = re.compile(
    r"\b((?:quận|huyện|thị xã|thành phố|tp\.?)\s+[\wÀ-ỹ]+(?:\s+[\wÀ-ỹ]+)?"
    r"(?:\s*,\s*(?:tỉnh\s+|tp\.?\s*)?[\wÀ-ỹ]+(?:\s+[\wÀ-ỹ]+)?)?)",
    re.IGNORECASE,
)
QUANTITY = re.compile(r"\b(\d{1,2}|hai|ba|bốn|năm)\s+(cái|chiếc|đôi|bộ|hộp|bình|máy)\b", re.IGNORECASE)
CHILD_AGE = re.compile(r"\b(?:bé|con|em bé)\s+(?:nhà (?:chị|anh|em) )?(?:được |mới )?(\d{1,2})\s*tháng", re.IGNORECASE)
CHILD_YEARS = re.compile(r"\b(?:bé|con|em bé)\s+(?:được |mới )?(\d)\s*tuổi", re.IGNORECASE)
PREFER_ZALO = re.compile(r"(nhắn|liên hệ|gửi)\s+(qua\s+)?zalo", re.IGNORECASE)
PREFER_CALL = re.compile(r"(gọi điện|gọi cho (chị|anh|em)|gọi vào số)", re.IGNORECASE)
PHONE_TOKEN = re.compile(r"<PHONE_\d+>")
WORD_NUMBERS = {"hai": 2, "ba": 3, "bốn": 4, "năm": 5}

FAMILY = {"ông xã": "chồng", "anh nhà": "chồng", "bà xã": "vợ", "gia đình": "người nhà", "bố mẹ": "bố mẹ"}


def rules_from_words(transcript: Sequence[dict[str, Any]]) -> list[Candidate]:
    """The customer's words by pattern, in turn order: the fallback when no model answers."""
    found: list[Candidate] = []

    def add(name: str, value: Any, turn: int) -> None:
        ok, typed = coerce(name, value)
        if ok:
            found.append(Candidate(name, typed, "customer", turn, extractor=RULES_VERSION))

    for line in transcript:
        if line.get("speaker") != "customer":
            continue
        text = str(line.get("text") or "")
        turn = int(line.get("turn") or 0)
        if match := ROOM_SIDES.search(text):
            add("room_area_m2", int(match.group(1)) * int(match.group(2)), turn)
        elif match := ROOM.search(text):
            add("room_area_m2", int(match.group(1)), turn)
        if CHILDREN_NO.search(text):
            add("has_children", False, turn)
        elif CHILDREN_YES.search(text):
            add("has_children", True, turn)
        if BUDGET_CUE.search(text) and (amounts := money_spans(text)):
            add("budget_vnd", amounts[-1].value, turn)
        if match := ASK_FAMILY.search(text):
            who = FAMILY.get(match.group(3).lower(), match.group(3).lower())
            add("blocker", f"cần hỏi {who}", turn)
            add("decision_maker", who, turn)
        elif THINK.search(text):
            add("blocker", "cần suy nghĩ thêm", turn)
        if COMPARE.search(text):
            add("objection", "dat_qua" if TOO_DEAR.search(text) else "so_sanh_gia", turn)
            if amounts := money_spans(text):
                add("competitor_price_vnd", amounts[0].value, turn)
        elif TOO_DEAR.search(text):
            add("objection", "dat_qua", turn)
        if match := SIZE.search(text):
            add("size", match.group(1), turn)
        if match := COLOUR.search(text):
            add("color", match.group(1), turn)
        if TRANSFER.search(text):
            add("payment", "bank", turn)
        elif COD.search(text):
            add("payment", "COD", turn)
        if UNHAPPY.search(text):
            add("sentiment", "kho_chiu", turn)
        if match := AREA.search(text):
            add("delivery_area", match.group(1).strip(" ,."), turn)
        if match := QUANTITY.search(text):
            raw = match.group(1).lower()
            add("quantity", WORD_NUMBERS.get(raw) or int(raw), turn)
        if match := CHILD_AGE.search(text):
            add("child_age_months", int(match.group(1)), turn)
        elif match := CHILD_YEARS.search(text):
            add("child_age_months", int(match.group(1)) * 12, turn)
        if PHONE_TOKEN.search(text):
            # Only that a number was given: the number itself stays in the vault.
            add("phone_provided", True, turn)
        if PREFER_ZALO.search(text):
            add("preferred_channel", "zalo", turn)
        elif PREFER_CALL.search(text):
            add("preferred_channel", "phone", turn)
    return found


# ── the agent ─────────────────────────────────────────────────────────────


class MemoryAgent(BaseAgent):
    """Decides what the call established about the customer."""

    def __init__(self, *, llm: BaseChatModel | None = None, use_model: bool = True) -> None:
        """The model is ``agents.memory`` in ``config/models.yaml``; *llm* replaces it in a test.

        Without a model (none configured, its key missing, or *use_model*
        off) the rules extract alone.
        """
        self.name, self.llm, self.model_name = "memory", None, None
        if llm is not None or use_model:
            try:
                super().__init__("memory", llm=llm)
            except RuntimeError as error:
                logger.warning("MemoryAgent extracts by rules: %s", str(error).splitlines()[0])
        self._labeller = StructuredOutput(self.llm, CallMemory) if self.llm is not None else None
        self.version = f"model-{self.model_name}-{PROMPT_SHA[:8]}" if self._labeller is not None else RULES_VERSION

    async def extract(self, transcript: Sequence[dict[str, Any]], tool_log: Sequence[dict[str, Any]], *,
                      on: str) -> list[Candidate]:
        """Candidates from the tool log and the customer's words, in turn order."""
        found = from_tools(tool_log, on=on)
        words = await self._from_words(transcript)
        found += words
        if not any(c.slot == "outcome" for c in found):
            outcome = _outcome_from_words(transcript)
            if outcome:
                found.append(outcome)
        return found

    async def _from_words(self, transcript: Sequence[dict[str, Any]]) -> list[Candidate]:
        if self._labeller is None or not any(line.get("speaker") == "customer" for line in transcript):
            return rules_from_words(transcript)
        try:
            read: CallMemory = await self._labeller.ainvoke(f"{PROMPT}\n\nTRANSCRIPT:\n{_transcript(transcript)}")
        except Exception as error:  # noqa: BLE001 - the rules stand in, and the version says which ran
            logger.warning("MemoryAgent model failed (%s); extracting by rules", type(error).__name__)
            return rules_from_words(transcript)
        found = []
        spoken = {(int(line.get("turn") or 0), "agent" if line.get("speaker") == "human_agent" else line.get("speaker"))
                  for line in transcript}
        for item in read.observations:
            name = None if item.slot == NOTE_SLOT else item.slot
            if name is not None and name not in FROM_WORDS:
                continue
            speaker = "agent" if name in ("commitments", "objection_handling") else "customer"
            if item.said_by != speaker or (item.turn, speaker) not in spoken:
                continue
            ok, value = coerce(name, item.value) if name else (bool(str(item.value).strip()), " ".join(str(item.value).split()))
            if ok:
                said_by = "agent" if name in ("commitments", "objection_handling") else item.said_by
                found.append(Candidate(name, value, said_by, item.turn, item.confidence, extractor=self.version))
        if read.sentiment != "binh_thuong":
            last = max((int(line.get("turn") or 0) for line in transcript), default=0)
            found.append(Candidate("sentiment", read.sentiment, "customer", last, extractor=self.version))
        return found

    async def summarize(self, candidates: Sequence[Candidate], *, call_number: int, day: str, channel: str) -> dict[str, Any]:
        """The episode: one line, and the outcome."""
        last = {c.slot: c.value for c in gate.settle(candidates) if c.slot and not _customer_record(c)}
        parts = []
        if "product_advised" in last:
            price = f" {format_vnd(last['price_quoted_vnd'])}" if "price_quoted_vnd" in last else ""
            promo = f" kèm {last['promo_code']}" if "promo_code" in last else ""
            parts.append(f"tư vấn {last['product_advised']}{price}{promo}")
        if "alt_suggested" in last:
            parts.append(f"gợi ý thêm {last['alt_suggested']}")
        if "order_id" in last:
            parts.append(f"chốt đơn {last['order_id']}")
        if "callback_at" in last:
            parts.append(f"hẹn gọi lại {last['callback_at']}")
        if "blocker" in last:
            parts.append(f"khách {last['blocker']}")
        if last.get("outcome") == "chuyen_may":
            parts.append("đã chuyển tư vấn viên")
        summary = f"Cuộc {call_number} ({day_label(day)[:5]}, {channel}): " + (", ".join(parts) or "chưa có gì đáng ghi")
        return {
            "summary": summary,
            "outcome": last.get("outcome") or "khac",
            "objection_type": last.get("objection"),
            "sentiment": last.get("sentiment") if last.get("sentiment") in SENTIMENTS else "binh_thuong",
            "commitments": [str(last["commitments"])] if "commitments" in last else (
                [f"gọi lại {last['callback_at']}"] if "callback_at" in last else []),
        }


def from_tools(tool_log: Sequence[dict[str, Any]], *, on: str) -> list[Candidate]:
    """Project one coherent product snapshot and all successful order IDs from tool events."""
    found: list[Candidate] = []
    quotes: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    for position, call in enumerate(tool_log):
        envelope = call.get("result") or {}
        if not envelope.get("ok") or call.get("blocked_by"):
            continue
        data, args = envelope.get("data") or {}, call.get("args") or {}
        turn, name = int(call.get("turn") or 0), call.get("name")
        if name == "pricing.get_quote" and data.get("sku"):
            quotes.append({"turn": turn, "sku": str(data["sku"]), "data": data, "position": position})
        elif name == "order.create" and data.get("order_id"):
            orders.append({"turn": turn, "sku": str(args.get("sku") or ""), "args": args, "data": data,
                           "position": position})
            found += _tool(turn, order_id=data["order_id"], outcome="chot_don")
            if args.get("payment"):
                found += _tool(turn, payment=args["payment"])
        elif name == "order.update" and data.get("status") and args.get("new_variant_sku"):
            changes.append({"turn": turn, "sku": str(args["new_variant_sku"]), "args": args, "data": data,
                            "position": position})
        elif name == "schedule.callback" and data.get("callback_at"):
            found += _tool(turn, callback_at=data["callback_at"], outcome="hen_goi_lai")
        elif name == "handoff.transfer" and data.get("ticket_id"):
            found += _tool(turn, outcome="chuyen_may")
        elif name == "crm.get_customer":
            owned = [o.get("sku") for o in data.get("orders") or [] if o.get("sku")]
            if owned:
                found += _tool(turn, owned_sku=owned[-1])
    primary = orders[-1] if orders else (quotes[0] if quotes else None)
    if changes and (not orders or changes[-1]["position"] > orders[-1]["position"]):
        primary = changes[-1]
    if primary is None:
        return found
    sku, turn = primary["sku"], primary["turn"]
    parent, variant = btc.product_of(sku)
    main = parent or sku
    found += _tool(turn, product_advised=main)
    found += _variant(turn, sku, variant)
    # The flat BTC slots are a projection of this frame, never independent last values.
    selected = next((q for q in reversed(quotes) if q["sku"] == sku
                     and (not (orders or changes) or q["position"] <= primary["position"])), None)
    if selected is not None:
        data, turn = selected["data"], selected["turn"]
        found += _tool(turn, price_quoted_vnd=int(data["final_price_vnd"]), quoted_on=on, quoted_sku=main)
        promos = [p for p in data.get("applied_promos") or [] if p.get("type") not in ("freeship", "freecod")]
        if promos:
            found += _tool(turn, promo_code=promos[0]["promo_code"])
            if promos[0].get("end"):
                found += _tool(turn, promo_expiry=promos[0]["end"])
    elif primary in orders and primary["args"].get("price_vnd") is not None:
        found += _tool(turn, price_quoted_vnd=int(primary["args"]["price_vnd"]), quoted_on=on, quoted_sku=main)
    others = [(q["turn"], btc.product_of(q["sku"])[0] or q["sku"]) for q in quotes]
    others = [(t, code) for t, code in others if code != main]
    if others:
        found += _tool(others[-1][0], alt_suggested=others[-1][1])
    if orders:
        found += _tool(orders[-1]["turn"], order_ids=list(dict.fromkeys(o["data"]["order_id"] for o in orders)))
    return found


def _tool(turn: int, **values: Any) -> list[Candidate]:
    return [Candidate(name, value, "tool", turn, extractor=RULES_VERSION) for name, value in values.items()]


def _variant(turn: int, code: str, variant: dict[str, Any] | None) -> list[Candidate]:
    """The variant a code names, with its size and colour typed as the catalogue writes them."""
    if not variant:
        return []
    found = _tool(turn, variant_sku=code)
    for name in ("size", "color"):
        ok, value = coerce(name, variant.get(name))
        if ok:
            found += _tool(turn, **{name: value})
    return found


def _outcome_from_words(transcript: Sequence[dict[str, Any]]) -> Candidate | None:
    """The outcome when no tool settled it: a callback the customer promised, or a no.

    The customer's latest line that says either decides; a line that says
    both ("thôi chị gọi lại sau") is a callback.
    """
    outcome = None
    for line in transcript:
        if line.get("speaker") != "customer":
            continue
        text = str(line.get("text") or "")
        if CALL_BACK.search(text):
            outcome = "hen_goi_lai"
        elif DECLINE.search(text):
            outcome = "tu_choi"
    if outcome is None:
        return None
    last = max((int(line.get("turn") or 0) for line in transcript), default=0)
    return Candidate("outcome", outcome, "system", last, extractor=RULES_VERSION)


def _customer_record(candidate: Candidate) -> bool:
    spec = slot(candidate.slot or "")
    return bool(spec and spec.kind in gate.RECORDS and candidate.said_by == "customer")


def _transcript(transcript: Sequence[dict[str, Any]]) -> str:
    who = {"customer": "KHÁCH", "agent": "NHÂN VIÊN", "human_agent": "TƯ VẤN VIÊN"}
    return "\n".join(f"T{line.get('turn')} {who.get(str(line.get('speaker')), str(line.get('speaker')).upper())}: "
                     f"{line.get('text')}" for line in transcript)
