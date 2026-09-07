-- 052_support_escalation_context.sql
-- Slice 3 of the support redesign: the self-service trail, urgency and origin
-- of a tenant support request.
--
-- APPLY THIS BEFORE DEPLOYING THE MATCHING CODE. The three new RPC parameters
-- all carry defaults, so a still-running old deployment (which sends five named
-- arguments) keeps working after this migration. The reverse is not true: new
-- code sends eight names and the pre-052 five-parameter function rejects them.
--
-- Numbers 050 and 051 are taken by two other in-flight streams; 052 is the
-- first free slot. Applied by hand in the Supabase SQL editor - this project
-- has no migration runner.
--
-- This migration relaxes two CHECK constraints that migration 030 wrote as
-- single-value locks (priority = 'normal', source = 'tenant'). Without that,
-- the urgency and origin decisions in 01-requirements.md decision 7 and FR-4
-- cannot be stored at all: the database would reject every row.

begin;

alter table public.tenant_support_requests
    add column if not exists escalation_context jsonb null;

comment on column public.tenant_support_requests.escalation_context is
    'Bounded self-service trail: searches[], viewed[], unhelpful[], from_page. Machine collected, so it is not subject to the prose redaction rules that govern redacted_description.';

-- Structural bound, mirroring app/services/tenant_support_service.py. The
-- service is the primary guard; this is the one that still holds if some future
-- writer forgets to go through it.
do $migration$
begin
    if exists (
        select 1
        from pg_catalog.pg_constraint
        where conname = 'tenant_support_requests_escalation_context_check'
          and conrelid = 'public.tenant_support_requests'::pg_catalog.regclass
    ) then
        alter table public.tenant_support_requests
            drop constraint tenant_support_requests_escalation_context_check;
    end if;

    alter table public.tenant_support_requests
        add constraint tenant_support_requests_escalation_context_check
        check (
            escalation_context is null
            or (
                jsonb_typeof(escalation_context) = 'object'
                and octet_length(escalation_context::text) <= 4000
            )
        );
end;
$migration$;

-- Urgency. 'normal' stays the default so every existing row remains valid.
alter table public.tenant_support_requests
    drop constraint if exists tenant_support_requests_priority_check;
alter table public.tenant_support_requests
    add constraint tenant_support_requests_priority_check
    check (priority in ('low', 'normal', 'urgent'));

-- Origin. 'tenant' is kept because it is what every row written before this
-- migration holds; dropping it would make the constraint fail against live
-- data. New rows use 'faq_dead_end' or 'direct'.
alter table public.tenant_support_requests
    drop constraint if exists tenant_support_requests_source_check;
alter table public.tenant_support_requests
    add constraint tenant_support_requests_source_check
    check (source in ('tenant', 'faq_dead_end', 'direct'));

-- The RPC has to be dropped, not just replaced: adding parameters produces a
-- second overload of the same name, and postgrest could then no longer resolve
-- a call unambiguously.
drop function if exists public.create_tenant_support_request(
    bigint, bigint, text, text, text
);

create or replace function public.create_tenant_support_request(
    p_company_id BIGINT,
    p_requester_user_id BIGINT,
    p_category TEXT,
    p_title TEXT,
    p_redacted_description TEXT,
    p_priority TEXT DEFAULT 'normal',
    p_source TEXT DEFAULT 'direct',
    p_escalation_context JSONB DEFAULT NULL
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

    IF p_priority IS NULL OR p_priority NOT IN ('low', 'normal', 'urgent') THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'Unsupported tenant support priority';
    END IF;

    IF p_source IS NULL OR p_source NOT IN ('faq_dead_end', 'direct') THEN
        RAISE EXCEPTION USING
            ERRCODE = '22023',
            MESSAGE = 'Unsupported tenant support source';
    END IF;

    IF p_escalation_context IS NOT NULL THEN
        IF jsonb_typeof(p_escalation_context) <> 'object' THEN
            RAISE EXCEPTION USING
                ERRCODE = '22023',
                MESSAGE = 'Tenant support escalation context must be an object';
        END IF;
        IF octet_length(p_escalation_context::text) > 4000 THEN
            RAISE EXCEPTION USING
                ERRCODE = '22023',
                MESSAGE = 'Tenant support escalation context is too large';
        END IF;
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
        priority,
        escalation_context
    ) VALUES (
        p_company_id,
        p_requester_user_id,
        p_source,
        p_category,
        v_title,
        v_redacted_description,
        'new',
        p_priority,
        p_escalation_context
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

    -- tenant_support_audit_events.source is a different column with its own
    -- CHECK (source = 'tenant'); it records who filed the row, not what led to
    -- it, and is left alone on purpose.
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
    BIGINT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_tenant_support_request(
    BIGINT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB
) TO service_role;

commit;
