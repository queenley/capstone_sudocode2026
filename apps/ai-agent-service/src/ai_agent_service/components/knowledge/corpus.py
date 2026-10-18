"""What the shop's documents say, cut where the organisers cut them. ``docs/design.md`` sections 7.1, 7.2 and 7.5.

Three sources end up in one knowledge base, each entry a :class:`Chunk`:

- **policy**: the organisers' corpus, ``policy/*.md``, one chunk per
  ``## [XX-nn]`` section, 99 in all. The section code is the ``chunk_id`` the
  organisers label Recall@k with (``rag/qa_labeled.json``), so a section is
  never split or merged, not even DT-01 with DT-OLD-01, which share a title.
- **faq** and **playbook**: entries the improvement loop adds after a person
  approved them. Approved entries ship in the repository as
  ``data/kb/v<N>.jsonl`` (section 7.5), because the organisers grade the final
  build from the README; entries saved during a demo stay in the database.

Every chunk carries what retrieval needs to be safe as well as relevant:
whether it is ``restricted`` (internal: purchase prices, suppliers, the price
floor), when it is in force (from ``changelog.md``), the changelog entries
that explain it, and the industry it is about.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

Source = Literal["policy", "faq", "playbook"]

#: ``## [DT-03] Đổi size / màu`` -> ("DT-03", "Đổi size / màu"); also DT-OLD-01, SP-AIR-01.
SECTION = re.compile(r"^## \[([A-Z]+(?:-[A-Z]+)?-\d+)\]\s*(.*)$", re.MULTILINE)
TITLE = re.compile(r"^# (.+)$", re.MULTILINE)

#: Section 7.2: restricted chunk by chunk, not only document by document. A
#: document marked internal is restricted whole; KM-06 sits in a public
#: document but holds the price floor percentages.
INTERNAL_MARK = "NỘI BỘ"
RESTRICTED_SECTIONS = frozenset({"KM-06"})

#: Restricted chunks whose one usable fact reaches the customer through a tool
#: instead: NB-02's restock dates come from ``inventory.check``
#: (``restock_expected``), never from the note itself (section 7.2).
THROUGH_TOOLS = {"NB-02": "inventory_check"}


@dataclass(frozen=True)
class Governs:
    """One row of section 7.2's fixed table: which chunks a changelog entry
    governs, and the window it puts them in force."""

    entry: str
    prefixes: tuple[str, ...] = ()
    ids: tuple[str, ...] = ()
    valid_from: str | None = None
    valid_to: str | None = None

    def covers(self, chunk_id: str) -> bool:
        return chunk_id in self.ids or any(chunk_id.startswith(p) for p in self.prefixes)


#: ``changelog.md``, read once by a person and fixed here (section 7.2).
#:
#: Only CL-01 puts chunks in windows, because only the returns policy exists
#: in two versions in the corpus: the 2026-06 text (DT-OLD) for orders placed
#: before 01/10 and the 2026-10 text (DT) after. The other entries changed a
#: rule whose old text the corpus no longer holds (CL-03's COD cap, CL-04's 24
#: months for older water purifiers): the current chunk stays in force, and
#: the entry travels with it to explain the exception, so "máy lọc không khí
#: mua tháng 7 bảo hành bao lâu" still finds BH-01.
CHANGELOG: tuple[Governs, ...] = (
    Governs("CL-01", prefixes=("DT-OLD-",), valid_to="2026-09-30"),
    Governs("CL-01", ids=tuple(f"DT-0{n}" for n in range(1, 8)), valid_from="2026-10-01"),
    Governs("CL-02", prefixes=("KM-",)),
    Governs("CL-03", prefixes=("VC-",)),
    Governs("CL-04", prefixes=("BH-",)),
    Governs("CL-05", ids=("FAQ-16", "SP-AIR-03")),
)

#: The industry a chunk is about, for the brief's mismatch check and the
#: playbook's situations. Policy chunks not listed apply to every industry.
INDUSTRY_BY_PREFIX = {
    "SP-AIR": "gia-dung", "SP-WF": "gia-dung", "SP-FAN": "gia-dung", "SP-AF": "gia-dung",
    "SP-SN": "thoi-trang", "SP-JK": "thoi-trang", "SP-MB": "me-be",
}
INDUSTRY_BY_ID = {
    **{f"FAQ-0{n}": "gia-dung" for n in range(1, 9)},
    "FAQ-09": "thoi-trang", "FAQ-10": "thoi-trang",
    "FAQ-11": "me-be", "FAQ-12": "me-be", "FAQ-13": "me-be",
    "FAQ-19": "gia-dung",
}


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage and everything retrieval must know about it."""

    chunk_id: str
    #: The document it comes from: a policy file name, or ``kb/v<N>.jsonl`` and ``kb_chunks``.
    doc: str
    #: The document's own title (its ``#`` line), part of what is indexed.
    doc_title: str
    title: str
    text: str
    source: Source = "policy"
    restricted: bool = False
    valid_from: str | None = None
    valid_to: str | None = None
    #: The changelog entries that explain this chunk's validity (CL-01 for a DT chunk).
    changelog: tuple[str, ...] = ()
    industry: str | None = None
    #: For a playbook entry: the situation of ``config/situations.yaml`` it handles.
    situation: str | None = None
    persona: str | None = None
    #: For a team entry: where it came from, who approved it, what it cites (section 5.5).
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def indexed(self) -> str:
        """The text the indexes see: the document and section titles first.

        The deterministic form of Contextual Retrieval (section 7.3): a section
        such as "Hoàn tiền" means nothing on its own, "Chính sách đổi trả ...
        Hoàn tiền ..." does, and no model is needed to say so.
        """
        return f"{self.doc_title}\n{self.title}\n{self.text}"

    def in_force(self, day: str | None) -> bool:
        """Whether this chunk's rule holds on *day* (``YYYY-MM-DD``); always, without a day."""
        if day is None:
            return True
        if self.valid_from and day < self.valid_from:
            return False
        return not (self.valid_to and day > self.valid_to)


# ── the organisers' corpus ────────────────────────────────────────────────


def policy_chunks(folder: Path) -> list[Chunk]:
    """Every ``## [XX-nn]`` section of every ``*.md`` under *folder*, in file order."""
    chunks: list[Chunk] = []
    for path in sorted(folder.glob("*.md")):
        body = path.read_text(encoding="utf-8")
        heading = TITLE.search(body)
        doc_title = heading.group(1).strip() if heading else path.stem
        internal = INTERNAL_MARK in doc_title
        sections = list(SECTION.finditer(body))
        for index, match in enumerate(sections):
            end = sections[index + 1].start() if index + 1 < len(sections) else len(body)
            chunk_id = match.group(1)
            window = _window(chunk_id)
            chunks.append(Chunk(
                chunk_id=chunk_id,
                doc=path.name,
                doc_title=doc_title,
                title=match.group(2).strip(),
                text=body[match.end():end].strip(),
                restricted=internal or chunk_id in RESTRICTED_SECTIONS,
                valid_from=window.valid_from,
                valid_to=window.valid_to,
                changelog=tuple(dict.fromkeys(g.entry for g in CHANGELOG if g.covers(chunk_id))),
                industry=_industry(chunk_id),
            ))
    return chunks


def _window(chunk_id: str) -> Governs:
    """The validity window the changelog puts *chunk_id* in, if any."""
    windows = [g for g in CHANGELOG if g.covers(chunk_id) and (g.valid_from or g.valid_to)]
    if len(windows) > 1:
        raise ValueError(f"{chunk_id} is governed by {len(windows)} windows; the table in corpus.CHANGELOG is ambiguous")
    return windows[0] if windows else Governs("")


def _industry(chunk_id: str) -> str | None:
    if chunk_id in INDUSTRY_BY_ID:
        return INDUSTRY_BY_ID[chunk_id]
    prefix = chunk_id.rsplit("-", 1)[0]
    return INDUSTRY_BY_PREFIX.get(prefix)


# ── the team's entries ────────────────────────────────────────────────────

#: Fields every line of ``data/kb/v<N>.jsonl`` must have (section 7.5).
ENTRY_REQUIRED = ("chunk_id", "source", "title", "text")


def entry_chunk(entry: Mapping[str, Any], *, doc: str) -> Chunk:
    """One FAQ or playbook entry as a chunk, from a version file or a ``kb_chunks`` row.

    Raises ``ValueError`` naming what is wrong: an entry that cannot be read
    is a mistake in an approved file, never something to skip in silence.
    """
    missing = [name for name in ENTRY_REQUIRED if not entry.get(name)]
    if missing:
        raise ValueError(f"{doc}: entry {entry.get('chunk_id') or '?'} lacks {', '.join(missing)}")
    source = str(entry["source"])
    if source not in ("faq", "playbook"):
        raise ValueError(f"{doc}: entry {entry['chunk_id']} has source {source!r}; only faq and playbook are added")
    title = str(entry["title"])
    known = {"chunk_id", "source", "title", "text", "situation", "persona", "valid_from", "valid_to"}
    return Chunk(
        chunk_id=str(entry["chunk_id"]),
        doc=doc,
        doc_title="Câu hỏi thường gặp" if source == "faq" else "Kịch bản xử lý tình huống",
        title=title,
        text=str(entry["text"]),
        source=source,  # type: ignore[arg-type]
        valid_from=_day(entry.get("valid_from")),
        valid_to=_day(entry.get("valid_to")),
        situation=entry.get("situation") or None,
        persona=entry.get("persona") or None,
        provenance={k: v for k, v in entry.items() if k not in known},
    )


def version_file(directory: Path, version: int) -> Path:
    """``data/kb/v<N>.jsonl``: the approved entries of knowledge version *version*."""
    return directory / f"v{version}.jsonl"


def load_version(directory: Path, version: int) -> list[Chunk]:
    """The approved entries of one knowledge version (section 7.5).

    A missing file is an error, not an empty base: the configured version is
    what the run's manifest records, so it must exist.
    """
    path = version_file(directory, version)
    if not path.exists():
        raise FileNotFoundError(f"Knowledge version {version} is configured but {path} does not exist")
    chunks: list[Chunk] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError as error:
            raise ValueError(f"{path.name}:{number} is not JSON: {error}") from error
        chunk = entry_chunk(entry, doc=path.name)
        if chunk.chunk_id in seen:
            raise ValueError(f"{path.name}:{number} repeats chunk_id {chunk.chunk_id}")
        seen.add(chunk.chunk_id)
        chunks.append(chunk)
    return chunks


def _day(value: Any) -> str | None:
    if not value:
        return None
    return (value if isinstance(value, date) else date.fromisoformat(str(value)[:10])).isoformat()


def by_id(chunks: Iterable[Chunk]) -> dict[str, Chunk]:
    return {chunk.chunk_id: chunk for chunk in chunks}
