-- 043_atomic_platform_support_case_creation.sql
-- MIGRATION DRAFT ONLY. Do not apply without approved executor, environment,
-- privacy, retention, rollback, and production-readiness approvals.
-- Makes initial platform support-case creation atomic with its first event and audit entry.

CREATE OR REPLACE FUNCTION public.create_platform_support_case(
    p_company_id BIGINT,
    p_platform_admin_user_id BIGINT,
    p_title TEXT,
    p_redacted_summary TEXT,
    p_status TEXT,
    p_priority TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_case public.platform_support_cases%ROWTYPE;
    v_event public.platform_support_case_events%ROWTYPE;
    v_audit public.platform_admin_audit_events%ROWTYPE;
    v_title TEXT;
    v_redacted_summary TEXT;
    v_now TIMESTAMPTZ := pg_catalog.now();
BEGIN
    PERFORM public.require_active_platform_admin_mapping(p_platform_admin_user_id);

    IF p_company_id IS NULL OR p_company_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid company ID';
    END IF;
    PERFORM 1
        FROM public.companies
        WHERE id = p_company_id
        FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Company not found';
    END IF;

    v_title := pg_catalog.btrim(p_title);
    v_redacted_summary := pg_catalog.btrim(p_redacted_summary);
    IF v_title IS NULL OR pg_catalog.char_length(v_title) < 1 OR pg_catalog.char_length(v_title) > 160 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid support case title';
    END IF;
    IF v_redacted_summary IS NULL
       OR pg_catalog.char_length(v_redacted_summary) < 1
       OR pg_catalog.char_length(v_redacted_summary) > 2000 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid support case summary';
    END IF;
    IF p_status IS NULL OR p_status NOT IN ('open', 'in_progress', 'waiting_for_tenant', 'resolved', 'closed') THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Unsupported support case status';
    END IF;
    IF p_priority IS NULL OR p_priority NOT IN ('low', 'normal', 'high', 'urgent') THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Unsupported support case priority';
    END IF;

    INSERT INTO public.platform_support_cases (
        company_id,
        created_by_platform_admin_user_id,
        status,
        priority,
        title,
        redacted_summary,
        created_at,
        updated_at,
        closed_at
    ) VALUES (
        p_company_id,
        p_platform_admin_user_id,
        p_status,
        p_priority,
        v_title,
        v_redacted_summary,
        v_now,
        v_now,
        CASE WHEN p_status = 'closed' THEN v_now ELSE NULL END
    )
    RETURNING * INTO v_case;

    INSERT INTO public.platform_support_case_events (
        case_id,
        event_type,
        actor_platform_admin_user_id,
        new_status,
        new_priority,
        created_at
    ) VALUES (
        v_case.id,
        'created',
        p_platform_admin_user_id,
        p_status,
        p_priority,
        v_now
    )
    RETURNING * INTO v_event;

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id,
        action,
        resource_type,
        resource_id,
        metadata,
        created_at
    ) VALUES (
        p_platform_admin_user_id,
        'platform_admin.support_case.create',
        'platform_support_cases',
        v_case.id::TEXT,
        pg_catalog.jsonb_build_object(
            'outcome', 'success',
            'endpoint', '/api/platform-admin/support-cases',
            'http_method', 'POST',
            'company_id', p_company_id,
            'status', p_status,
            'priority', p_priority
        ),
        v_now
    )
    RETURNING * INTO v_audit;

    RETURN pg_catalog.jsonb_build_object(
        'case', pg_catalog.to_jsonb(v_case),
        'event', pg_catalog.to_jsonb(v_event),
        'audit', pg_catalog.to_jsonb(v_audit)
    );
END;
$function$;

REVOKE ALL ON FUNCTION public.create_platform_support_case(BIGINT, BIGINT, TEXT, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.create_platform_support_case(BIGINT, BIGINT, TEXT, TEXT, TEXT, TEXT)
    TO service_role;
