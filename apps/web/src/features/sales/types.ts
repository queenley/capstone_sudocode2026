// What the sales workspace reads from the API (/api/seller/orders, /api/agent/callbacks).

export type OrderItem = {
  sku_code: string;
  name: string;
  quantity: number;
  unit_price: string;
  variant: Record<string, unknown>;
};

export type Order = {
  id: string;
  order_code?: string | null;
  status: string;
  total: string;
  created_at: string | null;
  conversation_id: string | null;
  shipping_address?: string;
  payment_method?: "cod" | "bank_transfer";
  payment_status?: string;
  items: OrderItem[];
};

export type Callback = {
  callback_id: string;
  callback_at: string;
  moved_from: string | null;
  note: string | null;
  phone_last4: string | null;
  customer_name: string | null;
};
