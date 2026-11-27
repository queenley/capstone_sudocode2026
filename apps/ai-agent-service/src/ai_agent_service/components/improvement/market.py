"""Battlecards from the market research: the gate, the store, a person's decision, publishing. ``docs/plan/002``.

A battlecard says what the **shop** offers a customer who compares one of its products with another seller's: the
warranty, the returns, the delivery, the product's own attributes, each point citing a section of the organisers'
documents. It never names another seller or a brand the shop does not sell, never runs anyone down, and never holds
an amount, a promotion code or a stock status (PB-02, PB-04, FAQ-15; the Gap Loop's gate 2).

What the research learned about other sellers (their products, specs, the prices seen, the links) is **evidence**:
``IMPROVEMENT_DIR/market/evidence.jsonl``, for staff to read. It never reaches the advisor.

| Step | Here |
|---|---|
| a card is written | :func:`add_card` stores it with the gate's reasons; a flagged card is never approvable |
| a person decides | :func:`decide`: a person's name (never an agent of the loop), a pending card, the gate again |
| it goes live | a playbook entry for the product (``situation: price_comparison``, ``applies_to: [sku]``) in the next
  knowledge version; an earlier card for the same product is revoked first, so one card is live per product |
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ...config.config_manager import btc_data_dir
from .. import market as market_text
from ..intake.text import plain
from ..knowledge.corpus import Chunk, policy_chunks
from . import review, signals, versions
from .gap import gate as knowledge_gate
from .lessons import MONEY
from .storage import atomic_text, locked

SITUATION = "price_comparison"
#: Always indexed with a card, whatever the model wrote.
COMPARISON_QUESTIONS = ("Sao bên kia bán rẻ hơn vậy em?", "Chỗ khác cũng có máy này, mua ở shop được gì hơn?",
                        "Trên mạng thấy giá thấp hơn, sao phải mua ở đây?")


def comparison_questions(questions: Iterable[str]) -> list[str]:
    """The model's questions that compare with another seller, then the fixed ones; nothing else is indexed."""
    kept = [str(q).strip() for q in questions if market_text.compares(str(q))]
    return list(dict.fromkeys([*kept, *COMPARISON_QUESTIONS]))
CHUNK_PREFIX = "BC-"
STATUSES = ("pending", "flagged", "approved", "rejected")


def _folder() -> Path:
    return signals.home() / "market"


def _cards_path() -> Path:
    return _folder() / "cards.json"


def _evidence_path() -> Path:
    return _folder() / "evidence.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── the catalogue and the sections a card may cite ─────────────────────────


def products(*, category: str | None = None, skus: Iterable[str] = ()) -> list[dict[str, Any]]:
    """The shop's products on sale, from the organisers' catalogue, optionally of one category prefix or some SKUs."""
    data = json.loads((btc_data_dir() / "catalog" / "products.json").read_text(encoding="utf-8"))
    wanted = {str(s) for s in skus}
    found = []
    for product in data.get("products") or []:
        if (product.get("attributes") or {}).get("discontinued"):
            continue
        if wanted and product["sku"] not in wanted:
            continue
        if category and not str(product.get("category") or "").startswith(category):
            continue
        found.append(product)
    return found


def our_brands() -> frozenset[str]:
    data = json.loads((btc_data_dir() / "catalog" / "products.json").read_text(encoding="utf-8"))
    return frozenset(plain(str(p.get("brand") or "")).casefold() for p in data.get("products") or [] if p.get("brand"))


def industry(category: str) -> str:
    return str(category or "").split("/", 1)[0]


def citable(category: str) -> dict[str, Chunk]:
    """The organisers' public sections in force a card about a product of *category* may cite, by code."""
    prefixes = tuple(str(p) for p in market_text.settings()["battlecard"].get("cite_prefixes") or ())
    kind = industry(category)
    found: dict[str, Chunk] = {}
    for chunk in policy_chunks(btc_data_dir() / "policy"):
        if chunk.restricted or chunk.valid_to or not chunk.chunk_id.startswith(prefixes):
            continue
        if chunk.industry and chunk.industry != kind:
            continue
        found[chunk.chunk_id] = chunk
    return found


# ── the gate ───────────────────────────────────────────────────────────────


def _mentions(text: str, name: str) -> bool:
    name = plain(name).casefold().strip()
    return bool(name) and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def card_texts(card: Mapping[str, Any]) -> list[str]:
    """Every sentence of *card* the advisor reads, and so a customer could end up hearing.

    The ``questions`` are not among them: they are indexed for retrieval and never read to the advisor
    (``Chunk.questions``), and a customer's own words ("bên kia bán rẻ hơn") are what they must match. They are
    still checked for amounts and personal data.
    """
    return [*(str(p.get("text") or "") for p in card.get("points") or ()), *map(str, card.get("compared_on") or ())]


def gate(card: Mapping[str, Any], *, product: Mapping[str, Any], cites: Mapping[str, Any],
         foreign_brands: Iterable[str] = ()) -> tuple[str, ...]:
    """Why *card* may not go live; empty when code finds nothing. A person still reads every card."""
    config = market_text.settings()["battlecard"]
    reasons: list[str] = []
    points = list(card.get("points") or ())
    if not points:
        reasons.append("Thẻ không có ý nào.")
    if len(points) > int(config.get("max_points") or 3):
        reasons.append(f"Thẻ có {len(points)} ý; tối đa {config.get('max_points')} (giới hạn số câu của hard guard).")
    for index, point in enumerate(points, 1):
        used = [str(c) for c in point.get("cites") or ()]
        if not used:
            reasons.append(f"Ý {index} không trích tài liệu nào: mỗi ý phải có nguồn trong tài liệu BTC.")
        unknown = [c for c in used if c not in cites]
        if unknown:
            reasons.append(f"Ý {index} trích mã không được phép hoặc không tồn tại: {', '.join(unknown)}.")
    joined = "\n".join(card_texts(card))
    questions = "\n".join(map(str, card.get("questions") or ()))
    reasons += knowledge_gate(questions, joined)
    if MONEY.search(questions):
        reasons.append("Câu hỏi mẫu có số tiền: giá chỉ đến từ tool, kể cả trong phần được lập chỉ mục.")
    if market_text.DIGIT_RUN.search(questions):
        reasons.append("Câu hỏi mẫu có một dãy số dài như số điện thoại.")
    said = plain(joined).casefold()
    named = [r for r in config.get("retailers") or () if _mentions(said, str(r))]
    if named:
        reasons.append(f"Nêu tên nơi bán khác ({', '.join(named)}): không so với nơi khác (PB-02, PB-04).")
    ours = our_brands()
    brands = sorted({b for b in foreign_brands if b and plain(b).casefold() not in ours and _mentions(said, b)})
    if brands:
        reasons.append(f"Nêu thương hiệu shop không bán ({', '.join(brands)}): thẻ chỉ nói về sản phẩm của shop.")
    down = [w for w in config.get("disparaging") or () if _mentions(said, str(w))]
    if down:
        reasons.append(f"Có lời so bì hoặc chê ({', '.join(down)}): không nói xấu, không so giá (PB-04).")
    if market_text.DIGIT_RUN.search(joined):
        reasons.append("Có một dãy số dài như số điện thoại hay số tài khoản.")
    if not str(product.get("sku") or ""):
        reasons.append("Thẻ không gắn với sản phẩm nào.")
    return tuple(dict.fromkeys(reasons))


# ── the store ──────────────────────────────────────────────────────────────


def _read() -> dict[str, dict[str, Any]]:
    path = _cards_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write(rows: Mapping[str, Any]) -> None:
    atomic_text(_cards_path(), json.dumps(rows, ensure_ascii=False, indent=2))


def add_evidence(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Append search results as evidence; returns their ids. Internal: staff read it, the advisor never does."""
    ids: list[str] = []
    if not rows:
        return ids
    with locked(_folder()):
        with _evidence_path().open("a", encoding="utf-8") as stream:
            for row in rows:
                evidence_id = hashlib.sha256(
                    f"{row.get('sku')}\n{row.get('query')}\n{row.get('url')}\n{row.get('fetched_at')}".encode()).hexdigest()[:16]
                stream.write(json.dumps({"id": evidence_id, **row}, ensure_ascii=False) + "\n")
                ids.append(evidence_id)
    return ids


def evidence(sku: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    path = _evidence_path()
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if sku is None or row.get("sku") == sku]
    return rows[-limit:]


def add_card(card: Mapping[str, Any], *, product: Mapping[str, Any], round_name: str, model: str | None,
             evidence_ids: Sequence[str], competitors: Sequence[Mapping[str, Any]] = (),
             foreign_brands: Iterable[str] = ()) -> dict[str, Any]:
    """Store a card the research wrote, with what the gate says of it; returns the stored record."""
    card = {**card, "questions": comparison_questions(card.get("questions") or ())}
    cites = citable(str(product.get("category") or ""))
    reasons = gate(card, product=product, cites=cites, foreign_brands=foreign_brands)
    body = json.dumps(card, ensure_ascii=False, sort_keys=True)
    card_id = hashlib.sha256(f"{product['sku']}\n{body}".encode()).hexdigest()[:12]
    record = {
        "id": card_id,
        "sku": product["sku"],
        "product": product.get("name"),
        "round": round_name,
        "created_at": _now(),
        "status": "flagged" if reasons else "pending",
        "gate": list(reasons),
        "card": {"compared_on": list(card.get("compared_on") or []), "points": list(card.get("points") or []),
                 "questions": list(card.get("questions") or [])},
        # Internal: what the research saw of other sellers, for the reviewer. Never published.
        "competitors": [dict(c) for c in competitors],
        "evidence_ids": list(evidence_ids),
        "model": model,
    }
    with locked(_folder()):
        rows = _read()
        if card_id in rows:
            return rows[card_id]
        rows[card_id] = record
        _write(rows)
    review.log("market_card", card_id=card_id, sku=product["sku"], round=round_name, status=record["status"],
               gate=list(reasons), author="market")
    return record


def cards(status: str | None = None) -> list[dict[str, Any]]:
    rows = sorted(_read().values(), key=lambda r: r.get("created_at") or "", reverse=True)
    return [row for row in rows if status is None or row.get("status") == status]


def card(card_id: str) -> dict[str, Any]:
    rows = _read()
    if card_id not in rows:
        raise KeyError(f"No battlecard {card_id}")
    return rows[card_id]


# ── a person's decision, and publishing ────────────────────────────────────


def entry(record: Mapping[str, Any], *, reviewer: str) -> dict[str, Any]:
    """The knowledge entry of an approved card: a playbook entry for one product, in the price comparison situation."""
    body = record["card"]
    # Codes in square brackets, never in parentheses: the advisor imitates the passages it is shown, and the marks
    # the customer never hears are removed in square brackets only (pipeline/hot/nodes.py, ``unmarked``).
    lines = ["Khách so sản phẩm này với nơi khác: không bình luận, không xác nhận hay phủ nhận giá hay chất lượng nơi "
             "khác, không nói xấu ai [PB-02, PB-04]. Nói điều khách nhận được khi mua ở shop:"]
    lines += [f"- {p['text'].strip()} [{', '.join(p.get('cites') or [])}]" for p in body["points"]]
    if body.get("compared_on"):
        lines.append("Khách hay so về: " + ", ".join(body["compared_on"]) + ". Đối chiếu đúng thuộc tính đó của sản "
                     "phẩm trong catalog_search; giá và khuyến mãi luôn lấy từ pricing_get_quote.")
    cites = sorted({str(c) for p in body["points"] for c in p.get("cites") or ()} | {"PB-02", "PB-04"})
    return {
        "chunk_id": f"{CHUNK_PREFIX}{record['sku']}-{record['id'][:6].upper()}",
        "source": "playbook",
        "situation": SITUATION,
        "title": f"{record['product'] or record['sku']}: khi khách so với nơi khác",
        "text": "\n".join(lines),
        "applies_to": [record["sku"]],
        "questions": comparison_questions(body.get("questions") or ()),
        "approved_by": reviewer,
        "cites": cites,
        "battlecard": {"card_id": record["id"], "round": record.get("round"), "evidence_ids": record.get("evidence_ids") or []},
    }


def _person(reviewer: str) -> str:
    name = str(reviewer or "").strip()
    if not name or name.casefold() in review.AGENTS or name.casefold() in {"market", "marketresearchagent"}:
        raise ValueError("A battlecard is decided by a person, never by an agent of the loop")
    return name


def decide(card_id: str, decision: str, *, reviewer: str, note: str = "", directory: Path | None = None,
           config_path: Path | None = None) -> dict[str, Any]:
    """Approve (publish) or reject one pending card. Returns the updated record.

    *directory* and *config_path* are the knowledge versions' folder and ``knowledge.yaml``, as for
    :func:`versions.publish`; the service's own when left out.
    """
    where: dict[str, Any] = {"directory": directory}
    if config_path is not None:
        where["config_path"] = config_path
    if decision not in ("approved", "rejected"):
        raise ValueError("decision is approved or rejected")
    reviewer = _person(reviewer)
    with locked(_folder()):
        rows = _read()
        record = rows.get(card_id)
        if record is None:
            raise KeyError(f"No battlecard {card_id}")
        if record["status"] != "pending":
            raise ValueError(f"Battlecard {card_id} is {record['status']}; only a pending card is decided")
        if decision == "rejected":
            record.update(status="rejected", reviewer=reviewer, note=note, decided_at=_now())
            _write(rows)
            review.log("market_card_rejected", card_id=card_id, sku=record["sku"], reviewer=reviewer, note=note)
            return record
        product = next(iter(products(skus=[record["sku"]])), None)
        if product is None:
            raise ValueError(f"{record['sku']} is not on sale any more")
        brands = [str(c.get("brand") or "") for c in record.get("competitors") or ()]
        reasons = gate(record["card"], product=product, cites=citable(str(product.get("category") or "")),
                       foreign_brands=brands)
        if reasons:
            record.update(status="flagged", gate=list(reasons))
            _write(rows)
            raise ValueError("The gate refuses this card now: " + " ".join(reasons))
        new = entry(record, reviewer=reviewer)
        active = versions.active(config_path) if config_path is not None else versions.active()
        live = [line["chunk_id"] for line in versions.entries(active, directory)
                if str(line.get("chunk_id", "")).startswith(f"{CHUNK_PREFIX}{record['sku']}-")]
        for old in live:
            versions.revoke(old, reviewer=reviewer, reason=f"Replaced by battlecard {card_id}", **where)
        version = versions.publish([new], reviewer=reviewer, note=f"Battlecard {card_id} for {record['sku']}", **where)
        record.update(status="approved", reviewer=reviewer, note=note, decided_at=_now(), chunk_id=new["chunk_id"],
                      knowledge_version=version, replaced=live)
        _write(rows)
    review.log("market_card_approved", card_id=card_id, sku=record["sku"], reviewer=reviewer,
               chunk_id=new["chunk_id"], version=version)
    return record
