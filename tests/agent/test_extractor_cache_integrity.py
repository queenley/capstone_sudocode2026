"""Cached labels must pass the same schema as fresh labels; concurrent saves cannot abort a run."""
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_agent_service.components.evaluation import scorers


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [
    {"items": [{"source_field": "agent_text", "quote": "Synthetic reply"}]},
    {"items": "invalid"},
    {"items": [], "recovered_errors": "invalid"},
    1,
])
async def test_invalid_cached_items_are_a_miss_instead_of_successful_empty_labels(tmp_path, entry):
    labeller = SimpleNamespace(ainvoke=AsyncMock(return_value=scorers.Items(items=[])))
    llm = SimpleNamespace(with_structured_output=lambda *args, **kwargs: labeller)
    path = tmp_path / "extractor.json"
    extractor = scorers.Extractor(llm, model_name="synthetic", cache_path=path)
    data = scorers.turn_input("Synthetic reply")
    key = hashlib.sha256(json.dumps([extractor.prompt_sha, extractor.model_name, data],
                                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    path.write_text(json.dumps({key: entry}), encoding="utf-8")
    extractor = scorers.Extractor(llm, model_name="synthetic", cache_path=path)

    result = await extractor.label(data)

    labeller.ainvoke.assert_awaited_once()
    assert "error" not in result and extractor.hits == 0
    assert json.loads(path.read_text(encoding="utf-8"))[key] == {"items": []}
    await extractor.label(data)
    labeller.ainvoke.assert_awaited_once()
    assert extractor.hits == 1


def test_concurrent_cache_saves_use_separate_temporary_files(tmp_path, monkeypatch):
    path = tmp_path / "extractor.json"
    writers = [scorers.Extractor.__new__(scorers.Extractor) for _ in range(2)]
    for index, writer in enumerate(writers):
        writer._cache_path = path
        writer._cache = {str(index): {"items": []}}
    replace, barrier = scorers.os.replace, threading.Barrier(2)

    def synchronized_replace(source, destination):
        barrier.wait(timeout=5)
        replace(source, destination)

    monkeypatch.setattr(scorers.os, "replace", synchronized_replace)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda writer: writer._save(), writers))

    assert json.loads(path.read_text(encoding="utf-8")) in [writer._cache for writer in writers]
    assert list(tmp_path.iterdir()) == [path]
