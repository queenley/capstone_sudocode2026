"""The knowledge base. ``docs/design.md`` section 7.

- :mod:`.corpus`: the chunks: the organisers' policy sections and the team's
  approved Knowledge Gap Loop and playbook entries, each with its validity window, its
  restriction, its industry and the changelog entries that explain it;
- :mod:`.lexical`: BM25 over syllables and syllable pairs, with and without
  accents;
- :mod:`.semantic`: the local embedding model (ONNX on CPU) and the passage
  vectors, cached on disk;
- :mod:`.search`: hybrid retrieval by Reciprocal Rank Fusion, the version in
  force on the day that matters, and when to abstain.

:func:`build` puts them together as ``config/knowledge.yaml`` says. The
knowledge server builds its index with it, and so does the evaluation's
``rag`` command, so what is measured is what answers calls.
"""

from __future__ import annotations

from typing import Sequence

from ...config.config_manager import btc_data_dir, embedding_dir, get_knowledge_config, kb_dir
from . import corpus, semantic
from .search import KnowledgeBase, Settings


def build(entries: Sequence[corpus.Chunk] | None = None, *, embed: bool = True) -> KnowledgeBase:
    """The organisers' corpus plus *entries*, indexed.

    *entries* are the team's approved ones; None reads them from the
    configured version file (the server passes the rows of ``kb_chunks``
    instead, which also hold the demo entries). ``embed=False`` builds the
    keyword-only index, the fallback when no model can be loaded.
    """
    config = get_knowledge_config()
    team = list(entries) if entries is not None else corpus.load_version(kb_dir(), config.version)
    chunks = corpus.policy_chunks(btc_data_dir() / "policy") + team
    r = config.retrieval
    settings = Settings(top_k=r.top_k, fusion_k=r.fusion_k, k1=r.k1, b=r.b, accents=r.accents,
                        abstain_cosine=r.abstain_cosine, abstain_coverage=r.abstain_coverage)
    embedder, cache = None, None
    if embed and config.embedding is not None:
        directory = embedding_dir() / config.embedding.name
        embedder = semantic.ensure(config.embedding.repo, directory, model_file=config.embedding.model_file,
                                   threads=config.embedding.threads)
        cache = directory / "vectors.npz"
    return KnowledgeBase(chunks, settings=settings, embedder=embedder, cache=cache)
