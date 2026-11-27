"use client";
// The orders an assistant message names, as links under it to the order on /don-hang. Only for a signed-in
// customer (or one who verified their phone), and only for orders that are theirs: the list comes from
// /api/customer/orders with their own token, and a code in the reply that is not on it gets no link. The model
// never writes a link; the reply's text is only read for the codes.
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { customerToken } from "@/lib/session";
import {
  CustomerOrder,
  ORDER_CODE,
  orderAnchor,
  orderCode,
  ordersNamed,
} from "@/lib/orders";

/** One list per token for every message of the chat, read again when a reply names a code not on it (an order the
 *  assistant has just placed). */
let cached: { token: string; orders: Promise<CustomerOrder[]> } | null = null;

function customerOrders(
  token: string,
  fresh = false,
): Promise<CustomerOrder[]> {
  if (fresh || !cached || cached.token !== token) {
    const orders = api<CustomerOrder[]>("/api/customer/orders", token).catch(
      () => [] as CustomerOrder[],
    );
    cached = { token, orders };
  }
  return cached.orders;
}

/** *onShow* runs once the links appear: the chat scrolls to keep them in view. */
export default function ChatOrders({
  text,
  onShow,
}: {
  text: string;
  onShow?: () => void;
}) {
  const [orders, setOrders] = useState<CustomerOrder[]>([]);
  const names = ORDER_CODE.test(text);
  useEffect(() => {
    const token = customerToken();
    if (!names || !token) return;
    let live = true;
    customerOrders(token)
      .then((list) =>
        ordersNamed(text, list).length ? list : customerOrders(token, true),
      )
      .then((list) => live && setOrders(list))
      .catch(() => undefined); // no link is fine: the text still says it
    return () => {
      live = false;
    };
  }, [names, text]);

  const named = names ? ordersNamed(text, orders) : [];
  useEffect(() => {
    if (named.length) onShow?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [named.length]);
  if (!named.length) return null;
  return (
    <div className="s-msg-orders" aria-label="Đơn hàng được nhắc tới">
      {named.map((order) => (
        <Link
          key={order.id}
          className="s-msg-order"
          href={`/don-hang#${orderAnchor(order)}`}
          onClick={(event) => {
            // Already on /don-hang: the router would change the hash without a hashchange, and the page would not
            // scroll to the order. Setting it directly does.
            if (window.location.pathname === "/don-hang") {
              event.preventDefault();
              window.location.hash = orderAnchor(order);
            }
          }}
        >
          <span>Đơn {orderCode(order)}</span>
          <span className="s-msg-order-link">Xem đơn hàng →</span>
        </Link>
      ))}
    </div>
  );
}
