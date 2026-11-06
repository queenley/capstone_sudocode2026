"""The performance table of a run: ``run_eval.py --performance``.

The organisers' "Chế độ vận hành & hiệu năng", read from what a run already wrote: no model call, unless ``--sessions``
asks for a load test (:func:`..runner.load_test`). Latency is ``reference_eval.latency`` itself, on the ``full`` trace,
as ``huong-dan-do-latency.md`` says (warm-up turns are never traced). What a run did not measure stays "chưa đo":
``run_eval.py`` plays text, so TTFA, which runs from the end of speech to the first audio byte, has no value here.

Cost is tokens times the list price of each model below, as if the same tokens had gone to it: only the model the run
used is a measurement, the other is an estimate. Prompt caching is not counted, so it is a ceiling.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from ...config.config_manager import btc_data_dir

#: USD per million tokens. GPT: ``config/models.yaml``. Gemini 3 Flash: third-party trackers of Google's price list
#: (benchlm.ai, evolink.ai, read 2026-11-05), not Google's page: check it before quoting a figure.
PRICES = {"gemini-3-flash": (0.50, 3.00), "gpt-4.1-mini": (0.40, 1.60)}
#: USD per million input tokens of the policy model (``config/models.yaml``); it is the same whichever model advises.
POLICY_PRICE = 0.042
#: ``huong-dan-do-latency.md``: chat p95 limits, and Call Brief's for chat and voice.
LIMITS_MS = {"ttft": 3000, "total": 8000, "ttfa": 2500, "call_brief_chat": 5000, "call_brief_voice": 3000}


def _reference_eval() -> Any:
    spec = importlib.util.spec_from_file_location("btc_reference_eval", btc_data_dir() / "eval" / "reference_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tokens(entries: Iterable[Mapping[str, Any]], part: str) -> dict[str, dict[str, int]]:
    total: dict[str, dict[str, int]] = {}
    for entry in entries:
        for agent, counts in (entry.get(part) or {}).items():
            bucket = total.setdefault(agent, {"calls": 0, "input": 0, "output": 0})
            for key in bucket:
                bucket[key] += int(counts.get(key, 0))
    return total


def _per_turn(tokens: Mapping[str, Mapping[str, int]], turns: int) -> dict[str, Any]:
    """Tokens and cost per customer turn; the policy model apart, at its own price."""
    model = [counts for agent, counts in tokens.items() if not agent.startswith("policy")]
    policy = [counts for agent, counts in tokens.items() if agent.startswith("policy")]
    used_in, used_out = sum(c["input"] for c in model), sum(c["output"] for c in model)
    policy_in, policy_out = sum(c["input"] for c in policy), sum(c["output"] for c in policy)
    shared = policy_in * POLICY_PRICE / 1_000_000
    return {
        "input": round((used_in + policy_in) / turns, 1), "output": round((used_out + policy_out) / turns, 1),
        "total": round((used_in + used_out + policy_in + policy_out) / turns, 1),
        "cost_usd": {name: round(((used_in * rate_in + used_out * rate_out) / 1_000_000 + shared) / turns, 6)
                     for name, (rate_in, rate_out) in PRICES.items()},
    }


def machine() -> dict[str, Any]:
    """Rule 4 of ``huong-dan-do-latency.md``: the numbers say what they were measured on."""
    return {"platform": platform.platform(), "processor": platform.processor() or platform.machine(), "cpus": os.cpu_count()}


def measure(directory: Path) -> dict[str, Any]:
    """The table's figures from a finished run's directory. A run without a ``full`` trace has nothing to report."""
    trace_path = directory / "full.jsonl"
    if not trace_path.is_file():
        raise ValueError(f"{directory} has no full.jsonl")
    btc = _reference_eval()
    trace = btc.load_trace(str(trace_path))
    rows = [row for lines in trace.values() for row in lines]
    if not rows:
        raise ValueError(f"{trace_path} is empty")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    usage_path = directory / "usage.json"
    usage = json.loads(usage_path.read_text(encoding="utf-8")).get("full", []) if usage_path.is_file() else []
    turn_tokens = _tokens(usage, "turns")
    after_tokens = _tokens(usage, "after_call")
    modes = Counter(str(row.get("input_mode") or "text") for row in rows)
    return {
        "turns": len(rows),
        "calls": len(trace),
        "modes": dict(modes),
        "advisor": (manifest.get("models") or {}).get("advisor"),
        "started_at": manifest.get("started_at"),
        "machine": machine(),
        "latency": btc.latency(trace),
        # Without usage.json the tokens are unknown, not zero.
        "tokens_per_turn": _per_turn(turn_tokens, len(rows)) if usage else None,
        "with_after_call": _per_turn({**turn_tokens, **{f"{k}#after": v for k, v in after_tokens.items()}}, len(rows)) if usage else None,
        "tokens_by_agent": turn_tokens,
    }


def _ms(stats: Mapping[str, Any] | None, limit: int | None = None) -> str:
    if not stats:
        return "chưa đo"
    verdict = "" if limit is None else (" (đạt)" if stats["p95_ms"] <= limit else " (vượt)")
    return f"p95 {stats['p95_ms'] / 1000:.2f} s, p50 {stats['p50_ms'] / 1000:.2f} s, n={stats['n']}{f', ngưỡng {limit / 1000:g} s' + verdict if limit else ''}"


def sessions_line(levels: Iterable[Mapping[str, Any]]) -> str:
    levels = list(levels)
    if not levels:
        return "chưa đo (thêm --sessions 1,3,5, tốn phí model)"
    held = [level["sessions"] for level in levels if level["held"]]
    detail = "; ".join(f"{level['sessions']} phiên: TTFT p95 {level['ttft_p95_ms'] / 1000:.2f} s, total p95 "
                       f"{level['total_p95_ms'] / 1000:.2f} s, lỗi {level['errors']}" for level in levels)
    return f"giữ được {max(held)} phiên ({detail})" if held else f"không mức nào đạt ngưỡng ({detail})"


def table(figures: Mapping[str, Any], sessions: Iterable[Mapping[str, Any]] = ()) -> str:
    latency = figures["latency"]
    voice = any(mode != "text" for mode in figures["modes"])
    advisor = figures.get("advisor") or {}
    tokens, whole = figures["tokens_per_turn"], figures["with_after_call"]
    lines = [
        "Hiệu năng (run_eval.py --performance)",
        f"  Chế độ vận hành            {'chat và lời ASR đã có sẵn' if voice else 'chat'}, streaming; "
        + ", ".join(f"{mode} {n} lượt" for mode, n in figures["modes"].items())
        + f"; {advisor.get('provider', '?')}/{advisor.get('model', '?')}",
        f"  Thời gian nạp Call Brief   {_ms(latency.get('call_brief'), LIMITS_MS['call_brief_chat'])}",
        f"  TTFT (chat)                {_ms(latency.get('ttft'), LIMITS_MS['ttft'])}",
        f"  TTFA (voice)               {_ms(latency.get('ttfa'), LIMITS_MS['ttfa'])}",
        f"  Total Latency              {_ms(latency.get('total'), LIMITS_MS['total'])}",
        f"  Số phiên đồng thời (demo)  {sessions_line(sessions)}",
    ]
    if tokens:
        lines += [f"  Token mỗi lượt (TB)        {tokens['total']:g} (vào {tokens['input']:g}, ra {tokens['output']:g}); "
                  f"kể cả after_call {whole['total']:g}"]
        lines += [f"  Chi phí mỗi lượt, {name:<13} ${tokens['cost_usd'][name]:.5f}; kể cả after_call ${whole['cost_usd'][name]:.5f}"
                  for name in PRICES]
        used = advisor.get("model")
        lines.append(f"  (Đo trên {used or 'model của run'}; model còn lại là ước tính cùng số token, chưa tính cache.)")
    else:
        lines.append("  Token và chi phí           chưa đo (run không có usage.json)")
    if latency.get("warning"):
        lines.append(f"  Cảnh báo: {latency['warning']}")
    return "\n".join(lines)
