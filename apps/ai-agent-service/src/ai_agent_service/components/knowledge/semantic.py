"""Meaning-based retrieval: a local multilingual embedding model. ``docs/design.md`` section 7.3.

Keyword search misses a question that shares no words with its answer
("giao về Cần Thơ mất mấy ngày" against a table of delivery zones); an
embedding of the question and of each passage finds it by meaning. The model
runs on this machine (Appendix C: embedding is local), as ONNX on CPU, with
the tokenizer and runtime the project already installs (``tokenizers``,
``onnxruntime``): no PyTorch, no new dependency.

The weights are not in the repository. The knowledge server fetches the
configured model into ``models/embedding/`` (git-ignored, like the voice
models) when it starts without it, as the API does for voice, so a new
machine and a new deployment run the same retrieval;
``python -m ai_agent_service.components.knowledge.semantic`` does it by hand. Without the
files and without a network, :func:`load` returns None and retrieval is
keyword-only, still correct, just blind to paraphrase, and the run's
manifest says so.

Passage vectors are cached on disk by the hash of their text, so a process
that starts again embeds only what changed.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Literal, Protocol, Sequence

import numpy as np

logger = logging.getLogger(__name__)

Kind = Literal["query", "passage"]


class Embedder(Protocol):
    """Turns texts into unit vectors; the cosine of two is their dot product."""

    name: str

    def embed(self, texts: Sequence[str], *, kind: Kind) -> np.ndarray: ...


class OnnxEmbedder:
    """An E5-style sentence encoder exported to ONNX, mean-pooled and normalised.

    E5 models expect every input prefixed with what it is, ``query: `` or
    ``passage: ``; leaving the prefixes out measurably lowers recall, so they
    belong to the model rather than to the caller.
    """

    PREFIX: dict[Kind, str] = {"query": "query: ", "passage": "passage: "}

    def __init__(self, directory: Path, *, model_file: str, max_tokens: int = 512, threads: int = 2) -> None:
        import onnxruntime
        from tokenizers import Tokenizer

        self.name = f"{directory.name}/{model_file}"
        self._tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=max_tokens)
        pad = self._tokenizer.token_to_id("<pad>")
        self._tokenizer.enable_padding(pad_id=pad if pad is not None else 1, pad_token="<pad>")
        options = onnxruntime.SessionOptions()
        # Few threads: the knowledge server shares a small machine with the API and the voice models.
        options.intra_op_num_threads = threads
        self._session = onnxruntime.InferenceSession(
            str(directory / model_file), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}
        # onnxruntime sessions may be shared across threads; the tokenizer's padding state is not.
        self._lock = threading.Lock()

    def embed(self, texts: Sequence[str], *, kind: Kind, batch: int = 8) -> np.ndarray:
        rows = [self._batch([self.PREFIX[kind] + t for t in texts[i:i + batch]]) for i in range(0, len(texts), batch)]
        return np.vstack(rows) if rows else np.zeros((0, 0), dtype=np.float32)

    def _batch(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            encoded = self._tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feed)[0]
        weights = mask[..., None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        return (pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)).astype(np.float32)


class Vectors:
    """Passage vectors by id, and the cosine of a query against each."""

    def __init__(self, embedder: Embedder, passages: Sequence[tuple[str, str]], *, cache: Path | None = None) -> None:
        self.embedder = embedder
        self._ids = [doc_id for doc_id, _ in passages]
        stored = _read_cache(cache)
        digests = [_digest(embedder.name, text) for _, text in passages]
        missing = [i for i, d in enumerate(digests) if d not in stored]
        if missing:
            fresh = embedder.embed([passages[i][1] for i in missing], kind="passage")
            for row, index in zip(fresh, missing):
                stored[digests[index]] = row
            _write_cache(cache, stored)
        self._matrix = np.vstack([stored[d] for d in digests]) if digests else np.zeros((0, 1), dtype=np.float32)

    def cosines(self, query: str) -> dict[str, float]:
        if not self._ids:
            return {}
        vector = self.embedder.embed([query], kind="query")[0]
        return {doc_id: float(score) for doc_id, score in zip(self._ids, self._matrix @ vector)}


def _digest(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


def _read_cache(path: Path | None) -> dict[str, np.ndarray]:
    if path is None or not path.exists():
        return {}
    try:
        with np.load(path) as stored:
            return {key: stored[key] for key in stored.files}
    except (OSError, ValueError) as error:
        logger.warning("Embedding cache %s unreadable (%s); recomputing", path, type(error).__name__)
        return {}


def _write_cache(path: Path | None, vectors: dict[str, np.ndarray]) -> None:
    """Write whole, then swap in: several knowledge servers may start at once."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.{os.getpid()}.tmp.npz")
    np.savez(temporary, **vectors)
    os.replace(temporary, path)


def load(directory: Path, *, model_file: str, threads: int = 2) -> OnnxEmbedder | None:
    """The configured model, or None (with one log line) when its files are not on this machine."""
    if not (directory / model_file).exists() or not (directory / "tokenizer.json").exists():
        logger.info("No embedding model at %s; knowledge retrieval is keyword-only", directory)
        return None
    try:
        return OnnxEmbedder(directory, model_file=model_file, threads=threads)
    except ImportError as error:
        logger.warning("Embedding packages missing (%s); knowledge retrieval is keyword-only", error.name)
        return None


def fetch(repo: str, directory: Path, *, model_file: str) -> None:
    """Download the model's ONNX file and tokenizer from the Hugging Face Hub; files present are kept."""
    from huggingface_hub import hf_hub_download

    for name in (model_file, "tokenizer.json", "config.json"):
        if not (directory / name).exists():
            hf_hub_download(repo, name, local_dir=str(directory))


def ensure(repo: str, directory: Path, *, model_file: str, threads: int = 2) -> OnnxEmbedder | None:
    """The configured model, fetched first when this machine lacks it; None when it cannot be had."""
    if not (directory / model_file).exists() or not (directory / "tokenizer.json").exists():
        try:
            logger.info("Fetching embedding model %s into %s", repo, directory)
            fetch(repo, directory, model_file=model_file)
        except Exception as error:  # noqa: BLE001 - offline: keyword retrieval still answers
            logger.warning("Could not fetch embedding model %s (%s); knowledge retrieval is keyword-only",
                           repo, type(error).__name__)
    return load(directory, model_file=model_file, threads=threads)


if __name__ == "__main__":
    from ...config.config_manager import embedding_dir, get_knowledge_config

    parser = argparse.ArgumentParser(description="Download the knowledge base's embedding model.")
    parser.parse_args()
    settings = get_knowledge_config().embedding
    if settings is None:
        raise SystemExit("config/knowledge.yaml names no embedding model")
    target = embedding_dir() / settings.name
    fetch(settings.repo, target, model_file=settings.model_file)
    print(f"{settings.repo} -> {target}")
