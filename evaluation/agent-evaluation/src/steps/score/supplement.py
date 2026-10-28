"""What BTC's table leaves out or gets by a different rule, beside it and never in its place.

``run-summary.json`` / ``run-summary.txt`` per configuration: latency without the warm-up (:mod:`src.criteria.latency`)
and Calls-to-Close by BTC's rule and by verified orders (:mod:`src.criteria.calls_to_close`).
"""
from src.criteria.calls_to_close import closing
from src.criteria.latency import latency_without_warmup


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
