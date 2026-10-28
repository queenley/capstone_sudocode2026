"""BTC's official scores: the organisers' ``reference_eval.py``, unmodified, as a separate process.

The script the run pinned must be byte-identical to the verified copy in ``contracts/sources/btc``. It reads the
scenarios and the two trace files the Score step wrote under ``scorer-input/`` and writes ``official-report.json``
(RQR, CCR, TSR, HR, guardrail violations, latency, memory_checks, full vs baseline) and its table on stdout. The
harness never edits these numbers.
"""
import hashlib
from pathlib import Path
import subprocess
import sys

from src.baseline.configs import BASELINE, FULL, TRACE_FILE
from src.common.contracts import ROOT


def run(target, scorer, configs):
    """Run the scorer in *target*; ``(returncode, invocation)`` with stdout/stderr saved beside it."""
    canonical = ROOT / "sources/btc/eval/reference_eval.py"
    if scorer.read_bytes() != canonical.read_bytes():
        raise ValueError("Run scorer source differs from verified BTC source")
    argv = [sys.executable, "-B", str(scorer), "--scenarios", str(target / "scorer-input/scenarios"),
            "--trace", str(target / "scorer-input" / TRACE_FILE[FULL]), "--out", str(target / "official-report.json")]
    if BASELINE in configs:
        argv += ["--baseline", str(target / "scorer-input" / TRACE_FILE[BASELINE])]
    try:
        process = subprocess.run(argv, cwd=target, capture_output=True, text=True, timeout=30)
        code, stdout, stderr = process.returncode, process.stdout, process.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = None, str(exc.stdout or ""), str(exc.stderr or "")
    for filename, content in (("scorer.stdout.txt", stdout), ("scorer.stderr.txt", stderr)):
        with (target / filename).open("x", encoding="utf-8") as stream:
            stream.write(content)
    return code, {"argv": argv, "returncode": code,
                  "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
