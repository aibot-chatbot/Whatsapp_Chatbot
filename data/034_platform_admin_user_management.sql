-- 034_platform_admin_user_management.sql
-- MIGRATION DRAFT ONLY. Do not apply without approved executor, environment,
-- privacy, rollback, bootstrap, and production-readiness approvals.
-- Adds the database-authoritative security foundation for platform-admin user
-- management. This migration intentionally does not seed any protected company.

CREATE TABLE IF NOT EXISTS public.platform_admin_protected_companies (
    company_id BIGINT PRIMARY KEY
        REFERENCES public.companies(id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id BIGINT NULL
        REFERENCES public.users(id)
        ON UPDATE RESTRICT
        ON DELETE SET NULL
);

COMMENT ON TABLE public.platform_admin_protected_companies IS
    'Database-authoritative registry of companies allowed to contain platform-admin identities. Rows are migration/bootstrap controlled, not application-managed.';

COMMENT ON COLUMN public.platform_admin_protected_companies.company_id IS
    'Protected internal company ID. Do not hardcode environment-specific IDs in RPCs or application code.';

ALTER TABLE public.platform_admin_protected_companies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS platform_admin_protected_companies_service_select
    ON public.platform_admin_protected_companies;
CREATE POLICY platform_admin_protected_companies_service_select
    ON public.platform_admin_protected_companies
    FOR SELECT
    TO service_role
    USING (TRUE);

REVOKE ALL ON public.platform_admin_protected_companies
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.platform_admin_protected_companies
    TO service_role;

CREATE OR REPLACE FUNCTION public.create_platform_admin_user_mapping(
    p_actor_platform_admin_user_id BIGINT,
    p_target_user_id BIGINT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_actor public.platform_admin_users%ROWTYPE;
    v_target_user public.users%ROWTYPE;
    v_existing_mapping_id BIGINT;
    v_new_mapping public.platform_admin_users%ROWTYPE;
    v_audit public.platform_admin_audit_events%ROWTYPE;
    v_now TIMESTAMPTZ := pg_catalog.now();
BEGIN
    IF p_actor_platform_admin_user_id IS NULL OR p_actor_platform_admin_user_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid platform-admin actor ID';
    END IF;
    IF p_target_user_id IS NULL OR p_target_user_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid target user ID';
    END IF;

    LOCK TABLE public.platform_admin_users IN SHARE ROW EXCLUSIVE MODE;

    PERFORM public.require_active_platform_admin_mapping(p_actor_platform_admin_user_id);

    SELECT * INTO v_actor
    FROM public.platform_admin_users
    WHERE id = p_actor_platform_admin_user_id
      AND is_active = TRUE
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Active platform-admin mapping is required';
    END IF;

    SELECT * INTO v_target_user
    FROM public.users
    WHERE id = p_target_user_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Target user not found';
    END IF;
    IF v_target_user.status IS DISTINCT FROM 'active' THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Target user must be active';
    END IF;
    IF v_target_user.company_id IS NULL THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Target user must belong to a protected company';
    END IF;

    PERFORM 1
    FROM public.platform_admin_protected_companies
    WHERE company_id = v_target_user.company_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Target user must belong to a protected company';
    END IF;

    SELECT id INTO v_existing_mapping_id
    FROM public.platform_admin_users
    WHERE user_id = p_target_user_id
    FOR UPDATE;

    IF FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '23505', MESSAGE = 'Platform-admin mapping already exists';
    END IF;

    INSERT INTO public.platform_admin_users (
        user_id,
        is_active,
        created_by_user_id
    ) VALUES (
        p_target_user_id,
        TRUE,
        v_actor.user_id
    )
    RETURNING * INTO v_new_mapping;

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id,
        action,
        resource_type,
        resource_id,
        metadata,
        created_at
    ) VALUES (
        p_actor_platform_admin_user_id,
        'platform_admin.user.create',
        'platform_admin_users',
        v_new_mapping.id::TEXT,
        pg_catalog.jsonb_build_object(
            'endpoint', '/api/platform-admin/users',
            'http_method', 'POST',
            'outcome', 'success',
            'target_platform_admin_user_id', v_new_mapping.id,
            'target_user_id', p_target_user_id,
            'old_is_active', NULL,
            'new_is_active', TRUE
        ),
        v_now
    )
    RETURNING * INTO v_audit;

    RETURN pg_catalog.jsonb_build_object(
        'platform_admin_user', pg_catalog.to_jsonb(v_new_mapping),
        'audit_event', pg_catalog.to_jsonb(v_audit)
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.set_platform_admin_user_active(
    p_actor_platform_admin_user_id BIGINT,
    p_target_platform_admin_user_id BIGINT,
    p_is_active BOOLEAN
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_actor public.platform_admin_users%ROWTYPE;
    v_target public.platform_admin_users%ROWTYPE;
    v_target_user public.users%ROWTYPE;
    v_active_count BIGINT;
    v_audit public.platform_admin_audit_events%ROWTYPE;
    v_action TEXT;
    v_now TIMESTAMPTZ := pg_catalog.now();
BEGIN
    IF p_actor_platform_admin_user_id IS NULL OR p_actor_platform_admin_user_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid platform-admin actor ID';
    END IF;
    IF p_target_platform_admin_user_id IS NULL OR p_target_platform_admin_user_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid target platform-admin user ID';
    END IF;
    IF p_is_active IS NULL THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid active state';
    END IF;
    IF p_actor_platform_admin_user_id = p_target_platform_admin_user_id
        AND p_is_active = FALSE
    THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Self-deactivation is not allowed';
    END IF;

    LOCK TABLE public.platform_admin_users IN SHARE ROW EXCLUSIVE MODE;

    PERFORM public.require_active_platform_admin_mapping(p_actor_platform_admin_user_id);

    SELECT * INTO v_actor
    FROM public.platform_admin_users
    WHERE id = p_actor_platform_admin_user_id
      AND is_active = TRUE
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Active platform-admin mapping is required';
    END IF;

    SELECT * INTO v_target
    FROM public.platform_admin_users
    WHERE id = p_target_platform_admin_user_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Platform-admin mapping not found';
    END IF;
    IF v_target.is_active = p_is_active THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Platform-admin mapping active state is unchanged';
    END IF;

    SELECT * INTO v_target_user
    FROM public.users
    WHERE id = v_target.user_id
    FOR UPDATE;

    IF p_is_active = TRUE THEN
        IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Target user not found';
        END IF;
        IF v_target_user.status IS DISTINCT FROM 'active' THEN
            RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Target user must be active';
        END IF;
        IF v_target_user.company_id IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Target user must belong to a protected company';
        END IF;
        PERFORM 1
        FROM public.platform_admin_protected_companies
        WHERE company_id = v_target_user.company_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Target user must belong to a protected company';
        END IF;
    ELSE
        SELECT COUNT(*) INTO v_active_count
        FROM public.platform_admin_users
        WHERE is_active = TRUE;

        IF v_active_count <= 1 THEN
            RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'At least one active platform-admin mapping is required';
        END IF;
    END IF;

    UPDATE public.platform_admin_users
    SET
        is_active = p_is_active,
        updated_at = v_now
    WHERE id = p_target_platform_admin_user_id
    RETURNING * INTO v_target;

    v_action := CASE
        WHEN p_is_active = TRUE THEN 'platform_admin.user.activate'
        ELSE 'platform_admin.user.deactivate'
    END;

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id,
        action,
        resource_type,
        resource_id,
        metadata,
        created_at
    ) VALUES (
        p_actor_platform_admin_user_id,
        v_action,
        'platform_admin_users',
        p_target_platform_admin_user_id::TEXT,
        pg_catalog.jsonb_build_object(
            'endpoint', '/api/platform-admin/users/<platform_admin_user_id>/active',
            'http_method', 'PATCH',
            'outcome', 'success',
            'target_platform_admin_user_id', p_target_platform_admin_user_id,
            'target_user_id', v_target.user_id,
            'old_is_active', NOT p_is_active,
            'new_is_active', p_is_active
        ),
        v_now
    )
    RETURNING * INTO v_audit;

    RETURN pg_catalog.jsonb_build_object(
        'platform_admin_user', pg_catalog.to_jsonb(v_target),
        'audit_event', pg_catalog.to_jsonb(v_audit)
    );
END;
$function$;

REVOKE ALL ON FUNCTION public.create_platform_admin_user_mapping(BIGINT, BIGINT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.set_platform_admin_user_active(BIGINT, BIGINT, BOOLEAN)
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.create_platform_admin_user_mapping(BIGINT, BIGINT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.set_platform_admin_user_active(BIGINT, BIGINT, BOOLEAN)
    TO service_role;
