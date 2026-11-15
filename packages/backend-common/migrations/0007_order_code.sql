-- One order store for the shop and its assistant: an order the AI agent places on Zalo, the fan page or the
-- hotline is kept here beside the website's own, under the code the customer was told (OD600001), and an order
-- from the organisers' CRM history is kept under its CRM code. source says which: website | agent | crm.
ALTER TABLE commerce.orders ADD COLUMN IF NOT EXISTS order_code text;
ALTER TABLE commerce.orders ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'website';
CREATE UNIQUE INDEX IF NOT EXISTS orders_order_code_key ON commerce.orders (order_code) WHERE order_code IS NOT NULL;
