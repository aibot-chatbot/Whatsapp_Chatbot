-- Industry classification is a draft until an authorized owner/admin confirms it.
-- Additive only: existing runtime, grants, RLS and profiles are unchanged.
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'chatbots'
          AND column_name IN ('industry_template_draft', 'industry_template_published')
          AND data_type <> 'jsonb'
    ) THEN
        RAISE EXCEPTION 'Industry template columns must be jsonb';
    END IF;
END $$;

ALTER TABLE public.chatbots
    ADD COLUMN IF NOT EXISTS industry_template_draft jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS industry_template_published jsonb NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.chatbots'::regclass
                   AND conname = 'chatbots_industry_template_objects') THEN
        ALTER TABLE public.chatbots ADD CONSTRAINT chatbots_industry_template_objects
            CHECK (jsonb_typeof(industry_template_draft) = 'object'
               AND jsonb_typeof(industry_template_published) = 'object') NOT VALID;
    END IF;
END $$;
COMMIT;

-- Run validation separately so the short ADD COLUMN lock is released first.
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.chatbots VALIDATE CONSTRAINT chatbots_industry_template_objects;
COMMIT;
-- Roll back application usage first; preserve the additive columns and confirmed selections.
