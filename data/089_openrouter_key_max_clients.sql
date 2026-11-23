BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.openrouter_client_keys
    ADD COLUMN max_clients smallint NOT NULL DEFAULT 20
    CONSTRAINT openrouter_client_keys_max_clients_check CHECK (max_clients BETWEEN 1 AND 20);

CREATE FUNCTION public.set_openrouter_key_max_clients(
    p_key_id bigint, p_max_clients integer, p_actor_id bigint
) RETURNS smallint
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    previous_limit smallint;
    old_status text;
BEGIN
    PERFORM 1 FROM public.platform_admin_users
        WHERE id = p_actor_id AND is_active AND platform_role = 'super_admin' FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Super Admin access is required.' USING ERRCODE = 'PT403';
    END IF;
    IF p_max_clients IS NULL OR p_max_clients NOT BETWEEN 1 AND 20 THEN
        RAISE EXCEPTION 'Enter a whole number from 1 to 20.' USING ERRCODE = 'PT400';
    END IF;
    SELECT max_clients, status INTO previous_limit, old_status FROM public.openrouter_client_keys
        WHERE id = p_key_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'The selected key no longer exists.' USING ERRCODE = 'PT404';
    END IF;
    IF old_status <> 'active' THEN
        RAISE EXCEPTION 'Key is unavailable.' USING ERRCODE = 'PT409';
    END IF;

    UPDATE public.openrouter_client_keys SET max_clients = p_max_clients WHERE id = p_key_id;
    INSERT INTO public.platform_admin_audit_events
        (platform_admin_user_id, action, resource_type, resource_id, metadata)
        VALUES (p_actor_id, 'platform_admin.openrouter_key.set_max_clients', 'openrouter_client_keys',
                p_key_id::text, jsonb_build_object(
                    'endpoint', '/api/platform-admin/openrouter-keys/<key_id>/max-clients',
                    'http_method', 'PATCH', 'outcome', 'success',
                    'previous_max_clients', previous_limit, 'max_clients', p_max_clients));
    RETURN previous_limit;
END;
$$;

REVOKE ALL ON FUNCTION public.set_openrouter_key_max_clients(bigint, integer, bigint)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_openrouter_key_max_clients(bigint, integer, bigint)
    TO service_role;

CREATE OR REPLACE FUNCTION public.replace_openrouter_client_key(
    p_old_id bigint, p_hash text, p_encrypted text, p_label text, p_actor_id bigint, p_reason text
) RETURNS bigint[]
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    new_id bigint;
    moved_ids bigint[];
BEGIN
    PERFORM 1 FROM public.platform_admin_users
        WHERE id = p_actor_id AND is_active AND platform_role = 'super_admin' FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Super Admin access is required.';
    END IF;
    IF p_label IS NULL OR p_label !~ '^sk-or-v1-[0-9a-f]{3}\.\.\.[0-9a-f]{4}$'
        OR p_reason IS NULL OR length(btrim(p_reason)) NOT BETWEEN 1 AND 240
        OR p_reason ~* 'sk-or-' THEN
        RAISE EXCEPTION 'Invalid replacement details.';
    END IF;
    PERFORM 1 FROM public.openrouter_client_keys
        WHERE id = p_old_id AND disabled_reason IS DISTINCT FROM 'manual_replacement' FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Key is unavailable for replacement.';
    END IF;

    INSERT INTO public.openrouter_client_keys (key_hash, encrypted_key, label, max_clients)
        SELECT p_hash, p_encrypted, p_label, max_clients FROM public.openrouter_client_keys
        WHERE id = p_old_id RETURNING id INTO new_id;
    WITH moved AS (
        UPDATE public.openrouter_key_assignments SET key_id = new_id
        WHERE key_id = p_old_id RETURNING company_id
    )
    SELECT coalesce(array_agg(company_id), '{}'::bigint[]) INTO moved_ids FROM moved;
    UPDATE public.openrouter_client_keys
        SET status = 'disabled', disabled_reason = 'manual_replacement', replacement_reason = p_reason
        WHERE id = p_old_id;

    INSERT INTO public.platform_admin_audit_events
        (platform_admin_user_id, action, resource_type, resource_id, metadata)
        VALUES (p_actor_id, 'platform_admin.openrouter_key.replace', 'openrouter_client_keys',
                p_old_id::text, jsonb_build_object(
                    'endpoint', '/api/platform-admin/openrouter-keys/<key_id>/replace',
                    'http_method', 'POST', 'outcome', 'success',
                    'replacement_id', new_id, 'masked_label', p_label));
    RETURN moved_ids;
END;
$$;

COMMIT;
