-- An order's way to the customer, kept by Sales by hand: confirmed -> shipping (on its way) -> fulfilled
-- (delivered); a return the customer asked for (the assistant records it) -> returned once the goods are back.
ALTER TABLE commerce.orders DROP CONSTRAINT IF EXISTS orders_status_check;
ALTER TABLE commerce.orders ADD CONSTRAINT orders_status_check
  CHECK (status IN ('pending', 'confirmed', 'shipping', 'fulfilled', 'return_requested', 'returned', 'cancelled'));
