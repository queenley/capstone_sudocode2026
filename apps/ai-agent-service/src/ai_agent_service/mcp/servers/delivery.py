"""The team's ``delivery_estimate`` tool, as plain functions over the organisers' mock module.

No import beyond the standard library, so the data generator loads this file by its path and labels its
scenarios with the same rule the agent answers by (evaluation/data-generation src/utils/btc_tools.py).
The rule is the mock's own: ``mock_tools._eta`` and its ``HOLIDAYS``.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import ModuleType
from typing import Any

#: The areas ``mock_tools._eta`` tells apart, each with an address it recognises.
DELIVERY_AREAS = (("Hà Nội, TP.HCM, Đà Nẵng", "Hà Nội"), ("tỉnh thành khác", None))


def working_days(m: ModuleType, start: str, end: str) -> int:
    """Days after *start*, up to and including *end*, that the mock delivers on."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    days = (first + timedelta(days=n) for n in range(1, (last - first).days + 1))
    return sum(1 for d in days if d.weekday() != 6 and d.isoformat() not in m.HOLIDAYS)


def estimate(m: ModuleType, address: str | None, on: str) -> dict[str, Any]:
    """When an order placed on *on* would arrive, by the mock's own rule (``mock_tools._eta``).

    With an address: its working days and date, which ``order.create`` will
    then return as ``estimated_delivery``. Without one the area decides, so
    both areas are given and no single figure is: a number for an address
    nobody gave would be a promise nobody made.
    """
    if address:
        estimated = m._eta(on, address)
        return {"address_known": True, "delivery_days": working_days(m, on, estimated), "estimated_delivery": estimated}
    areas = []
    for area, example in DELIVERY_AREAS:
        estimated = m._eta(on, example)
        areas.append({"area": area, "delivery_days": working_days(m, on, estimated), "estimated_delivery": estimated})
    return {"address_known": False, "delivery_days": None, "estimated_delivery": None, "by_area": areas}
