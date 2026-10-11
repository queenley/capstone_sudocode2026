"""Ground-truth stock and promotion resolution shared by generation and validation.

These functions are the single source of truth for prices, promotions and
stock on a given date. Scenario labels (``ground_truth_facts``,
``success_if.args_match``, ``forbidden_claims``) are computed here, never by an LLM.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from src.schemas.catalog import InventoryTimeline, Product, ProductCatalog, Promotion, PromotionCatalog


def _index(catalog: ProductCatalog) -> tuple[dict[str, Any], dict[str, str]]:
    """Map every product/variant SKU to its object and to its parent SKU."""
    items, parents = {}, {}
    for product in catalog.products:
        items[product.sku] = product
        parents[product.sku] = product.sku
        for variant in product.variants:
            items[variant.variant_sku] = variant
            parents[variant.variant_sku] = product.sku
    return items, parents


def parent_product(sku_or_variant: str, catalog: ProductCatalog) -> Product:
    _, parents = _index(catalog)
    if sku_or_variant not in parents:
        raise KeyError(f"Unknown SKU: {sku_or_variant}")
    return next(p for p in catalog.products if p.sku == parents[sku_or_variant])


def promo_covers(promo: Promotion, sku_or_variant: str, parent: Product) -> bool:
    """True when ``applies_to`` targets the SKU, its parent, its category or ``*``."""
    return any(
        target == "*" or target in (sku_or_variant, parent.sku)
        or (target.startswith("category:") and parent.category.startswith(target[len("category:"):]))
        for target in promo.applies_to
    )


def resolve_stock(sku_or_variant: str, on_date: date, catalog: ProductCatalog,
                  timeline: InventoryTimeline) -> int:
    """Timeline quantity in effect on ``on_date``; static catalog stock otherwise."""
    items, _ = _index(catalog)
    if sku_or_variant not in items:
        raise KeyError(f"Unknown SKU: {sku_or_variant}")
    events = sorted((e for e in timeline.events if e.sku == sku_or_variant and e.date <= on_date),
                    key=lambda e: e.date)
    return events[-1].qty if events else int(items[sku_or_variant].stock)


def next_restock_date(sku_or_variant: str, on_date: date, timeline: InventoryTimeline) -> date | None:
    """First future timeline event with positive stock, if any."""
    future = sorted((e for e in timeline.events if e.sku == sku_or_variant and e.date > on_date and e.qty > 0),
                    key=lambda e: e.date)
    return future[0].date if future else None


def stock_change_dates(sku_or_variant: str, after: date, timeline: InventoryTimeline) -> list[date]:
    return sorted(e.date for e in timeline.events if e.sku == sku_or_variant and e.date > after)


def _saving(promo: Promotion, price: int) -> int:
    if promo.type in {"percent", "percent_second_item"}:
        return int(price * (promo.discount_percent or 0) / 100)
    if promo.type == "fixed":
        return promo.discount_vnd
    return 0  # gift / freeship / freecod do not change the item price


def resolve_price_and_promos(sku_or_variant: str, on_date: date, customer: dict[str, Any],
                             catalog: ProductCatalog, promotions: PromotionCatalog,
                             cart: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return list price, final price and applied/rejected promotions on ``on_date``.

    Rules: date window (inclusive), SKU/category coverage, min order, region,
    excluded variant size, once-per-customer, required owned SKU, min quantity in
    category. Stackable offers always apply; among non-stackable discounts the one
    with the highest customer saving wins.
    """
    items, parents = _index(catalog)
    if sku_or_variant not in items:
        raise KeyError(f"Unknown SKU: {sku_or_variant}")
    parent = parent_product(sku_or_variant, catalog)
    variant = items[sku_or_variant]
    base = parent.list_price_vnd + (getattr(variant, "price_delta_vnd", 0) or 0)

    cart = cart or [{"sku": sku_or_variant, "qty": 1, "category": parent.category}]
    normalized_cart = []
    for entry in cart:
        entry_sku = entry.get("sku", sku_or_variant)
        if entry_sku not in items:
            raise KeyError(f"Unknown cart SKU: {entry_sku}")
        entry_parent = parent_product(entry_sku, catalog)
        unit_price = int(entry.get("unit_price_vnd", entry_parent.list_price_vnd
                                   + (getattr(items[entry_sku], "price_delta_vnd", 0) or 0)))
        normalized_cart.append({**entry, "sku": entry_sku, "qty": int(entry.get("qty", 1)),
                                "category": entry.get("category", entry_parent.category),
                                "unit_price_vnd": unit_price})
    cart_total = sum(x["unit_price_vnd"] * x["qty"] for x in normalized_cart)
    history = customer.get("orders", [])

    applied, rejected, eligible = [], [], []
    for promo in promotions.promotions:
        cond = promo.conditions
        reason = None
        if not promo.start <= on_date <= promo.end:
            reason = "outside_promotion_period"
        elif not promo_covers(promo, sku_or_variant, parent):
            reason = "sku_or_category_not_covered"
        elif promo.min_order_vnd is not None and cart_total < promo.min_order_vnd:
            reason = "minimum_order_not_met"
        elif cond.get("region") and customer.get("region") not in (
                [cond["region"]] if isinstance(cond["region"], str) else cond["region"]):
            reason = "region_not_eligible"
        elif cond.get("exclude_variant_size") and str(getattr(variant, "size", "")) in {
                str(x) for x in cond["exclude_variant_size"]}:
            reason = "variant_size_excluded"
        elif cond.get("once_per_customer") and (
                any(o.get("promo_code") == promo.promo_code for o in history)
                or any(o.get("sku") in {sku_or_variant, parent.sku}
                       and promo.start <= date.fromisoformat(str(o["date"])) <= min(on_date, promo.end)
                       for o in history if o.get("date"))):
            reason = "already_used_by_customer"
        elif cond.get("requires_owned_sku") and not any(o.get("sku") == cond["requires_owned_sku"] for o in history):
            reason = "required_owned_sku_missing"
        elif promo.type == "percent_second_item" and sum(
                x["qty"] for x in normalized_cart if x["category"] == parent.category) < int(cond.get("min_qty", 2)):
            reason = "minimum_quantity_not_met"
        if reason:
            rejected.append({"promo_code": promo.promo_code, "reason": reason})
        else:
            eligible.append(promo)

    # Stackable offers first; then the single best non-stackable discount.
    eligible.sort(key=lambda p: (not p.stackable, p.promo_code))
    price = base
    used_nonstackable = False
    for promo in eligible:
        if not promo.stackable:
            best = max(_saving(p, price) for p in eligible if not p.stackable)
            if used_nonstackable or _saving(promo, price) < best:
                rejected.append({"promo_code": promo.promo_code, "reason": "better_nonstackable_offer_selected"})
                continue
            used_nonstackable = True
        saving = _saving(promo, price)
        price = max(0, price - saving)
        applied.append({"promo_code": promo.promo_code, "type": promo.type, "saving_vnd": saving,
                        "gift_sku": promo.gift_sku, "free_shipping": promo.type == "freeship",
                        "free_cod": promo.type == "freecod", "end": str(promo.end)})
    return {"sku": sku_or_variant, "list_price_vnd": base, "final_price_vnd": price,
            "applied_promos": applied, "rejected_promos_with_reason": rejected}
