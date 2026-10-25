"""What BTC's table leaves out or gets by a different rule, beside it and never in its place.

- **Latency without the warm-up.** BTC's rule is to drop the first three turns of a run (model load, connections)
  before the p95 (``huong-dan-do-latency.md`` rule 2), but ``reference_eval.latency`` takes every row. The collector
  already marks those turns (``TimingEvidence.warmup``); here the p50/p95 are taken over the others, with the same
  p95 as the organisers' script.
- **Calls-to-Close.** BTC's script computes it but its table does not print it, and it counts any ``order.create``
  call, failed or not. The harness's own metric counts only orders proven in the mock's state. Both are shown, and
  when one is empty the reason is: no order was placed at all, or the run is missing evidence.
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


def closing(official_side, verified):
    """Calls-to-Close by the organisers' rule and by the verified one, each with the reason when it is empty."""
    btc = official_side["calls_to_close"]
    return {
        "btc": {**btc, "reason": None if btc["value"] is not None else "không có order.create nào trong trace"},
        "verified": {"value": verified["value"], "orders": verified["numerator"], "closed_scenarios": verified["denominator"],
                     "status": verified["status"],
                     "reason": {"UNDEFINED": "không có đơn nào được xác minh trong trạng thái mock",
                                "INCOMPLETE": "thiếu bằng chứng (trace hoặc kiểm toán không đủ)"}.get(verified["status"])},
    }


def build(official, traces, timings, metrics):
    """``{"configs": {config: {...}}}`` and the lines to print under BTC's table."""
    summary = {"notice": "Beside the organisers' table, not in place of it", "configs": {}}
    side_of = {"full": "system", "baseline_no_memory": "baseline"}
    lines = ["Bổ sung (bên cạnh bảng BTC, không thay bảng):"]
    for config, trace in traces.items():
        side = official.get(side_of[config])
        if side is None:
            continue
        verified = next((m for m in metrics if m["metric_id"] == config + "/verified_calls_to_close"), None)
        entry = {"latency_without_warmup": latency_without_warmup(trace, timings.get(config, [])),
                 "calls_to_close": closing(side, verified) if verified else None}
        summary["configs"][config] = entry
        label = "Hệ thống" if config == "full" else "Baseline"
        latency = entry["latency_without_warmup"]
        ttft, total = latency["ttft"], latency["total"]
        lines.append(f"  {label}: bỏ {latency['warmup_turns_dropped']} lượt warm-up, {latency['n_turns']} lượt; "
                     + (f"TTFT p50/p95 {ttft['p50_ms']}/{ttft['p95_ms']} ms; Total {total['p50_ms']}/{total['p95_ms']} ms"
                        if ttft and total else "không có số đo độ trễ")
                     + (f" ({latency['warning']})" if latency["warning"] else ""))
        if entry["calls_to_close"]:
            btc, ver = entry["calls_to_close"]["btc"], entry["calls_to_close"]["verified"]
            lines.append(f"    Calls-to-Close: BTC {btc['value'] if btc['value'] is not None else 'n/a'} "
                         f"({btc['n_closed']}/{btc['n_scenarios']} kịch bản có order.create"
                         + (f"; {btc['reason']}" if btc["reason"] else "") + "); "
                         f"đã xác minh {round(ver['value'], 2) if ver['value'] is not None else 'n/a'} "
                         f"({ver['closed_scenarios']} kịch bản"
                         + (f"; {ver['reason']}" if ver["reason"] else "") + ")")
    return summary, "\n".join(lines) + "\n"
