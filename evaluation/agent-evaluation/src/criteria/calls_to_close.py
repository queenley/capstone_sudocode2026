"""Criterion Calls-to-Close, by BTC's rule and by the verified one.

BTC's script computes it but its table does not print it, and it counts any ``order.create`` call, failed or not.
The harness also counts only orders proven in the mock's state (:mod:`.tool_state`). Both are shown, and when one is
empty the reason is: no order was placed at all, or the run is missing evidence.
"""


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
