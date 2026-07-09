-- 006_create_company_subscription_orders.sql
-- Idempotent migration to create the subscription payment orders table.
--
-- This table tracks one-off subscription checkout orders processed
-- through ToyyibPay (or another supported payment gateway).
-- It is intentionally separate from ai_credit_topup_orders because
-- the fulfilment logic is different: a subscription order activates
-- or upgrades a plan, allocates AI credits, and may trigger trial-to-paid
-- chatbot conversion.
--
-- Safe to run multiple times (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS company_subscription_orders (
    id              BIGSERIAL PRIMARY KEY,
    company_id      BIGINT NOT NULL,
    subscription_id BIGINT NOT NULL,
    new_plan_id     BIGINT NOT NULL,
    order_reference UUID NOT NULL UNIQUE,
    amount_sen      INTEGER NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    payment_gateway VARCHAR(20),
    gateway_order_id VARCHAR(255),
    checkout_url    TEXT,
    payment_reference VARCHAR(255),
    paid_at         TIMESTAMPTZ,
    credited_at     TIMESTAMPTZ,
    idempotency_key VARCHAR(255) UNIQUE,
    created_by_user_id BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ
);

-- Index for fast lookup by gateway order ID (used in payment callbacks).
CREATE INDEX IF NOT EXISTS idx_cso_gateway
    ON company_subscription_orders (payment_gateway, gateway_order_id);

-- Index for fast lookup by company (admin list view).
CREATE INDEX IF NOT EXISTS idx_cso_company
    ON company_subscription_orders (company_id, created_at DESC);

-- Index for idempotency key lookups.
CREATE INDEX IF NOT EXISTS idx_cso_idempotency
    ON company_subscription_orders (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
