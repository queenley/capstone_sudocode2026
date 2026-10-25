"""Live progress lines for long evaluation runs, on stderr.

Each line starts with the time, so a slow step shows. ``EVAL_QUIET=1`` turns
them off. Progress only: the run's evidence is in its folder, never here.
"""
import os
import sys
import time

_START = time.monotonic()


def say(message):
    if os.environ.get("EVAL_QUIET") == "1":
        return
    elapsed = int(time.monotonic() - _START)
    try:
        print(f"[{time.strftime('%H:%M:%S')} +{elapsed // 60:02d}:{elapsed % 60:02d}] {message}", file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass  # a closed console must never stop a run


def short(text, limit=70):
    """One line of *text*, cut to *limit* characters."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
