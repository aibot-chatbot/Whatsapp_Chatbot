-- 022_permanently_delete_archived_chatbot_rpc.sql
-- Transactional permanent deletion for archived chatbots.
--
-- This function intentionally preserves public.ai_usage_logs as billing/audit
-- history. It deletes known orphan-prone operational tables, then deletes the
-- archived chatbot row last. The function is SECURITY DEFINER so the app role
-- does not need broad DELETE grants on those tables.

CREATE OR REPLACE FUNCTION public.permanently_delete_archived_chatbot(
    p_chatbot_id bigint,
    p_company_id bigint,
    p_confirm_bot_name text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_bot public.chatbots%ROWTYPE;
    v_wasender_deleted integer := 0;
    v_telegram_deleted integer := 0;
    v_whatsapp_deleted integer := 0;
    v_graph_edges_deleted integer := 0;
    v_graph_nodes_deleted integer := 0;
    v_crm_leads_deleted integer := 0;
    v_agent_actions_deleted integer := 0;
    v_chatbots_deleted integer := 0;
BEGIN
    IF p_chatbot_id IS NULL OR p_company_id IS NULL THEN
        RETURN jsonb_build_object(
            'status', 'error',
            'code', 'invalid_request',
            'message', 'chatbot_id and company_id are required'
        );
    END IF;

    SELECT *
    INTO v_bot
    FROM public.chatbots
    WHERE id = p_chatbot_id
      AND company_id = p_company_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'status', 'error',
            'code', 'not_found',
            'message', 'Bot not found'
        );
    END IF;

    IF COALESCE(v_bot.status, 'active') <> 'archived'
       AND v_bot.deleted_at IS NULL THEN
        RETURN jsonb_build_object(
            'status', 'error',
            'code', 'active_bot',
            'message', 'Only archived bots can be permanently deleted'
        );
    END IF;

    IF p_confirm_bot_name IS NULL OR p_confirm_bot_name <> COALESCE(v_bot.bot_name, '') THEN
        RETURN jsonb_build_object(
            'status', 'error',
            'code', 'confirmation_mismatch',
            'message', 'Confirmation bot name does not match'
        );
    END IF;

    DELETE FROM public.wasender_channels
    WHERE chatbot_id = p_chatbot_id
      AND company_id = p_company_id;
    GET DIAGNOSTICS v_wasender_deleted = ROW_COUNT;

    DELETE FROM public.telegram_channels
    WHERE chatbot_id = p_chatbot_id
      AND company_id = p_company_id;
    GET DIAGNOSTICS v_telegram_deleted = ROW_COUNT;

    DELETE FROM public.whatsapp_channels
    WHERE chatbot_id = p_chatbot_id
      AND company_id = p_company_id;
    GET DIAGNOSTICS v_whatsapp_deleted = ROW_COUNT;

    DELETE FROM public.knowledge_graph_edges
    WHERE chatbot_id = p_chatbot_id;
    GET DIAGNOSTICS v_graph_edges_deleted = ROW_COUNT;

    DELETE FROM public.knowledge_graph_nodes
    WHERE chatbot_id = p_chatbot_id;
    GET DIAGNOSTICS v_graph_nodes_deleted = ROW_COUNT;

    DELETE FROM public.crm_leads
    WHERE chatbot_id = p_chatbot_id
      AND company_id = p_company_id;
    GET DIAGNOSTICS v_crm_leads_deleted = ROW_COUNT;

    DELETE FROM public.agent_actions
    WHERE chatbot_id = p_chatbot_id
      AND company_id = p_company_id;
    GET DIAGNOSTICS v_agent_actions_deleted = ROW_COUNT;

    DELETE FROM public.chatbots
    WHERE id = p_chatbot_id
      AND company_id = p_company_id;
    GET DIAGNOSTICS v_chatbots_deleted = ROW_COUNT;

    RETURN jsonb_build_object(
        'status', 'success',
        'code', 'deleted',
        'message', 'Bot permanently deleted',
        'chatbot_id', p_chatbot_id,
        'company_id', p_company_id,
        'deleted_counts', jsonb_build_object(
            'wasender_channels', v_wasender_deleted,
            'telegram_channels', v_telegram_deleted,
            'whatsapp_channels', v_whatsapp_deleted,
            'knowledge_graph_edges', v_graph_edges_deleted,
            'knowledge_graph_nodes', v_graph_nodes_deleted,
            'crm_leads', v_crm_leads_deleted,
            'agent_actions', v_agent_actions_deleted,
            'chatbots', v_chatbots_deleted,
            'ai_usage_logs', 0
        ),
        'preserved_tables', jsonb_build_array('ai_usage_logs')
    );
END;
$function$;

REVOKE ALL
ON FUNCTION public.permanently_delete_archived_chatbot(bigint, bigint, text)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION public.permanently_delete_archived_chatbot(bigint, bigint, text)
TO service_role;

COMMENT ON FUNCTION public.permanently_delete_archived_chatbot(bigint, bigint, text)
IS 'Permanently deletes an archived chatbot transactionally. Preserves ai_usage_logs for billing/audit history.';
