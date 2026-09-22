-- One open inbox conversation per website visitor and chatbot.
-- Without this guard, simultaneous first messages can create two rows:
-- customer_phone is NULL for web visitors, so the legacy phone index does
-- not reject duplicates. The existing repository retries its lookup after
-- an INSERT conflict and returns the winning conversation.
--
-- Preflight on the approved target must return zero rows:
-- SELECT chatbot_id, platform_user_id, count(*)
-- FROM public.conversations
-- WHERE source_channel = 'web' AND source_channel_id IS NULL
--   AND conversation_status = 'open' AND platform_user_id IS NOT NULL
-- GROUP BY chatbot_id, platform_user_id HAVING count(*) > 1;
--
-- This bounded index build briefly blocks conversation writes. The verified
-- target is small; if either timeout expires, stop and reassess instead of
-- extending it. A large target requires a separate CONCURRENTLY rollout.
-- No backfill, row deletion, RPC, RLS, or feature-flag change is involved.
SET lock_timeout = '3s';
SET statement_timeout = '30s';

CREATE UNIQUE INDEX unique_open_web_widget_session
    ON public.conversations (chatbot_id, platform_user_id)
    WHERE source_channel = 'web'
      AND source_channel_id IS NULL
      AND conversation_status = 'open'
      AND platform_user_id IS NOT NULL;

-- Application rollback should retain this data-integrity guard. Dropping it
-- requires a separate approval and reintroduces the duplicate-session race.
