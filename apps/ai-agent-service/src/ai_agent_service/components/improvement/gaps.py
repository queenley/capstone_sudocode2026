"""Knowledge gaps collected from real turns; publication requires a staff review.

Regression suggestions stay outside evaluation datasets and are never approved labels.
"""
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Sequence

from ..intake import pii
from . import signals, versions, review
from .gap import gate
from .storage import atomic_text, locked
from ...config.config_manager import btc_data_dir
from ..knowledge.corpus import policy_chunks


#: Who approved an entry in an evaluation run, where no person does.
SCRIPTED = "scripted-eval"


def _path() -> Path:
    return signals.home() / "knowledge-gaps.json"


def _read() -> dict:
    path = _path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def record(question: str, *, call_id: str, turn_id: str, recent: Sequence[str] = ()) -> str | None:
    """A question the agent could not answer, as it was said; :func:`restate_open` makes it findable later."""
    question = pii.tokenise(question.strip(), pii.Vault())
    if len(question) < 3:
        return None
    key = hashlib.sha256(" ".join(question.casefold().split()).encode()).hexdigest()[:16]
    with locked(signals.home()):
        forgotten = signals.home() / "forgotten-calls.json"
        if forgotten.exists() and str(call_id) in json.loads(forgotten.read_text()):
            return None
        rows = _read()
        gap = rows.setdefault(key, {"id": key, "question": question, "status": "open", "occurrences": [],
                                    "created_at": datetime.now(timezone.utc).isoformat()})
        if recent and not gap.get("recent"):
            gap["recent"] = [pii.tokenise(line, pii.Vault()) for line in recent]
        occurrence = {"call_id": str(call_id), "turn_id": str(turn_id)}
        if occurrence not in gap["occurrences"]:
            gap["occurrences"].append(occurrence)
        atomic_text(_path(), json.dumps(rows, ensure_ascii=False, indent=2))
    return key


#: A transfer the advisor made because the documents do not answer (rule 4 of its prompt, PB-05).
OUT_OF_DOCUMENTS = "ngoai_pham_vi_tai_lieu"


def record_from_run(rows: Sequence[Mapping[str, Any]], diagnostics: Sequence[Mapping[str, Any]] = ()) -> int:
    """The questions a finished run could not answer, recorded as a live call records them.

    A run of the evaluation does not go through the live call's store, so its gaps are read from the trace: a turn
    in which the advisor transferred the call because the documents do not answer, or one whose retrieval abstained
    (no passage, or the passage says there is no information, the harness's own rule) and in which the assistant
    told the customer it has no information, as the organisers' grader reads that (its ``ABSTAIN_KW``). Retrieval
    abstaining alone is not a gap: it also abstains on "Dạ chị hiểu rồi, cảm ơn em", and ten such lines were
    recorded as open questions on 2026-11-12. The earlier turns of the call go with it, for :func:`restate_open` to
    resolve "máy này".
    """
    grader = signals.grader()
    abstained = {(str(d["scenario_id"]), str(d["call"]), int(d["turn"])) for d in diagnostics
                 if d.get("config") in (None, "full") and d.get("turn") is not None
                 and ((d.get("knowledge") or {}).get("abstain") in ("no_match", "absence"))}
    by_call: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        by_call.setdefault((str(row["scenario_id"]), str(row["call"])), []).append(row)
    recorded = 0
    for (scenario, call), turns in by_call.items():
        turns = sorted(turns, key=lambda r: int(r.get("turn") or 0))
        for index, row in enumerate(turns):
            transferred = any(tool.get("name") == "handoff.transfer"
                              and (((tool.get("args") or {}).get("brief") or {}).get("escalation_reason") == OUT_OF_DOCUMENTS)
                              for tool in row.get("tool_calls") or [])
            if not str(row.get("customer_text") or "").strip():
                continue
            told = any(grader.said(grader._say_norm(str(row.get("agent_text") or "")), phrase) for phrase in grader.ABSTAIN_KW)
            if not transferred and not ((scenario, call, int(row.get("turn") or 0)) in abstained and told):
                continue
            recent = [str(t.get(key) or "") for t in turns[max(0, index - 2):index] for key in ("customer_text", "agent_text")]
            if record(str(row.get("customer_text") or ""), call_id=f"{scenario}/{call}", turn_id=str(row.get("turn")),
                      recent=recent):
                recorded += 1
    return recorded


async def restate_open(restate: Callable[[str, Sequence[str]], Awaitable[Any]]) -> int:
    """Write each open question as a standalone one, with other ways to ask it. The answer is never touched."""
    done = 0
    pending = [dict(gap) for gap in _read().values() if gap["status"] == "open" and not gap.get("restated")]
    for gap in pending:
        answer = await restate(gap["question"], gap.get("recent") or ())
        if answer is None or not answer.question.strip():
            continue
        with locked(signals.home()):
            rows = _read()
            if gap["id"] in rows:
                rows[gap["id"]].update(restated=pii.tokenise(answer.question.strip(), pii.Vault()),
                                       variants=[pii.tokenise(v.strip(), pii.Vault()) for v in answer.variants if v.strip()])
                atomic_text(_path(), json.dumps(rows, ensure_ascii=False, indent=2))
                done += 1
    return done


#: Two questions whose cosine passes this are put to the QaAgent; the embedding only finds candidates, it never decides.
SAME_CANDIDATE = 0.75
#: Asks whether two standalone questions ask the same thing (``QaAgent.same_question``); None when it cannot tell.
Same = Callable[[str, str], Awaitable[bool | None]]


async def merge_same(embed: Callable[[Sequence[str]], Any], same: Same, *, threshold: float = SAME_CANDIDATE) -> int:
    """Questions that mean the same become one gap, its occurrences together: the count is what a reviewer reads.

    The embedding finds the candidates; a model reads both questions and decides. Nearness of words is not sameness of
    meaning: "giao mấy lần không gặp" and "khách đổi ý không nhận hàng" are both about delivery and ask different things.
    """
    open_gaps = [gap for gap in _read().values() if gap["status"] == "open" and gap.get("restated")]
    if len(open_gaps) < 2:
        return 0
    vectors = embed([gap["restated"] for gap in open_gaps])
    into: dict[str, str] = {}
    kept: list[int] = []
    for index, gap in enumerate(open_gaps):
        candidates = sorted((k for k in kept if float(vectors[index] @ vectors[k]) >= threshold),
                            key=lambda k: -float(vectors[index] @ vectors[k]))
        target = None
        for k in candidates:
            if await same(gap["restated"], open_gaps[k]["restated"]):
                target = k
                break
        if target is None:
            kept.append(index)
        else:
            into[gap["id"]] = open_gaps[target]["id"]
    if not into:
        return 0
    with locked(signals.home()):
        rows = _read()
        for source, target in into.items():
            if source in rows and target in rows:
                rows[target]["occurrences"] += [o for o in rows[source]["occurrences"] if o not in rows[target]["occurrences"]]
                del rows[source]
        atomic_text(_path(), json.dumps(rows, ensure_ascii=False, indent=2))
    return len(into)


async def answer_from_script(script: Sequence[Mapping[str, Any]], embed: Callable[[Sequence[str]], Any], fits: Same, *,
                             threshold: float = SAME_CANDIDATE,
                             questions_of: Callable[[str, str], Awaitable[Sequence[str]]] | None = None) -> list[dict]:
    """In an evaluation there is no consultant: each scripted answer goes to the open gap it answers.

    The embedding ranks the open gaps by the scripted question; the model reads the gap's question and the answer and
    says whether the answer answers it (``fits(question, answer)``). A gap answered earlier in the same
    script is no longer open, so one answer never lands twice. Each still passes the entry's gate and carries its
    sources. ``SCRIPTED`` as reviewer says in the record and the log that no person approved it, and a report must
    say so too.
    """
    results: list[dict] = []
    for item in script:
        open_gaps = [gap for gap in list_gaps() if gap["status"] == "open" and gap.get("restated")]
        if not open_gaps:
            results.append({"question": item["question"], "status": "no_gap"})
            continue
        scores = embed([gap["restated"] for gap in open_gaps]) @ embed([str(item["question"])])[0]
        ranked = [int(i) for i in scores.argsort()[::-1] if float(scores[int(i)]) >= threshold]
        gap_row = None
        for index in ranked[:3]:
            if await fits(open_gaps[index]["restated"], str(item["answer"])):
                gap_row = open_gaps[index]
                break
        if gap_row is None:
            results.append({"question": item["question"], "status": "no_gap"})
            continue
        flags = gate(gap_row["restated"], str(item["answer"]))
        if flags:
            results.append({"question": item["question"], "status": "refused", "flags": list(flags)})
            continue
        asked = await questions_of(gap_row["restated"], str(item["answer"])) if questions_of else ()
        version = resolve(gap_row["id"], answer=str(item["answer"]), cites=list(item.get("cites") or []), reviewer=SCRIPTED,
                          source=str(item.get("source") or "documents"), questions=list(asked))
        results.append({"question": item["question"], "status": "published", "gap": gap_row["id"], "version": version})
    return results


def list_gaps() -> list[dict]:
    """Open questions first, the most asked at the top."""
    return sorted(_read().values(), key=lambda row: (row["status"] != "open", -len(row["occurrences"]), row["id"]))


#: Where an entry's knowledge comes from: the organisers' documents it cites, or the consultant who answered the
#: question the documents do not cover (the brief, C.5: "bổ sung vào tài liệu"), recorded with who approved it.
SOURCES = ("documents", "consultant")


def resolve(key: str, *, answer: str, cites: list[str], reviewer: str, source: str = "documents",
            directory: Path | None = None, config_path: Path | None = None, questions: Sequence[str] = ()) -> int:
    """Publish a reviewed answer to gap *key* as a knowledge entry.

    ``source="documents"``: every cited section must be public and in force. ``source="consultant"``: new knowledge
    from the person who answered; citations are optional and, when given, still checked. Either way the gate holds:
    no amount, promotion code or stock status, and no topic that must go to a person.
    """
    if source not in SOURCES:
        raise ValueError(f"Unknown source {source!r}; one of {', '.join(SOURCES)}")
    if not re.fullmatch(r"[a-f0-9]{16}", key) or not answer.strip() or (source == "documents" and not cites):
        raise ValueError("A gap, an answer and supporting sources are required")
    if not reviewer.strip() or reviewer.casefold() in review.AGENTS:
        raise ValueError("A human reviewer is required")
    if pii.tokenise(answer, pii.Vault()) != answer:
        raise ValueError("FAQ answers must contain no raw personal data")
    with locked(signals.home()):
        rows = _read()
        if key not in rows:
            raise KeyError(key)
        gap = rows[key]
        if gap["status"] == "resolved":
            return gap["knowledge_version"]
        if gap["status"] == "faq":
            raise ValueError("This gap already became an FAQ")
        refused = gate(gap["question"], answer)
        if refused:
            raise ValueError(" ".join(refused))
        title = " | ".join(x for x in (gap.get("restated"), *(gap.get("variants") or [])) if x) or gap["question"]
        entry = {"chunk_id": "FAQ-GAP-" + key.upper(), "source": "faq", "title": title,
                 "text": answer.strip(), "approved_by": reviewer,
                 "provenance": {"gap_id": key, "cites": cites, "source": source}}
        # Other ways a customer asks it (knowledge/expand.entry_questions): indexed, never read out, no personal data.
        asked = [q.strip() for q in questions if q.strip() and pii.tokenise(q, pii.Vault()) == q]
        if asked:
            entry["questions"] = asked
        options = {"directory": directory} if directory else {}
        if config_path is not None:
            options["config_path"] = config_path
        # A retry after a crash between publishing and updating this record must not duplicate the entry.
        current = versions.active(config_path) if config_path is not None else versions.active()
        allowed = {chunk.chunk_id for chunk in policy_chunks(btc_data_dir() / "policy") if not chunk.restricted and not chunk.valid_to}
        allowed.update(row["chunk_id"] for row in versions.entries(current, directory))
        if not set(cites).issubset(allowed):
            raise ValueError("Citations must refer to published, public knowledge")
        existing = next((row for row in versions.entries(current, directory) if row["chunk_id"] == entry["chunk_id"]), None)
        if existing and existing != entry:
            raise ValueError("This gap was already published with different content")
        version = current if existing else versions.publish([entry], reviewer=reviewer, note="Reviewed knowledge gap", **options)
        gap.update(status="resolved", knowledge_version=version, reviewed_by=reviewer)
        atomic_text(_path(), json.dumps(rows, ensure_ascii=False, indent=2))
        atomic_text(signals.home() / "regression-proposals" / f"{key}.json", json.dumps({
            "gap_id": key, "question": gap["question"], "expected_answer": answer,
            "cites": cites, "knowledge_version": version, "status": "pending_human_review",
        }, ensure_ascii=False, indent=2))
    return version


def open_question(key: str) -> str:
    """The words of a gap still open; raises ``KeyError``, or ``ValueError`` when it was already dealt with."""
    gap = _read().get(key)
    if gap is None:
        raise KeyError(key)
    if gap["status"] != "open":
        raise ValueError("This gap was already dealt with")
    return gap["question"]


def became_faq(key: str, *, faq_id: str, reviewer: str) -> None:
    """Record that an admin's FAQ entry now answers this gap; approving it is the FAQ's own step."""
    with locked(signals.home()):
        rows = _read()
        if key not in rows:
            raise KeyError(key)
        rows[key].update(status="faq", faq_id=faq_id, reviewed_by=reviewer)
        atomic_text(_path(), json.dumps(rows, ensure_ascii=False, indent=2))
    review.log("gap_to_faq", gap_id=key, chunk_id=faq_id, reviewer=reviewer)


def dismiss(key: str, *, reason: str, reviewer: str) -> None:
    """Close a question that needs no answer, with why; a published one stays published."""
    if not reviewer.strip() or reviewer.casefold() in review.AGENTS:
        raise ValueError("A human reviewer is required")
    if not reason.strip():
        raise ValueError("A reason is required")
    with locked(signals.home()):
        rows = _read()
        if key not in rows:
            raise KeyError(key)
        gap = rows[key]
        if gap["status"] in ("resolved", "faq"):
            raise ValueError("This gap was already published; revoke its entry instead")
        gap.update(status="dismissed", reviewed_by=reviewer, reason=pii.tokenise(reason.strip(), pii.Vault()))
        atomic_text(_path(), json.dumps(rows, ensure_ascii=False, indent=2))
    review.log("gap_dismiss", gap_id=key, reviewer=reviewer)


def forget_calls(call_ids: list[int]) -> None:
    ids = {str(value) for value in call_ids}
    with locked(signals.home()):
        forgotten = signals.home() / "forgotten-calls.json"
        previous = set(json.loads(forgotten.read_text())) if forgotten.exists() else set()
        atomic_text(forgotten, json.dumps(sorted(previous | ids)))
        if signals.store().exists():
            kept = [row for row in signals.read() if str(row.get("call_id")) not in ids]
            atomic_text(signals.store(), ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in kept))
        rows = _read()
        for key, gap in list(rows.items()):
            gap["occurrences"] = [item for item in gap["occurrences"] if item["call_id"] not in ids]
            if not gap["occurrences"]:
                del rows[key]
                (signals.home() / "regression-proposals" / f"{key}.json").unlink(missing_ok=True)
        atomic_text(_path(), json.dumps(rows, ensure_ascii=False, indent=2))
