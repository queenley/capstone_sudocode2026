"""The questions each policy section answers, written once, indexed with it. ``docs/design.md`` section 7.3.

Customers do not ask in the documents' words: "shipper tới mà nhà không có ai thì đơn có bị hủy không" is VC-07,
"Giao hàng thất bại", and neither BM25 nor the embedding found it in the five passages the advisor reads. So each
public section in force carries the questions a customer would ask of it, in their words, written by a model once
(document expansion by query prediction, doc2query: Nogueira et al., 2019). They join only the indexed text: what
the advisor reads of a section is still its own words, and the hot path asks no model.

``data/kb/questions.jsonl``, one line per section: its id, a digest of its title and text, and the questions. A
section whose words changed has a different digest and keeps no stale questions until they are written again::

    python -m ai_agent_service.components.knowledge.expand          # the missing and the stale ones
    python -m ai_agent_service.components.knowledge.expand --check  # count them, write nothing
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field

from ...config.config_manager import btc_data_dir, get_models_config, kb_dir, load_prompt
from . import corpus

logger = logging.getLogger(__name__)

#: The model that writes them: ``agents.knowledge`` in ``config/models.yaml``.
AGENT = "knowledge"


class Questions(BaseModel):
    questions: list[str] = Field(description="Six to eight questions a customer would ask that this section answers, "
                                             "in everyday spoken Vietnamese with diacritics, each different in words.")


def path() -> Path:
    return kb_dir() / "questions.jsonl"


def digest(chunk: corpus.Chunk) -> str:
    return hashlib.sha256(f"{chunk.title}\n{chunk.text}".encode("utf-8")).hexdigest()[:16]


#: Documents written for the staff, not answers a customer asks for: the playbook says how to speak (its PB-05 says
#: "chưa có thông tin", and questions written for it drew unrelated questions to that line), the staff rules are, in
#: the organisers' own title, "không dùng để tư vấn khách". Customers find them by their own words or not at all.
STAFF_DOCUMENTS = frozenset({"playbook-telesale.md", "noi-quy-nhan-vien.md"})


def wanted(chunk: corpus.Chunk) -> bool:
    """A public section in force that answers customers: an internal one must not be found more easily, a retired
    one is withheld anyway, a staff document is not what a customer asks for."""
    return (chunk.source == "policy" and not chunk.restricted and not chunk.valid_to
            and chunk.doc not in STAFF_DOCUMENTS)


def load(file: Path | None = None) -> dict[str, dict[str, Any]]:
    source = file or path()
    if not source.is_file():
        return {}
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["chunk_id"]: row for row in rows}


def attach(chunks: Sequence[corpus.Chunk], file: Path | None = None) -> list[corpus.Chunk]:
    """*chunks* with the questions written for their current words; a stale or missing line adds nothing."""
    written = load(file)
    out = []
    for chunk in chunks:
        row = written.get(chunk.chunk_id)
        if row and wanted(chunk) and row.get("digest") == digest(chunk):
            chunk = dataclasses.replace(chunk, questions=tuple(str(q) for q in row.get("questions") or ()))
        out.append(chunk)
    return out


async def write(chunks: Sequence[corpus.Chunk], llm: Any, file: Path | None = None) -> int:
    """Write the questions of every wanted chunk that has none for its current words; the others are kept."""
    target = file or path()
    written = load(target)
    instructions = load_prompt("knowledge_questions.md")
    todo = [c for c in chunks if wanted(c) and (written.get(c.chunk_id) or {}).get("digest") != digest(c)]
    for chunk in todo:
        request = f"{instructions}\n\nDOCUMENT: {chunk.doc_title}\nSECTION [{chunk.chunk_id}] {chunk.title}\n{chunk.text}"
        try:
            answer = await llm.with_structured_output(Questions).ainvoke(request)
        except Exception as error:  # noqa: BLE001 - a section without questions is still found by its own words
            logger.warning("No questions for %s: %s", chunk.chunk_id, type(error).__name__)
            continue
        questions = [q.strip() for q in answer.questions if q.strip()][:8]
        written[chunk.chunk_id] = {"chunk_id": chunk.chunk_id, "digest": digest(chunk), "questions": questions}
    kept = {c.chunk_id for c in chunks if wanted(c)}
    lines = [json.dumps(written[key], ensure_ascii=False) for key in sorted(written) if key in kept]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(todo)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="expand", description="Write the questions each policy section answers.")
    parser.add_argument("--check", action="store_true", help="Count the missing and stale sections, write nothing")
    args = parser.parse_args(argv)
    chunks = corpus.policy_chunks(btc_data_dir() / "policy")
    written = load()
    stale = [c.chunk_id for c in chunks if wanted(c) and (written.get(c.chunk_id) or {}).get("digest") != digest(c)]
    print(f"{sum(1 for c in chunks if wanted(c))} public sections in force; {len(stale)} without current questions")
    if args.check or not stale:
        return 1 if args.check and stale else 0
    from ...llm.factory import LLMFactory

    from ...llm import tracing

    llm = LLMFactory.create_llm(get_models_config().agent_llm_config(AGENT), agent_name=AGENT)
    print(f"Wrote questions for {asyncio.run(write(chunks, llm))} sections -> {path()}")
    tracing.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
