"""Suggested answers for the Knowledge Gap Loop, from a web search. ``docs/plan/002``, section 11.

An open gap is a question a customer asked that the documents did not answer (:mod:`.gaps`). Here the research
drafts an answer for the consultant who will answer it: what the manufacturer says, with the links, in words a
consultant could say. A suggestion is **never published**: it waits beside the gap in ``/admin/kien-thuc``, and the
consultant edits it and resolves the gap through the Gap Loop's own gate and review (``gaps.resolve``).

What leaves the shop is the query alone, and the query is the gap's standalone question with every personal-data
token removed. A question on health, pregnancy, medicine or the law is never searched: PB-06 sends it to a person.

| Check | Here |
|---|---|
| the Gap Loop's gate | no amount, promotion code or stock status; no topic that must go to a person |
| links | every link the draft rests on is one the search returned: a model never makes a source up |
| grounds | a draft rests on a link or on a public section of the shop's documents, or it is not offered |
| wording | no other seller named, nothing run down, no long digit run; at most ``gaps.max_answer_chars`` |
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ...config.config_manager import btc_data_dir
from .. import market as market_text
from ..intake.text import plain
from ..knowledge.corpus import Chunk, policy_chunks
from . import gaps, review, signals
from .gap import MUST_TRANSFER, gate as knowledge_gate
from .market import _mentions, industry, products
from .storage import atomic_text, locked

#: A personal-data token of :mod:`..intake.pii`, e.g. ``<PHONE_1>``.
TOKEN = re.compile(r"<[A-Z][A-Z_]*_?\d*>")


def _path() -> Path:
    return signals.home() / "market" / "gap-suggestions.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def settings() -> Mapping[str, Any]:
    return market_text.settings().get("gaps") or {}


def question_of(gap: Mapping[str, Any]) -> str:
    """The gap's standalone question, as the Gap Loop restated it."""
    return str(gap.get("restated") or "").strip()


def query_of(gap: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """The web query for *gap*, or None and why it is not searched.

    Only a restated question is searched: the customer's own words may hold a name, which :mod:`..intake.pii` does
    not mask (it masks phones, ID and account numbers, addresses), and "máy này" means nothing to a search engine.
    """
    question = question_of(gap)
    if not question:
        return None, "Câu hỏi chưa được viết lại thành câu độc lập: chạy `improve gaps` trước."
    if MUST_TRANSFER.search(plain(question)):
        return None, "Chủ đề y tế, thuốc, thai sản hoặc pháp lý phải chuyển người (PB-06): không tìm trên web."
    query = " ".join(TOKEN.sub(" ", question).split())
    if market_text.DIGIT_RUN.search(query):
        return None, "Câu hỏi có một dãy số dài: không gửi ra ngoài."
    if len(query.split()) < 3:
        return None, "Câu hỏi quá ngắn để tìm."
    return query[:200], None


def products_in(question: str) -> list[dict[str, Any]]:
    """The products on sale *question* names, by name, else by brand (at most five)."""
    said = plain(question).casefold()
    on_sale = products()
    named = [p for p in on_sale if _mentions(said, str(p.get("name") or ""))]
    if not named:
        named = [p for p in on_sale if p.get("brand") and _mentions(said, str(p["brand"]))]
    return named[:5]


def public_rules(about: Sequence[Mapping[str, Any]]) -> dict[str, Chunk]:
    """The organisers' public sections in force, of the industries of *about* (all when none) and the general ones."""
    kinds = {industry(str(p.get("category") or "")) for p in about}
    return {c.chunk_id: c for c in policy_chunks(btc_data_dir() / "policy")
            if not c.restricted and not c.valid_to and not c.chunk_id.startswith("CL-")
            and (not c.industry or not kinds or c.industry in kinds)}


def grounds(draft: Mapping[str, Any], *, result_urls: Iterable[str], rules: Mapping[str, Any]) -> str:
    """What a draft rests on: ``documents`` (the shop's own sections only), ``web``, or ``documents_and_web``.

    ``documents`` is a finding of its own: the documents already answer the question, so the gap is a retrieval
    miss, not missing knowledge (the first trial, 2026-11-27: all three questions were answered by SP-AF-01,
    SP-SN-02 and SP-MB-01). Publishing another entry would hide the miss rather than fix it.
    """
    returned = set(result_urls)
    on_web = any(str(s) in returned for s in draft.get("sources") or ())
    in_docs = any(str(c) in rules for c in draft.get("cites") or ())
    return "documents_and_web" if on_web and in_docs else "web" if on_web else "documents" if in_docs else "none"


def gate(draft: Mapping[str, Any], *, question: str, result_urls: Iterable[str], rules: Mapping[str, Any]) -> tuple[str, ...]:
    """Why *draft* may not be offered; empty when code finds nothing. The consultant still reads every word."""
    answer = str(draft.get("answer") or "").strip()
    reasons: list[str] = []
    if not answer:
        return ("Không có câu trả lời.",)
    limit = int(settings().get("max_answer_chars") or 600)
    if len(answer) > limit:
        reasons.append(f"Câu trả lời dài {len(answer)} ký tự; tối đa {limit}.")
    reasons += knowledge_gate(question, answer)
    returned = set(result_urls)
    sources = [str(s) for s in draft.get("sources") or ()]
    invented = [s for s in sources if s not in returned]
    if invented:
        reasons.append(f"Có link không nằm trong kết quả tìm kiếm ({len(invented)}): nguồn không được tự tạo.")
    cites = [str(c) for c in draft.get("cites") or ()]
    unknown = [c for c in cites if c not in rules]
    if unknown:
        reasons.append(f"Trích mã không công khai hoặc không tồn tại: {', '.join(unknown)}.")
    if not [s for s in sources if s in returned] and not [c for c in cites if c in rules]:
        reasons.append("Câu trả lời không dựa vào link hay tài liệu nào.")
    said = plain(answer).casefold()
    config = market_text.settings()["battlecard"]
    named = [r for r in config.get("retailers") or () if _mentions(said, str(r))]
    if named:
        reasons.append(f"Nêu tên nơi bán khác ({', '.join(named)}).")
    down = [w for w in config.get("disparaging") or () if _mentions(said, str(w))]
    if down:
        reasons.append(f"Có lời so bì hoặc chê ({', '.join(down)}).")
    if market_text.DIGIT_RUN.search(answer):
        reasons.append("Có một dãy số dài như số điện thoại hay số tài khoản.")
    return tuple(dict.fromkeys(reasons))


# ── the store ──────────────────────────────────────────────────────────────


def _read() -> dict[str, dict[str, Any]]:
    path = _path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(gap_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the latest suggestion for *gap_id*: a later run replaces it."""
    row = {"gap_id": gap_id, "created_at": _now(), **record}
    with locked(_path().parent):
        rows = _read()
        rows[gap_id] = row
        atomic_text(_path(), json.dumps(rows, ensure_ascii=False, indent=2))
    review.log("market_gap_suggestion", gap_id=gap_id, status=row.get("status"), gate=row.get("gate") or [],
               author="market")
    return row


def suggestions(*, open_only: bool = True) -> list[dict[str, Any]]:
    """The suggestions, newest first; only for gaps still open unless *open_only* is False."""
    rows = sorted(_read().values(), key=lambda r: r.get("created_at") or "", reverse=True)
    # The sources a reviewer may give the customer with the answer: a manufacturer's own page (section 12).
    rows = [{**row, "official_sources": [s for s in row.get("sources") or () if market_text.official(str(s))]}
            for row in rows]
    if not open_only:
        return rows
    still_open = {g["id"] for g in gaps.list_gaps() if g.get("status") == "open"}
    return [row for row in rows if row["gap_id"] in still_open]


def open_gaps(limit: int | None = None) -> list[dict[str, Any]]:
    """Open gaps without a suggestion yet, the most asked first."""
    have = set(_read())
    pending = [g for g in gaps.list_gaps() if g.get("status") == "open" and g["id"] not in have]
    pending.sort(key=lambda g: -len(g.get("occurrences") or ()))
    return pending[:limit] if limit else pending
