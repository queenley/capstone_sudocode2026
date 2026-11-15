"""Seed the storefront with the organisers' (BTC) CRM customers and their order history.

    python -m scripts.seed.catalog --dataset /app/data --btc /app/btc     (the ``seed`` service runs this)

So a fresh ``docker compose up`` opens a shop that already knows chị Hoa (0984726714) and the other 69 customers
the agent's scenarios talk about, each with the orders the CRM says they placed, under the same codes the agent
reads (OD188213, OD900101...). Reads ``catalog/crm_seed.json`` and the team's ``catalog/crm_seed_synthetic.json``.

``DEMO_CUSTOMER_PASSWORD`` (a local demo, never production): every CRM customer without an account gets one with
this password, so the shop can be opened as any of them at /dang-nhap.

Safe to run again: a customer is found by phone, an order by its CRM code (``src/commerce/crm_seed.py``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.commerce.crm_seed import seed_customers
from src.core.config import Settings
from src.security.service import Security


def crm_rows(btc: Path) -> list[dict]:
    rows: list[dict] = []
    for name in ("crm_seed.json", "crm_seed_synthetic.json"):
        path = btc / "catalog" / name
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            rows += data["customers"] if isinstance(data, dict) else data
    return rows


def demo_password(settings: Settings) -> str | None:
    password = os.environ.get("DEMO_CUSTOMER_PASSWORD", "").strip()
    if not password:
        return None
    if settings.environment == "production":
        print("DEMO_CUSTOMER_PASSWORD is ignored in production: CRM customers get no password.")
        return None
    if not 8 <= len(password) <= 128:
        raise SystemExit("DEMO_CUSTOMER_PASSWORD needs 8 to 128 characters")
    return password


def seed_btc_customers(db, btc: Path) -> dict:
    settings = Settings()
    customers, orders = seed_customers(db, Security(settings), crm_rows(btc), demo_password=demo_password(settings))
    return {"customers": customers, "orders": orders}
