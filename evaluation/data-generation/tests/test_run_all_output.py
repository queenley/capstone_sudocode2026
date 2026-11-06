"""``run_all --output``: the flags that choose the folder do not reach the second run, which has it in its environment."""
from __future__ import annotations

import pytest

from src.pipeline.run_all import without_output_flags


@pytest.mark.parametrize("argv", [
    ["--output", "x", "--fresh", "--limit", "2"],
    ["--fresh", "--output=x", "--limit", "2"],
    ["--seed", "v5", "--fresh", "--output", "x", "--limit", "2"],
    ["--fresh", "--limit", "2", "--seed=v5"],
])
def test_folder_flags_are_dropped_and_the_rest_kept(argv):
    assert without_output_flags(argv) == ["--fresh", "--limit", "2"]
