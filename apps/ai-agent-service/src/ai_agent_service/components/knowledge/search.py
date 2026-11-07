"""Searching the knowledge base: which passages a turn may read, and when to say "no information".

``docs/design.md`` sections 4.2 and 7.3. :class:`KnowledgeBase` answers one
question per customer turn, in a few milliseconds, with:

- the top passages, keyword (BM25) and meaning (embedding) rankings fused by
  Reciprocal Rank Fusion, each with its flags: ``restricted`` (its text is
  never handed out, only its code and what to do instead), and the changelog
  entries that explain them. A passage not in force on the day that matters
  (the call's day, or the order's day when the question is about an order,
  CL-01) is never among them: it is filtered out before the top is taken, so
  its old figures cannot reach the model and a passage in force gets its place;
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
from datetime import date
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
#: The day the customer says an order was placed, words without diacritics: "đơn tạo ngày 28/09/2026", "mua hôm 28/9",
#: "đặt tháng 9/2026". A delivery day in between is not it, nor is the date a request was made.
ORDER_DAY = re.compile(r"\b(?:don|dat|mua)\b(?P<between>[^.,;?!\n]{0,24}?)\b(?:(?P<day>\d{1,2})/|thang )"
                       r"(?P<month>\d{1,2})(?:/(?P<year>\d{4}))?\b")
NOT_PLACED = re.compile(r"\b(?:giao|nhan|ship|den)\b")


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
    #: The sentence the question is about says there is no information, or bans saying it.
    absence: bool
    #: For a restricted passage: what to do instead of reading it.
    instruction: str | None
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
    #: Passages that ranked but were not in force on the day that matters, for the trace; never their text.
    withheld: tuple[str, ...] = ()
    #: The changelog entries that explain the withheld passages: what changed, and which orders keep the old rule.
    explains: tuple[str, ...] = ()
    #: The other orders' days on which a passage of this result would not hold: which order is meant must be asked.
    version_differs: tuple[str, ...] = ()


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
        other_order_dates: Sequence[str] = (),
    ) -> Result:
        """The top *k* passages for *query* and whether to abstain.

        *on* is the call's day; *order_date*, when the question is about an
        order already placed, decides which version of a policy holds (CL-01:
        an order placed before 01/10 keeps the old returns policy). Without
        either day nothing is filtered. A playbook entry for *situation* is
        preferred over others (section 7.3). *other_order_dates* are this
        customer's other orders when the question names none: the answer may
        differ between them, and the result says so.
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
        ranked = [doc_id for doc_id, _ in fused]
        top = [doc_id for doc_id in ranked if self._by_id[doc_id].in_force(day)][:k]
        reached = ranked[:ranked.index(top[-1])] if top else ranked
        withheld = tuple(doc_id for doc_id in reached if not self._by_id[doc_id].in_force(day))
        scores = dict(fused)
        hits = tuple(self._hit(query, doc_id, scores.get(doc_id, 0.0), rank, cosines.get(doc_id))
                     for rank, doc_id in enumerate(top, 1))
        top_score = (hits[0].cosine if self._vectors is not None else hits[0].coverage) if hits else None
        reason = self._abstain(hits, top_score)
        cited = [*(hit.chunk for hit in hits), *(self._by_id[doc_id] for doc_id in withheld)]
        changelog = {entry: self._by_id[entry] for chunk in cited for entry in chunk.changelog if entry in self._by_id}
        explains = tuple(dict.fromkeys(entry for doc_id in withheld for entry in self._by_id[doc_id].changelog
                                       if entry in changelog))
        differs = tuple(other for other in other_order_dates if any(not hit.chunk.in_force(other) for hit in hits))
        return Result(query, hits, top_score, reason is not None, reason, changelog, self.mode, withheld, explains,
                      differs)

    def _hit(self, query: str, doc_id: str, score: float, rank: int, cosine: float | None) -> Hit:
        chunk = self._by_id[doc_id]
        instruction = None
        if chunk.restricted:
            tool = THROUGH_TOOLS.get(doc_id)
            instruction = (REDIRECT.format(id=doc_id, title=chunk.title, tool=tool) if tool
                           else REFUSE.format(id=doc_id, title=chunk.title))
        return Hit(
            chunk=chunk,
            rank=rank,
            score=round(score, 6),
            cosine=round(cosine, 4) if cosine is not None else None,
            coverage=round(self._lexical.overlap(query, chunk.indexed), 4),
            absence=self.about_absence(query, chunk),
            instruction=instruction,
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


def stated_order_day(said: str, on: str | None) -> str | None:
    """The day *said* says an order was placed, ``YYYY-MM-DD``; a month alone counts as its first day.

    Without a year it is the year of *on*. A day after *on* was not an order placed, whatever the words
    around it say: choosing the old policy on such a reading would be worse than choosing none.
    """
    for match in ORDER_DAY.finditer(plain(said)):
        if NOT_PLACED.search(match["between"]):
            continue
        year = match["year"] or (on or "")[:4]
        if not year:
            continue
        try:
            day = date(int(year), int(match["month"]), int(match["day"] or 1)).isoformat()
        except ValueError:
            continue
        if on is None or day <= on:
            return day
    return None
