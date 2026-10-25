"""Baseline retriever over the BTC policy corpus (``data/policy/``), dependency-free.

* Chunking follows BTC ``chunk_id_rule``: one chunk per ``## [XX-nn]`` section, id = ``XX-nn``
  (so retrieved ids map 1:1 to ``relevant_chunk_ids`` in ``rag/qa_labeled.json``).
* Scoring: BM25 over Vietnamese syllable unigrams + bigrams (diacritics kept), the
  document title is prepended to every chunk. Chunks of expired documents
  (``*HET-HIEU-LUC*``) are down-weighted so the current version wins version conflicts.
* Abstain policy (guardrail, BTC types ``restricted`` / ``unanswerable``):
  - the question asks for confidential data (import/floor price, supplier, margin, KPI) → refuse;
  - the top chunk is internal (``NOI-BO``) and the question is not about restock dates → refuse;
  - a top-2 chunk says the information is not available *about the asked topic* → "không có thông tin".
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

HEADER = re.compile(r"^##\s*\[([A-Z0-9-]+)\]\s*(.*)$", re.MULTILINE)
EXPIRED_MARK = "HET-HIEU-LUC"
INTERNAL_MARK = "NOI-BO"
EXPIRED_WEIGHT = 0.6
ABSENCE_PHRASES = ("không có thông tin", "chưa có thông tin")


@dataclass
class Chunk:
    chunk_id: str
    doc: str
    title: str
    text: str
    internal: bool
    expired: bool


def tokenize(text: str) -> list[str]:
    words = re.findall(r"\w+", unicodedata.normalize("NFC", text.lower()))
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


def load_chunks(policy_dir: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(policy_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        doc_title = text.splitlines()[0].lstrip("# ").strip() if text else path.stem
        matches = list(HEADER.finditer(text))
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[match.start():end].strip()
            chunks.append(Chunk(match.group(1), path.name, f"{doc_title} — {match.group(2)}", body,
                                INTERNAL_MARK in path.name.upper(), EXPIRED_MARK in path.name.upper()))
    return chunks


class BM25Retriever:
    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.docs = [Counter(tokenize(c.title + " " + c.text)) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lengths) / max(1, len(self.lengths))
        df = Counter(term for d in self.docs for term in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query: str) -> list[tuple[Chunk, float]]:
        terms = tokenize(query)
        scored = []
        for chunk, doc, length in zip(self.chunks, self.docs, self.lengths):
            s = 0.0
            for t in terms:
                tf = doc.get(t, 0)
                if tf:
                    s += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg))
            if chunk.expired:
                s *= EXPIRED_WEIGHT
            scored.append((chunk, s))
        return sorted(scored, key=lambda x: -x[1])

    def retrieve(self, query: str, k: int = 5) -> list[tuple[Chunk, float]]:
        return self.score(query)[:k]


# Questions asking for confidential data (NB-01/NB-03/NB-04, KM-06 floor price): always refuse.
RESTRICTED_INTENT = re.compile(r"giá nhập|nhập vào|nhập về bao nhiêu|giá sàn|nhà cung cấp|biên lợi nhuận|lợi nhuận|kpi|chiết khấu nội bộ",
                               re.IGNORECASE)
# Internal docs may be USED for restock dates (NB-02 says so) but never quoted otherwise.
RESTOCK_INTENT = re.compile(r"bao giờ có|khi nào có|hàng về|có hàng|nhập hàng về|hết hàng", re.IGNORECASE)


def _absence_about_query(query: str, chunk: Chunk) -> bool:
    """True when a 'không có thông tin' sentence of the chunk talks about what was asked."""
    terms = {t for t in tokenize(query) if "_" not in t and len(t) > 2}
    for sentence in re.split(r"(?<=[.!?\n])\s+", chunk.text.lower()):
        if any(p in sentence for p in ABSENCE_PHRASES) and len(terms & set(tokenize(sentence))) >= 2:
            return True
    return False


def should_abstain(top: list[tuple[Chunk, float]], query: str = "") -> tuple[bool, str]:
    if not top or top[0][1] <= 0:
        return True, "no_evidence"
    if RESTRICTED_INTENT.search(query):
        return True, "restricted_intent"
    best = top[0][0]
    if best.internal and not RESTOCK_INTENT.search(query):
        return True, "restricted_internal_document"
    if any(_absence_about_query(query, chunk) for chunk, _ in top[:2]):
        return True, "corpus_states_information_unavailable"
    return False, ""
