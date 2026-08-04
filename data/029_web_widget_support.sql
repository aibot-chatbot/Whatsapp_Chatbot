-- 029_web_widget_support.sql
-- Website chat widget: embeddable chat bubble, iframe embed and public share link.
--
-- Each chatbot may have exactly one widget configuration. The widget is
-- addressed publicly by an unguessable `public_key` so the internal
-- chatbot_id is never exposed in customer-facing embed snippets.

CREATE TABLE IF NOT EXISTS public.chatbot_web_widgets (
    id                       bigserial PRIMARY KEY,
    chatbot_id               bigint NOT NULL
                                 REFERENCES public.chatbots (id) ON DELETE CASCADE,
    company_id               bigint NOT NULL,

    -- Public addressing
    public_key               text NOT NULL,
    is_enabled               boolean NOT NULL DEFAULT false,

    -- Security: empty array means "any domain" (useful while testing)
    allowed_domains          text[] NOT NULL DEFAULT '{}',

    -- Appearance / branding
    display_name             text NOT NULL DEFAULT 'Chat with us',
    subtitle                 text NOT NULL DEFAULT 'We typically reply instantly',
    primary_color            text NOT NULL DEFAULT '#4F46E5',
    text_color               text NOT NULL DEFAULT '#FFFFFF',
    avatar_url               text,
    launcher_position        text NOT NULL DEFAULT 'right',
    launcher_label           text NOT NULL DEFAULT '',
    welcome_message          text NOT NULL DEFAULT 'Hi! How can I help you today?',
    input_placeholder        text NOT NULL DEFAULT 'Type your message...',
    suggested_questions      text[] NOT NULL DEFAULT '{}',

    show_branding            boolean NOT NULL DEFAULT true,
    branding_text            text NOT NULL DEFAULT 'Powered by AI',

    -- Lead capture
    collect_lead             boolean NOT NULL DEFAULT false,
    lead_prompt              text NOT NULL DEFAULT
                                 'Before we start, may I have your details?',
    lead_require_name        boolean NOT NULL DEFAULT true,
    lead_require_email       boolean NOT NULL DEFAULT true,
    lead_require_phone       boolean NOT NULL DEFAULT false,

    -- Abuse control
    max_messages_per_session integer NOT NULL DEFAULT 50,

    created_at               timestamp with time zone NOT NULL DEFAULT now(),
    updated_at               timestamp with time zone NOT NULL DEFAULT now()
);

-- One widget per chatbot.
CREATE UNIQUE INDEX IF NOT EXISTS idx_chatbot_web_widgets_chatbot
    ON public.chatbot_web_widgets (chatbot_id);

-- Public key lookups happen on every widget request.
CREATE UNIQUE INDEX IF NOT EXISTS idx_chatbot_web_widgets_public_key
    ON public.chatbot_web_widgets (public_key);

CREATE INDEX IF NOT EXISTS idx_chatbot_web_widgets_company
    ON public.chatbot_web_widgets (company_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chatbot_web_widgets_position_check'
          AND conrelid = 'public.chatbot_web_widgets'::regclass
    ) THEN
        ALTER TABLE public.chatbot_web_widgets
            ADD CONSTRAINT chatbot_web_widgets_position_check
            CHECK (launcher_position IN ('right', 'left'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chatbot_web_widgets_max_messages_check'
          AND conrelid = 'public.chatbot_web_widgets'::regclass
    ) THEN
        ALTER TABLE public.chatbot_web_widgets
            ADD CONSTRAINT chatbot_web_widgets_max_messages_check
            CHECK (max_messages_per_session BETWEEN 1 AND 500);
    END IF;
END $$;

-- Tenant isolation: the backend uses the service-role key, but RLS is enabled
-- so that any future anon/authenticated access is denied by default.
ALTER TABLE public.chatbot_web_widgets ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.chatbot_web_widgets IS
    'Per-chatbot website widget configuration (embed script, iframe, share link).';
COMMENT ON COLUMN public.chatbot_web_widgets.public_key IS
    'Unguessable public identifier used in embed snippets instead of chatbot_id.';
COMMENT ON COLUMN public.chatbot_web_widgets.allowed_domains IS
    'Hostname allowlist for embedding. Empty array allows any origin.';

-- Privileges: the backend connects as service_role, which does NOT inherit
-- table privileges automatically when the table is created outside the
-- dashboard SQL editor (e.g. via the Management API or a direct psql
-- connection). Without these grants every query fails with 42501
-- "permission denied for table". Mirrors the grants on public.chatbots.
-- anon and authenticated are deliberately NOT granted DML: the widget is
-- served through the backend, never queried directly from the browser.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.chatbot_web_widgets TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.chatbot_web_widgets_id_seq TO service_role;
