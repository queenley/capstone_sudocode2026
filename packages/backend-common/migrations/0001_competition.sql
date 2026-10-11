-- PostgreSQL 16+. Apply once with psql -v ON_ERROR_STOP=1 -f this-file.
BEGIN;
CREATE SCHEMA commerce;
CREATE SCHEMA identity;
CREATE SCHEMA conversation;
CREATE SCHEMA memory;
CREATE SCHEMA improvement;
CREATE SCHEMA evaluation;

CREATE TABLE commerce.products (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), external_id text UNIQUE,
 name text NOT NULL, brand text, category text NOT NULL, description text,
 active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE commerce.skus (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), product_id uuid NOT NULL REFERENCES commerce.products,
 sku_code text NOT NULL UNIQUE, variant jsonb NOT NULL DEFAULT '{}',
 list_price numeric(18,2) NOT NULL CHECK (list_price >= 0),
 sale_price numeric(18,2) NOT NULL CHECK (sale_price >= 0 AND sale_price <= list_price),
 currency char(3) NOT NULL DEFAULT 'VND', active boolean NOT NULL DEFAULT true,
 synthetic boolean NOT NULL DEFAULT false, source text,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE commerce.inventory (
 sku_id uuid PRIMARY KEY REFERENCES commerce.skus,
 quantity_on_hand integer NOT NULL CHECK (quantity_on_hand >= 0),
 reserved_quantity integer NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
 quantity_available integer GENERATED ALWAYS AS (quantity_on_hand - reserved_quantity) STORED,
 updated_at timestamptz NOT NULL DEFAULT now(), CHECK (reserved_quantity <= quantity_on_hand)
);
CREATE TABLE commerce.promotions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), external_id text UNIQUE,
 sku_id uuid REFERENCES commerce.skus, channel text NOT NULL,
 name text NOT NULL, description text NOT NULL,
 promotion_type text NOT NULL CHECK (promotion_type IN ('percent','fixed','informational')),
 value numeric(18,2), starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL,
 active boolean NOT NULL DEFAULT true, synthetic boolean NOT NULL DEFAULT false,
 CHECK (ends_at > starts_at),
 CHECK ((promotion_type = 'informational' AND value IS NULL) OR
        (promotion_type IN ('percent','fixed') AND value >= 0 AND value IS NOT NULL)),
 CHECK (promotion_type <> 'percent' OR value <= 100)
);
CREATE TABLE commerce.policies (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), external_id text UNIQUE,
 category text NOT NULL, body text NOT NULL, version integer NOT NULL DEFAULT 1,
 effective_at timestamptz NOT NULL, retired_at timestamptz,
 CHECK (retired_at IS NULL OR retired_at > effective_at)
);
CREATE TABLE identity.customers (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), external_id text UNIQUE,
 full_name text, region text, synthetic boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
-- Shared phone/email identifiers are deliberately not globally unique.
CREATE TABLE identity.customer_identities (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), customer_id uuid NOT NULL REFERENCES identity.customers,
 kind text NOT NULL CHECK (kind IN ('phone','email','channel_account')),
 identifier_digest text NOT NULL, provider text NOT NULL DEFAULT '',
 encrypted_value bytea, verified_at timestamptz, consent_at timestamptz,
 revoked_at timestamptz, UNIQUE (customer_id, kind, provider, identifier_digest)
);
CREATE INDEX identity_lookup ON identity.customer_identities(kind, provider, identifier_digest)
 WHERE revoked_at IS NULL;
CREATE TABLE conversation.conversations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), customer_id uuid REFERENCES identity.customers,
 channel text NOT NULL, anonymous_session_digest text,
 status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','handed_off','closed')),
 assigned_actor_id text, started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
 CHECK (ended_at IS NULL OR ended_at >= started_at)
);
CREATE INDEX customer_history ON conversation.conversations(customer_id, started_at DESC);
CREATE TABLE conversation.messages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), conversation_id uuid NOT NULL REFERENCES conversation.conversations,
 sequence integer NOT NULL CHECK (sequence >= 0),
 speaker text NOT NULL CHECK (speaker IN ('customer','agent','assistant','system','tool')),
 body text NOT NULL, normalized_text text, asr_text text,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (conversation_id, sequence)
);
CREATE TABLE conversation.turn_traces (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), message_id uuid NOT NULL REFERENCES conversation.messages,
 route text, route_confidence numeric CHECK (route_confidence BETWEEN 0 AND 1),
 config_version text NOT NULL, latency_ms integer CHECK (latency_ms >= 0),
 token_usage jsonb NOT NULL DEFAULT '{}', errors jsonb NOT NULL DEFAULT '[]'
);
CREATE TABLE conversation.tool_executions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), trace_id uuid NOT NULL REFERENCES conversation.turn_traces,
 tool_name text NOT NULL, redacted_arguments jsonb NOT NULL, redacted_result jsonb,
 status text NOT NULL CHECK (status IN ('success','error','timeout','denied')),
 latency_ms integer CHECK (latency_ms >= 0), observed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE memory.profile_facts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), customer_id uuid NOT NULL REFERENCES identity.customers,
 slot text NOT NULL, value jsonb NOT NULL, source_message_id uuid NOT NULL REFERENCES conversation.messages,
 confidence numeric NOT NULL CHECK (confidence BETWEEN 0 AND 1),
 consent_at timestamptz NOT NULL, valid_from timestamptz NOT NULL DEFAULT now(), valid_to timestamptz,
 supersedes_id uuid REFERENCES memory.profile_facts,
 CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX one_current_fact ON memory.profile_facts(customer_id, slot) WHERE valid_to IS NULL;
CREATE TABLE memory.episodes (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), customer_id uuid NOT NULL REFERENCES identity.customers,
 conversation_id uuid NOT NULL UNIQUE REFERENCES conversation.conversations,
 summary text NOT NULL, structured_context jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE conversation.handoffs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), conversation_id uuid NOT NULL REFERENCES conversation.conversations,
 from_actor_id text NOT NULL, to_actor_id text, reason text NOT NULL,
 brief jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), accepted_at timestamptz
);
CREATE TABLE commerce.orders (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), customer_id uuid NOT NULL REFERENCES identity.customers,
 conversation_id uuid REFERENCES conversation.conversations,
 idempotency_key text NOT NULL UNIQUE,
 status text NOT NULL CHECK (status IN ('pending','confirmed','cancelled','fulfilled')),
 currency char(3) NOT NULL DEFAULT 'VND', subtotal numeric(18,2) NOT NULL CHECK (subtotal >= 0),
 discount numeric(18,2) NOT NULL DEFAULT 0 CHECK (discount >= 0 AND discount <= subtotal),
 total numeric(18,2) GENERATED ALWAYS AS (subtotal - discount) STORED,
 encrypted_shipping_address bytea NOT NULL, confirmed_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE commerce.order_items (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), order_id uuid NOT NULL REFERENCES commerce.orders,
 sku_id uuid NOT NULL REFERENCES commerce.skus, quantity integer NOT NULL CHECK (quantity > 0),
 unit_price numeric(18,2) NOT NULL CHECK (unit_price >= 0),
 discount numeric(18,2) NOT NULL DEFAULT 0 CHECK (discount >= 0 AND discount <= unit_price * quantity),
 promotion_id uuid REFERENCES commerce.promotions,
 line_total numeric(18,2) GENERATED ALWAYS AS (unit_price * quantity - discount) STORED
);
CREATE TABLE improvement.feedback (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), conversation_id uuid NOT NULL REFERENCES conversation.conversations,
 message_id uuid REFERENCES conversation.messages, actor_id text NOT NULL,
 rating smallint CHECK (rating BETWEEN 1 AND 5), category text NOT NULL, comment text,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE improvement.proposals (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_message_id uuid REFERENCES conversation.messages,
 kind text NOT NULL CHECK (kind IN ('knowledge_gap','exemplar','policy_correction')),
 candidate jsonb NOT NULL, status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
 reviewed_by text, reviewed_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR
        (status <> 'pending' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);
CREATE TABLE improvement.outbox (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_type text NOT NULL, aggregate_id uuid NOT NULL,
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz
);
CREATE INDEX unpublished_events ON improvement.outbox(created_at) WHERE published_at IS NULL;

-- Evaluation-only fixtures. Never expose these tables to the agent's DB role.
CREATE TABLE evaluation.datasets (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, version text NOT NULL,
 manifest_sha256 char(64) NOT NULL, imported_at timestamptz NOT NULL DEFAULT now(), UNIQUE (name, version)
);
CREATE TABLE evaluation.fixtures (
 dataset_id uuid NOT NULL REFERENCES evaluation.datasets, kind text NOT NULL,
 external_id text NOT NULL, payload jsonb NOT NULL,
 PRIMARY KEY (dataset_id, kind, external_id)
);
CREATE TABLE evaluation.runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id uuid NOT NULL REFERENCES evaluation.datasets,
 mode text NOT NULL CHECK (mode IN ('baseline','harness')), round integer NOT NULL CHECK (round >= 0),
 model text NOT NULL, temperature numeric NOT NULL, config_sha256 char(64) NOT NULL,
 tools_sha256 char(64) NOT NULL, prompt_sha256 char(64) NOT NULL,
 started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz
);
CREATE TABLE evaluation.results (
 run_id uuid NOT NULL REFERENCES evaluation.runs, scenario_id text NOT NULL,
 call_index integer NOT NULL CHECK (call_index BETWEEN 1 AND 3),
 assertions jsonb NOT NULL, runtime_signals jsonb NOT NULL,
 metrics jsonb NOT NULL, PRIMARY KEY (run_id, scenario_id, call_index)
);
COMMIT;
