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
from . import gap as gate, signals, versions, review
from .storage import atomic_text, locked
from ...config.config_manager import btc_data_dir
from ..knowledge.corpus import policy_chunks


#: Who approved an entry in an evaluation run, where no person does.
SCRIPTED = "scripted-eval"
#: Cosine of two questions that ask the same; of a scripted question and the gap it answers.
SAME_QUESTION = 0.88
SCRIPT_MATCH = 0.80


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


def merge_same(embed: Callable[[Sequence[str]], Any], *, threshold: float = SAME_QUESTION) -> int:
    """Questions that mean the same become one gap, its occurrences together: the count is what a reviewer reads."""
    with locked(signals.home()):
        rows = _read()
        open_gaps = [gap for gap in rows.values() if gap["status"] == "open" and gap.get("restated")]
        if len(open_gaps) < 2:
            return 0
        vectors = embed([gap["restated"] for gap in open_gaps])
        merged = 0
        kept: list[int] = []
        for index, gap in enumerate(open_gaps):
            same = next((k for k in kept if float(vectors[index] @ vectors[k]) >= threshold), None)
            if same is None:
                kept.append(index)
                continue
            target = open_gaps[same]
            target["occurrences"] += [o for o in gap["occurrences"] if o not in target["occurrences"]]
            del rows[gap["id"]]
            merged += 1
        if merged:
            atomic_text(_path(), json.dumps(rows, ensure_ascii=False, indent=2))
    return merged


def answer_from_script(script: Sequence[Mapping[str, Any]], embed: Callable[[Sequence[str]], Any], *,
                       threshold: float = SCRIPT_MATCH) -> list[dict]:
    """In an evaluation there is no consultant: each scripted answer goes to the open gap it best matches.

    Each still passes the entry's gate and carries its sources. ``SCRIPTED`` as reviewer says in the record and the
    log that no person approved it, and a report must say so too.
    """
    open_gaps = [gap for gap in list_gaps() if gap["status"] == "open" and gap.get("restated")]
    results: list[dict] = []
    if not open_gaps or not script:
        return results
    vectors = embed([gap["restated"] for gap in open_gaps])
    for item in script:
        scores = vectors @ embed([str(item["question"])])[0]
        best = int(scores.argmax())
        gap_row = open_gaps[best]
        if float(scores[best]) < threshold:
            results.append({"question": item["question"], "status": "no_gap"})
            continue
        flags = gate.gate(gap_row["restated"], str(item["answer"]))
        if flags:
            results.append({"question": item["question"], "status": "refused", "flags": list(flags)})
            continue
        version = resolve(gap_row["id"], answer=str(item["answer"]), cites=list(item.get("cites") or []), reviewer=SCRIPTED)
        results.append({"question": item["question"], "status": "published", "gap": gap_row["id"], "version": version})
    return results


def list_gaps() -> list[dict]:
    return sorted(_read().values(), key=lambda row: (-len(row["occurrences"]), row["id"]))


def resolve(key: str, *, answer: str, cites: list[str], reviewer: str,
            directory: Path | None = None, config_path: Path | None = None) -> int:
    if not re.fullmatch(r"[a-f0-9]{16}", key) or not answer.strip() or not cites:
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
        title = " | ".join(x for x in (gap.get("restated"), *(gap.get("variants") or [])) if x) or gap["question"]
        entry = {"chunk_id": "FAQ-GAP-" + key.upper(), "source": "faq", "title": title,
                 "text": answer.strip(), "approved_by": reviewer,
                 "provenance": {"gap_id": key, "cites": cites}}
        options = {"directory": directory} if directory else {}
        if config_path is not None:
            options["config_path"] = config_path
        # A retry after a crash between publishing and updating this record must not duplicate the entry.
        current = versions.active(config_path) if config_path is not None else versions.active()
        allowed = {chunk.chunk_id for chunk in policy_chunks(btc_data_dir() / "policy") if not chunk.restricted}
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
