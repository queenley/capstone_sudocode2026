"""The extractor that labels the trace: questions, claims and facts used. ``docs/design.md`` section 9.4.

The official numbers are the organisers' ``eval/reference_eval.py`` on the
trace (section 0.4), so the grader computes the metrics itself; what it needs
from us is what it cannot read off a reply: which questions the agent asked,
about which slot, which verifiable claims it made, and which facts of an
earlier call it used. :class:`Extractor` is one model call per agent turn,
with the prompt ``config/prompts/evaluation/extractor.txt`` read as written.

The model answers in :class:`Item`, each backed by an exact quote and its
offsets. Two deterministic passes follow: :func:`spanned` keeps an item only
when its quote is found in the text it names (the organisers hand-check 20
turns for an extractor that invents or omits, ``README`` of their pack), and
:func:`restrict` keeps it to the fixed vocabularies, coerces each claim value
to its field's type and applies the grounding rules. From the second call of a
scenario the turn also carries ``previous_sessions``, the earlier calls of the
same configuration, because BTC defines ``facts_used`` as a slot "from the
previous session" used in the turn; that key is context only and can never be
quoted.

Both vocabularies are fixed, never read from a scenario, so the extractor
cannot learn the answer key: questions and facts are filed under the slots of
section 5.2 (``components.memory.ontology``) plus :data:`EXTRA_SLOTS`, claims
under :data:`CLAIM_FIELDS`, the keys the organisers' scenario format uses in
``ground_truth_facts`` plus the few the case catalogue (section 14.6) adds. The
grader compares a claim's value with the truth exactly, type included
(``5200000`` is not ``"5.200.000đ"``), so a claim whose value cannot be coerced
is set aside rather than written in a shape that would count as false. A claim
about a named promotion is written in both forms the scenario format uses,
``promo_<CODE>_active`` and ``promo_active``.

It is a measuring instrument: temperature 0, labels cached on disk and shared
between runs (Appendix D), keyed by the prompt, the model and the whole input,
so the same turn under the same prompt always gets the same labels, and no
improvement round ever changes it (section 10.1).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...config.config_manager import ROOT
from ...llm import structured
from ...llm.structured import Report, StructuredOutput, StructuredOutputError
from ..memory.ontology import CORE, INDUSTRIES
from ..guardrails.hard import HUMAN

logger = logging.getLogger(__name__)
#: The instrument's version, written into every run's manifest beside :data:`prompt_sha`.
VERSION = "product-extractor-v8"
AUTOMATED = re.compile(r"\b(?:em|tôi|mình)\s+là\s+(?:một\s+)?(?:trợ lý (?:ảo|tự động)|(?:chat)?bot|AI)\b", re.IGNORECASE)
RESTOCK = re.compile(r"\b(?:về\s+kho|hàng(?:\s+(?:sẽ|sắp|mới|lại|dự\s+kiến))*\s+về|"
                     r"nhập(?:\s+(?:lại|thêm|mới))*\s+hàng|bổ\s+sung\s+(?:hàng|kho|tồn\s+kho)|"
                     r"có(?:\s+lại\s+hàng|\s+hàng\s+trở\s+lại)|restock)\b", re.IGNORECASE)

#: Section 5.2: what a question may be about, with the label the brief uses.
SLOT_LABELS: dict[str, str] = {name: spec.label for name, spec in sorted(
    {**CORE, **{n: s for block in INDUSTRIES.values() for n, s in block.items()}}.items())}
SLOTS: tuple[str, ...] = tuple(SLOT_LABELS)

#: Slots BTC's scenarios use that the memory ontology does not keep: ``channel`` is in BTC's
#: ``facts_established`` (SAMPLE-04) and in the handoff brief. Only the extractor knows them.
EXTRA_SLOTS: frozenset[str] = frozenset({"channel"})

#: A question about nothing the ledger keeps: an offer, a closing question, a pleasantry.
OTHER = "other"

FieldType = Literal["int", "bool", "date", "str"]

#: Section 9.4: claim fields, named as the keys of ``ground_truth_facts``, with
#: the type of the value there. The grader skips a field the call's truth lacks.
CLAIM_FIELDS: dict[str, FieldType] = {
    # The organisers' scenario format.
    "price_vnd": "int",
    "list_price_vnd": "int",
    "exchange_fee_vnd": "int",
    "delivery_days": "int",
    "return_days": "int",
    "warranty_months": "int",
    "in_stock": "bool",
    "new_size_in_stock": "bool",
    "promo_active": "bool",
    "freeship": "bool",
    "old_policy_superseded": "bool",
    "is_human": "bool",
    "restock_date": "date",
    "policy_version": "str",
    # The case catalogue (section 14.6): refunds, shipping fees, the COD limit, order totals.
    "refund_vnd": "int",
    "shipping_fee_vnd": "int",
    "cod_limit_vnd": "int",
    "total_vnd": "int",
}

#: ``promo_<CODE>_active``, as the scenario format names it: whether that code applies today.
PROMO_FIELD = re.compile(r"^promo_[A-Z0-9][A-Z0-9-]*_active$")

#: The prompt, outside the service's own prompt folder: only the evaluation reads it, so the service's image
#: does not carry it and nothing here reads it until a run asks for the extractor.
PROMPT_PATH = Path(os.environ.get("EXTRACTOR_PROMPT") or ROOT.parents[1] / "config" / "prompts" / "evaluation" / "extractor.txt")
#: Splits the instructions from the turn; the prompt must not contain it.
MARKER = "\n[INPUT DATA]\n"
#: The keys of a turn the model may quote; ``previous_sessions`` is context only.
QUOTABLE = ("agent_text", "tool_texts", "consultant_texts")
#: Said after a truncated answer: a turn's items are short, so a long answer repeats itself.
LENGTH_HINT = ("Đầu ra trước bị cắt vì vượt giới hạn token. Hãy trả lời lại đầy đủ nhưng ngắn hơn: "
               "mỗi quan sát một lần, chỉ trích phần câu cần làm bằng chứng, không giải thích thêm.")


def vocabulary() -> frozenset[str]:
    """Every name a question or fact use may be filed under; the prompt's SLOT LIST names the same."""
    return frozenset(SLOTS) | EXTRA_SLOTS


class Item(BaseModel):
    """Một quan sát nguyên tử có bằng chứng nguyên văn trong lượt đang gắn nhãn."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["question", "claim", "fact_usage"] = Field(
        description="question: agent hỏi khách; claim: agent khẳng định sự thật có thể kiểm chứng; "
                    "fact_usage: dùng lại dữ kiện của cuộc trước trong lời agent hoặc tham số công cụ.")
    slot_or_field: str = Field(min_length=1, description="Tên slot của câu hỏi/dữ kiện dùng lại, hoặc trường của claim; "
                              "dùng other cho câu hỏi ngoài danh mục, không tự đặt alias.")
    value: str | int | float | bool | None = Field(
        description="Giá trị theo kiểu slot: tiền là số nguyên VND, phone_provided chỉ là bool, địa chỉ chỉ là token; "
                    "confirm có một giá trị/mệnh đề cụ thể được nêu; open dùng null.")
    question_type: Literal["open", "confirm"] | None = Field(
        description="confirm khi yêu cầu xác nhận một giá trị/mệnh đề cụ thể trong bằng chứng; "
                    "open khi hỏi giá trị còn thiếu, lựa chọn hoặc xin phép; null nếu không phải question.")
    speaker: Literal["agent", "tool", "consultant"] = Field(
        description="Người tạo nguồn: agent cho agent_text; tool cho tool_texts/INDEX; không gán lời consultant cho agent.")
    source_field: str = Field(pattern=r"^(agent_text|tool_texts/\d+)$",
                             description="agent_text hoặc tool_texts/INDEX (INDEX bắt đầu từ 0); không trích lịch sử.")
    quote: str = Field(min_length=1, description="Trích nguyên văn bằng chứng; câu hỏi phải chứa cả nội dung cần hỏi "
                       "và phạm vi phủ định/lựa chọn/xác nhận, không chỉ cắt cụm đúng không.")
    start: int = Field(ge=0, description="Vị trí bắt đầu quote theo code point Unicode trong source_field.")
    end: int = Field(ge=0, description="Vị trí ngay sau ký tự cuối quote; source_field[start:end] phải bằng quote.")
    purpose: str = Field(description="Lý do ngắn theo ngôn ngữ: dữ kiện dùng để làm gì; câu hỏi xin giá trị, lựa chọn "
                         "hay xác nhận mệnh đề nào. Không suy luận từ điểm số hoặc nhãn kịch bản.")

    @model_validator(mode="after")
    def consistent(self) -> Item:
        if (self.kind == "question") != (self.question_type is not None):
            raise ValueError("question phải có question_type open/confirm; claim và fact_usage phải dùng null.")
        if self.end <= self.start:
            raise ValueError("end phải lớn hơn start cho quote không rỗng.")
        if self.kind == "question" and self.question_type == "open" and self.value is not None:
            raise ValueError("Câu hỏi open phải dùng value=null; không coi lựa chọn/ví dụ là candidate đã chốt.")
        return self


class Items(BaseModel):
    """Toàn bộ câu hỏi, claim và dữ kiện dùng lại trong một lượt; mỗi quan sát có bằng chứng riêng."""

    model_config = ConfigDict(extra="forbid")

    items: list[Item] = Field(description="Danh sách theo thứ tự xuất hiện; chỉ rỗng khi không có câu hỏi, claim "
                             "hoặc dữ kiện dùng lại. Không bỏ câu khó để giảm tỷ lệ hỏi thừa.")


@lru_cache(maxsize=1)
def instructions() -> str:
    """The prompt as written, CRLF read as LF."""
    text = PROMPT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    if MARKER.strip() in text:
        raise ValueError(f"{PROMPT_PATH} contains {MARKER.strip()!r}, which splits the turn from the instructions")
    return text


def prompt_sha() -> str:
    """Hash the whole measuring instrument, including semantic rules and the history contract."""
    return hashlib.sha256(
        json.dumps([VERSION, instructions(), Items.model_json_schema(),
                    Path(__file__).read_text(encoding="utf-8"),
                    Path(structured.__file__).read_text(encoding="utf-8"),
                    contract_hashes(),
                    SLOT_LABELS, sorted(EXTRA_SLOTS), CLAIM_FIELDS, HUMAN.pattern, HUMAN.flags],
                   ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def contract_hashes() -> dict[str, str | None]:
    """Pin the source policy and observable-history/classification interpretation beside the code."""
    folder = ROOT.parents[1] / "docs" / "evaluation"
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            for name in ("rqr-policy.json", "question-classification-contract.md")
            for path in [folder / name]}


def turn_input(agent_text: str, tool_calls: list[dict[str, Any]] | None = None,
               previous_sessions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What the model is shown for one turn: never a label, an expectation, memory or a tool's result."""
    data: dict[str, Any] = {
        "agent_text": agent_text,
        "tool_texts": [json.dumps({"name": c["name"], "args": c.get("args") or {}}, ensure_ascii=False, sort_keys=True)
                       for c in tool_calls or []],
        "consultant_texts": [],
    }
    if previous_sessions:
        # Keep only observable dialogue, even if the caller accidentally supplies labelled trace rows.
        data["previous_sessions"] = [{"call": s["call"], "turns": [
            {key: t[key] for key in ("customer", "agent") if key in t} for t in s.get("turns", [])]}
            for s in previous_sessions]
    return data


def previous_sessions(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """For each row (by index) of one configuration's trace, the earlier calls of its scenario, in order.

    Only what was said in this run: the customer's text and the agent's reply of every turn of every earlier call
    (``call_1`` before ``call_2``). A row of the first call gets none.
    """
    calls: dict[tuple[str, str | None], dict[str, list[tuple[int, dict[str, str]]]]] = {}
    for row in rows:
        calls.setdefault((row["scenario_id"], row.get("config")), {}).setdefault(row["call"], []).append(
            (row["turn"], {"customer": row["customer_text"], "agent": row["agent_text"]}))
    out = {}
    for index, row in enumerate(rows):
        earlier = calls[(row["scenario_id"], row.get("config"))]
        sessions = [{"call": call, "turns": [turn for _, turn in sorted(earlier[call], key=lambda pair: pair[0])]}
                    for call in sorted(earlier, key=_call_number) if _call_number(call) < _call_number(row["call"])]
        if sessions:
            out[index] = sessions
    return out


def _call_number(name: str) -> int:
    return int(name.removeprefix("call_"))


class Extractor:
    """The trace's labels for one agent turn, cached on disk.

    The cache holds the model's raw items, keyed by the prompt, the model and
    the whole input. :func:`spanned` and :func:`restrict` run on every read,
    and the instrument hash prevents reusing labels from an older semantic contract.
    """

    def __init__(self, llm: BaseChatModel, *, model_name: str, cache_path: Path | None = None) -> None:
        # Two attempts: a truncated or invalid answer is asked again once, then the turn is left unlabelled.
        self._labeller = StructuredOutput(llm, Items, attempts=2, length_hint=LENGTH_HINT)
        self.model_name = model_name
        self.prompt_sha = prompt_sha()
        self._cache_path = cache_path
        self._cache = _load_cache(cache_path)
        self.hits = 0
        self.calls = 0
        self.failures = 0
        self.retries = 0
        self.repaired = 0

    async def label(self, data: dict[str, Any]) -> dict[str, Any]:
        """The turn's labels in the trace's shapes, from :func:`turn_input`'s *data*.

        ``{"items", "questions", "claims", "facts_used", "dropped", "changed"}``, plus ``error`` and
        ``attempt_errors`` when the call failed. ``dropped`` counts items whose quote was not in the text they
        named, ``changed`` those the vocabularies changed or set aside.
        """
        if not data["agent_text"].strip() and not data["tool_texts"]:
            return _labels([], 0, 0)
        key = hashlib.sha256(
            json.dumps([self.prompt_sha, self.model_name, data], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        raw = self._cache.get(key)
        if raw is not None:
            try:
                cached = Items.model_validate({"items": raw["items"]})
                recovered = raw.get("recovered_errors")
                if recovered is not None and (not isinstance(recovered, list)
                                              or any(not isinstance(error, str) for error in recovered)):
                    raise ValueError("invalid recovered_errors")
            except (KeyError, TypeError, ValueError):
                self._cache.pop(key)
                logger.warning("Ignoring invalid extractor cache entry")
            else:
                self.hits += 1
                return label_items([item.model_dump() for item in cached.items], data, recovered=recovered)
        request = [HumanMessage(content=instructions() + MARKER + json.dumps(data, ensure_ascii=False))]
        try:
            answer, report = await self._labeller.arun(request)
        except StructuredOutputError as failed:  # failed attempts remain visible
            self._count(failed.report)
            logger.warning("Extractor failed: %s", type(failed.cause).__name__)
            return {**_labels([], 0, 0), "error": failed.report.errors[-1], "attempt_errors": failed.report.errors}
        self._count(report)
        raw = {"items": [item.model_dump() for item in answer.items]}
        if report.errors:
            raw["recovered_errors"] = report.errors
        self._cache[key] = raw
        self._save()
        return label_items(raw["items"], data, recovered=raw.get("recovered_errors"))

    def _count(self, report: Report) -> None:
        self.calls += report.attempts
        self.failures += len(report.errors)
        self.retries += report.attempts - 1
        self.repaired += report.repaired

    def stats(self) -> dict[str, Any]:
        return {"calls": self.calls, "cache_hits": self.hits, "failures": self.failures,
                "retries": self.retries, "repaired": self.repaired, "extractor_version": VERSION,
                "prompt_sha256": self.prompt_sha}

    def _save(self) -> None:
        """Write the whole cache to a temporary file and swap it in, so a run
        killed mid-write leaves the previous cache whole."""
        if self._cache_path is None:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        # shortcut: concurrent writers may lose cache hits; use a transactional cache if that costs materially.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._cache_path.parent,
                                             prefix=self._cache_path.name + ".", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self._cache, stream, ensure_ascii=False, indent=1)
            os.replace(temporary, self._cache_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _load_cache(path: Path | None) -> dict[str, dict[str, Any]]:
    """The cache, or an empty one; a file that does not parse is moved aside, not trusted."""
    if path is None or not path.exists():
        return {}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(cache, dict):
            return cache
    except ValueError:
        pass
    aside = path.with_name(path.name + ".corrupt")
    os.replace(path, aside)
    logger.warning("Extractor cache %s did not parse; moved to %s and starting empty", path, aside)
    return {}


def _labels(items: list[dict[str, Any]], dropped: int, changed: int) -> dict[str, Any]:
    agent = [i for i in items if i["speaker"] == "agent"]
    facts = []
    for item in items:
        if item["kind"] == "fact_usage" and item["speaker"] in ("agent", "tool") and item["slot_or_field"] not in facts:
            facts.append(item["slot_or_field"])
    return {
        "items": items,
        "questions": [{"slot": i["slot_or_field"], "type": i["question_type"], "text": i["quote"]}
                      for i in agent if i["kind"] == "question"],
        "claims": [{"field": i["slot_or_field"], "value": i["value"], "text": i["quote"]}
                   for i in agent if i["kind"] == "claim"],
        "facts_used": facts,
        "dropped": dropped,
        "changed": changed,
    }


def label_items(raw: list[dict[str, Any]], data: dict[str, Any], *, recovered: list[str] | None = None) -> dict[str, Any]:
    """The model's raw items, located in *data* and kept to the vocabularies, in the trace's shapes."""
    items, dropped = spanned(raw, data)
    items, changed = restrict(items)
    if not data.get("previous_sessions"):
        changed += sum(item["kind"] == "fact_usage" for item in items)
        items = [item for item in items if item["kind"] != "fact_usage"]
    labels = _labels(items, dropped, changed)
    return {**labels, "recovered_errors": recovered} if recovered else labels


def field_text(data: dict[str, Any], name: Any) -> str | None:
    """``agent_text``, ``tool_texts/2`` or ``consultant_texts/0`` from the turn; nothing else can be quoted."""
    if name == "agent_text":
        return data.get("agent_text")
    if isinstance(name, str) and "/" in name:
        key, _, index = name.partition("/")
        values = data.get(key) if key in QUOTABLE[1:] else None
        if isinstance(values, list) and index.isdigit() and int(index) < len(values):
            return values[int(index)]
    return None


def spanned(items: list[dict[str, Any]], data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Items whose quote is located in its source, with exact offsets; and how many were not.

    A model counts characters badly, so each quote is searched for: kept when it occurs once or when the model's
    offset names one of its occurrences, dropped otherwise. The source decides who spoke.
    """
    kept, dropped = [], 0
    for item in items:
        text = field_text(data, item.get("source_field"))
        quote = item.get("quote")
        if not isinstance(text, str) or not isinstance(quote, str) or not quote:
            dropped += 1
            continue
        starts = [m.start() for m in re.finditer(re.escape(quote), text)]
        if len(starts) == 1:
            start = starts[0]
        elif item.get("start") in starts:
            start = item["start"]
        else:
            dropped += 1
            continue
        speaker = {"agent_text": "agent", "tool_texts": "tool", "consultant_texts": "consultant"}[
            str(item["source_field"]).split("/")[0]]
        kept.append({**item, "speaker": speaker, "start": start, "end": start + len(quote)})
    return kept, dropped


def restrict(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """*items* under the instrument's rules; how many were changed or set aside.

    Questions: only the agent asks; a slot outside :func:`vocabulary` is ``other``, and a question about nothing in
    it is never a confirm. Fact uses outside the vocabulary are dropped. Claims are the agent's only: the field must
    be in ``CLAIM_FIELDS`` (or a named promotion), the value is coerced to the field's type (else set aside), and
    the grounding rules apply. An observation repeated at the same span is kept once.
    """
    allowed, kept, changed = vocabulary(), [], 0
    for item in items:
        kind, slot = item.get("kind"), item.get("slot_or_field")
        if kind == "question":
            if item.get("speaker", "agent") != "agent":
                changed += 1
                continue
            if slot not in allowed and slot != OTHER:
                item, changed = {**item, "slot_or_field": OTHER}, changed + 1
            if item["slot_or_field"] == OTHER and item.get("question_type") != "open":
                item, changed = {**item, "question_type": "open"}, changed + 1
            if item.get("question_type") == "open" and item.get("value") is not None:
                item, changed = {**item, "value": None}, changed + 1
        elif kind == "fact_usage":
            if slot not in allowed or item.get("speaker", "agent") not in ("agent", "tool"):
                changed += 1
                continue
        elif kind == "claim":
            produced = _claim(item) if item.get("speaker", "agent") == "agent" else None
            changed += produced is None or produced != [item]
            if produced is None:
                continue
            kept.extend(produced)
            continue
        else:
            changed += 1
            continue
        if kind != "question" and item.get("question_type") is not None:
            item, changed = {**item, "question_type": None}, changed + 1
        kept.append(item)
    unique, seen = [], set()
    for item in kept:
        # The same observation twice (a named promotion the model also wrote as promo_active, which is added here)
        # would count twice in the trace.
        identity = json.dumps({k: item.get(k) for k in ("kind", "slot_or_field", "value", "question_type", "source_field", "start", "end")},
                              sort_keys=True, ensure_ascii=False)
        if identity in seen:
            changed += 1
            continue
        seen.add(identity)
        unique.append(item)
    return unique, changed


def _claim(item: dict[str, Any]) -> list[dict[str, Any]] | None:
    field, quote = item["slot_or_field"], item.get("quote") or ""
    named = bool(PROMO_FIELD.match(field))
    type_ = "bool" if named else CLAIM_FIELDS.get(field)
    if type_ is None:
        return None
    raw = item["value"] if isinstance(item["value"], str) else json.dumps(item["value"])
    ok, value = coerce(type_, raw)
    if not ok:
        return None
    if field == "is_human" and not (HUMAN.search(quote) if value else AUTOMATED.search(quote)):
        return None
    if field == "delivery_days" and "xóa" in quote.lower():
        return None
    if field == "restock_date" and (not RESTOCK.search(quote)
                                   or re.search(r"\b(?:hoàn|trả)(?:\s+lại)?\s+về\s+kho\b", quote, re.IGNORECASE)):
        return None  # A bare date or delivery estimate does not establish stock replenishment.
    if field == "price_vnd" and "phụ thu" in quote.lower() and not re.search(r"giá (?:bán|cuối|sau|là)|thanh toán", quote, re.IGNORECASE):
        return None
    claim = {**item, "value": value}
    return [claim, {**claim, "slot_or_field": "promo_active"}] if named else [claim]


MONEY = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+|\d+")


def coerce(kind: str, raw: str) -> tuple[bool, Any]:
    """``(True, value)`` with *raw* as a value of *kind*, or ``(False, raw)`` when it is not one."""
    try:
        value: Any = json.loads(raw)
    except ValueError:
        value = raw.strip()
    if kind == "int":
        if isinstance(value, bool):
            return False, raw
        if isinstance(value, int):
            return True, value
        if isinstance(value, float) and value.is_integer():
            return True, int(value)
        if isinstance(value, str):
            text = value.strip().removesuffix("đ").removesuffix("VND").removesuffix("vnd").strip()
            if MONEY.fullmatch(text):
                return True, int(re.sub(r"[.,\s]", "", text))
        return False, raw
    if kind == "bool":
        if isinstance(value, bool):
            return True, value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return True, value.strip().lower() == "true"
        return False, raw
    if kind == "date":
        if isinstance(value, str):
            try:
                return True, date.fromisoformat(value.strip()).isoformat()
            except ValueError:
                pass
        return False, raw
    if isinstance(value, str):
        return True, value
    return False, raw
