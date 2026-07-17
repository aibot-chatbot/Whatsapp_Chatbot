-- Add soft-delete/archive support for chatbots.
-- Normal UI/API deletion should archive chatbots instead of hard-deleting rows.

ALTER TABLE public.chatbots
    ADD COLUMN IF NOT EXISTS status text;

UPDATE public.chatbots
SET status = 'active'
WHERE status IS NULL OR btrim(status) = '';

ALTER TABLE public.chatbots
    ALTER COLUMN status SET DEFAULT 'active';

ALTER TABLE public.chatbots
    ALTER COLUMN status SET NOT NULL;

ALTER TABLE public.chatbots
    ADD COLUMN IF NOT EXISTS deleted_at timestamp with time zone;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chatbots_status_check'
          AND conrelid = 'public.chatbots'::regclass
    ) THEN
        ALTER TABLE public.chatbots
            ADD CONSTRAINT chatbots_status_check
            CHECK (status IN ('active', 'archived'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_chatbots_company_active
    ON public.chatbots (company_id, created_at DESC)
    WHERE deleted_at IS NULL AND status <> 'archived';
