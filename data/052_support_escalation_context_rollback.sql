-- Reverses 052_support_escalation_context.sql back to the migration 030 shape.
--
-- DESTRUCTIVE: dropping escalation_context discards every trail collected
-- since 052 was applied. Read them out first if they still matter.
--
-- Rolling back also narrows the two CHECK constraints again, so any row written
-- with priority 'low'/'urgent' or source 'faq_dead_end'/'direct' must be reset
-- first or the ALTER TABLE will fail. The two UPDATEs below do that, and they
-- lose information: an urgent ticket becomes an ordinary one.

begin;

alter table public.tenant_support_requests
    drop constraint if exists tenant_support_requests_escalation_context_check;

alter table public.tenant_support_requests
    drop column if exists escalation_context;

update public.tenant_support_requests
    set priority = 'normal'
    where priority <> 'normal';

alter table public.tenant_support_requests
    drop constraint if exists tenant_support_requests_priority_check;
alter table public.tenant_support_requests
    add constraint tenant_support_requests_priority_check
    check (priority = 'normal');

update public.tenant_support_requests
    set source = 'tenant'
    where source <> 'tenant';

alter table public.tenant_support_requests
    drop constraint if exists tenant_support_requests_source_check;
alter table public.tenant_support_requests
    add constraint tenant_support_requests_source_check
    check (source = 'tenant');

drop function if exists public.create_tenant_support_request(
    bigint, bigint, text, text, text, text, text, jsonb
);

create or replace function public.create_tenant_support_request(
    p_company_id BIGINT,
    p_requester_user_id BIGINT,
    p_category TEXT,
    p_title TEXT,
    p_redacted_description TEXT
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_request_id BIGINT;
    v_title TEXT;
    v_redacted_description TEXT;
BEGIN
    IF p_category IS NULL OR p_category NOT IN (
        'technical', 'account', 'chatbot', 'integration',
        'billing_question', 'ai_credits', 'other'
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'Unsupported tenant support category';
    END IF;

    IF p_title IS NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'Tenant support title must contain 1 to 160 characters';
    END IF;
    v_title := btrim(p_title);
    IF char_length(v_title) NOT BETWEEN 1 AND 160 THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'Tenant support title must contain 1 to 160 characters';
    END IF;

    IF p_redacted_description IS NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'Tenant support description must contain 1 to 2000 characters';
    END IF;
    v_redacted_description := btrim(p_redacted_description);
    IF char_length(v_redacted_description) NOT BETWEEN 1 AND 2000 THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'Tenant support description must contain 1 to 2000 characters';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.users
        WHERE id = p_requester_user_id
          AND company_id = p_company_id
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23503',
            MESSAGE = 'Tenant support requester does not belong to the company';
    END IF;

    INSERT INTO public.tenant_support_requests (
        company_id,
        requester_user_id,
        source,
        category,
        title,
        redacted_description,
        status,
        priority
    ) VALUES (
        p_company_id,
        p_requester_user_id,
        'tenant',
        p_category,
        v_title,
        v_redacted_description,
        'new',
        'normal'
    )
    RETURNING id INTO v_request_id;

    INSERT INTO public.tenant_support_request_events (
        request_id,
        event_type,
        actor_user_id,
        actor_platform_admin_user_id,
        actor_type
    ) VALUES (
        v_request_id,
        'created',
        p_requester_user_id,
        NULL,
        'tenant'
    );

    INSERT INTO public.tenant_support_audit_events (
        request_id,
        company_id,
        requester_user_id,
        action,
        outcome,
        category,
        source
    ) VALUES (
        v_request_id,
        p_company_id,
        p_requester_user_id,
        'tenant_support.request.create',
        'success',
        p_category,
        'tenant'
    );

    RETURN v_request_id;
END;
$function$;

REVOKE ALL ON FUNCTION public.create_tenant_support_request(
    BIGINT, BIGINT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_tenant_support_request(
    BIGINT, BIGINT, TEXT, TEXT, TEXT
) TO service_role;

commit;
