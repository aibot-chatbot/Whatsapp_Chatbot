BEGIN;
UPDATE public.subscription_plans
SET feature_flags = COALESCE(feature_flags, '{}'::jsonb) - 'geo_analysis'
WHERE lower(code) IN ('free','essential','advanced','pro');
DROP FUNCTION IF EXISTS public.reserve_geo_analysis(bigint, bigint, text, integer, integer, text, jsonb, jsonb, jsonb, text, text, jsonb, jsonb, smallint);
DROP TABLE IF EXISTS public.geo_execution_citations;
DROP TABLE IF EXISTS public.geo_prompt_executions;
DROP TABLE IF EXISTS public.geo_analyses;
COMMIT;
