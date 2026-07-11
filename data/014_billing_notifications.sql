-- 014_billing_notifications.sql
-- Phase 4J: Billing notifications and customer communication.
--
-- Creates the billing_notifications table for in-app notification history
-- covering subscription expiry reminders, grace-period alerts, payment
-- confirmations, activation outcomes, and AI-credit threshold alerts.
--
-- Requirements:
--  - Company-scoped with tenant isolation.
--  - Deduplication via unique event_key.
--  - Indexed for company-wide listing and unread filtering.
--  - Service-role write, no PUBLIC write access.
--  - Safe text only — no secrets, provider payloads, or stack traces.

CREATE TABLE IF NOT EXISTS public.billing_notifications (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL,
    notification_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    reference_type TEXT,
    reference_value TEXT,
    event_key TEXT NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

COMMENT ON TABLE public.billing_notifications IS
    'Company-scoped billing notifications for subscription, payment, and AI-credit events.';

COMMENT ON COLUMN public.billing_notifications.company_id IS
    'Company that owns this notification. Used for tenant isolation.';

COMMENT ON COLUMN public.billing_notifications.notification_type IS
    'Category: subscription_expiry_reminder, grace_period, payment_confirmed, activation_completed, ai_credit_low, etc.';

COMMENT ON COLUMN public.billing_notifications.severity IS
    'Severity level: info, warning, critical.';

COMMENT ON COLUMN public.billing_notifications.event_key IS
    'Unique deduplication key, e.g., "subscription:{id}:renewal_reminder:7d:{period_end}".';

COMMENT ON COLUMN public.billing_notifications.reference_type IS
    'Type of associated resource: order_reference, subscription_id, company_id.';

COMMENT ON COLUMN public.billing_notifications.reference_value IS
    'Value of the associated resource reference.';

COMMENT ON COLUMN public.billing_notifications.metadata IS
    'Safe structured metadata - never secrets or provider payloads.';

-- Unique constraint on event_key for idempotent insertion.
-- Using a unique index rather than UNIQUE constraint to allow NULL
-- event_key values if ever needed (though all current events require one).
CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_notifications_event_key
    ON public.billing_notifications (event_key);

-- Index for company-scoped list queries with newest-first ordering.
CREATE INDEX IF NOT EXISTS ix_billing_notifications_company_created
    ON public.billing_notifications (company_id, created_at DESC);

-- Index for unread filtering with company scope.
CREATE INDEX IF NOT EXISTS ix_billing_notifications_company_unread
    ON public.billing_notifications (company_id, is_read, created_at DESC)
    WHERE is_read = FALSE;

-- Service-role permissions
GRANT SELECT, INSERT, UPDATE ON public.billing_notifications TO service_role;
GRANT USAGE ON SEQUENCE public.billing_notifications_id_seq TO service_role;

-- No PUBLIC access to billing_notifications table.
REVOKE ALL ON public.billing_notifications FROM PUBLIC;
