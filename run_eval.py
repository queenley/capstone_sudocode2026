#!/usr/bin/env python3
"""The organisers' evaluation command, in the form their pack's README asks for.

    python run_eval.py --scenarios <dir> --config full --out full.jsonl
    python run_eval.py --scenarios <dir> --config baseline_no_memory --out baseline.jsonl
    python run_eval.py --scenarios <dir>

The agent lives in ``apps/ai-agent-service``; this file only puts it on the
path and hands over to ``ai_agent_service/pipeline/eval/cli.py``, which
documents the options. Run it with the agent's interpreter
(``apps/ai-agent-service/.venv``), from any directory. It is the only evaluation
command: ``--relabel <run>`` labels a finished run again without running the agent.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
sys.path[:0] = [str(ROOT / "apps" / "ai-agent-service" / "src"), str(ROOT / "packages" / "backend-common")]

from ai_agent_service.pipeline.eval.cli import main  # noqa: E402  (the path above first)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
