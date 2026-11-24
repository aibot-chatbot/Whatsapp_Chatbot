-- 093: add an existing OpenRouter key to the Client pool and record who added it.
-- Apply after 089. Rollback: 093_openrouter_key_add_rollback.sql.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

-- Imported keys can wait for their first Client across empty-key retirement runs.
ALTER TABLE public.openrouter_client_keys
    ADD COLUMN awaiting_first_client boolean NOT NULL DEFAULT false;

CREATE FUNCTION public.mark_openrouter_key_assigned() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public, pg_temp
AS $$
BEGIN
    UPDATE public.openrouter_client_keys SET awaiting_first_client = false
        WHERE id = NEW.key_id AND awaiting_first_client;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.mark_openrouter_key_assigned() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.mark_openrouter_key_assigned() TO service_role;
CREATE TRIGGER mark_openrouter_key_assigned
    AFTER INSERT OR UPDATE OF key_id ON public.openrouter_key_assignments
    FOR EACH ROW EXECUTE FUNCTION public.mark_openrouter_key_assigned();

CREATE FUNCTION public.add_openrouter_client_key(
    p_key_hash text, p_encrypted_key text, p_label text, p_max_clients integer, p_actor_id bigint
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $$
DECLARE
    new_id bigint;
BEGIN
    PERFORM 1 FROM public.platform_admin_users
        WHERE id = p_actor_id AND is_active AND platform_role = 'super_admin' FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Super Admin access is required.' USING ERRCODE = 'PT403';
    END IF;
    IF p_max_clients IS NULL OR p_max_clients NOT BETWEEN 1 AND 20 THEN
        RAISE EXCEPTION 'Enter a whole number from 1 to 20.' USING ERRCODE = 'PT400';
    END IF;
    IF p_label IS NULL OR p_label !~ '^sk-or-v1-[0-9a-f]{3}\.\.\.[0-9a-f]{4}$' THEN
        RAISE EXCEPTION 'Invalid masked key label.' USING ERRCODE = 'PT400';
    END IF;

    INSERT INTO public.openrouter_client_keys
        (key_hash, encrypted_key, label, status, max_clients, awaiting_first_client)
        VALUES (p_key_hash, p_encrypted_key, p_label, 'active', p_max_clients, true)
        ON CONFLICT (key_hash) DO NOTHING RETURNING id INTO new_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'This key is already in the pool.' USING ERRCODE = 'PT409';
    END IF;

    INSERT INTO public.platform_admin_audit_events
        (platform_admin_user_id, action, resource_type, resource_id, metadata)
        VALUES (p_actor_id, 'platform_admin.openrouter_key.add', 'openrouter_client_keys',
                new_id::text, jsonb_build_object(
                    'endpoint', '/api/platform-admin/openrouter-keys',
                    'http_method', 'POST', 'outcome', 'success',
                    'masked_label', p_label, 'max_clients', p_max_clients));
    RETURN new_id;
END;
$$;

REVOKE ALL ON FUNCTION public.add_openrouter_client_key(text, text, text, integer, bigint)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.add_openrouter_client_key(text, text, text, integer, bigint)
    TO service_role;
COMMIT;
