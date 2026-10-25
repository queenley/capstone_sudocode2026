-- Customer accounts on the storefront: a password beside the verified phone (the
-- phone stays the identity, as on the hotline and Zalo), a lockout after failed
-- logins, and the cart kept per customer so it follows them between devices.
ALTER TABLE identity.customers ADD COLUMN IF NOT EXISTS password_hash text;
ALTER TABLE identity.customers ADD COLUMN IF NOT EXISTS registered_at timestamptz;
ALTER TABLE identity.customers ADD COLUMN IF NOT EXISTS failed_logins integer NOT NULL DEFAULT 0;
ALTER TABLE identity.customers ADD COLUMN IF NOT EXISTS locked_until timestamptz;

-- An account's one-time code (register, reset a password) belongs to no conversation.
ALTER TABLE identity.challenges ALTER COLUMN conversation_id DROP NOT NULL;
ALTER TABLE identity.challenges ADD COLUMN IF NOT EXISTS purpose text NOT NULL DEFAULT 'conversation';
-- What the code confirms (the name and password hash chosen at registration), encrypted.
ALTER TABLE identity.challenges ADD COLUMN IF NOT EXISTS encrypted_payload bytea;

CREATE TABLE IF NOT EXISTS commerce.cart_items (
  customer_id uuid NOT NULL REFERENCES identity.customers,
  sku_code text NOT NULL,
  quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 99),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (customer_id, sku_code)
);
