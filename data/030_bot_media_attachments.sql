-- 030_bot_media_attachments.sql
-- Per-chatbot media library used when the bot replies with an image, video or
-- document (WhatsApp Cloud API, Wasender and broadcast campaigns).
--
-- Reconstructed from the repository layer, which is the only place the shape is
-- defined: app/database/bot_media_attachment_repository.py (insert payload,
-- lines 45-59) and app/services/media_send_service.py (media_type branches).
-- No CREATE TABLE for this relation existed in data/ before this file.

CREATE TABLE IF NOT EXISTS public.bot_media_attachments (
    id                  bigserial PRIMARY KEY,
    chatbot_id          bigint NOT NULL
                            REFERENCES public.chatbots (id) ON DELETE CASCADE,
    company_id          bigint NOT NULL,

    -- Human-facing label shown in the media library UI
    label               text NOT NULL DEFAULT '',

    -- Public URL the messaging provider fetches the media from
    media_url           text NOT NULL DEFAULT '',
    media_type          text NOT NULL DEFAULT 'image',
    caption             text NOT NULL DEFAULT '',

    -- Trigger words matched against the inbound message to pick an attachment
    keywords            text[] NOT NULL DEFAULT '{}',

    -- Meta approved-template pairing (blank when sent as a free-form message)
    meta_template_name  text NOT NULL DEFAULT '',
    meta_language_code  text NOT NULL DEFAULT 'en_US',

    is_active           boolean NOT NULL DEFAULT true,

    created_at          timestamp with time zone NOT NULL DEFAULT now(),
    updated_at          timestamp with time zone NOT NULL DEFAULT now()
);

-- get_active_attachments() filters chatbot_id + is_active, ordered by created_at.
CREATE INDEX IF NOT EXISTS idx_bot_media_attachments_chatbot_active
    ON public.bot_media_attachments (chatbot_id, is_active, created_at);

CREATE INDEX IF NOT EXISTS idx_bot_media_attachments_company
    ON public.bot_media_attachments (company_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'bot_media_attachments_media_type_check'
          AND conrelid = 'public.bot_media_attachments'::regclass
    ) THEN
        ALTER TABLE public.bot_media_attachments
            ADD CONSTRAINT bot_media_attachments_media_type_check
            CHECK (media_type IN ('image', 'video', 'document'));
    END IF;
END $$;

-- Tenant isolation: the backend uses the service-role key, but RLS is enabled
-- so any future anon/authenticated access is denied by default. Matches the
-- posture established in 025_enable_platform_admin_rls.sql and 029.
ALTER TABLE public.bot_media_attachments ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.bot_media_attachments IS
    'Per-chatbot media library (image/video/document) for outbound bot replies.';
COMMENT ON COLUMN public.bot_media_attachments.keywords IS
    'Trigger words matched against inbound messages to select this attachment.';
COMMENT ON COLUMN public.bot_media_attachments.meta_template_name IS
    'Meta approved template to pair the media with; blank for free-form sends.';

-- Privileges: see the equivalent note in 029. service_role needs explicit
-- DML plus sequence USAGE (the PK is bigserial, so INSERT fails without it).
-- Mirrors the grants on public.chatbots. anon and authenticated get nothing.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.bot_media_attachments TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.bot_media_attachments_id_seq TO service_role;
