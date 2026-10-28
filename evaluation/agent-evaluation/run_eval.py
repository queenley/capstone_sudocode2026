#!/usr/bin/env python3
"""The one script that runs the evaluation: ``run_eval.py evaluate`` (all four steps), or one of its tools.

Run with the agent's interpreter (it has the evaluator's dependencies too):

    apps/ai-agent-service/.venv/Scripts/python evaluation/agent-evaluation/run_eval.py evaluate
    apps/ai-agent-service/.venv/Scripts/python evaluation/agent-evaluation/run_eval.py --help   # every command

On Windows the process restarts itself in UTF-8 mode: the harness and the
organisers' files read and print Vietnamese text without naming an encoding.
"""
import os
import subprocess
import sys

if __name__ == "__main__" and not sys.flags.utf8_mode:
    env = {**os.environ, "PYTHONUTF8": "1"}
    raise SystemExit(subprocess.call([sys.executable, "-X", "utf8", *sys.argv], env=env))

from src.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
