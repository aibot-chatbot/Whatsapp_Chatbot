-- A Telegram provider bot supports one webhook and therefore one active owner.
-- Resolve existing duplicate active identities with the authorized owner first.
-- This fails without modifying channel history if duplicates remain.
CREATE UNIQUE INDEX IF NOT EXISTS telegram_channels_active_provider_identity_uidx
    ON public.telegram_channels (telegram_bot_id)
    WHERE is_active = true;
