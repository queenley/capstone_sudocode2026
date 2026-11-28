"""The improvement folder sits under AGENT_HOME, where the pods mount the shared volume.

Counted from the code's own location it was /app/data/improvement in the image (code in /app/service, data in
/app/agent): off the volume, on a read-only root, so erasing a customer (gaps.forget_calls) failed and rolled the
whole deletion back on EKS.
"""

import importlib
import subprocess
import sys
from pathlib import Path

from ai_agent_service.config.config_manager import ROOT
from ai_agent_service.components.improvement import signals


def test_the_default_folder_is_under_the_agent_home():
    assert signals.DEFAULT_DIR == ROOT / "data" / "improvement"


def test_agent_home_moves_it(tmp_path):
    code = ("from ai_agent_service.components.improvement import signals; print(signals.DEFAULT_DIR)")
    env = {**__import__("os").environ, "AGENT_HOME": str(tmp_path)}
    env.pop("IMPROVEMENT_DIR", None)
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True,
                         cwd=Path(importlib.import_module("ai_agent_service").__file__).parents[1])
    assert Path(out.stdout.strip()) == (tmp_path / "data" / "improvement").resolve()
