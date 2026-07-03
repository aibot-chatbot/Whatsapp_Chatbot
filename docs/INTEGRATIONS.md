# Integrations

## Overview

The platform integrates with AI providers, messaging channels, Supabase, email services, and ToyyibPay.

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

Provide access to multiple AI models through a common API.

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

Direct AI model access for configured chatbot flows.

### Verification

- API key
- Model mapping
- Timeout behavior
- Error handling
- Usage logging

## Gemini

### Purpose

Used in AI and/or embedding-related flows.

### Verification

- Active call paths
- API key
- Embedding model
- Generation model
- Rate limits
- Failure handling

## Telegram

### Connection flow

1. Authorized user submits bot token and chatbot selection.
2. Backend validates token.
3. Channel record is stored.
4. Webhook is configured.
5. Incoming updates are processed and deduplicated.

### Runtime flow

1. Telegram calls the webhook.
2. Backend validates the webhook secret.
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

## ToyyibPay

ToyyibPay is the active payment gateway for AI-credit top-ups.

See `BILLING_AND_AI_CREDIT.md` for the full payment flow.

### Verification

- Production configuration
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
