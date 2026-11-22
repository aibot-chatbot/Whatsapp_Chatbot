BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.openrouter_client_keys
    DROP CONSTRAINT openrouter_client_keys_disabled_reason_check,
    ADD CONSTRAINT openrouter_client_keys_disabled_reason_check
        CHECK (disabled_reason IN ('ours', 'openrouter', 'manual_replacement')),
    ADD COLUMN replacement_reason text,
    ADD CONSTRAINT openrouter_manual_replacement_is_final CHECK (
        replacement_reason IS NULL OR
        (status = 'disabled' AND disabled_reason IS NOT DISTINCT FROM 'manual_replacement')
    );

-- One transaction prevents a database or audit failure from stranding part of a Client group.
CREATE FUNCTION public.replace_openrouter_client_key(
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

    INSERT INTO public.openrouter_client_keys (key_hash, encrypted_key, label)
        VALUES (p_hash, p_encrypted, p_label) RETURNING id INTO new_id;
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

REVOKE ALL ON FUNCTION public.replace_openrouter_client_key(bigint, text, text, text, bigint, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.replace_openrouter_client_key(bigint, text, text, text, bigint, text)
    TO service_role;
COMMIT;
