-- 032_platform_support_case_operations.sql
-- MIGRATION DRAFT ONLY. Do not apply without approved executor, environment,
-- privacy, retention, rollback, and production-readiness approvals.
-- Extends the existing platform_support_cases model for Phase 2 operations.

ALTER TABLE public.platform_support_case_events
    ADD COLUMN IF NOT EXISTS old_assigned_platform_admin_user_id BIGINT NULL,
    ADD COLUMN IF NOT EXISTS new_assigned_platform_admin_user_id BIGINT NULL;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conname = 'platform_support_case_events_old_assignee_fkey'
          AND conrelid = 'public.platform_support_case_events'::pg_catalog.regclass
    ) THEN
        ALTER TABLE public.platform_support_case_events
            ADD CONSTRAINT platform_support_case_events_old_assignee_fkey
            FOREIGN KEY (old_assigned_platform_admin_user_id)
            REFERENCES public.platform_admin_users(id)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conname = 'platform_support_case_events_new_assignee_fkey'
          AND conrelid = 'public.platform_support_case_events'::pg_catalog.regclass
    ) THEN
        ALTER TABLE public.platform_support_case_events
            ADD CONSTRAINT platform_support_case_events_new_assignee_fkey
            FOREIGN KEY (new_assigned_platform_admin_user_id)
            REFERENCES public.platform_admin_users(id)
            ON DELETE RESTRICT;
    END IF;
END;
$migration$;

DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conname = 'platform_support_cases_status_check'
          AND conrelid = 'public.platform_support_cases'::pg_catalog.regclass
    ) THEN
        ALTER TABLE public.platform_support_cases
            DROP CONSTRAINT platform_support_cases_status_check;
    END IF;
    ALTER TABLE public.platform_support_cases
        ADD CONSTRAINT platform_support_cases_status_check
        CHECK (status IN ('open', 'in_progress', 'waiting_for_tenant', 'resolved', 'closed'));

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conname = 'platform_support_case_events_type_check'
          AND conrelid = 'public.platform_support_case_events'::pg_catalog.regclass
    ) THEN
        ALTER TABLE public.platform_support_case_events
            DROP CONSTRAINT platform_support_case_events_type_check;
    END IF;
    ALTER TABLE public.platform_support_case_events
        ADD CONSTRAINT platform_support_case_events_type_check
        CHECK (event_type IN (
            'created',
            'note_added',
            'status_changed',
            'priority_changed',
            'assignment_changed'
        ));

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conname = 'platform_support_case_events_status_check'
          AND conrelid = 'public.platform_support_case_events'::pg_catalog.regclass
    ) THEN
        ALTER TABLE public.platform_support_case_events
            DROP CONSTRAINT platform_support_case_events_status_check;
    END IF;
    ALTER TABLE public.platform_support_case_events
        ADD CONSTRAINT platform_support_case_events_status_check
        CHECK (
            (old_status IS NULL OR old_status IN ('open', 'in_progress', 'waiting_for_tenant', 'resolved', 'closed'))
            AND (new_status IS NULL OR new_status IN ('open', 'in_progress', 'waiting_for_tenant', 'resolved', 'closed'))
        );
END;
$migration$;

CREATE INDEX IF NOT EXISTS ix_platform_support_cases_assignee_updated
    ON public.platform_support_cases (assigned_platform_admin_user_id, updated_at DESC, id DESC);

REVOKE ALL ON public.platform_support_cases
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.platform_support_case_events
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE public.platform_support_cases_id_seq
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE public.platform_support_case_events_id_seq
    FROM PUBLIC, anon, authenticated, service_role;

GRANT SELECT, INSERT, UPDATE ON public.platform_support_cases
    TO service_role;
GRANT SELECT, INSERT ON public.platform_support_case_events
    TO service_role;
GRANT USAGE ON SEQUENCE public.platform_support_cases_id_seq
    TO service_role;
GRANT USAGE ON SEQUENCE public.platform_support_case_events_id_seq
    TO service_role;

CREATE OR REPLACE FUNCTION public.platform_support_case_operation_result(
    p_case_id BIGINT,
    p_event_id BIGINT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_case public.platform_support_cases%ROWTYPE;
    v_event public.platform_support_case_events%ROWTYPE;
BEGIN
    SELECT * INTO v_case
    FROM public.platform_support_cases
    WHERE id = p_case_id;

    SELECT * INTO v_event
    FROM public.platform_support_case_events
    WHERE id = p_event_id;

    RETURN pg_catalog.jsonb_build_object(
        'case', pg_catalog.to_jsonb(v_case),
        'event', pg_catalog.to_jsonb(v_event)
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.require_active_platform_admin_mapping(
    p_platform_admin_user_id BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
BEGIN
    IF p_platform_admin_user_id IS NULL OR p_platform_admin_user_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid platform-admin user ID';
    END IF;
    PERFORM 1
        FROM public.platform_admin_users
        WHERE id = p_platform_admin_user_id
          AND is_active = TRUE
        FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'Active platform-admin mapping is required';
    END IF;
END;
$function$;

CREATE OR REPLACE FUNCTION public.assign_platform_support_case(
    p_case_id BIGINT,
    p_platform_admin_user_id BIGINT,
    p_assignee_platform_admin_user_id BIGINT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_case public.platform_support_cases%ROWTYPE;
    v_event_id BIGINT;
    v_now TIMESTAMPTZ := pg_catalog.now();
    v_action TEXT;
BEGIN
    PERFORM public.require_active_platform_admin_mapping(p_platform_admin_user_id);
    IF p_case_id IS NULL OR p_case_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid support case ID';
    END IF;
    IF p_assignee_platform_admin_user_id IS NOT NULL THEN
        PERFORM public.require_active_platform_admin_mapping(p_assignee_platform_admin_user_id);
    END IF;

    SELECT * INTO v_case
    FROM public.platform_support_cases
    WHERE id = p_case_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Support case not found';
    END IF;
    IF v_case.assigned_platform_admin_user_id IS NOT DISTINCT FROM p_assignee_platform_admin_user_id THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Support case assignee is unchanged';
    END IF;

    UPDATE public.platform_support_cases
    SET assigned_platform_admin_user_id = p_assignee_platform_admin_user_id,
        updated_at = v_now
    WHERE id = p_case_id;

    INSERT INTO public.platform_support_case_events (
        case_id, event_type, actor_platform_admin_user_id,
        old_assigned_platform_admin_user_id, new_assigned_platform_admin_user_id,
        created_at
    ) VALUES (
        p_case_id, 'assignment_changed', p_platform_admin_user_id,
        v_case.assigned_platform_admin_user_id, p_assignee_platform_admin_user_id,
        v_now
    )
    RETURNING id INTO v_event_id;

    v_action := CASE
        WHEN p_assignee_platform_admin_user_id IS NULL THEN 'platform_admin.support_case.unassign'
        ELSE 'platform_admin.support_case.assign'
    END;

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id, action, resource_type, resource_id, metadata, created_at
    ) VALUES (
        p_platform_admin_user_id,
        v_action,
        'platform_support_cases',
        p_case_id::TEXT,
        pg_catalog.jsonb_build_object(
            'endpoint', '/api/platform-admin/support-cases/<case_id>/assignment',
            'http_method', 'PATCH',
            'outcome', 'success',
            'old_assigned_platform_admin_user_id', v_case.assigned_platform_admin_user_id,
            'new_assigned_platform_admin_user_id', p_assignee_platform_admin_user_id
        ),
        v_now
    );

    RETURN public.platform_support_case_operation_result(p_case_id, v_event_id);
END;
$function$;

CREATE OR REPLACE FUNCTION public.set_platform_support_case_status(
    p_case_id BIGINT,
    p_platform_admin_user_id BIGINT,
    p_status TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_case public.platform_support_cases%ROWTYPE;
    v_event_id BIGINT;
    v_now TIMESTAMPTZ := pg_catalog.now();
BEGIN
    PERFORM public.require_active_platform_admin_mapping(p_platform_admin_user_id);
    IF p_case_id IS NULL OR p_case_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid support case ID';
    END IF;
    IF p_status IS NULL OR p_status NOT IN ('open', 'in_progress', 'waiting_for_tenant', 'resolved', 'closed') THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Unsupported support case status';
    END IF;

    SELECT * INTO v_case
    FROM public.platform_support_cases
    WHERE id = p_case_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Support case not found';
    END IF;
    IF v_case.status = p_status THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Support case status is unchanged';
    END IF;
    IF NOT (
        (v_case.status = 'open' AND p_status IN ('in_progress', 'waiting_for_tenant', 'resolved'))
        OR (v_case.status = 'in_progress' AND p_status IN ('waiting_for_tenant', 'resolved'))
        OR (v_case.status = 'waiting_for_tenant' AND p_status IN ('in_progress', 'resolved'))
        OR (v_case.status = 'resolved' AND p_status IN ('closed', 'in_progress'))
        OR (v_case.status = 'closed' AND p_status = 'in_progress')
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Support case transition is not allowed';
    END IF;

    UPDATE public.platform_support_cases
    SET status = p_status,
        updated_at = v_now,
        closed_at = CASE WHEN p_status = 'closed' THEN v_now ELSE NULL END
    WHERE id = p_case_id;

    INSERT INTO public.platform_support_case_events (
        case_id, event_type, actor_platform_admin_user_id,
        old_status, new_status, created_at
    ) VALUES (
        p_case_id, 'status_changed', p_platform_admin_user_id,
        v_case.status, p_status, v_now
    )
    RETURNING id INTO v_event_id;

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id, action, resource_type, resource_id, metadata, created_at
    ) VALUES (
        p_platform_admin_user_id,
        'platform_admin.support_case.status.update',
        'platform_support_cases',
        p_case_id::TEXT,
        pg_catalog.jsonb_build_object(
            'endpoint', '/api/platform-admin/support-cases/<case_id>/status',
            'http_method', 'PATCH',
            'outcome', 'success',
            'old_status', v_case.status,
            'new_status', p_status
        ),
        v_now
    );

    RETURN public.platform_support_case_operation_result(p_case_id, v_event_id);
END;
$function$;

CREATE OR REPLACE FUNCTION public.set_platform_support_case_priority(
    p_case_id BIGINT,
    p_platform_admin_user_id BIGINT,
    p_priority TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_case public.platform_support_cases%ROWTYPE;
    v_event_id BIGINT;
    v_now TIMESTAMPTZ := pg_catalog.now();
BEGIN
    PERFORM public.require_active_platform_admin_mapping(p_platform_admin_user_id);
    IF p_case_id IS NULL OR p_case_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid support case ID';
    END IF;
    IF p_priority IS NULL OR p_priority NOT IN ('low', 'normal', 'high', 'urgent') THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Unsupported support case priority';
    END IF;

    SELECT * INTO v_case
    FROM public.platform_support_cases
    WHERE id = p_case_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Support case not found';
    END IF;
    IF v_case.priority = p_priority THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Support case priority is unchanged';
    END IF;

    UPDATE public.platform_support_cases
    SET priority = p_priority,
        updated_at = v_now
    WHERE id = p_case_id;

    INSERT INTO public.platform_support_case_events (
        case_id, event_type, actor_platform_admin_user_id,
        old_priority, new_priority, created_at
    ) VALUES (
        p_case_id, 'priority_changed', p_platform_admin_user_id,
        v_case.priority, p_priority, v_now
    )
    RETURNING id INTO v_event_id;

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id, action, resource_type, resource_id, metadata, created_at
    ) VALUES (
        p_platform_admin_user_id,
        'platform_admin.support_case.priority.update',
        'platform_support_cases',
        p_case_id::TEXT,
        pg_catalog.jsonb_build_object(
            'endpoint', '/api/platform-admin/support-cases/<case_id>/priority',
            'http_method', 'PATCH',
            'outcome', 'success',
            'old_priority', v_case.priority,
            'new_priority', p_priority
        ),
        v_now
    );

    RETURN public.platform_support_case_operation_result(p_case_id, v_event_id);
END;
$function$;

CREATE OR REPLACE FUNCTION public.add_platform_support_case_note(
    p_case_id BIGINT,
    p_platform_admin_user_id BIGINT,
    p_redacted_note TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $function$
DECLARE
    v_case public.platform_support_cases%ROWTYPE;
    v_event_id BIGINT;
    v_note TEXT;
    v_now TIMESTAMPTZ := pg_catalog.now();
BEGIN
    PERFORM public.require_active_platform_admin_mapping(p_platform_admin_user_id);
    IF p_case_id IS NULL OR p_case_id <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid support case ID';
    END IF;
    v_note := pg_catalog.btrim(p_redacted_note);
    IF v_note IS NULL OR pg_catalog.char_length(v_note) < 1 OR pg_catalog.char_length(v_note) > 2000 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'Invalid internal note';
    END IF;

    SELECT * INTO v_case
    FROM public.platform_support_cases
    WHERE id = p_case_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'Support case not found';
    END IF;

    UPDATE public.platform_support_cases
    SET updated_at = v_now
    WHERE id = p_case_id;

    INSERT INTO public.platform_support_case_events (
        case_id, event_type, actor_platform_admin_user_id,
        redacted_note, created_at
    ) VALUES (
        p_case_id, 'note_added', p_platform_admin_user_id,
        v_note, v_now
    )
    RETURNING id INTO v_event_id;

    INSERT INTO public.platform_admin_audit_events (
        platform_admin_user_id, action, resource_type, resource_id, metadata, created_at
    ) VALUES (
        p_platform_admin_user_id,
        'platform_admin.support_case.note.create',
        'platform_support_case_events',
        p_case_id::TEXT,
        pg_catalog.jsonb_build_object(
            'endpoint', '/api/platform-admin/support-cases/<case_id>/notes',
            'http_method', 'POST',
            'outcome', 'success'
        ),
        v_now
    );

    RETURN public.platform_support_case_operation_result(p_case_id, v_event_id);
END;
$function$;

REVOKE ALL ON FUNCTION public.platform_support_case_operation_result(BIGINT, BIGINT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.require_active_platform_admin_mapping(BIGINT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.assign_platform_support_case(BIGINT, BIGINT, BIGINT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.set_platform_support_case_status(BIGINT, BIGINT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.set_platform_support_case_priority(BIGINT, BIGINT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.add_platform_support_case_note(BIGINT, BIGINT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.assign_platform_support_case(BIGINT, BIGINT, BIGINT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.platform_support_case_operation_result(BIGINT, BIGINT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.require_active_platform_admin_mapping(BIGINT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.set_platform_support_case_status(BIGINT, BIGINT, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.set_platform_support_case_priority(BIGINT, BIGINT, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.add_platform_support_case_note(BIGINT, BIGINT, TEXT)
    TO service_role;
