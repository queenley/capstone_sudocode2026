"""mcp-catalog: products, stock by day, the price of a product on a day, and when it would arrive.

``docs/design.md`` section 6.1. Three tools under the organisers' names and
required arguments, ``catalog.search``, ``inventory.check`` and
``pricing.get_quote``, each a thin wrapper over the reference mock
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

from typing import Any

from ..server_base import Server, apply_schema
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
    server.run()
