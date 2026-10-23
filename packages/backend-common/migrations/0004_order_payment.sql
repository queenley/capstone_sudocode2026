-- Orders: several lines per order already fit (order_items); add how the order is paid.
ALTER TABLE commerce.orders ADD COLUMN IF NOT EXISTS payment_method text NOT NULL DEFAULT 'cod'
  CHECK (payment_method IN ('cod', 'bank_transfer'));
ALTER TABLE commerce.orders ADD COLUMN IF NOT EXISTS payment_status text NOT NULL DEFAULT 'unpaid'
  CHECK (payment_status IN ('unpaid', 'awaiting_transfer', 'paid', 'refunded'));
ALTER TABLE commerce.orders ADD COLUMN IF NOT EXISTS paid_at timestamptz;
