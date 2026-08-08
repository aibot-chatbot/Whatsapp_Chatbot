-- 031_tenant_support_review_conversion.sql
-- MIGRATION DRAFT ONLY. Do not apply without approved executor, environment,
-- privacy, retention, rollback, and production-readiness approvals.
-- This draft does not modify platform_admin_users mappings or tenant audit rows.
-- Future runtime must add the three tenant-support actions below to the
-- platform-admin audit allowlist and metadata schema before calling these RPCs.

ALTER TABLE public.tenant_support_requests
    ADD COLUMN IF NOT EXISTS converted_platform_support_case_id BIGINT NULL;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint
        WHERE conname = 'tenant_support_requests_converted_case_fkey'
          AND conrelid = 'public.tenant_support_requests'::pg_catalog.regclass
    ) THEN
        ALTER TABLE public.tenant_support_requests
            ADD CONSTRAINT tenant_support_requests_converted_case_fkey
            FOREIGN KEY (converted_platform_support_case_id)
            REFERENCES public.platform_support_cases(id)
            ON DELETE RESTRICT;
    END IF;
END;
$migration$;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint
        WHERE conname = 'tenant_support_requests_converted_case_status_check'
          AND conrelid = 'public.tenant_support_requests'::pg_catalog.regclass
    ) THEN
        ALTER TABLE public.tenant_support_requests
            ADD CONSTRAINT tenant_support_requests_converted_case_status_check
            CHECK (
                converted_platform_support_case_id IS NULL
                OR status = 'converted'
            );
    END IF;
END;
$migration$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_tenant_support_requests_converted_case
    ON public.tenant_support_requests (converted_platform_support_case_id)
    WHERE converted_platform_support_case_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.set_tenant_support_request_status(
    p_request_id BIGINT,
    p_platform_admin_user_id BIGINT,
    p_status TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_old_status TEXT;
    v_closed_at TIMESTAMPTZ;
    v_action TEXT;
    v_event_type TEXT;
    v_now TIMESTAMPTZ := pg_catalog.now();
BEGIN
    IF p_request_id IS NULL OR p_request_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid tenant support request ID';
    END IF;
    IF p_platform_admin_user_id IS NULL OR p_platform_admin_user_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid platform-admin user ID';
    END IF;
    IF p_status IS NULL OR p_status NOT IN ('reviewed', 'closed') THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Unsupported tenant support request status';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.platform_admin_users
        WHERE id = p_platform_admin_user_id
          AND is_active = TRUE
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Active platform-admin mapping is required';
    END IF;

    SELECT status, closed_at
    INTO v_old_status, v_closed_at
    FROM public.tenant_support_requests
    WHERE id = p_request_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Tenant support request not found';
    END IF;
    IF v_old_status = 'converted' OR v_old_status = 'closed' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Tenant support request status cannot be changed';
    END IF;
    IF p_status = v_old_status THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Tenant support request status is unchanged';
    END IF;
    IF p_status = 'reviewed' AND v_old_status <> 'new' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Tenant support request transition is not allowed';
    END IF;
    IF p_status = 'closed' AND v_old_status NOT IN ('new', 'reviewed') THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Tenant support request transition is not allowed';
    END IF;

    v_event_type := p_status;
    v_action := CASE p_status
        WHEN 'reviewed' THEN 'platform_admin.tenant_support_request.review'
        ELSE 'platform_admin.tenant_support_request.close'
    END;
    IF p_status = 'closed' THEN
        v_closed_at := v_now;
    ELSE
        v_closed_at := NULL;
    END IF;

    UPDATE public.tenant_support_requests
    SET status = p_status,
        updated_at = v_now,
        closed_at = v_closed_at
    WHERE id = p_request_id;

    INSERT INTO public.tenant_support_request_events (
        request_id, event_type, actor_user_id,
        actor_platform_admin_user_id, actor_type, created_at
    ) VALUES (
        p_request_id, v_event_type, NULL,
        p_platform_admin_user_id, 'platform_admin', v_now
    );

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id, action, resource_type, resource_id, metadata, created_at
    ) VALUES (
        p_platform_admin_user_id,
        v_action,
        'tenant_support_requests',
        p_request_id::TEXT,
        pg_catalog.jsonb_build_object(
            'endpoint', '/api/platform-admin/tenant-support-requests/<request_id>',
            'http_method', 'PATCH',
            'outcome', 'success',
            'old_status', v_old_status,
            'new_status', p_status
        ),
        v_now
    );

    RETURN pg_catalog.jsonb_build_object(
        'request_id', p_request_id,
        'status', p_status,
        'old_status', v_old_status
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.convert_tenant_support_request(
    p_request_id BIGINT,
    p_platform_admin_user_id BIGINT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_company_id BIGINT;
    v_requester_user_id BIGINT;
    v_status TEXT;
    v_title TEXT;
    v_redacted_description TEXT;
    v_existing_case_id BIGINT;
    v_case_id BIGINT;
    v_now TIMESTAMPTZ := pg_catalog.now();
BEGIN
    IF p_request_id IS NULL OR p_request_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid tenant support request ID';
    END IF;
    IF p_platform_admin_user_id IS NULL OR p_platform_admin_user_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid platform-admin user ID';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.platform_admin_users
        WHERE id = p_platform_admin_user_id
          AND is_active = TRUE
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Active platform-admin mapping is required';
    END IF;

    SELECT company_id, requester_user_id, status, title,
           redacted_description, converted_platform_support_case_id
    INTO v_company_id, v_requester_user_id, v_status, v_title,
         v_redacted_description, v_existing_case_id
    FROM public.tenant_support_requests
    WHERE id = p_request_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Tenant support request not found';
    END IF;
    IF v_existing_case_id IS NOT NULL OR v_status = 'converted' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Tenant support request is already converted';
    END IF;
    IF v_status NOT IN ('new', 'reviewed') THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Tenant support request cannot be converted';
    END IF;

    INSERT INTO public.platform_support_cases (
        company_id,
        created_by_platform_admin_user_id,
        status,
        priority,
        title,
        redacted_summary,
        created_at,
        updated_at
    ) VALUES (
        v_company_id,
        p_platform_admin_user_id,
        'open',
        'normal',
        v_title,
        v_redacted_description,
        v_now,
        v_now
    )
    RETURNING id INTO v_case_id;

    INSERT INTO public.platform_support_case_events (
        case_id, event_type, actor_platform_admin_user_id,
        new_status, new_priority, created_at
    ) VALUES (
        v_case_id, 'created', p_platform_admin_user_id,
        'open', 'normal', v_now
    );

    UPDATE public.tenant_support_requests
    SET status = 'converted',
        converted_platform_support_case_id = v_case_id,
        updated_at = v_now,
        closed_at = NULL
    WHERE id = p_request_id;

    INSERT INTO public.tenant_support_request_events (
        request_id, event_type, actor_user_id,
        actor_platform_admin_user_id, actor_type, created_at
    ) VALUES (
        p_request_id, 'converted', NULL,
        p_platform_admin_user_id, 'platform_admin', v_now
    );

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id, action, resource_type, resource_id, metadata, created_at
    ) VALUES (
        p_platform_admin_user_id,
        'platform_admin.tenant_support_request.convert',
        'tenant_support_requests',
        p_request_id::TEXT,
        pg_catalog.jsonb_build_object(
            'endpoint', '/api/platform-admin/tenant-support-requests/<request_id>/convert',
            'http_method', 'POST',
            'outcome', 'success',
            'old_status', v_status,
            'new_status', 'converted',
            'converted_platform_support_case_id', v_case_id
        ),
        v_now
    );

    RETURN pg_catalog.jsonb_build_object(
        'request_id', p_request_id,
        'status', 'converted',
        'converted_platform_support_case_id', v_case_id
    );
END;
$function$;

REVOKE ALL ON FUNCTION public.set_tenant_support_request_status(
    BIGINT, BIGINT, TEXT
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.set_tenant_support_request_status(
    BIGINT, BIGINT, TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.convert_tenant_support_request(
    BIGINT, BIGINT
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.convert_tenant_support_request(
    BIGINT, BIGINT
) TO service_role;
