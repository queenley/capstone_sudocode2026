// The words the sales workspace shows for the API's codes, and the one next step Sales takes on an order.

export const ORDER_STATUS: Record<string, string> = {
  confirmed: "Chờ xử lý",
  shipping: "Đang giao",
  fulfilled: "Đã giao",
  return_requested: "Khách yêu cầu trả",
  returned: "Đã nhận hàng trả",
  cancelled: "Đã hủy",
};

/** The one next step Sales takes on an order (POST /api/seller/orders/{id}/status): the assistant reads it back. */
export const NEXT_STEP: Record<string, { status: string; label: string; ask: string }> = {
  confirmed: { status: "shipping", label: "Giao hàng", ask: "Chuyển đơn sang đang giao?" },
  shipping: { status: "fulfilled", label: "Đã giao", ask: "Xác nhận khách đã nhận hàng? Đơn COD được tính là đã thu tiền." },
  return_requested: { status: "returned", label: "Đã nhận hàng trả", ask: "Xác nhận đã nhận lại hàng? Hàng về kho, tiền đã thu được hoàn." },
};

export const CHANNEL: Record<string, string> = { web: "Web", zalo: "Zalo", hotline: "Hotline", facebook: "Facebook" };

export const PAYMENT: Record<string, string> = {
  unpaid: "Chưa thu",
  awaiting_transfer: "Chờ chuyển khoản",
  paid: "Đã thanh toán",
  refunded: "Đã hoàn",
};

export function isToday(iso: string | null): boolean {
  if (!iso) return false;
  return new Date(iso).toDateString() === new Date().toDateString();
}

/** The code the customer was told: the assistant's (OD600001), else WEB- and the id's start. */
export const orderCode = (o: { id: string; order_code?: string | null }) =>
  o.order_code || `WEB-${o.id.slice(0, 8).toUpperCase()}`;
