-- Company-scoped GEO measurement. Apply before deploying the GEO routes.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.geo_analyses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
  actor_user_id bigint NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
  plan_code text NOT NULL CHECK (plan_code IN ('essential','advanced','pro')),
  execution_count smallint NOT NULL CHECK (execution_count BETWEEN 1 AND 12),
  brand_name text NOT NULL CHECK (length(brand_name) BETWEEN 1 AND 120),
  aliases jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(aliases) = 'array' AND octet_length(aliases::text) <= 8192),
  competitors jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(competitors) = 'array' AND octet_length(competitors::text) <= 8192),
  owned_domains jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(owned_domains) = 'array' AND octet_length(owned_domains::text) <= 8192),
  country text NOT NULL CHECK (country ~ '^[A-Z]{2}$'),
  language text NOT NULL CHECK (language IN ('en','ms','zh')),
  platforms jsonb NOT NULL CHECK (jsonb_typeof(platforms) = 'array' AND octet_length(platforms::text) <= 1024),
  prompts jsonb NOT NULL CHECK (jsonb_typeof(prompts) = 'array' AND octet_length(prompts::text) <= 16384),
  samples_per_prompt smallint NOT NULL CHECK (samples_per_prompt BETWEEN 1 AND 3),
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running','complete','partial','failed')),
  metrics jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(metrics) = 'object' AND octet_length(metrics::text) <= 32768),
  methodology jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(methodology) = 'object' AND octet_length(methodology::text) <= 16384),
  error_code text CHECK (error_code ~ '^[a-z][a-z0-9_]{0,63}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id, company_id)
);
CREATE INDEX geo_analyses_company_created ON public.geo_analyses(company_id, created_at DESC, id);

CREATE TABLE public.geo_prompt_executions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  analysis_id uuid NOT NULL,
  company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
  prompt text NOT NULL CHECK (length(prompt) BETWEEN 1 AND 500),
  prompt_index smallint NOT NULL CHECK (prompt_index BETWEEN 0 AND 9),
  platform text NOT NULL CHECK (platform IN ('chatgpt','gemini','perplexity')),
  surface text NOT NULL CHECK (length(surface) BETWEEN 1 AND 80),
  model text NOT NULL CHECK (length(model) BETWEEN 1 AND 160),
  sample_index smallint NOT NULL CHECK (sample_index BETWEEN 0 AND 2),
  country text NOT NULL DEFAULT 'MY' CHECK (country ~ '^[A-Z]{2}$'),
  language text NOT NULL DEFAULT 'en' CHECK (language IN ('en','ms','zh')),
  raw_response text NOT NULL DEFAULT '' CHECK (length(raw_response) <= 100000),
  request_status text NOT NULL CHECK (request_status IN ('complete','failed')),
  error_code text CHECK (error_code ~ '^[a-z][a-z0-9_]{0,63}$'),
  latency_ms integer NOT NULL CHECK (latency_ms >= 0),
  cost_usd numeric(12,6) CHECK (cost_usd IS NULL OR cost_usd >= 0),
  is_search_experience boolean NOT NULL,
  brand_mentioned boolean NOT NULL DEFAULT false,
  brand_mention_count integer NOT NULL DEFAULT 0 CHECK (brand_mention_count >= 0),
  competitor_mentions jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(competitor_mentions) = 'object' AND octet_length(competitor_mentions::text) <= 8192),
  owned_citation_count integer NOT NULL DEFAULT 0 CHECK (owned_citation_count >= 0),
  recommendation_position integer CHECK (recommendation_position IS NULL OR recommendation_position > 0),
  sentiment text NOT NULL CHECK (sentiment IN ('positive','neutral','negative')),
  provider_metadata jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(provider_metadata) = 'object' AND octet_length(provider_metadata::text) <= 65536),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(analysis_id, prompt_index, platform, sample_index),
  UNIQUE(id, company_id),
  FOREIGN KEY (analysis_id, company_id) REFERENCES public.geo_analyses(id, company_id) ON DELETE CASCADE
);
CREATE INDEX geo_executions_analysis_order ON public.geo_prompt_executions(analysis_id, prompt_index, platform, sample_index);
CREATE INDEX geo_executions_company_created ON public.geo_prompt_executions(company_id, created_at DESC, id);

CREATE TABLE public.geo_execution_citations (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  execution_id bigint NOT NULL,
  company_id bigint NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
  url text NOT NULL CHECK (length(url) BETWEEN 1 AND 4096),
  domain text CHECK (length(domain) <= 253),
  title text CHECK (length(title) <= 1000),
  citation_position integer CHECK (citation_position IS NULL OR citation_position > 0),
  provider_metadata jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(provider_metadata) = 'object' AND octet_length(provider_metadata::text) <= 32768),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(execution_id, url),
  FOREIGN KEY (execution_id, company_id) REFERENCES public.geo_prompt_executions(id, company_id) ON DELETE CASCADE
);
CREATE INDEX geo_citations_execution_position ON public.geo_execution_citations(execution_id, citation_position, id);
CREATE INDEX geo_citations_company_domain ON public.geo_execution_citations(company_id, domain);

-- Reserve the full provider fan-out before any external API call.  The
-- transaction-scoped advisory lock makes the monthly allowance atomic even
-- when two web workers start analyses for the same company concurrently.
CREATE OR REPLACE FUNCTION public.reserve_geo_analysis(
  p_company_id bigint,
  p_actor_user_id bigint,
  p_plan_code text,
  p_monthly_limit integer,
  p_execution_count integer,
  p_brand_name text,
  p_aliases jsonb,
  p_competitors jsonb,
  p_owned_domains jsonb,
  p_country text,
  p_language text,
  p_platforms jsonb,
  p_prompts jsonb,
  p_samples_per_prompt smallint
)
RETURNS SETOF public.geo_analyses
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_monthly_limit < 1 OR p_execution_count < 1 OR p_execution_count > 12 THEN
    RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'invalid_geo_allowance';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended('geo:' || p_company_id::text, 0));
  IF COALESCE((
    SELECT sum(execution_count)
    FROM public.geo_analyses
    WHERE company_id = p_company_id
      AND created_at >= date_trunc('month', now())
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
  )
  RETURNING *;
END;
$$;

ALTER TABLE public.geo_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.geo_prompt_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.geo_execution_citations ENABLE ROW LEVEL SECURITY;

CREATE POLICY geo_analyses_service_select ON public.geo_analyses FOR SELECT TO service_role USING (TRUE);
CREATE POLICY geo_analyses_service_insert ON public.geo_analyses FOR INSERT TO service_role WITH CHECK (TRUE);
CREATE POLICY geo_analyses_service_update ON public.geo_analyses FOR UPDATE TO service_role USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY geo_executions_service_select ON public.geo_prompt_executions FOR SELECT TO service_role USING (TRUE);
CREATE POLICY geo_executions_service_insert ON public.geo_prompt_executions FOR INSERT TO service_role WITH CHECK (TRUE);
CREATE POLICY geo_citations_service_select ON public.geo_execution_citations FOR SELECT TO service_role USING (TRUE);
CREATE POLICY geo_citations_service_insert ON public.geo_execution_citations FOR INSERT TO service_role WITH CHECK (TRUE);

REVOKE ALL ON public.geo_analyses, public.geo_prompt_executions, public.geo_execution_citations FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE public.geo_prompt_executions_id_seq, public.geo_execution_citations_id_seq FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.reserve_geo_analysis(bigint, bigint, text, integer, integer, text, jsonb, jsonb, jsonb, text, text, jsonb, jsonb, smallint) FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON public.geo_analyses, public.geo_prompt_executions, public.geo_execution_citations TO service_role;
GRANT UPDATE (status, metrics, methodology, error_code, updated_at) ON public.geo_analyses TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.geo_prompt_executions_id_seq, public.geo_execution_citations_id_seq TO service_role;
GRANT EXECUTE ON FUNCTION public.reserve_geo_analysis(bigint, bigint, text, integer, integer, text, jsonb, jsonb, jsonb, text, text, jsonb, jsonb, smallint) TO service_role;

-- GEO is included in every paid plan and unavailable on Free/trial.
UPDATE public.subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || '{"geo_analysis": false}'::jsonb
WHERE lower(code) = 'free';
UPDATE public.subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) || '{"geo_analysis": true}'::jsonb
WHERE lower(code) IN ('essential','advanced','pro');

COMMIT;
