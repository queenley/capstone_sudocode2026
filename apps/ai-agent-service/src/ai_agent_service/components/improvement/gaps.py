"""Knowledge gaps collected from real turns; publication requires a staff review.

Regression suggestions stay outside evaluation datasets and are never approved labels.
"""
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone

from ..intake import pii
from . import signals, versions, review
from .storage import atomic_text, locked
from ...config.config_manager import btc_data_dir
from ..knowledge.corpus import policy_chunks


def _path() -> Path:
    return signals.home() / "knowledge-gaps.json"


def _read() -> dict:
    path = _path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def record(question: str, *, call_id: str, turn_id: str) -> str | None:
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
        occurrence = {"call_id": str(call_id), "turn_id": str(turn_id)}
        if occurrence not in gap["occurrences"]:
            gap["occurrences"].append(occurrence)
        atomic_text(_path(), json.dumps(rows, ensure_ascii=False, indent=2))
    return key


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
        entry = {"chunk_id": "FAQ-GAP-" + key.upper(), "source": "faq", "title": gap["question"],
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
