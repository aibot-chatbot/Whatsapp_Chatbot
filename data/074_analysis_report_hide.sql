-- 074_analysis_report_hide.sql
-- "Remove" and "Clear finished reports" on the Analysis page. A cleared report leaves the
-- owner's list but stays in analysis_reports, with its model steps and stored files, for
-- billing and AI-credit audit: nothing is deleted. hidden_at and hidden_by record when it was
-- cleared and by which signed-in user (the Flask route passes g.user_id after its role check).
--
-- Apply BEFORE deploying the code that reads it: analysis_repository.list_reports filters on
-- hidden_at, so the old list query keeps working and the new one needs the column.
-- Not yet applied anywhere. Rollback: 074_analysis_report_hide_rollback.sql.
--
-- service_role holds only SELECT on analysis_reports (writes go through SECURITY DEFINER
-- functions), so clearing is one more function, scoped by company and chatbot, that can only
-- set hidden_at on reports that are finished. Queued and running reports are never cleared:
-- their worker still owns them.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE public.analysis_reports ADD COLUMN IF NOT EXISTS hidden_at timestamptz;
ALTER TABLE public.analysis_reports ADD COLUMN IF NOT EXISTS hidden_by bigint;
CREATE INDEX IF NOT EXISTS analysis_reports_visible
  ON public.analysis_reports (company_id, chatbot_id, created_at DESC, id DESC) WHERE hidden_at IS NULL;

-- Clears the listed finished reports of one Bot, or every finished one when p_report_ids is
-- NULL. Returns {"hidden": <count>}. Already-cleared and unfinished reports are skipped.
-- Rows are locked in id order first, so a "clear all" and a single "remove" racing each other
-- wait instead of deadlocking.
CREATE OR REPLACE FUNCTION public.analysis_hide_reports(
  p_company_id bigint, p_chatbot_id bigint, p_actor_user_id bigint, p_report_ids uuid[] DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_hidden integer;
BEGIN
  IF p_company_id IS NULL OR p_chatbot_id IS NULL OR p_actor_user_id IS NULL THEN
    RAISE EXCEPTION 'analysis_scope_required' USING ERRCODE = '22023';
  END IF;
  -- Same check as 063's write functions: a live chatbot of this company, an active owner/admin.
  PERFORM public.analysis_require_actor(p_company_id, p_chatbot_id, p_actor_user_id);
  IF p_report_ids IS NOT NULL AND (cardinality(p_report_ids) NOT BETWEEN 1 AND 100) THEN
    RAISE EXCEPTION 'analysis_hide_batch_invalid' USING ERRCODE = '22023';
  END IF;
  UPDATE public.analysis_reports
     SET hidden_at = now(), hidden_by = p_actor_user_id
   WHERE id IN (SELECT id FROM public.analysis_reports
                 WHERE company_id = p_company_id AND chatbot_id = p_chatbot_id AND hidden_at IS NULL
                   AND status IN ('complete', 'partial', 'needs_input', 'needs_review', 'failed')
                   AND (p_report_ids IS NULL OR id = ANY (p_report_ids))
                 ORDER BY id FOR UPDATE);
  GET DIAGNOSTICS v_hidden = ROW_COUNT;
  RETURN jsonb_build_object('hidden', v_hidden);
END
$$;

REVOKE ALL ON FUNCTION public.analysis_hide_reports(bigint, bigint, bigint, uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.analysis_hide_reports(bigint, bigint, bigint, uuid[]) TO service_role;

COMMIT;
