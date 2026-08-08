-- 036_platform_admin_company_suspension.sql
-- DRAFT ONLY. Do not apply without approved executor, environment,
-- rollback, and production-readiness approvals.
-- Adds the database-authoritative company suspension foundation for
-- platform-admin tenant/company administration.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.companies
        WHERE status IS NULL
           OR status NOT IN ('active', 'inactive')
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'companies.status contains values outside active/inactive';
    END IF;
END;
$$;

ALTER TABLE public.companies
    ALTER COLUMN status SET DEFAULT 'active',
    ALTER COLUMN status SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint AS con
        JOIN pg_catalog.pg_class AS rel
          ON rel.oid = con.conrelid
        JOIN pg_catalog.pg_namespace AS nsp
          ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = 'public'
          AND rel.relname = 'companies'
          AND con.conname = 'companies_status_check'
    ) THEN
        ALTER TABLE public.companies
            ADD CONSTRAINT companies_status_check
            CHECK (status IN ('active', 'inactive'));
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.suspend_platform_company(
    p_actor_platform_admin_user_id BIGINT,
    p_company_id BIGINT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_company public.companies%ROWTYPE;
    v_old_status TEXT;
    v_audit public.platform_admin_audit_events%ROWTYPE;
    v_now TIMESTAMPTZ := pg_catalog.now();
BEGIN
    IF p_actor_platform_admin_user_id IS NULL OR p_actor_platform_admin_user_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid platform-admin actor ID';
    END IF;
    IF p_company_id IS NULL OR p_company_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid company ID';
    END IF;

    PERFORM public.require_active_platform_admin_mapping(p_actor_platform_admin_user_id);

    SELECT * INTO v_company
    FROM public.companies
    WHERE id = p_company_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Company not found';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.platform_admin_protected_companies
        WHERE company_id = p_company_id
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Protected platform-admin company cannot be suspended';
    END IF;

    IF v_company.status IS DISTINCT FROM 'active' THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Company status is unchanged';
    END IF;

    v_old_status := v_company.status;

    UPDATE public.companies
    SET
        status = 'inactive',
        updated_at = v_now
    WHERE id = p_company_id
    RETURNING * INTO v_company;

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id,
        action,
        resource_type,
        resource_id,
        metadata,
        created_at
    ) VALUES (
        p_actor_platform_admin_user_id,
        'platform_admin.company.suspend',
        'company',
        p_company_id::TEXT,
        pg_catalog.jsonb_build_object(
            'endpoint', '/api/platform-admin/companies/<company_id>/suspend',
            'http_method', 'POST',
            'outcome', 'success',
            'company_id', p_company_id,
            'old_status', v_old_status,
            'new_status', 'inactive'
        ),
        v_now
    )
    RETURNING * INTO v_audit;

    RETURN pg_catalog.jsonb_build_object(
        'company', pg_catalog.jsonb_build_object(
            'id', v_company.id,
            'old_status', v_old_status,
            'new_status', v_company.status,
            'updated_at', v_company.updated_at
        ),
        'audit_event', pg_catalog.to_jsonb(v_audit)
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.restore_platform_company(
    p_actor_platform_admin_user_id BIGINT,
    p_company_id BIGINT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_company public.companies%ROWTYPE;
    v_old_status TEXT;
    v_audit public.platform_admin_audit_events%ROWTYPE;
    v_now TIMESTAMPTZ := pg_catalog.now();
BEGIN
    IF p_actor_platform_admin_user_id IS NULL OR p_actor_platform_admin_user_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid platform-admin actor ID';
    END IF;
    IF p_company_id IS NULL OR p_company_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid company ID';
    END IF;

    PERFORM public.require_active_platform_admin_mapping(p_actor_platform_admin_user_id);

    SELECT * INTO v_company
    FROM public.companies
    WHERE id = p_company_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Company not found';
    END IF;

    IF v_company.status IS DISTINCT FROM 'inactive' THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Company status is unchanged';
    END IF;

    v_old_status := v_company.status;

    UPDATE public.companies
    SET
        status = 'active',
        updated_at = v_now
    WHERE id = p_company_id
    RETURNING * INTO v_company;

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id,
        action,
        resource_type,
        resource_id,
        metadata,
        created_at
    ) VALUES (
        p_actor_platform_admin_user_id,
        'platform_admin.company.restore',
        'company',
        p_company_id::TEXT,
        pg_catalog.jsonb_build_object(
            'endpoint', '/api/platform-admin/companies/<company_id>/restore',
            'http_method', 'POST',
            'outcome', 'success',
            'company_id', p_company_id,
            'old_status', v_old_status,
            'new_status', 'active'
        ),
        v_now
    )
    RETURNING * INTO v_audit;

    RETURN pg_catalog.jsonb_build_object(
        'company', pg_catalog.jsonb_build_object(
            'id', v_company.id,
            'old_status', v_old_status,
            'new_status', v_company.status,
            'updated_at', v_company.updated_at
        ),
        'audit_event', pg_catalog.to_jsonb(v_audit)
    );
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.suspend_platform_company(BIGINT, BIGINT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.restore_platform_company(BIGINT, BIGINT)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.suspend_platform_company(BIGINT, BIGINT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.restore_platform_company(BIGINT, BIGINT)
    TO service_role;

REVOKE ALL ON public.companies FROM PUBLIC, anon, authenticated;
REVOKE DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.companies FROM service_role;
GRANT SELECT, INSERT, UPDATE ON public.companies TO service_role;

DO $$
BEGIN
    IF pg_catalog.to_regclass('public.companies_id_seq') IS NOT NULL THEN
        REVOKE ALL ON SEQUENCE public.companies_id_seq FROM PUBLIC, anon, authenticated;
        GRANT USAGE ON SEQUENCE public.companies_id_seq TO service_role;
    END IF;
END;
$$;
