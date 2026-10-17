"""Searching the knowledge base: which passages a turn may read, and when to say "no information".

``docs/design.md`` sections 4.2 and 7.3. :class:`KnowledgeBase` answers one
question per customer turn, in a few milliseconds, with:

- the top passages, keyword (BM25) and meaning (embedding) rankings fused by
  Reciprocal Rank Fusion, each with its flags: ``restricted`` (its text is
  never handed out, only its code and what to do instead), ``superseded``
  (not in force on the day that matters: the call's day, or the order's day
  when the question is about an order, CL-01), and the changelog entries that
  explain why;
- whether to **abstain**, and why, for the router's rule 5 and the advisor's
  "Dạ hiện em chưa có thông tin về…" (PB-05):

  | Reason | When |
  |---|---|
  | ``restricted`` | the best passage is internal and holds nothing a tool gives instead (purchase prices, suppliers, the price floor) |
  | ``absence`` | the best passage answers by saying there is no information, or that this must not be said (FAQ-03 on radon, KM-02 on unannounced sales) |
  | ``no_match`` | the best passage's similarity is under θ |

The organisers label "unanswerable" questions with the passage that proves
the absence (``rag/qa_labeled.json``: "bằng chứng vắng mặt"), so a good
retriever finds FAQ-03 for "radon" with high similarity: a threshold alone
can never abstain there. What abstains is reading which sentence of the
passage the question is about; when it is the sentence that says "không có
thông tin", that is the answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Sequence

from ..intake.text import plain
from .corpus import THROUGH_TOOLS, Chunk, by_id
from .lexical import Lexical, fuse
from .semantic import Embedder, Vectors

Reason = Literal["no_match", "restricted", "absence"]

#: Sentences that answer by absence or by a ban (diacritics removed). Each is
#: a phrase of the organisers' corpus that means "the shop does not say":
#: FAQ-03, FAQ-11, FAQ-13, SP-MB-01, SP-MB-03 (no information), SP-AIR-03 (not
#: sold), FAQ-02 and PB-06 (no medical advice, hand over), KM-02 and FAQ-14
#: (an unannounced promotion). "chưa hỗ trợ trả góp" is not one: that is an answer.
ABSENCE = re.compile(
    r"khong co thong tin|chua co thong tin|chua kinh doanh|khong (duoc )?tu van|khong co bang chung"
    r"|chuyen may|khong duoc bao truoc|khong duoc tiet lo"
)
SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")
#: What the advisor is told instead of a restricted passage's text (its context is Vietnamese).
REFUSE = ("Đoạn [{id}] ({title}) là tài liệu nội bộ: không đọc, không trích, không xác nhận nội dung của nó; khách hỏi "
          "đúng điều đó thì nói đây là thông tin nội bộ em không cung cấp được.")
REDIRECT = ("Đoạn [{id}] ({title}) là tài liệu nội bộ: điều khách cần ở đây chỉ lấy từ kết quả của {tool}; không nói "
            "số lượng, giá nhập hay nhà cung cấp.")
#: What the advisor is told of a passage not in force on the day that matters.
EXPIRED = ("hết hiệu lực từ {day}; chỉ áp dụng cho đơn tạo trước ngày đó. Với đơn mới hay câu hỏi chung, nói theo bản "
           "đang hiệu lực và ngày cập nhật, không nhắc lại con số của đoạn này")
NOT_YET = "áp dụng cho đơn tạo từ {day}; đơn đang hỏi tạo trước ngày đó nên theo bản cũ"


@dataclass(frozen=True)
class Settings:
    """How retrieval behaves; ``config/knowledge.yaml`` holds the values (section 7.3)."""

    top_k: int = 5
    fusion_k: int = 60
    k1: float = 1.2
    b: float = 0.75
    accents: bool = True
    #: θ, on the cosine of the best passage when an embedding model is loaded.
    abstain_cosine: float = 0.0
    #: θ, on the best passage's share of the question's information when keyword-only.
    abstain_coverage: float = 0.0


@dataclass(frozen=True)
class Hit:
    """One passage of a result, with everything the caller may need to decide on it."""

    chunk: Chunk
    rank: int
    #: The fused score (Reciprocal Rank Fusion), or BM25 when keyword-only.
    score: float
    cosine: float | None
    #: The share of the question's information this passage holds, 0 to 1.
    coverage: float
    superseded: bool
    #: The sentence the question is about says there is no information, or bans saying it.
    absence: bool
    #: For a restricted passage: what to do instead of reading it.
    instruction: str | None
    #: For a superseded passage: since or until when it holds, and what that means for the answer.
    validity: str | None = None
    #: For a restricted passage whose one usable fact a tool gives instead: that tool.
    redirect: str | None = None


@dataclass(frozen=True)
class Result:
    query: str
    hits: tuple[Hit, ...]
    #: θ's score of the best passage: its cosine, or its coverage when keyword-only.
    top_score: float | None
    abstain: bool
    reason: Reason | None
    #: The changelog entries the hits cite, pulled along with them (section 4.2).
    changelog: dict[str, Chunk] = field(default_factory=dict)
    #: "hybrid" or "keyword": which retrieval produced the ranking.
    mode: str = "keyword"


class KnowledgeBase:
    """The chunks, their two indexes, and the search policy of section 7.3."""

    def __init__(
        self,
        chunks: Sequence[Chunk],
        *,
        settings: Settings = Settings(),
        embedder: Embedder | None = None,
        cache: Path | None = None,
    ) -> None:
        ids = [c.chunk_id for c in chunks]
        if len(ids) != len(set(ids)):
            repeated = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"Chunk ids must be unique; repeated: {', '.join(repeated)}")
        self.chunks: tuple[Chunk, ...] = tuple(chunks)
        self.settings = settings
        self._by_id = by_id(chunks)
        documents = [(c.chunk_id, c.indexed) for c in chunks]
        self._lexical = Lexical(documents, k1=settings.k1, b=settings.b, accents=settings.accents)
        self._embedder, self._cache = embedder, cache
        self._vectors = Vectors(embedder, documents, cache=cache) if embedder is not None else None

    @property
    def mode(self) -> str:
        return "hybrid" if self._vectors is not None else "keyword"

    def extended(self, extra: Sequence[Chunk]) -> "KnowledgeBase":
        """This base with *extra* chunks added (entries saved at runtime), same model and cache."""
        return KnowledgeBase([*self.chunks, *extra], settings=self.settings, embedder=self._embedder, cache=self._cache)

    def search(
        self,
        query: str,
        *,
        k: int | None = None,
        on: str | None = None,
        order_date: str | None = None,
        situation: str | None = None,
    ) -> Result:
        """The top *k* passages for *query* and whether to abstain.

        *on* is the call's day; *order_date*, when the question is about an
        order already placed, decides which version of a policy holds (CL-01:
        an order placed before 01/10 keeps the old returns policy). A playbook
        entry for *situation* is preferred over others (section 7.3).
        """
        k = k or self.settings.top_k
        lexical = self._lexical.ranking(query)
        rankings = [lexical]
        cosines: dict[str, float] = {}
        if self._vectors is not None:
            cosines = self._vectors.cosines(query)
            rankings.append(sorted(cosines.items(), key=lambda pair: (-pair[1], pair[0])))
        if situation:
            preferred = [(doc_id, s) for doc_id, s in lexical
                         if self._by_id[doc_id].source == "playbook" and self._by_id[doc_id].situation == situation]
            if preferred:
                rankings.append(preferred)
        fused = fuse(rankings, k=self.settings.fusion_k) if self._vectors is not None or len(rankings) > 1 else lexical
        day = order_date or on
        top = self._with_versions_in_force([doc_id for doc_id, _ in fused], day, k)
        scores = dict(fused)
        hits = tuple(self._hit(query, doc_id, scores.get(doc_id, 0.0), rank, cosines.get(doc_id), day)
                     for rank, doc_id in enumerate(top, 1))
        top_score = (hits[0].cosine if self._vectors is not None else hits[0].coverage) if hits else None
        reason = self._abstain(hits, top_score)
        changelog = {entry: self._by_id[entry] for hit in hits for entry in hit.chunk.changelog
                     if entry in self._by_id}
        return Result(query, hits, top_score, reason is not None, reason, changelog, self.mode)

    def _with_versions_in_force(self, ranked: Sequence[str], day: str | None, k: int) -> list[str]:
        """The top *k*, with the version in force placed just before any version that is not.

        A question worded on an old rule finds the old text first; the passage
        that holds on *day* must come with it, ahead of it, or the old number
        is the only one the model reads (CL-01). Nothing is dropped: the old
        passage stays, marked ``superseded`` (section 7.2).
        """
        top: list[str] = []
        for doc_id in ranked:
            if len(top) >= k:
                break
            if doc_id in top:
                continue
            current = self.counterpart(self._by_id[doc_id], day)
            if current is not None and current.chunk_id not in top:
                top.append(current.chunk_id)
            if len(top) < k:
                top.append(doc_id)
        return top

    def counterpart(self, chunk: Chunk, day: str | None) -> Chunk | None:
        """The version of *chunk* in force on *day*, when *chunk* is not: DT-01 for DT-OLD-01 after 01/10, and back.

        Versions pair by the changelog entry that windows them and the number
        of their section ("DT-OLD-03" and "DT-03").
        """
        if chunk.in_force(day) or not (chunk.valid_from or chunk.valid_to):
            return None
        number = chunk.chunk_id.rsplit("-", 1)[-1]
        for other in self.chunks:
            if (other is not chunk and other.chunk_id.rsplit("-", 1)[-1] == number
                    and set(other.changelog) & set(chunk.changelog)
                    and (other.valid_from or other.valid_to) and other.in_force(day)):
                return other
        return None

    def _hit(self, query: str, doc_id: str, score: float, rank: int, cosine: float | None, day: str | None) -> Hit:
        chunk = self._by_id[doc_id]
        instruction = None
        if chunk.restricted:
            tool = THROUGH_TOOLS.get(doc_id)
            instruction = (REDIRECT.format(id=doc_id, title=chunk.title, tool=tool) if tool
                           else REFUSE.format(id=doc_id, title=chunk.title))
        superseded = not chunk.in_force(day)
        validity = None
        if superseded and chunk.valid_to and day and day > chunk.valid_to:
            validity = EXPIRED.format(day=_label(date.fromisoformat(chunk.valid_to) + timedelta(days=1)))
        elif superseded and chunk.valid_from:
            validity = NOT_YET.format(day=_label(date.fromisoformat(chunk.valid_from)))
        return Hit(
            chunk=chunk,
            rank=rank,
            score=round(score, 6),
            cosine=round(cosine, 4) if cosine is not None else None,
            coverage=round(self._lexical.overlap(query, chunk.indexed), 4),
            superseded=superseded,
            absence=self.about_absence(query, chunk),
            instruction=instruction,
            validity=validity,
            redirect=THROUGH_TOOLS.get(doc_id) if chunk.restricted else None,
        )

    def about_absence(self, query: str, chunk: Chunk) -> bool:
        """Whether the sentence of *chunk* that *query* is most about says "no information" or bans the answer.

        A tie goes to the answering sentence: abstaining on an answerable
        question costs a sale, so the absence must be the clearer match.
        """
        overlap, is_absence = self._closest_sentence(query, chunk)
        return overlap > 0 and is_absence

    def _closest_sentence(self, query: str, chunk: Chunk) -> tuple[float, bool]:
        """The overlap of *query* with the sentence of *chunk* it is most about, and whether that one is an absence."""
        best_overlap, best_is_absence = 0.0, False
        for sentence in SENTENCE.split(chunk.text):
            if not sentence.strip():
                continue
            overlap = self._lexical.overlap(query, sentence)
            is_absence = bool(ABSENCE.search(plain(sentence)))
            if overlap > best_overlap or (overlap == best_overlap and best_is_absence and not is_absence):
                best_overlap, best_is_absence = overlap, is_absence
        return best_overlap, best_is_absence

    def _abstain(self, hits: Sequence[Hit], top_score: float | None) -> Reason | None:
        if not hits:
            return "no_match"
        if hits[0].chunk.restricted and hits[0].chunk.chunk_id not in THROUGH_TOOLS:
            return "restricted"
        open_hits = [hit for hit in hits if not hit.chunk.restricted]
        if open_hits and open_hits[0].absence:
            return "absence"
        threshold = self.settings.abstain_cosine if self._vectors is not None else self.settings.abstain_coverage
        if top_score is None or top_score < threshold:
            return "no_match"
        return None

    def sentence_for(self, query: str, chunk: Chunk) -> str:
        """The sentence of *chunk* that best answers *query*: an extractive answer for review."""
        sentences = [s.strip() for s in SENTENCE.split(chunk.text) if s.strip()]
        return max(sentences, key=lambda s: self._lexical.overlap(query, s), default="")


def _label(day: date) -> str:
    return day.strftime("%d/%m/%Y")
