#!/usr/bin/env python3
"""Preflight, raw execution, offline collection and BTC wire export.

Run with the agent's interpreter (it has the harness's dependencies too):

    apps/ai-agent-service/.venv/Scripts/python evaluation/harness/run_eval.py evaluate

On Windows the process restarts itself in UTF-8 mode: the harness and the
organisers' files read and print Vietnamese text without naming an encoding.
"""
import os
import subprocess
import sys

if __name__ == "__main__" and not sys.flags.utf8_mode:
    env = {**os.environ, "PYTHONUTF8": "1"}
    raise SystemExit(subprocess.call([sys.executable, "-X", "utf8", *sys.argv], env=env))

from eval_harness.__main__ import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
