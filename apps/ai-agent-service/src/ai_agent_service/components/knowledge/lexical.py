"""Keyword retrieval: Okapi BM25 over syllables and syllable pairs. ``docs/design.md`` section 7.3.

Vietnamese words are written as syllables separated by spaces, and the unit
that carries meaning is often two of them ("đổi trả", "bảo hành"), so a pair
of neighbouring syllables is a term as well as each syllable.

Every syllable is indexed twice. Without diacritics, because customers type
without them ("doi tra") and ASR sometimes gets a tone wrong. And, when it
has them, as written, because folding merges words that mean different
things: "giá sàn" (the price floor) and "giá sản phẩm" both fold to
``gia san``. A query with its diacritics matches the exact form strongly and
the folded one as well; a query without them still matches the folded one.

Besides the ranking, :meth:`Lexical.overlap` says how much of a query a text
holds, on a 0-to-1 scale that means the same for every query: the share of
the query's information (summed IDF) found in it. A raw BM25 score cannot
carry a threshold, because it grows with the length of the question.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Iterable, Sequence

from ..intake.text import plain

FOLDED = re.compile(r"[a-z0-9]+")
WORD = re.compile(r"[^\W_]+")


def syllables(text: str) -> list[str]:
    """Lower-case syllables without diacritics: "Đổi size" -> ["doi", "size"]."""
    return FOLDED.findall(plain(text))


def terms(text: str, *, accents: bool = True) -> list[str]:
    """The unit index and query share: folded syllables and pairs, and the
    syllables and pairs that carry diacritics as written (prefixed ``~``)."""
    folded = syllables(text)
    found = folded + [f"{a}_{b}" for a, b in zip(folded, folded[1:])]
    if not accents:
        return found
    written = WORD.findall(unicodedata.normalize("NFC", text.lower()))
    found += [f"~{w}" for w in written if not w.isascii()]
    found += [f"~{a}_{b}" for a, b in zip(written, written[1:]) if not (a.isascii() and b.isascii())]
    return found


class Lexical:
    """A BM25 index over fixed documents, its statistics computed once."""

    def __init__(
        self, documents: Iterable[tuple[str, str]], *, k1: float = 1.2, b: float = 0.75, accents: bool = True,
    ) -> None:
        self._accents = accents
        self._ids: list[str] = []
        self._counts: list[Counter[str]] = []
        for doc_id, text in documents:
            self._ids.append(doc_id)
            self._counts.append(Counter(terms(text, accents=accents)))
        self._k1, self._b = k1, b
        self._lengths = [sum(c.values()) for c in self._counts]
        self._average = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        frequency: Counter[str] = Counter()
        for counts in self._counts:
            frequency.update(counts.keys())
        n = len(self._counts)
        self._idf = {term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in frequency.items()}
        #: A term no document has: as informative as a term can be.
        self._unseen = math.log(1 + (n + 0.5) / 0.5) if n else 0.0

    def __len__(self) -> int:
        return len(self._ids)

    def query_terms(self, query: str) -> set[str]:
        return set(terms(query, accents=self._accents))

    def scores(self, query: str) -> dict[str, float]:
        """BM25 of every document with a positive score."""
        wanted = self.query_terms(query)
        scored: dict[str, float] = {}
        for doc_id, counts, length in zip(self._ids, self._counts, self._lengths):
            norm = self._k1 * (1 - self._b + self._b * length / self._average)
            score = sum(
                self._idf[term] * counts[term] * (self._k1 + 1) / (counts[term] + norm)
                for term in wanted if term in counts
            )
            if score > 0:
                scored[doc_id] = score
        return scored

    def ranking(self, query: str) -> list[tuple[str, float]]:
        """Documents by BM25, best first; ties by id, so a ranking is reproducible."""
        return sorted(self.scores(query).items(), key=lambda pair: (-pair[1], pair[0]))

    def weight(self, term: str) -> float:
        """A term's IDF; a term no document has counts as the rarest."""
        return self._idf.get(term, self._unseen)

    def overlap(self, query: str, text: str) -> float:
        """The share of *query*'s information found in *text*, from 0 to 1.

        Weighted by this index's IDF whatever *text* is (a passage, or one
        sentence of it), so a common word counts for little everywhere.
        """
        wanted = self.query_terms(query)
        if not wanted:
            return 0.0
        present = set(terms(text, accents=self._accents))
        total = sum(self.weight(term) for term in wanted)
        return sum(self.weight(term) for term in wanted if term in present) / total if total else 0.0


def fuse(rankings: Sequence[Sequence[tuple[str, float]]], *, k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion (Cormack, Clarke and Büttcher, SIGIR 2009): each
    ranking adds ``1 / (k + rank)`` to a document, best first.

    Rank, not score, is what is combined, because a BM25 score and a cosine
    are on scales nothing relates; that is also why the fused score cannot
    carry the abstain threshold (``docs/design.md`` section 7.3).
    """
    fused: dict[str, float] = {}
    for ranking in rankings:
        for position, (doc_id, _) in enumerate(ranking, 1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + position)
    return sorted(fused.items(), key=lambda pair: (-pair[1], pair[0]))
