"""Entities from what a recogniser heard, for BTC's ``entity_accuracy`` (exact match of ``hypotheses[id].entities``).

A recogniser writes numbers as words ("năm triệu", "hai mươi lăm mét vuông"). The agent reads them back to digits
with its own ITN (``ai_agent_service.components.intake.itn``); the same step is used here so the score reflects what
the agent would understand. Only entities a sentence states plainly are produced: the money after "ngân sách"
(``budget_vnd``), after "giá" (``price_vnd``) or after "rẻ hơn/bên kia" (``competitor_price_vnd``), the room area
(``room_area_m2``), children at home (``has_children``) and the payment (``payment``, BTC's ``COD`` / ``bank``).
Anything else stays out, so a wrong guess never counts as an entity the recogniser got right.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SERVICE_SRC = Path(__file__).resolve().parents[4] / "apps/ai-agent-service/src"

_MONEY = r"(\d[\d.,]*)\s*(?:đ|đồng|vnđ|vnd)"


def _itn():
    if str(SERVICE_SRC) not in sys.path:
        sys.path.insert(0, str(SERVICE_SRC))
    from ai_agent_service.components.intake import itn  # noqa: PLC0415

    return itn


def _vnd(raw: str) -> int:
    return int(re.sub(r"[.,]", "", raw))


def extract(text: str) -> dict[str, Any]:
    """The entities a recognised sentence (or a whole dialogue) states, as BTC's ground truth writes them."""
    plain = _itn().normalise(text.lower(), datetime(2026, 1, 1))
    found: dict[str, Any] = {}
    for key, cue in (("budget_vnd", r"ngân sách[^.?!]*?"), ("competitor_price_vnd", r"(?:bên kia|chỗ khác|nơi khác|rẻ hơn)[^.?!]*?"),
                     ("price_vnd", r"giá[^.?!]*?")):
        match = re.search(cue + _MONEY, plain)
        if match:
            found[key] = _vnd(match.group(1))
    area = re.search(r"(\d+)\s*(?:mét vuông|m2|m²)", plain)
    if area:
        found["room_area_m2"] = int(area.group(1))
    if re.search(r"không (?:có )?(?:trẻ|con nhỏ|em bé|bé)", plain):
        found["has_children"] = False
    elif re.search(r"(?:có|nhà có) (?:trẻ|con nhỏ|em bé|bé)", plain):
        found["has_children"] = True
    if re.search(r"\bcod\b|thu hộ|nhận hàng.*trả tiền", plain):
        found["payment"] = "COD"
    elif re.search(r"chuyển khoản|banking", plain):
        found["payment"] = "bank"
    return found
