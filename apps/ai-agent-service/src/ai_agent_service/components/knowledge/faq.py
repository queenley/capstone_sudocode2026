"""FAQ entries an admin keeps in ``kb_chunks``: drafts wait, live ones are served, deleted ones stay as a record.

Changes here reach the agent through the knowledge server's refresh, within seconds and with no restart; they do not
touch ``data/kb/v<N>.jsonl``, so the version a run was measured on stays what it was. An entry goes live only when a
person approves it and the code's gate finds nothing (:func:`.gap.gate`): a draft, the ones in ``data/kb/drafts.jsonl``
included, is never read by the agent. Rows from a release file are read-only here: change the file instead.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from typing import Any, Literal, Mapping, Sequence

from ...config.config_manager import btc_data_dir
from ..improvement.gap import gate
from ..intake import pii
from . import corpus, promotions

Status = Literal["draft", "live"]

#: ``applies_to`` as ``promotions.json`` writes it.
TARGET = re.compile(r"\*|SKU-[A-Z0-9-]+|category:[a-z0-9/-]+")
COLUMNS = "chunk_id, source, title, text, valid_from, valid_to, provenance, scope, status, updated_at"
LIST = f"SELECT {COLUMNS} FROM kb_chunks WHERE source = 'faq' AND status <> 'deleted' ORDER BY status, chunk_id"
ONE = f"SELECT {COLUMNS} FROM kb_chunks WHERE chunk_id = %s AND source = 'faq' AND status <> 'deleted'"
SAVE = ("INSERT INTO kb_chunks (chunk_id, source, title, text, valid_from, valid_to, provenance, scope, status, revoked,"
        " updated_at) VALUES (%s, 'faq', %s, %s, %s, %s, %s, 'demo', %s, %s, now()) "
        "ON CONFLICT (chunk_id) DO UPDATE SET title = EXCLUDED.title, text = EXCLUDED.text,"
        " valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to, provenance = EXCLUDED.provenance,"
        " status = EXCLUDED.status, revoked = EXCLUDED.revoked, updated_at = now()")
DELETE = "UPDATE kb_chunks SET status = 'deleted', revoked = true, updated_at = now() WHERE chunk_id = %s"


class ReadOnly(Exception):
    """The entry belongs to a release file."""


def citable() -> set[str]:
    """The passages an answer may rest on: public and in force for good, so no retired or internal one."""
    return {chunk.chunk_id for chunk in corpus.policy_chunks(btc_data_dir() / "policy")
            if not chunk.restricted and not chunk.valid_to}


def problems(entry: Mapping[str, Any], *, status: Status) -> list[str]:
    """Why *entry* cannot be saved with *status*; a draft needs only to be well formed."""
    found = [f"applies_to không hợp lệ: {target}" for target in entry.get("applies_to") or ()
             if not TARGET.fullmatch(target)]
    start, end = entry.get("valid_from"), entry.get("valid_to")
    if start and end and str(start) > str(end):
        found.append("Ngày bắt đầu sau ngày kết thúc.")
    try:
        corpus.with_campaigns([corpus.entry_chunk({"source": "faq", "chunk_id": "check", **entry}, doc="faq")], promotions())
    except ValueError as error:
        found.append(str(error).removeprefix("faq: "))
    if status == "draft":
        return found
    found.extend(gate(str(entry.get("title") or ""), str(entry.get("text") or "")))
    if pii.tokenise(str(entry.get("text") or ""), pii.Vault()) != entry.get("text"):
        found.append("Câu trả lời có dữ liệu cá nhân.")
    cites = list(entry.get("cites") or ())
    if not cites:
        found.append("Cần ít nhất một nguồn để duyệt.")
    unknown = sorted(set(cites) - citable())
    if unknown:
        found.append(f"Nguồn không công khai hoặc đã hết hiệu lực: {', '.join(unknown)}")
    return found


def view(row: Mapping[str, Any], on: str) -> dict[str, Any]:
    """One row as the console shows it: what was written, and the days and products that will really apply."""
    provenance = dict(row.get("provenance") or {})
    entry = {**provenance, **{key: row[key] for key in ("chunk_id", "source", "title", "text", "valid_from", "valid_to")}}
    try:
        chunk = corpus.with_campaigns([corpus.entry_chunk(entry, doc="faq")], promotions())[0]
    except ValueError:  # A row saved before these checks, or a promotion that left the catalogue.
        chunk = corpus.entry_chunk({**entry, "applies_to": None}, doc="faq")
    return {
        "chunk_id": row["chunk_id"], "title": row["title"], "text": row["text"], "status": row["status"],
        "valid_from": _iso(row["valid_from"]), "valid_to": _iso(row["valid_to"]),
        "campaign": provenance.get("campaign"), "applies_to": provenance.get("applies_to") or [],
        "cites": provenance.get("cites") or [], "approved_by": provenance.get("approved_by"),
        "effective": {"valid_from": chunk.valid_from, "valid_to": chunk.valid_to, "applies_to": list(chunk.applies_to)},
        "in_force": row["status"] == "live" and chunk.in_force(on),
        "editable": row["scope"] != "release",
    }


async def entries(conn: Any, on: str) -> list[dict[str, Any]]:
    rows = await (await conn.execute(LIST)).fetchall()
    return [view(row, on) for row in rows]


async def save(conn: Any, chunk_id: str | None, entry: Mapping[str, Any], *, status: Status, actor: str, on: str,
               new_id: str | None = None) -> dict[str, Any]:
    """Add an entry, as *new_id* if given, or replace *chunk_id*.

    Raises ``KeyError``, :class:`ReadOnly` or ``ValueError`` with the reasons.
    """
    found = problems(entry, status=status)
    if found:
        raise ValueError(" ".join(found))
    old: dict[str, Any] = {}
    if chunk_id is not None:
        row = await (await conn.execute(ONE, (chunk_id,))).fetchone()
        if row is None:
            raise KeyError(chunk_id)
        if row["scope"] == "release":
            raise ReadOnly(chunk_id)
        old = dict(row["provenance"] or {})
    chunk_id = chunk_id or new_id or f"FAQ-{uuid.uuid4().hex[:8].upper()}"
    provenance = {**old, "cites": list(entry.get("cites") or ()), "edited_by": actor}
    for key in ("campaign", "applies_to"):
        provenance.pop(key, None)
        if entry.get(key):
            provenance[key] = entry[key]
    if status == "live":
        provenance["approved_by"] = actor
    else:
        provenance.pop("approved_by", None)
    await conn.execute(SAVE, (chunk_id, entry["title"], entry["text"], entry.get("valid_from") or None,
                              entry.get("valid_to") or None, json.dumps(provenance, ensure_ascii=False), status,
                              status != "live"))
    row = await (await conn.execute(ONE, (chunk_id,))).fetchone()
    return view(row, on)


async def delete(conn: Any, chunk_id: str) -> None:
    row = await (await conn.execute(ONE, (chunk_id,))).fetchone()
    if row is None:
        raise KeyError(chunk_id)
    if row["scope"] == "release":
        raise ReadOnly(chunk_id)
    await conn.execute(DELETE, (chunk_id,))


def promotion_choices() -> Sequence[dict[str, Any]]:
    """What a campaign may name, for the console's list."""
    return [{"code": p["promo_code"], "name": p["name"], "start": p["start"], "end": p["end"]} for p in promotions()]


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, date) else value
