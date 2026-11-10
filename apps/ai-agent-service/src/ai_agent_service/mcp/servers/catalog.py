"""mcp-catalog: products, stock by day, the price of a product on a day, and when it would arrive.

``docs/design.md`` section 6.1. Four tools under the organisers' names and
required arguments, ``catalog.search``, ``inventory.check``,
``pricing.get_quote`` and ``pricing.quote_order`` (an order of more than one
unit, added by the organisers in 11/2026), each a thin wrapper over the reference mock
(:mod:`.btc`), so the price after promotions, the promotion conditions and
the stock on a given day are the grader's own. One tool of our own,
``delivery.estimate``, the mock's delivery rule asked before an order exists
so the advisor can read the order back with its delivery time (PB-09).

A price is never something the advisor remembers: it is asked here, for the
day of the call (``on``), every turn it is needed (principle 5). The harness
fills ``on`` and ``customer_phone`` in; the model never has to, and never
sees the phone number.

What this server adds to the mock (the loose search, a promotion's end date)
is in :mod:`.btc`, because the evaluation harness's own copy of the mock must
answer the same through ``pipeline/eval/bridge.py``.
"""

from __future__ import annotations

from typing import Any, TypedDict

from ..server_base import Server, ToolFailure, apply_schema
from . import btc

READERS = {"advisor", "harness"}

server = Server("catalog")


@server.tool(roles=READERS, name="catalog_search")
async def catalog_search(
    query: str | None = None,
    category: str | None = None,
    sku: str | None = None,
    max_price_vnd: int | None = None,
    min_room_area_m2: int | None = None,
) -> dict[str, Any]:
    """Find products in the catalogue.

    Categories are slugs: gia-dung/may-loc-khong-khi (air purifiers),
    gia-dung/may-loc-nuoc, gia-dung/quat, gia-dung/noi-chien, gia-dung/phu-kien,
    gia-dung/combo, thoi-trang/giay, thoi-trang/ao-khoac, thoi-trang/phu-kien,
    me-be. A category prefix such as gia-dung matches all beneath it. Prices
    here are list prices; the price to tell a customer comes from
    pricing_get_quote. Discontinued products are hidden unless asked for by sku.

    match says how the query was read. exact: every word is in the product.
    loose: no product has every word; these share a phrase with the query,
    so check each is the kind, brand and model the customer asked for before
    offering it, and say plainly what the shop does not have. none: no
    product is named so. If what was asked could belong to a category above,
    search that category first; otherwise the shop does not sell it: say so,
    and do not offer a product of another kind in its place.

    Args:
        query: Words from the product's name or brand, e.g. "AirPure" or "Xiaomi".
        category: A category slug or prefix from the list above.
        sku: One product or variant code.
        max_price_vnd: Only products listed at or below this price, in VND.
        min_room_area_m2: Only products rated for at least this room size, in m².
    """
    m = btc.mock()

    async def search(args: dict[str, Any]) -> dict[str, Any]:
        return await btc.call("catalog.search", m.catalog_search, **args)

    return await btc.search_catalog(
        {"query": query, "category": category, "sku": sku, "max_price_vnd": max_price_vnd,
         "min_room_area_m2": min_room_area_m2},
        search,
    )


@server.tool(roles=READERS, name="inventory_check")
async def inventory_check(sku: str, on: str | None = None) -> dict[str, Any]:
    """Whether a product or a variant is in stock on the day of the call.

    Out of stock may come with restock_expected, the date it returns. A
    discontinued product names its successor_sku.

    Args:
        sku: A catalogue code such as SKU-AP-X, or a variant_sku, as
            catalog_search returned it. Never a product name: with only a
            name, call catalog_search first and wait for its result.
        on: The day of the call, YYYY-MM-DD. Set by the system; leave it out.
    """
    m = btc.mock()
    return await btc.call("inventory.check", m.inventory_check, sku=sku, on=on or btc.reference_date())


@server.tool(roles=READERS, name="pricing_get_quote")
async def pricing_get_quote(
    sku: str,
    on: str | None = None,
    qty: int = 1,
    customer_phone: str | None = None,
    address: str | None = None,
    basket_skus: list[str] | None = None,
) -> dict[str, Any]:
    """The price to tell the customer for one unit of a product, on the day of the call.

    final_price_vnd is the price after the best promotion that applies;
    applied_promos lists what was applied, each with the last day it runs
    (end); a gift promotion has discount 0 and a gift_sku. expired_promos
    lists what has ended, ineligible_promos what does not apply and why.
    This is the only source of a price or a promotion to state to a customer.

    Args:
        sku: A catalogue code such as SKU-AP-X, or a variant_sku, as
            catalog_search returned it; never a product name. A bigger size
            may cost more.
        on: The day of the call, YYYY-MM-DD. Set by the system; leave it out.
        qty: How many units the customer is buying.
        customer_phone: Set by the system; leave it out.
        address: The delivery address, when known; some promotions are regional.
        basket_skus: Other skus in the same order, for promotions on a second item.
    """
    m = btc.mock()
    return await btc.call(
        "pricing.get_quote", m.pricing_get_quote,
        sku=sku, on=on or btc.reference_date(), qty=qty,
        customer_phone=customer_phone, address=address, basket_skus=basket_skus,
    )


# Typed, so the schema the model reads names its fields: an untyped object is sent as an empty one under a strict
# schema (2026-11-10, every line arrived as {}). The docstring is the model's: it is the schema's description.
class QuoteLine(TypedDict):
    """One product of the order: its sku and how many."""

    sku: str
    qty: int


@server.tool(roles=READERS, name="pricing_quote_order")
async def pricing_quote_order(
    lines: list[QuoteLine],
    on: str | None = None,
    customer_phone: str | None = None,
    address: str | None = None,
) -> dict[str, Any]:
    """The price of every unit of an order of more than one unit, on the day of the call.

    Use it, not pricing_get_quote per product, whenever the order has more than one unit: two products, or two of
    one. A promotion on a second item (AIR-2ND-50) goes to one unit only, and each unit gets at most one promotion
    that does not stack, so only this tool knows which unit pays what. units lists every unit in order with its
    final_price_vnd and applied_promos; lines gives each line's unit_prices_vnd and line_total_vnd; total_vnd is
    the order's total. This is the only source of these prices to state to a customer.

    Args:
        lines: The order's products, each {"sku": ..., "qty": ...}; sku as catalog_search returned it.
        on: The day of the call, YYYY-MM-DD. Set by the system; leave it out.
        customer_phone: Set by the system; leave it out.
        address: The delivery address, when known; some promotions are regional.
    """
    m = btc.mock()
    clean = [{"sku": str(line.get("sku")), "qty": int(line.get("qty") or 1)} for line in lines if line.get("sku")]
    if not clean:
        raise ToolFailure("BAD_ARGUMENTS", "lines needs at least one {sku, qty}: the order's products, as "
                          "catalog_search returned their sku", retryable=False)
    return await btc.call(
        "pricing.quote_order", m.pricing_quote_order,
        lines=clean, on=on or btc.reference_date(), customer_phone=customer_phone, address=address,
    )


@server.tool(roles=READERS, name="delivery_estimate")
async def delivery_estimate(address: str | None = None, on: str | None = None) -> dict[str, Any]:
    """How many working days delivery takes for an order placed today, and the date it arrives.

    Sundays and the shop's holidays are not delivery days. Without an
    address the area decides, so the answer gives each area and no single
    figure: ask for the address, or tell the customer both.

    Args:
        address: The delivery address the customer gave, when known.
        on: The day of the call, YYYY-MM-DD. Set by the system; leave it out.
    """
    return btc.delivery_estimate(address, on or btc.reference_date())


if __name__ == "__main__":
    apply_schema(btc.STATE_SCHEMA)
    # The organisers' mock loaded now, not inside the first call's 2-second budget.
    btc.mock()
    server.run()
