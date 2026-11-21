# Security and Tenant Isolation

Payment status (2026-09-15): CHIP replaces ToyyibPay and HitPay in the current code.
Local tests and a provider sandbox payment are verified; deployment is pending.
Use the [CHIP payment guide](CHIP_PAYMENT_GATEWAY.md) for current routes, configuration, and rollout.

## Security Model

The platform is a multi-tenant server-side application.

Security depends on:

- JWT validation
- Role checks
- Company-scoped data access
- Chatbot ownership checks
- Backend-only secrets
- Safe external webhook validation
- Idempotent payment processing
- Secure deployment configuration

## Authentication

The backend issues and validates JWTs.

Requirements:

- Use a strong production JWT secret.
- Enforce expiry.
- Reject inactive users.
- Do not log tokens.
- Do not expose tokens in URLs.
- Avoid returning raw authentication exceptions.
- Add rate limiting to login, registration, password-reset, and OTP endpoints.

Logout removes the client token. There is no documented server-side token revocation.

## OTP and Password Reset

OTP values must never be printed or logged in production.

Required controls:

- Short expiry
- Attempt limits
- Rate limiting
- One-time use
- Email ownership verification
- Safe error responses
- No account-existence disclosure where avoidable

OTP logging is a production-blocking issue until removed or safely restricted.

## Tenant Isolation

### Core rule

Every company-owned operation must derive company context from the authenticated request.

Never use a company ID supplied by the frontend as the sole authorization control.

### Required checks

- User belongs to the company
- User status is active
- Role allows the action
- Chatbot belongs to the company
- Conversation belongs to an accessible chatbot/company
- CRM lead belongs to the company
- Channel belongs to the company
- Billing order belongs to the company
- Team member changes stay within the company

### Testing

For every resource route, include a cross-company denial test.

## Supabase Privileged Access

The backend uses privileged Supabase access.

This is acceptable only when:

- Credentials remain server-side
- Repositories scope all tenant data
- Public endpoints cannot reach unrestricted repository operations
- Logs do not expose credentials
- Deployment secrets are protected

The live RLS state must be reviewed separately. The absence of RLS SQL in the repository does not prove whether RLS is enabled or disabled in Supabase.

## Frontend Security

The frontend stores JWTs in browser storage.

Risks:

- XSS can expose tokens
- Unsafe `innerHTML` can execute untrusted content
- External content must not be inserted as raw HTML

Requirements:

- Prefer DOM node creation and `textContent`
- Sanitize any necessary HTML
- Avoid inline rendering of untrusted model, message, or file content
- Review every use of `innerHTML`
- Apply a production Content Security Policy where practical

## Webhook Security

### CHIP Collect

- Verify RSA/SHA256 `X-Signature` over the original callback bytes, then fetch authoritative purchase state
- Match stored purchase ID, reference, brand, mode, MYR, and exact integer amount
- Keep test payments separate; they cannot grant subscriptions or AI credit
- Enforce idempotency
- Never grant credit solely from frontend return parameters
- Record processing state

### Meta WhatsApp

- Verify webhook signatures
- Validate expected payload structure
- Deduplicate incoming messages

### Telegram and linked devices

- Verify Telegram webhook secrets and the raw-body HMAC-SHA512 signature on linked-device events
- Validate channel configuration
- Deduplicate incoming updates/messages
- Avoid exposing provider credentials

## Secrets

Secrets include:

- Supabase service-role key
- JWT secret
- AI-provider API keys
- Messaging provider tokens
- Meta app secret and access tokens
- Separate CHIP test/live API keys
- Email credentials

Rules:

- Store secrets in environment configuration or a secret manager.
- Never commit live secrets.
- Never send secrets to the browser.
- Never include secrets in test fixtures.
- Mask secrets in logs and support reports.
- Rotate exposed credentials immediately.

## Payment Security

AI-credit payment processing must preserve:

- Authentic callback verification
- Expected gateway and order identity
- Amount validation
- Idempotent paid handling
- Idempotent credit granting
- Atomic database operations
- Company-scoped order status
- Clear audit transactions

Frontend payment-return parameters are informational only.

## AI Security

Treat user messages and retrieved documents as untrusted content.

Controls:

- Keep system instructions separate.
- Do not include secrets in model context.
- Restrict tool or action capabilities.
- Validate structured model output.
- Test prompt-injection attempts.
- Avoid allowing retrieved content to override security instructions.

## Production Configuration

Before deployment:

- Disable debug mode
- Disable development tunnels
- Restrict CORS
- Use HTTPS
- Configure secure webhook URLs
- Protect logs
- Remove sensitive debug output
- Configure monitoring and alerting
- Confirm backup and recovery
