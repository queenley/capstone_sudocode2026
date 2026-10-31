"""The improvement loop, offline: the one place it plays calls. ``docs/design.md`` section 10.

:mod:`.explore` searches, for each failure the organisers' grader found on a
learning run, a hint that fixes it (QaAgent, the exploration's customer,
branches from one snapshot); :mod:`.cli` is the command. What it decides
with lives in ``components.improvement``; it never touches the evaluation,
whose runner it only reuses to play a call.
"""
