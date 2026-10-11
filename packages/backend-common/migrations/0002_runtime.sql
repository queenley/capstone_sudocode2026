BEGIN;
CREATE TABLE identity.challenges (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), conversation_id uuid NOT NULL REFERENCES conversation.conversations,
 identifier_digest text NOT NULL, kind text NOT NULL, encrypted_value bytea NOT NULL, code_digest text NOT NULL,
 expires_at timestamptz NOT NULL, attempts integer NOT NULL DEFAULT 0, consumed_at timestamptz
);
CREATE TABLE identity.customer_access (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), customer_id uuid NOT NULL REFERENCES identity.customers,
 token_digest text NOT NULL UNIQUE, expires_at timestamptz NOT NULL, revoked_at timestamptz
);
CREATE TABLE improvement.processed_events (id uuid PRIMARY KEY, processed_at timestamptz NOT NULL DEFAULT now());
COMMIT;
