-- 081: separate OpenRouter keys for groups of Clients.
--
--   openrouter_client_keys       one row per key. key_hash is OpenRouter's public id for the key.
--                                encrypted_key is a Fernet token; the master key that opens it
--                                lives only in Fly secrets, so a database leak alone exposes nothing.
--   openrouter_key_assignments   which key each Client uses. company_id is the primary key, so a
--                                Client has exactly one key, and two racing first calls cannot
--                                create two rows. The cascade frees the slot when a Client is
--                                deleted, so delete_company_account() needs no change.
--
-- Both tables are for the service role only. Row level security is on with no policies, and the
-- client roles lose their default grants, so the browser API can never read a key.
--
-- Not applied by this file's author. Apply BEFORE setting OPENROUTER_CLIENT_KEYS_ENABLED=true.
-- With the setting off, no code reads these tables. Rollback:
-- 081_openrouter_client_keys_rollback.sql.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.openrouter_client_keys (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key_hash text NOT NULL UNIQUE,
    encrypted_key text NOT NULL,
    label text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.openrouter_key_assignments (
    company_id bigint PRIMARY KEY REFERENCES public.companies(id) ON DELETE CASCADE,
    key_id bigint NOT NULL REFERENCES public.openrouter_client_keys(id),
    assigned_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX openrouter_key_assignments_key_id_idx ON public.openrouter_key_assignments (key_id);

ALTER TABLE public.openrouter_client_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.openrouter_key_assignments ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.openrouter_client_keys FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.openrouter_key_assignments FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.openrouter_client_keys_id_seq FROM PUBLIC, anon, authenticated;

-- Required: on this database a new table gives service_role no read or write access.
GRANT SELECT, INSERT, UPDATE ON public.openrouter_client_keys TO service_role;
GRANT SELECT, INSERT ON public.openrouter_key_assignments TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.openrouter_client_keys_id_seq TO service_role;

COMMIT;
