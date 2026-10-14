-- Roll back only after removing executions that use an expanded platform id.
ALTER TABLE public.geo_prompt_executions
    DROP CONSTRAINT IF EXISTS geo_prompt_executions_platform_check;

ALTER TABLE public.geo_prompt_executions
    ADD CONSTRAINT geo_prompt_executions_platform_check
    CHECK (platform IN ('chatgpt', 'gemini', 'perplexity'));

ALTER TABLE public.geo_analyses
    DROP CONSTRAINT IF EXISTS geo_analyses_execution_count_check;

ALTER TABLE public.geo_analyses
    ADD CONSTRAINT geo_analyses_execution_count_check
    CHECK (execution_count BETWEEN 1 AND 12);

CREATE OR REPLACE FUNCTION public.reserve_geo_analysis(
  p_company_id bigint, p_actor_user_id bigint, p_plan_code text,
  p_monthly_limit integer, p_execution_count integer, p_brand_name text,
  p_aliases jsonb, p_competitors jsonb, p_owned_domains jsonb,
  p_country text, p_language text, p_platforms jsonb, p_prompts jsonb,
  p_samples_per_prompt smallint
)
RETURNS SETOF public.geo_analyses
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_monthly_limit < 1 OR p_execution_count < 1 OR p_execution_count > 12 THEN
    RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'invalid_geo_allowance';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('geo:' || p_company_id::text, 0));
  IF COALESCE((
    SELECT sum(execution_count) FROM public.geo_analyses
    WHERE company_id = p_company_id AND created_at >= date_trunc('month', now())
  ), 0) + p_execution_count > p_monthly_limit THEN
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'geo_monthly_limit';
  END IF;
  RETURN QUERY
  INSERT INTO public.geo_analyses (
    company_id, actor_user_id, plan_code, execution_count, brand_name,
    aliases, competitors, owned_domains, country, language, platforms,
    prompts, samples_per_prompt, status
  ) VALUES (
    p_company_id, p_actor_user_id, p_plan_code, p_execution_count, p_brand_name,
    p_aliases, p_competitors, p_owned_domains, p_country, p_language,
    p_platforms, p_prompts, p_samples_per_prompt, 'running'
  ) RETURNING *;
END;
$$;
