"""mcp-account: the logged-in shopper's own account on the storefront.

The shop's website keeps an account per customer (``packages/backend-common``,
``src.identity.accounts``): the profile, the cart, the orders placed on the
site. These three tools read them for the customer *of this call*, never another:

- ``account_id`` is the platform customer the web conversation belongs to
  (the shopper logged in, or verified their phone). The tool guard fills it in
  from the run context (``mcp/tools.py``) and overrides anything the model
  wrote, and the lane middleware offers these tools only when there is one, so
  a guest, a phone call or an evaluation scenario never sees them;
- read only, no personal data the model does not need: the name, the last four
  digits of the phone, the cart lines and the orders with their totals.

The cart's total is computed here, so the advisor may state it: the guard lets
a reply say only amounts the tools returned (``components/guardrails/hard.py``).
Prices are the shop's current sale prices; a quote (``pricing.get_quote``) still
decides the price of an order.

Organiser names have one dot (``inventory.check``); these are the team's own
tools, named the same way (``account.cart``) so the trace reads alike.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..server_base import Server, ToolFailure, database

server = Server("account")


def _vnd(value: Any) -> int:
    return int(Decimal(value or 0))


def _variant(variant: dict[str, Any] | None) -> str:
    v = variant or {}
    return " · ".join(part for part in (f"size {v['size']}" if v.get("size") not in (None, "") else "",
                                        str(v.get("color") or "")) if part)


async def _customer(conn: Any, account_id: str | None) -> dict[str, Any]:
    if not account_id:
        raise ToolFailure("NOT_LOGGED_IN", "Khách chưa đăng nhập tài khoản trên website.")
    cursor = await conn.execute(
        "SELECT id::text AS id, full_name, registered_at, created_at FROM identity.customers "
        "WHERE id = %s AND deleted_at IS NULL", (account_id,))
    row = await cursor.fetchone()
    if row is None:
        raise ToolFailure("NOT_FOUND", "Không tìm thấy tài khoản này.")
    return row


@server.tool(roles={"advisor"}, name="account_profile")
async def account_profile(account_id: str | None = None) -> dict[str, Any]:
    """The logged-in customer's account on the website: name, since when, how many orders and cart lines.

    Args:
        account_id: Filled in by the system for the logged-in customer; leave empty.
    """
    pool = await database()
    async with pool.connection() as conn:
        customer = await _customer(conn, account_id)
        cursor = await conn.execute(
            "SELECT (SELECT count(*) FROM commerce.orders WHERE customer_id = %s) AS orders, "
            "(SELECT count(*) FROM commerce.cart_items WHERE customer_id = %s) AS cart_lines, "
            "(SELECT EXISTS (SELECT 1 FROM identity.customer_identities WHERE customer_id = %s "
            "AND kind = 'email' AND revoked_at IS NULL)) AS has_email",
            (account_id, account_id, account_id))
        counts = await cursor.fetchone()
    since = customer["registered_at"] or customer["created_at"]
    return {"full_name": customer["full_name"], "registered": customer["registered_at"] is not None,
            "member_since": since.date().isoformat() if since else None,
            "orders_on_website": counts["orders"], "cart_lines": counts["cart_lines"],
            "has_email": counts["has_email"]}


@server.tool(roles={"advisor"}, name="account_cart")
async def account_cart(account_id: str | None = None) -> dict[str, Any]:
    """What the logged-in customer has in their website cart, with today's shop prices and the total.

    Args:
        account_id: Filled in by the system for the logged-in customer; leave empty.
    """
    pool = await database()
    async with pool.connection() as conn:
        await _customer(conn, account_id)
        cursor = await conn.execute(
            "SELECT c.sku_code, c.quantity, p.name, s.variant, s.list_price, s.sale_price, "
            "COALESCE(i.quantity_on_hand - i.reserved_quantity, 0) AS available "
            "FROM commerce.cart_items c JOIN commerce.skus s ON s.sku_code = c.sku_code "
            "JOIN commerce.products p ON p.id = s.product_id "
            "LEFT JOIN commerce.inventory i ON i.sku_id = s.id "
            "WHERE c.customer_id = %s ORDER BY c.updated_at, c.sku_code", (account_id,))
        rows = await cursor.fetchall()
    items = [{"sku": r["sku_code"], "name": r["name"], "variant": _variant(r["variant"]), "qty": r["quantity"],
              "list_price_vnd": _vnd(r["list_price"]), "sale_price_vnd": _vnd(r["sale_price"]),
              "line_total_vnd": _vnd(r["sale_price"]) * r["quantity"], "in_stock": r["available"] >= r["quantity"]}
             for r in rows]
    return {"items": items, "total_vnd": sum(i["line_total_vnd"] for i in items),
            "note": "Giá bán hiện tại trên website; giá chốt đơn theo báo giá pricing.get_quote."}


STATUS = {"pending": "chờ xác nhận", "confirmed": "đã xác nhận", "shipping": "đang giao", "delivered": "đã giao", "fulfilled": "đã hoàn tất",
          "cancelled": "đã hủy", "returned": "đã trả hàng"}
PAYMENT = {"unpaid": "chưa thanh toán", "awaiting_transfer": "chờ chuyển khoản", "paid": "đã thanh toán",
           "refunded": "đã hoàn tiền"}


@server.tool(roles={"advisor"}, name="account_orders")
async def account_orders(account_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    """The logged-in customer's orders placed on the website, newest first, with items and totals.

    Args:
        account_id: Filled in by the system for the logged-in customer; leave empty.
        limit: How many recent orders, 1 to 10.
    """
    limit = max(1, min(10, int(limit or 5)))
    pool = await database()
    async with pool.connection() as conn:
        await _customer(conn, account_id)
        cursor = await conn.execute(
            "SELECT id::text AS id, status, subtotal, discount, payment_method, payment_status, created_at "
            "FROM commerce.orders WHERE customer_id = %s ORDER BY created_at DESC LIMIT %s", (account_id, limit))
        orders = await cursor.fetchall()
        result = []
        for order in orders:
            cursor = await conn.execute(
                "SELECT p.name, s.variant, i.quantity, i.unit_price FROM commerce.order_items i "
                "JOIN commerce.skus s ON s.id = i.sku_id JOIN commerce.products p ON p.id = s.product_id "
                "WHERE i.order_id = %s", (order["id"],))
            items = [{"name": r["name"], "variant": _variant(r["variant"]), "qty": r["quantity"],
                      "unit_price_vnd": _vnd(r["unit_price"])} for r in await cursor.fetchall()]
            result.append({
                # As the website's order page shows it: "#" and the first eight characters.
                "order_ref": "#" + order["id"][:8].upper(),
                "placed_on": order["created_at"].date().isoformat() if order["created_at"] else None,
                "status": STATUS.get(order["status"], order["status"]),
                "payment": {"cod": "COD", "bank_transfer": "chuyển khoản"}.get(order["payment_method"], order["payment_method"]),
                "payment_status": PAYMENT.get(order["payment_status"], order["payment_status"]),
                "total_vnd": _vnd(order["subtotal"]) - _vnd(order["discount"]),
                "items": items})
    return {"orders": result, "note": "Đơn đặt trên website; đơn qua hotline/Zalo tra bằng order.status."}


if __name__ == "__main__":
    server.run()
