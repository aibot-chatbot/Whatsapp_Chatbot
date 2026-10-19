# Integrations

Payment status (2026-09-15): CHIP replaces ToyyibPay and HitPay in the current code.
Local tests and a provider sandbox payment are verified; deployment is pending.
Use the [CHIP payment guide](CHIP_PAYMENT_GATEWAY.md) for current routes, configuration, and rollout.

## Overview

The platform integrates with AI providers, messaging channels, Supabase, email services, and CHIP Collect.

All credentials must remain server-side.

## Supabase

### Purpose

- PostgreSQL database
- RPC execution
- Application persistence

### Main responsibilities

- Store tenant, chatbot, knowledge, conversation, CRM, integration, subscription, and credit data
- Execute atomic billing and credit operations

### Required configuration

- Supabase project URL
- Server-side service-role key

### Verification

- Confirm schema
- Confirm RPC definitions
- Confirm RLS state
- Confirm backup strategy

## OpenRouter

### Purpose

Provide paid-plan access to tenant-selected supported AI models through a common API.

### Flow

1. Chatbot configuration selects a provider/model.
2. AI routing resolves the model.
3. The backend sends the request.
4. Usage data is recorded.
5. AI credit may be charged.

### Verification

- API key
- Model identifiers
- Timeout behavior
- Provider error mapping
- Usage metadata

## DeepSeek

### Purpose

Direct AI model access for the Free trial provider policy.

Free trial generative access is forced to `deepseek-v4-flash`. Paid-plan
generative calls use the tenant-selected supported model through OpenRouter and
do not fall back to direct DeepSeek.

### Verification

- API key
- Model mapping
- Timeout behavior
- Error handling
- Usage logging

## Gemini

### Purpose

Used by the current embedding infrastructure for vector generation and semantic
retrieval. Tenant-selected generative Gemini models, when available, are routed
through the central AI router rather than through this embedding path.

### Verification

- Active embedding call paths
- API key
- Embedding model
- Cataloged generative model identifiers, where routed through OpenRouter
- Rate limits
- Failure handling

## Web Widget

The one channel we host ourselves. There is no vendor, no account for the
tenant to create, and no plan slot consumed.

### Purpose

- A hosted chat page at `/chat/<public_key>` that needs no website and no install
- An embeddable bubble (`/widget.js`) and an inline iframe (`/widget/<public_key>`)

### Connection flow

1. Opening the publish screen calls `ensure_widget`, which creates the record
   if it is absent and generates a `public_key`.
2. New records are created enabled, so the share link works before the tenant
   has touched a setting. The column default stays `false`, so existing rows
   are unchanged.
3. The tenant shares the link, prints its QR code, or hands the snippet to
   whoever maintains their website.

### Runtime flow

1. Visitor opens the share link or the embed.
2. `resolve_public_widget` rejects a disabled widget and enforces the domain
   allowlist.
3. Per-session message caps apply.
4. AI response is generated and returned.

### Verification

- Share link with the widget enabled and disabled
- Domain allowlist
- Session cap
- Public config leaks no internal field
- `dashboard_health_service` reports an enabled widget as a connected channel

## Telegram

### Connection flow

1. Authorized user submits bot token and chatbot selection.
2. Backend validates token with `getMe`.
3. Channel record is stored.
4. Webhook is configured with `setWebhook`, passing the generated webhook
   secret as `secret_token`.
5. Incoming updates are processed and deduplicated.

### Runtime flow

1. Telegram calls the webhook, sending the registered secret in the
   `X-Telegram-Bot-Api-Secret-Token` header.
2. Backend rejects a mismatched header with 403. A missing header is accepted
   and logged, because channels connected before `secret_token` was registered
   do not send one; the 256-bit path secret remains the primary gate.
3. Duplicate updates are ignored.
4. Conversation and chatbot context are resolved.
5. AI response is generated.
6. Reply is sent through Telegram.

### Verification

- Connect
- Disconnect
- Reconnect
- Incoming text
- Duplicate update
- Delivery failure
- Secret rotation
- Webhook posted with a wrong secret token header is rejected
- Reconnect on a channel that is not currently counted passes the channel limit
  check, and a live channel is not re-checked

## WasenderAPI

### Connection flow

1. Authorized user submits connection information.
2. Backend stores channel credentials.
3. Webhook is configured.
4. Channel status is recorded.

### Runtime flow

1. Wasender sends an inbound message webhook.
2. Backend validates the channel secret.
3. Duplicate messages are ignored.
4. Chatbot response is generated.
5. Outgoing reply is sent.
6. Failed deliveries may enter retry processing.

### Verification

- Connection
- Disconnection
- Incoming messages
- Duplicate messages
- Failed outgoing messages
- Retry limits
- Worker startup behavior
- Credential protection

## Meta WhatsApp Cloud API

### Setup flow

The project includes an Embedded Signup-related backend flow.

Expected behavior:

1. Authorized user starts Meta Embedded Signup.
2. The frontend receives setup data.
3. Backend exchanges or validates Meta credentials.
4. Phone and business metadata are stored.
5. Webhook traffic is handled through the WhatsApp webhook route.

### Runtime flow

1. Meta sends webhook payload.
2. Backend verifies the signature.
3. Duplicate messages are ignored.
4. Conversation and chatbot context are resolved.
5. AI response is generated.
6. Reply is sent through the Cloud API.

### Verification

- Meta app configuration
- Embedded Signup configuration ID
- Business approval status
- Phone-number registration
- Token expiry and renewal
- Webhook verification
- Signature validation
- Disconnect behavior

## CHIP Collect

CHIP is the current backend gateway for subscriptions and AI-credit top-ups.
See the [CHIP payment guide](CHIP_PAYMENT_GATEWAY.md) for the payment flow and deployment status.

Active routes: `POST /api/billing/subscription/checkout`,
`POST /api/billing/chip/checkout`, and `POST /api/billing/chip/callback`.
The optional event webhook uses `POST /api/billing/chip/webhook` with its own public key.

Subscription checkout accepts `billing_term_months` with a strict value of 1,
3, 6, or 12. Prices are resolved from the server-owned integer-sen catalogue;
the frontend cannot submit a price. CHIP charges the full term upfront, while
the active subscription exposes a separate monthly allowance window. Deploy
`data/079_prepaid_subscription_terms.sql` before deploying this contract.

### Verification

- Test/live configuration and mode isolation
- Checkout creation
- Callback authenticity
- Return URL
- Duplicate callbacks
- Order status
- Credit grant
- Reconciliation

## Email

Email is used for account or password-related flows.

### Verification

- Sender configuration
- SMTP or active email provider
- Delivery failure behavior
- No OTP leakage in logs
- Retry and support procedures

## Integration Test Rules

- Mock external APIs in automated tests.
- Use controlled test accounts for manual verification.
- Never use production credentials in test fixtures.
- Record the date and outcome of live integration verification.
- Require human approval before live payment or messaging tests.
