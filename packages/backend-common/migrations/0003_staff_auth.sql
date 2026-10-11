BEGIN;
CREATE TABLE identity.staff_users (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), username text NOT NULL UNIQUE, password_hash text NOT NULL,
 role text NOT NULL CHECK (role IN ('agent','admin','seller','developer')), active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE identity.audit_logs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor_id text NOT NULL, action text NOT NULL,
 resource_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
COMMIT;
