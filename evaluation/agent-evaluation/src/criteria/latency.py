"""Criterion latency without the warm-up, beside BTC's (which takes every turn).

BTC's rule is to drop the first three turns of a run (model load, connections) before the p95
(``huong-dan-do-latency.md`` rule 2), but ``reference_eval.latency`` takes every row. The collector already marks
those turns (``TimingEvidence.warmup``); here the p50/p95 are taken over the others, with the organisers' p95.
"""
import statistics


def p95(values):
    """The organisers' p95 (``reference_eval.p95``)."""
    values = sorted(values)
    return values[min(len(values) - 1, int(round(0.95 * len(values) + 0.5)) - 1)] if values else None


def _stats(values):
    return None if not values else {"n": len(values), "p50_ms": int(statistics.median(values)), "p95_ms": int(p95(values))}


def latency_without_warmup(trace, timing):
    """TTFT and total over the turns the collector did not mark as warm-up; also what was left out."""
    warm = {(t["context"]["scenario_id"], t["context"]["call"], t["context"]["turn"]) for t in timing if t.get("warmup")}
    kept = [r for r in trace if (r["scenario_id"], r["call"], r["turn"]) not in warm]
    ttft = [r["latency"]["ttft_ms"] for r in kept if r.get("latency", {}).get("ttft_ms") is not None]
    total = [r["latency"]["total_ms"] for r in kept if r.get("latency", {}).get("total_ms") is not None]
    return {"warmup_turns_dropped": len(trace) - len(kept), "n_turns": len(kept),
            "warning": None if len(kept) >= 100 else "Cần ≥ 100 lượt để p95 có ý nghĩa",
            "ttft": _stats(ttft), "total": _stats(total)}
