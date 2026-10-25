"""Seed the storefront from the organisers' (BTC) catalogue, so the shop and the AI agent sell the same things.

    python -m scripts.seed.catalog --dataset /app/data --btc /app/btc

Every price and stock figure comes from running the organisers' own mock
(``eval/mock_tools.py``) on its reference day, the day the agent's calls run on:

- one SKU per variant (size/colour), or the product's own SKU when it has none;
- ``list_price``: the mock's list price (variant delta included);
- ``sale_price``: the mock's ``final_price_vnd`` for a customer the shop does not
  know yet (no phone, no address), i.e. the best promotion everybody gets;
- stock: the mock's ``inventory_check`` quantity on that day;
- the promotions the quote applied are stored as ``informational`` rows, so the
  product page shows them without discounting the sale price a second time.

Customer-specific promotions (regional, trade-in, once per customer) are left
to the agent, which quotes them per customer. The mock's internal price floor
is never stored. Products outside the BTC catalogue are deactivated (not
deleted: past orders still point at them). Safe to run again: existing rows are
updated in place.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from src.db.models import Inventory, Product, Promotion, SKU

SOURCE = "btc"
VN = timezone(timedelta(hours=7))

#: Attribute keys as a shopper reads them.
LABELS = {
    "room_area_m2": "Diện tích phòng phù hợp (m²)",
    "features": "Tính năng",
    "warranty_months": "Bảo hành (tháng)",
    "child_safe_lock": "Khóa an toàn trẻ em",
    "return_days": "Đổi trả trong (ngày)",
    "material": "Chất liệu",
    "stages": "Số cấp lọc",
    "max_weight_kg": "Tải trọng tối đa (kg)",
    "saving_vnd": "Tiết kiệm so với mua lẻ (đ)",
    "volume_ml": "Dung tích (ml)",
}
#: Internal or shown elsewhere (bundle contents are SKU codes, not words).
HIDDEN = {"discontinued", "successor_sku", "bundle_of"}


def load_mock(btc: Path):
    """The organisers' mock, from ``<btc>/eval/mock_tools.py`` (it reads ``<btc>/catalog``)."""
    spec = importlib.util.spec_from_file_location("btc_mock_tools", btc / "eval" / "mock_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def describe(attributes: dict) -> str:
    """The product's attributes as readable lines: ``Label: value``."""
    lines = []
    for key, value in attributes.items():
        if key in HIDDEN or value in (None, "", []):
            continue
        if isinstance(value, bool):
            value = "Có" if value else "Không"
        elif isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append(f"{LABELS.get(key, key.replace('_', ' ').capitalize())}: {value}")
    return "\n".join(lines)


def _upsert_product(db, product: dict) -> Product:
    row = db.scalar(select(Product).where(Product.external_id == product["sku"]))
    if row is None:
        row = Product(external_id=product["sku"], name=product["name"], category=product["category"])
        db.add(row)
    row.name, row.brand, row.category = product["name"], product["brand"], product["category"]
    row.description = describe(product.get("attributes") or {})
    row.active = not (product.get("attributes") or {}).get("discontinued", False)
    db.flush()
    return row


def _upsert_sku(db, product_row: Product, code: str, variant: dict, quote: dict, stock: int) -> SKU:
    sku = db.scalar(select(SKU).where(SKU.sku_code == code))
    if sku is None:
        sku = SKU(product_id=product_row.id, sku_code=code, list_price=0, sale_price=0)
        db.add(sku)
    sku.product_id = product_row.id
    sku.variant = variant
    sku.list_price = quote["list_price_vnd"]
    sku.sale_price = quote["final_price_vnd"]
    sku.currency = "VND"
    sku.active = product_row.active
    sku.synthetic = False
    sku.source = SOURCE
    db.flush()
    inventory = db.get(Inventory, sku.id)
    if inventory is None:
        db.add(Inventory(sku_id=sku.id, quantity_on_hand=stock, reserved_quantity=0))
    else:
        # Keep what open orders reserved; the stock itself is the mock's on the reference day.
        inventory.quantity_on_hand = max(stock, inventory.reserved_quantity)
    return sku


def _promotions(db, sku: SKU, quote: dict, promos: dict, reference: str) -> None:
    """The quote's applied promotions as display-only rows, one per SKU and code."""
    for applied in quote.get("applied_promos") or []:
        code = applied["promo_code"]
        promo = promos.get(code) or {}
        external = f"btc:{code}:{sku.sku_code}"
        row = db.scalar(select(Promotion).where(Promotion.external_id == external))
        if row is None:
            row = Promotion(external_id=external, channel="all", name=code, description="",
                            promotion_type="informational", starts_at=datetime.now(VN), ends_at=datetime.now(VN))
            db.add(row)
        start = promo.get("start") or reference
        end = promo.get("end") or reference
        row.sku_id = sku.id
        row.channel = "all"
        row.name = code
        row.description = promo.get("name") or code
        row.promotion_type = "informational"
        # Display only: the schema requires no value for informational rows, and
        # the discount is already in sale_price (and in the description).
        row.value = None
        row.starts_at = datetime.fromisoformat(start).replace(tzinfo=VN)
        row.ends_at = datetime.fromisoformat(end).replace(tzinfo=VN) + timedelta(days=1)
        row.active = True
        row.synthetic = False


def apply_images(db, manifest: Path) -> int:
    """Photos picked by ``scripts/seed/product_images.py`` (file and credit), onto their products."""
    if not manifest.is_file():
        return 0
    import json

    photos = json.loads(manifest.read_text(encoding="utf-8"))
    applied = 0
    for row in db.scalars(select(Product)):
        entry = photos.get(row.external_id)
        # A photo dropped from the manifest (it did not show the product) goes back to the drawing.
        row.image_url, row.image_credit = (entry["image_url"], entry["credit"]) if entry else (None, None)
        applied += bool(entry)
    db.flush()
    return applied


def seed_btc(db, btc: Path) -> dict:
    mock = load_mock(btc)
    reference = mock.REF
    promos = {p["promo_code"]: p for p in mock.PROMOS}
    kept, skus = set(), 0
    for product in mock.PRODUCTS:
        product_row = _upsert_product(db, product)
        kept.add(product_row.id)
        variants = product.get("variants") or []
        targets = ([(v["variant_sku"], {k: v[k] for k in ("size", "color") if v.get(k) not in (None, "")})
                    for v in variants] if variants else [(product["sku"], {})])
        for code, variant in targets:
            quote = mock.pricing_get_quote(code, on=reference)
            stock = mock.inventory_check(code, on=reference).get("qty", 0)
            sku = _upsert_sku(db, product_row, code, variant, quote, int(stock or 0))
            _promotions(db, sku, quote, promos, reference)
            skus += 1
    # The storefront sells the BTC catalogue only; older demo products stay for past orders.
    retired = 0
    for row in db.scalars(select(Product).where(Product.active.is_(True))):
        if row.id not in kept:
            row.active = False
            retired += 1
    db.flush()
    return {"products": len(kept), "skus": skus, "retired_demo_products": retired, "reference_date": reference}
