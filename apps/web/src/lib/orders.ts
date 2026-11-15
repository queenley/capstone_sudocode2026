// A customer's orders as the shop shows them (/don-hang, the empty cart): one code everywhere, the status in the
// customer's words, and whether the shop still calls before it ships (a COD order over 2 million: the sales team's
// "Cần gọi xác nhận đơn trên 2 triệu", /ban-hang/tong-quan).
import type { Transfer } from "@/components/shop/TransferInfo";

export type CustomerOrder = {
  id: string;
  /** The code the assistant told the customer (OD600001); none for a checkout on this site. */
  order_code?: string | null;
  /** website | agent (placed by the assistant on Zalo, the fan page or the hotline) | crm (the shop's history). */
  source?: string;
  status: string;
  total: string;
  discount: string;
  created_at: string | null;
  payment_method: "cod" | "bank_transfer";
  payment_status: string;
  transfer: Transfer | null;
  items: {
    sku_code: string;
    name: string;
    quantity: number;
    unit_price: string;
    variant: Record<string, unknown>;
  }[];
};

/** One code for an order everywhere: the assistant's (OD600001), or WEB- and the id's start, as the assistant reads it. */
export const orderCode = (order: { id: string; order_code?: string | null }) =>
  order.order_code || `WEB-${order.id.slice(0, 8).toUpperCase()}`;

export const ORDER_SOURCE: Record<string, string> = { agent: "Đặt qua trợ lý AI", crm: "Đơn trước đây" };

export const PAYMENT_LABEL: Record<string, string> = {
  unpaid: "Thanh toán khi nhận hàng",
  awaiting_transfer: "Chờ chuyển khoản",
  paid: "Đã thanh toán",
  refunded: "Đã hoàn tiền",
};

const STATUS_LABEL: Record<string, string> = {
  confirmed: "Đang chuẩn bị hàng",
  cancelled: "Đã hủy",
  shipping: "Đang giao",
  fulfilled: "Đã giao",
  return_requested: "Đang chờ trả hàng",
  returned: "Đã trả hàng",
};

/** Above this, a cash-on-delivery order is confirmed by phone before it ships. */
export const CALL_ABOVE_VND = 2_000_000;

/** The shop still calls the customer before shipping this order. */
export const awaitsCall = (order: CustomerOrder) =>
  order.status === "confirmed" && order.payment_method !== "bank_transfer" && Number(order.total) > CALL_ABOVE_VND;

export const statusLabel = (order: CustomerOrder) =>
  awaitsCall(order) ? "Chờ gọi xác nhận" : STATUS_LABEL[order.status] || order.status;

/** Not yet with the customer, nor cancelled: what "đơn đang xử lý" means on the cart. */
export const isOpen = (order: CustomerOrder) => ["confirmed", "shipping", "return_requested"].includes(order.status);

export const CALL_NOTE = "Đơn COD trên 2 triệu: cửa hàng sẽ gọi cho bạn để xác nhận trước khi giao.";
