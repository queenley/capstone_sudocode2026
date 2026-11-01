"""Stage 1 — validate BTC's catalogue (the agent's ``apps/ai-agent-service/data/btc/catalog``, the only copy).

Checks, offline (``<seed>/reports/catalog_check.json``; non-zero exit on an error):

* each file parses: products, promotions, inventory timeline, CRM seed, synthetic CRM;
* prices, variants, stock and promotions agree with each other: every SKU a
  promotion, a gift, the inventory timeline or a CRM order names exists; a CRM
  order's variant was in stock on its date and costs what ``mock_tools`` quotes
  for that day (the promotions of that day applied); synthetic ids and phones
  do not collide with BTC's;

    python -m src.pipeline.build_catalog
"""
from __future__ import annotations

import sys

from src.schemas.catalog import CustomerCatalog, InventoryTimeline, ProductCatalog, PromotionCatalog
from src.utils.btc_tools import mock_tools
from src.utils.io import load_model, write_json
from src.utils.paths import CATALOG_DIR, REPORTS_DIR


def consistency_errors() -> tuple[list[str], dict[str, int]]:
    catalog = load_model(CATALOG_DIR / "products.json", ProductCatalog)
    promotions = load_model(CATALOG_DIR / "promotions.json", PromotionCatalog)
    timeline = load_model(CATALOG_DIR / "inventory_timeline.json", InventoryTimeline)
    official = load_model(CATALOG_DIR / "crm_seed.json", CustomerCatalog).customers
    synthetic_path = CATALOG_DIR / "crm_seed_synthetic.json"
    synthetic = load_model(synthetic_path, CustomerCatalog).customers if synthetic_path.exists() else []

    skus = {p.sku for p in catalog.products} | {v.variant_sku for p in catalog.products for v in p.variants}
    errors = []
    for promo in promotions.promotions:
        unknown = [t for t in promo.applies_to if t != "*" and not t.startswith("category:") and t not in skus]
        if unknown:
            errors.append(f"promotion {promo.promo_code} applies to unknown SKUs {unknown}")
        if promo.gift_sku and promo.gift_sku not in skus:
            errors.append(f"promotion {promo.promo_code} gives unknown SKU {promo.gift_sku}")
    errors += [f"inventory event for unknown SKU {e.sku} on {e.date}" for e in timeline.events if e.sku not in skus]

    mock = mock_tools()
    for customer in official + synthetic:
        for order in customer.orders:
            if order.sku not in skus:
                errors.append(f"{customer.customer_id} order {order.order_id}: unknown SKU {order.sku}")
                continue
            if not customer.synthetic:
                continue   # BTC's own records are theirs; ours must match the catalogue of their day
            on = order.date.isoformat()
            if not mock.inventory_check(order.sku, on).get("in_stock"):
                errors.append(f"{customer.customer_id} order {order.order_id}: {order.sku} out of stock on {on}")
            quoted = mock.pricing_get_quote(order.sku, on)["final_price_vnd"]
            if order.price_vnd != quoted:
                errors.append(f"{customer.customer_id} order {order.order_id}: price {order.price_vnd} "
                              f"but mock_tools quotes {quoted} on {on}")
    ids, phones = {c.customer_id for c in official}, {c.phone for c in official}
    errors += [f"synthetic {c.customer_id} collides with a BTC customer id or phone"
               for c in synthetic if c.customer_id in ids or c.phone in phones]
    counts = {"products": len(catalog.products), "variants": sum(len(p.variants) for p in catalog.products),
              "promotions": len(promotions.promotions), "inventory_events": len(timeline.events),
              "btc_customers": len(official), "synthetic_customers": len(synthetic),
              "zalo_ids": sum(bool(c.zalo_id) for c in official + synthetic),
              "fb_ids": sum(bool(c.fb_id) for c in official + synthetic)}
    return errors, counts


def main() -> None:
    errors, counts = consistency_errors()
    write_json(REPORTS_DIR / "catalog_check.json", {"counts": counts, "errors": errors})
    print(", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items()))
    for error in errors:
        print(f"  ERROR {error}")
    if errors:
        sys.exit(1)
    print("Catalogue consistent.")


if __name__ == "__main__":
    main()
