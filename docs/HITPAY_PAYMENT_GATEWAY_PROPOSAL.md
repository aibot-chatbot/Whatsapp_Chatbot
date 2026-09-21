# HitPay Payment Gateway Integration Proposal

> Historical proposal: active integration retired by the [CHIP replacement](CHIP_PAYMENT_GATEWAY.md).

Status: approved implementation proposal; HitPay remains dormant until the
focused test, security, merchant-dashboard, and controlled-pilot gates in this
document are complete.

This document is the operator and implementation reference for adding HitPay
to the existing Flask and Supabase billing flow. It contains no credentials,
does not authorize a live payment, and does not apply a Supabase migration.

## 1. Executive summary

HitPay will become the primary Malaysian subscription-payment gateway while
ToyyibPay remains available during rollout and for historical orders. The
platform uses one HitPay business account. Authenticated companies are
isolated SaaS tenants, not separate HitPay merchants or submerchants.

HitPay-hosted checkout keeps card numbers, wallet credentials, and bank
credentials outside this application. The existing Flask backend remains the
authority for creating a local order, authorizing the tenant, receiving and
verifying events, activating subscriptions, allocating included credits, and
reconciling missed events.

The browser redirect is only a customer navigation result. A plan is never
activated from that redirect. Activation requires a verified HitPay event plus
an authoritative HitPay status lookup, or an authoritative reconciliation that
reaches the same activation service.

### Implementation safety boundary

- No HitPay credential, webhook registration, merchant setting, or production
  environment is changed by this implementation.
- No live payment, refund, recurring charge, or customer message is sent.
- No production data is modified.
- Migration 049 belongs to automation events. It is not changed, reapplied,
  rolled back, or used for payment processing.
- A future migration numbered after 049 is only a reviewed proposal until a
  separate explicit approval authorizes application in a named environment.

## 2. Goals and non-goals

### Goals

- Offer card, FPX, DuitNow QR, and Touch 'n Go through HitPay-hosted checkout
  when each method is enabled for the merchant account.
- Support one-time initial purchases and manual monthly renewals.
- Keep all tenant, order, amount, and activation checks in the backend.
- Make webhook delivery, provider status, reconciliation, and database health
  visible to operators.
- Preserve existing ToyyibPay order history, callbacks, and fallback path
  during rollout.
- Make a provider timeout safe: never issue an uncontrolled second payment
  request.

### Non-goals for the first HitPay phase

- No HitPay Platform API or tenant-owned merchant accounts.
- No raw card or wallet processing in Flask or the frontend.
- No automatic FPX, DuitNow, or Touch 'n Go renewal.
- No automatic card renewal until recurring-billing events, cancellation, and
  correlation are separately validated.
- No migration execution, RLS change, RPC deployment, or production-data
  cleanup as part of this proposal.

## 3. Payment methods

HitPay treats DuitNow and Touch 'n Go as distinct payment methods. A customer
may scan a DuitNow QR code using a participating Touch 'n Go wallet, but that
does not make the two merchant capabilities interchangeable.

| Payment method | Initial purchase | Manual monthly renewal | Automatic renewal in first phase |
|---|---:|---:|---:|
| Credit/debit card | Yes | Yes | No - enable only after recurring-billing validation |
| FPX | Yes | Yes | No |
| DuitNow QR | Yes | Yes | No |
| Touch 'n Go | Yes, if enabled by the merchant account | Yes, if enabled by the merchant account | No - later capability gate |

The application does not force a payment-method list into each payment request.
The merchant dashboard is the source of truth for enabled methods, and the
test matrix verifies that the hosted checkout displays the expected methods.

Official provider references:

- [HitPay saved payment methods and recurring-payment guide](https://docs.hitpayapp.com/apis/guide/save-payment-method)
- [HitPay FPX](https://docs.hitpayapp.com/payment-methods/fpx)
- [HitPay DuitNow](https://docs.hitpayapp.com/payment-methods/duitnow)
- [HitPay Touch 'n Go](https://docs.hitpayapp.com/payment-methods/touchngo)

Availability, fees, settlement timing, and sandbox support are merchant-
account and provider concerns. Recheck the provider dashboard before each
rollout stage; do not infer availability from a frontend control.

## 4. Customer payment experience

### Manual monthly payment

The customer selects a plan in the application and submits the checkout form.
The application creates one internal pending order for the authenticated
company, then requests one non-repeatable HitPay payment request. The customer
is redirected to the HitPay-hosted page, where the enabled card, FPX, DuitNow,
and Touch 'n Go methods are presented.

Each billing period receives a new local order reference and a new hosted
checkout. A completed previous order must not be reused for a new charge.

### Automatic monthly renewal

Automatic renewal is not enabled by this phase. The first candidate is card
recurring billing through HitPay saved-payment capability. Before enabling it,
the team must validate:

1. recurring authorization and event correlation;
2. exact order, amount, currency, and tenant matching;
3. retry and duplicate-event behavior;
4. cancellation and saved-method deletion behavior;
5. reconciliation of a missed recurring event; and
6. operator visibility for a failed or overdue renewal.

FPX and DuitNow customers remain on manual renewal. Touch 'n Go remains behind
a capability gate until the merchant account and sandbox or controlled-pilot
events prove that its saved-payment workflow is supported.

## 5. Multi-tenant payment model

The platform has one HitPay business account that receives SaaS subscription
revenue. A tenant company is represented by the authenticated application
context, not by a HitPay merchant account.

The following rules are mandatory:

- `company_id` and `user_id` come from the authenticated server context.
- The browser cannot select a company, merchant, or payment gateway for the
  order.
- A server-controlled gateway setting may select HitPay globally or for a
  small, explicitly configured canary company list.
- Every order has a unique internal order reference before any provider call.
- The provider reference, provider request ID, currency, and exact amount are
  matched against the stored order before activation.
- Order history, status lookup, reconciliation, and support actions are
  company-scoped.
- Only the minimum customer information required by HitPay is sent.
- Provider API keys and webhook salts remain server-side.

HitPay Platform APIs are unnecessary for this model. They would become
relevant only if tenant companies later need their own HitPay merchants,
settlements, or onboarding flows.

Reference: [HitPay Platform APIs](https://docs.hitpayapp.com/apis/guide/platform-apis).

## 6. Integration architecture

The current route-service-repository billing boundary is retained. HitPay is a
provider adapter, not a second subscription system.

```text
Authenticated browser
        |
        v
Flask billing route -- derives company/user context and plan amount
        |
        v
Subscription checkout service -- creates local pending order first
        |
        v
HitPay API -- creates hosted payment request; returns checkout URL
        |
        v
HitPay-hosted checkout -- card, FPX, DuitNow, or Touch 'n Go

HitPay event webhook --> raw-body HMAC check --> authoritative GET status
                                      |
                                      v
                          order/reference/amount/currency checks
                                      |
                                      v
                 shared payment callback and activation/credit service

Scheduled reconciliation --> HitPay GET or exact-reference search
                                      |
                                      v
                 the same verified activation path, never a second charge
```

### Create-checkout sequence

1. Authenticate the request and derive `company_id` and `user_id` from the
   server context.
2. Validate the plan against the server-side plan catalogue and calculate the
   amount in integer sen.
3. Create the local pending subscription order, including its activation
   sequence key and internal reference.
4. Call HitPay's payment-request endpoint with MYR, the exact amount, the
   internal reference, and the server-owned redirect URL.
5. Treat a definite provider rejection as a safe no-bill failure. Release the
   local checkout claim only when no provider request could have been created.
6. Treat a timeout, 5xx response, malformed success response, missing ID, or
   missing checkout URL as ambiguous. Mark the order for reconciliation and do
   not issue another request automatically.
7. Attach the HitPay request ID and hosted checkout URL to the still-pending
   local order using a guarded update.
8. Return only the safe checkout result to the browser.

### Completion sequence

1. Receive the provider event at the configured HTTPS webhook endpoint.
2. Read the exact raw request body before parsing JSON.
3. Verify the `Hitpay-Signature` HMAC with the environment-specific webhook
   salt.
4. Accept only the event/object combinations enabled for this phase.
5. Re-fetch the payment request from HitPay using the server-side API key.
6. Normalize the authoritative response and require a successful payment for
   a completed status.
7. Match provider request ID, internal reference, MYR currency, and exact
   integer-sen amount to the local order.
8. Invoke the existing idempotent subscription activation and included-credit
   allocation service.
9. Return a success response for a duplicate event that is already safely
   completed; return a retryable server error for temporary database or
   provider failures.

## 7. Application reference

The names below describe the existing billing surface and the HitPay behavior
that must remain compatible with it.

| Surface | Purpose | Tenant or side-effect boundary |
|---|---|---|
| `POST /api/billing/subscription/checkout` | Creates a hosted subscription checkout | Requires authentication; company and user come from the token; does not activate a plan |
| `GET /api/billing/subscription/orders` | Lists subscription order history | Company-scoped and read-only |
| `GET /api/billing/subscription/orders/<reference>` | Reads one order and receipt-safe details | Company-scoped; provider secrets and raw payloads are excluded |
| `GET /api/billing/health` | Reports billing and provider readiness | Operator-visible; health checks must not expose secret values |
| Configured HitPay HTTPS webhook endpoint | Receives provider events | Provider-authenticated by HMAC; no browser token is trusted for payment proof |
| Subscription reconciliation job | Repairs missed webhooks and incomplete activation | Reuses the existing order and activation idempotency keys |

The browser may display the returned checkout URL and local order reference.
It must not receive the HitPay business API key, webhook salt, full provider
payload, or an authority to mark an order paid.

## 8. Environment-variable guide

Values below are placeholders only. Store secrets in the deployment secret
store, not in frontend assets, committed example files, logs, or test data.

| Variable | Required when | Safe placeholder or default | Operator meaning |
|---|---|---|---|
| `SUBSCRIPTION_PAYMENT_GATEWAY` | Selecting a default provider | `toyyibpay` | Server-controlled value: `toyyibpay` or `hitpay`; browser input is ignored |
| `HITPAY_CANARY_COMPANY_IDS` | Gradual rollout | empty | Optional comma-separated internal company IDs; invalid values must fail configuration validation |
| `HITPAY_ENABLED` | Any HitPay use | `false` | Dormant when false; enabling it without the checks below must produce degraded health |
| `HITPAY_ENV` | Any HitPay use | `sandbox` | `sandbox` or `production`; production requires an explicit rollout approval |
| `HITPAY_API_KEY` | Checkout creation or status lookup | `<server-secret>` | HitPay business API key; never expose or log |
| `HITPAY_WEBHOOK_SALT` | Webhook verification | `<server-secret>` | Salt for the exact raw-body HMAC; never expose or log |
| `HITPAY_REDIRECT_URL` | Hosted checkout | `https://<public-app>/billing/return` | Public HTTPS customer return URL; redirect is not payment proof |
| `HITPAY_WEBHOOK_URL` | HitPay event configuration | `https://<public-app>/<configured-hitpay-webhook-path>` | Public HTTPS event endpoint registered in the HitPay dashboard |
| `SUBSCRIPTION_CHECKOUT_EXPIRY_DAYS` | Hosted checkout | `1` | Integer from 1 through 100; limits how long a pending checkout is reusable |
| `SUPABASE_URL` | Existing application runtime | `<project-url>` | Existing Supabase project URL; use the approved environment only |
| `SUPABASE_SERVICE_ROLE_KEY` | Existing server-side repository access | `<server-secret>` | Server-side only; never place in browser code or provider payloads |
| `SECRET_KEY` | Existing Flask authentication/runtime | `<server-secret>` | Existing application secret; unrelated to HitPay signing |

The reconciliation scheduler is a deployment concern. Before HitPay is
selected for a tenant, the operator must confirm that the subscription
reconciliation job is enabled, has a bounded batch size, and can reach HitPay
and Supabase. If the implementation exposes a separate reconciliation feature
flag, keep it false until that job is deployed and verified.

### Environment separation

- Use separate HitPay sandbox and production keys and salts.
- Use a sandbox API base and sandbox checkout host for sandbox configuration.
- Do not copy a production key into a local test or CI environment.
- Do not print environment values as part of health output; report only
  presence, format, and last-known operational state.
- Changing the selected provider or enabling a canary is a rollout action and
  requires an approved change record.

## 9. HitPay merchant-dashboard checklist

Complete this checklist in the named HitPay environment and record the result
without copying secrets into the repository.

### Account and checkout

- [ ] Confirm the selected business account is the single SaaS merchant account.
- [ ] Confirm the settlement and business profile are owned by the platform,
      not by an individual tenant.
- [ ] Confirm the return URL is the intended public HTTPS application URL.
- [ ] Confirm card payments are enabled for the merchant account.
- [ ] Confirm FPX is enabled where the merchant account and region support it.
- [ ] Confirm DuitNow QR is enabled.
- [ ] Confirm Touch 'n Go availability and eligibility.
- [ ] Confirm the hosted checkout displays the enabled methods in a controlled
      test before rollout.

### Webhooks

- [ ] Register the application HTTPS webhook endpoint in the HitPay event
      settings.
- [ ] Subscribe only to the payment-request completion event required for the
      first phase.
- [ ] Keep recurring-billing events disabled until the recurring phase is
      approved and separately tested.
- [ ] Generate or retrieve the environment-specific webhook salt and store it
      in the deployment secret store.
- [ ] Confirm dashboard delivery attempts and response codes are visible to
      operators.
- [ ] Confirm no per-request webhook override is required; event webhooks are
      configured in the dashboard.

### API access

- [ ] Create or select the server-side business API key for the correct
      environment.
- [ ] Store the key only in the server secret store.
- [ ] Record the key rotation owner and date without recording the secret.
- [ ] Verify the API key can create and read a sandbox payment request before
      selecting HitPay for a tenant.

## 10. Webhook registration and rotation runbook

### Registering the first endpoint

1. Confirm the application has a public HTTPS route and that the deployment
   can read the HitPay API key and webhook salt.
2. Configure `HITPAY_WEBHOOK_URL` with the exact public endpoint URL.
3. Register that URL in the HitPay dashboard event settings.
4. Select the payment-request completion event only.
5. Send a provider test event or a controlled sandbox event, depending on what
   the merchant account supports.
6. Confirm the application verifies the signature before trusting event data,
   performs the authoritative HitPay status lookup, and leaves a duplicate
   event idempotent.
7. Confirm the operator health surface reports the webhook configuration as
   healthy and does not reveal the salt.

### Rotating the webhook salt

Coordinate the dashboard change and deployment change as one maintenance
operation. The application must not silently accept an unverified event while
the salt is being changed.

1. Identify the current environment and endpoint; never rotate sandbox and
   production values as if they were one credential.
2. Prepare the replacement salt in the deployment secret store without
   printing it.
3. Coordinate the provider dashboard salt update with the application
   deployment so that both sides use the same value.
4. Send a controlled test event after the change.
5. Monitor invalid-signature responses and reconciliation backlog.
6. Remove the old secret from the deployment secret store only after the
   provider and application agree on the new value and the delivery queue is
   healthy.

If the provider cannot expose both salts during rotation, use a short approved
maintenance window and rely on reconciliation for events that arrive during
the transition. Do not weaken signature validation to avoid a retry.

## 11. Webhook security and event reference

The endpoint is an untrusted network boundary. Only the following sequence is
valid:

1. Read the exact raw request bytes before JSON parsing or reserialization.
2. Calculate HMAC-SHA256 with the environment-specific webhook salt.
3. Compare the calculated digest to the `Hitpay-Signature` header using a
   constant-time comparison.
4. Reject missing, malformed, or mismatched signatures without changing order,
   subscription, or credit state.
5. Inspect `Hitpay-Event-Type` and `Hitpay-Event-Object`; ignore valid but
   unsupported event types without activating billing.
6. Parse the body only after signature verification.
7. Re-fetch the authoritative payment request from HitPay using the server API
   key.
8. Require exact provider request ID, internal reference, MYR currency, and
   amount-in-sen matches.
9. For a provider `completed` request, require a successful payment entry in
   the authoritative response.
10. Pass only normalized, verified data to the existing activation service.

### Event outcomes

| Condition | Billing action | Webhook outcome |
|---|---|---|
| Valid signature and authoritative completed payment | Activate through the shared idempotent service | Success |
| Valid signature, pending provider status | Leave local order pending | Success or retry-safe acknowledgement |
| Valid signature, failed/expired/cancelled provider status | Mark only the still-pending local order terminal | Success |
| Duplicate valid completion | No second activation or credit grant | Success |
| Invalid signature | No state change | Rejected |
| Reference, amount, currency, or provider-ID mismatch | No state change; manual review/reconciliation | Rejected or retry-safe error according to endpoint contract |
| Temporary database failure | No partial activation | Server error so provider can retry |
| Temporary HitPay status lookup failure | No state change | Server error or reconciliation retry |

Never log API keys, webhook salts, full event bodies, card numbers, wallet
credentials, bank account information, or unredacted customer payment data.
Log only the internal order reference, safe provider status, bounded error code,
and correlation metadata needed for operations.

References:

- [HitPay event webhooks](https://docs.hitpayapp.com/apis/guide/events)
- [HitPay online payment flow](https://docs.hitpayapp.com/apis/guide/online-payments)

## 12. Server availability, outage, and recovery

HitPay does not require a separate payment server. It does require one
publicly reachable HTTPS endpoint for event delivery. The existing Flask
deployment can host the checkout route and webhook route together.

### Normal operation

- HitPay-hosted checkout handles payment credentials.
- HitPay sends the completion event to Flask.
- Flask verifies the event and re-fetches authoritative status.
- The shared callback service performs idempotent activation and credit
  allocation.
- The scheduled reconciliation job checks pending or ambiguous orders.

### When Flask is temporarily unavailable

1. Do not create a second payment request from a customer retry based only on a
   timeout or an unchanged browser page.
2. Restore the application endpoint and database connectivity.
3. Inspect HitPay delivery attempts and the local pending-order backlog.
4. Run bounded reconciliation. It must query HitPay by stored provider request
   ID or search by the exact internal reference when the create response was
   ambiguous.
5. Process a completed payment through the same callback and activation service.
6. Leave pending payments pending and allow provider retries or a later
   reconciliation pass.
7. Route mismatched or multiply matched references to manual review.

The provider timeout rule is strict: an ambiguous create call is not evidence
that no charge exists. Search HitPay by the unique internal reference before
any operator considers a new checkout.

### What the outage must not do

- It must not activate a plan from the redirect page.
- It must not grant included credits from a client-supplied status.
- It must not issue uncontrolled second charges.
- It must not cross company boundaries while searching or reconciling.
- It must not hide a database failure behind a successful webhook response.

The health report is observational. A degraded health result keeps the health
endpoint usable for operators; it does not bypass payment verification or
change tenant authorization.

## 13. Reconciliation and outage-recovery runbook

The existing subscription reconciliation job is the recovery path for missed
webhooks and incomplete activation. It is safe to rerun because activation and
credit allocation use existing idempotency keys.

### Before running reconciliation

- Confirm the HitPay environment and API key are the intended pair.
- Confirm Supabase connectivity and that the subscription order repository is
  readable.
- Confirm the provider endpoint is reachable from the worker environment.
- Confirm no operator is attempting a duplicate checkout for the same period.
- Record the incident or correlation reference without recording payment
  credentials.

### Bounded recovery procedure

1. Start with a dry run or a single internal order reference.
2. For an order with a stored HitPay request ID, fetch that request's
   authoritative status.
3. For an ambiguous create outcome with no stored provider ID, search HitPay
   by the exact internal order reference and require one exact match.
4. Match provider request ID, internal reference, MYR, and exact amount in sen.
5. If status is completed and the payment entry is successful, pass the
   normalized result to the shared callback service.
6. If status is pending, make no billing-state change; schedule a later pass.
7. If status is failed, expired, or cancelled, terminalize only the local
   pending order. Never downgrade a paid or credited order.
8. If no match, multiple matches, or any mismatch exists, stop and create a
   manual-review item.
9. Review the final counts and the remaining reconciliation backlog.

The job supports a bounded batch, dry-run mode, a specific order reference,
and an optional company filter. Use the repository's documented module entry
point rather than a hand-written provider request. A scheduler should run it
regularly in one coordinated worker. If multiple app processes are used,
avoid independent uncoordinated schedulers that can create duplicate work.

### Recovery completion evidence

Record:

- the environment and time window;
- orders scanned, completed, already completed, conflicts, and failures;
- whether the provider lookup used stored ID or exact-reference search;
- the operator who approved any manual review; and
- the post-recovery health and backlog state.

Do not record full provider payloads or secrets in the incident report.

## 14. Operator-visible billing health

The operator billing health surface must expose HitPay readiness without
exposing secrets or causing normal application requests to fail.

### Required states

| State | Meaning | Operator action |
|---|---|---|
| `disabled` | HitPay is not selected and no HitPay canary is active | No HitPay incident; ToyyibPay remains the active path |
| `healthy` | HitPay is selected or canary-enabled, required configuration is present, the order table is reachable, and reconciliation is configured with recent evidence | Continue normal monitoring |
| `degraded` | HitPay is enabled or selected, but a required credential/configuration, database check, webhook readiness check, or reconciliation freshness check is missing or failing | Do not widen rollout; inspect the reason list and recover the failing dependency |

The response should identify safe component names and reason codes, for example
configuration incomplete, webhook not configured, order table unavailable,
status lookup unavailable, or reconciliation stale. It must not include API
keys, salts, authorization headers, full error payloads, or customer payment
data.

### Degraded-status contract

- Enabling HitPay while the required configuration is incomplete must visibly
  report `degraded`, not silently report `ok`.
- A missing `automation_events` table is not a HitPay payment dependency and
  must not be used as a reason to deny ordinary user workflows. The separate
  automation health contract may report its own degraded state.
- A missing subscription-order table or unavailable billing database must be
  visible to operators and must prevent unverified payment activation.
- Health reporting itself should return a stable operator-readable response
  even when a dependency is unavailable.
- The health endpoint must remain safe for repeated polling and must not mutate
  billing or customer data.

## 15. Data and migration proposal

Existing subscription orders and subscription records can hold most HitPay
information: internal order reference, company ID, plan, integer-sen amount,
payment gateway, provider request ID, hosted checkout URL, status, activation
state, and safe timestamps.

### Proposed future migration after 049

A future migration numbered after migration 049 should add uniqueness
protection for the pair `(payment_gateway, gateway_order_id)` when both values
are present. Before that migration is applied in any environment:

1. inspect for existing duplicate pairs;
2. disposition duplicates through an approved, reversible data procedure;
3. review the migration for partial-index, null, and rollback behavior;
4. verify the target Supabase environment and migration history; and
5. obtain explicit approval for the named environment.

The proposed uniqueness rule is a database guardrail. Application checks and
tenant-scoped provider matching remain necessary even after it exists.

### Migration 049 boundary

Migration 049 defines `automation_events`. It is unrelated to HitPay payment
requests, payment webhooks, subscription activation, and reconciliation. Do
not edit, reapply, roll back, or use migration 049 as part of this integration.
If that table is unavailable, report the automation integration as degraded and
preserve the existing fail-open user workflow contract; do not block or mutate
HitPay payment state to compensate.

### Supabase operating rules

- Keep Supabase service-role access in server-side repositories only.
- Do not add payment RLS policies or RPCs as an undocumented shortcut.
- Do not expose payment-order tables or provider secrets to browser clients.
- Treat schema access errors as health/reconciliation evidence, not as proof of
  payment success.
- Apply any future migration only through the approved Supabase change process.

## 16. Rollout plan

1. Review this proposal with the merchant, security, billing, and operations
   owners.
2. Confirm the HitPay account, enabled methods, event settings, redirect URL,
   and secret-store placeholders without activating production payments.
3. Implement HitPay in dormant sandbox mode while ToyyibPay remains default.
4. Run focused unit, route, callback, tenant-isolation, duplicate, timeout,
   and reconciliation tests.
5. Validate card checkout, signed completion webhooks, duplicate delivery,
   invalid signatures, mismatches, and provider failures.
6. Validate Touch 'n Go sandbox events if the merchant account exposes them.
7. Enable HitPay for one internal tenant through a server-controlled canary.
8. Conduct an explicitly approved low-value FPX and DuitNow production pilot if
   those methods still lack usable sandbox support.
9. Review operator health, delivery attempts, reconciliation evidence, and
   tenant-scoped order history after the pilot.
10. Make HitPay the default only after the pilot and rollback path are signed
    off; retain ToyyibPay support for existing and fallback orders.
11. Consider automatic card renewal only after recurring event correlation,
    cancellation, failure recovery, and reconciliation are independently
    accepted.

Rollback means changing the server-controlled selection back to ToyyibPay for
new checkouts and continuing to reconcile already-created HitPay orders. It
does not mean deleting HitPay orders or ignoring provider callbacks.

## 17. Sandbox test matrix and controlled production pilot

### Automated test matrix

| Area | Required case | Expected result |
|---|---|---|
| Configuration | HitPay disabled | No HitPay request; existing ToyyibPay default remains usable |
| Configuration | Invalid environment, missing API key, or invalid HTTPS URL | Safe configuration error and degraded health when HitPay is selected |
| Checkout | Valid plan and authenticated company | Local order is written first; one hosted request is created; safe URL returned |
| Checkout | Browser attempts to choose another company or gateway | Server ignores the attempt; authenticated context remains authoritative |
| Checkout | HitPay 4xx rejection | Definite no-bill failure releases only the safe local checkout claim |
| Checkout | Timeout, 5xx, malformed success, missing ID, or missing URL | Order is marked for reconciliation; no automatic second request |
| Checkout | Existing reusable pending order | Existing safe checkout is reused only for the same tenant, plan, and period |
| Hosted page | Card | Card checkout is available when merchant dashboard enables it |
| Hosted page | FPX | FPX appears when merchant account and environment support it |
| Hosted page | DuitNow QR | DuitNow appears when enabled |
| Hosted page | Touch 'n Go | Touch 'n Go appears only when enabled and available |
| Webhook | Exact raw-body valid HMAC | Event may proceed to authoritative lookup |
| Webhook | Changed body, missing signature, wrong salt, or malformed signature | No billing mutation |
| Webhook | Unsupported event type/object | Ignored or safely acknowledged; no activation |
| Webhook | Provider ID, reference, currency, or amount mismatch | No activation; manual review/retry-safe outcome |
| Webhook | Completed status without a successful payment entry | No activation |
| Webhook | Duplicate completed event | One activation and one credit allocation at most |
| Webhook | Temporary Supabase failure | Server error; provider can retry; no partial state claim |
| Reconciliation | Missed completion webhook with stored provider ID | Authoritative lookup recovers the order |
| Reconciliation | Ambiguous create with exact-reference provider match | Existing provider request is reconciled; no second charge |
| Reconciliation | No match or multiple matches | Manual review; no activation |
| Tenant isolation | Tenant A accesses Tenant B order/reference | Not found or denied; no data leakage |
| Compatibility | Existing ToyyibPay order and callback | Existing behavior remains green |
| Health | HitPay enabled with missing config, database, or reconciliation evidence | Operator-visible `degraded` state, no secret leakage |

### Controlled production pilot

The pilot is a production action and needs explicit approval. Before it begins:

- select one internal tenant and record its company ID in the server-controlled
  canary configuration;
- select the smallest approved charge and confirm refund/support ownership;
- confirm the merchant dashboard methods and settlement destination;
- capture pre-pilot health and reconciliation evidence;
- confirm a public webhook endpoint and delivery monitoring;
- confirm the rollback selection to ToyyibPay;
- confirm no customer payment credentials enter the application; and
- confirm the operator knows how to stop duplicate checkout attempts.

During the pilot, verify the local order, hosted checkout, provider request ID,
authoritative status, webhook delivery, subscription activation, included-credit
allocation, receipt-safe order history, and post-payment health. Do not mark the
pilot successful from the browser redirect alone.

After the pilot, reconcile the order by provider ID and internal reference,
confirm the event is idempotent when replayed, and record the final outcome.

## 18. Acceptance criteria

The integration is production-ready only when all of the following have current
evidence:

- A tenant can purchase a plan through a HitPay-hosted checkout.
- The four requested manual methods appear when enabled on the merchant
  account.
- Invalid, modified, or mismatched webhooks cannot activate a subscription.
- Duplicate events cannot activate or credit an order twice.
- Tenant A cannot read or modify Tenant B's payment.
- A missed webhook can be recovered through reconciliation.
- A provider timeout cannot create an uncontrolled second payment request.
- Existing ToyyibPay orders and callbacks continue to work.
- Operator health visibly reports degraded HitPay and reconciliation states.
- Missing `automation_events` reports automation degradation without blocking
  ordinary fail-open user workflows.
- Focused billing tests pass.
- The broader safe test suite, syntax checks, and `git diff --check` pass.
- A scoped Codex Security scan completes successfully; a blocked scan is an
  incomplete gate, not a pass.
- No migration has been applied without explicit environment approval.

## 19. Operator troubleshooting guide

| Symptom | Likely cause | Safe response |
|---|---|---|
| Health reports `degraded` before rollout | Missing HitPay key, salt, HTTPS URL, database access, or reconciliation evidence | Keep ToyyibPay as the active provider; fix the named configuration or dependency; do not paste secrets into logs |
| Customer paid but plan is still pending | Webhook unavailable, signature mismatch, or temporary database error | Inspect delivery response, restore dependencies, then reconcile by provider ID or exact internal reference |
| Checkout creation timed out | Provider outcome is ambiguous | Do not retry payment creation automatically; search HitPay by the local reference first |
| Provider says completed but local amount differs | Tampering, stale order, wrong plan, or provider mismatch | Reject activation and route to manual review; never override the amount from the browser |
| Invalid signature responses increase | Wrong environment salt, dashboard rotation mismatch, or body changed before verification | Compare endpoint and salt configuration out of band; preserve strict verification and use reconciliation |
| Multiple provider requests share a reference | Data or provider ambiguity | Stop activation, preserve all evidence in redacted form, and resolve through approved manual review |
| Browser shows success but subscription is unchanged | Redirect was reached before webhook/reconciliation | Explain that redirect is informational; inspect provider status and reconciliation |
| Automation table is unavailable | Migration 049 or automation dependency is unavailable | Report automation as degraded and preserve fail-open user workflows; do not modify payment state |
| ToyyibPay fallback is needed | HitPay pilot or configuration is paused | Select ToyyibPay server-side for new checkouts; continue handling existing HitPay orders safely |

## 20. Documentation deliverable and ownership

This file is the architecture proposal, reference, how-to, and operator runbook
for the HitPay phase. Implementation, testing, and rollout owners should keep
the following evidence alongside the approved change record:

- HitPay merchant-method checklist;
- environment-variable presence and format check, with no values;
- webhook registration and rotation record;
- sandbox and controlled-pilot test results;
- reconciliation and outage evidence;
- operator health screenshots or response summaries with secrets redacted;
- migration duplicate-preflight evidence if a future migration is proposed; and
- focused tests, broader test results, syntax checks, diff validation, and
  security-scan results.

The implementation status must remain `Implemented` until current verification
evidence satisfies the acceptance criteria. Live production readiness must not
be inferred from source files, a successful browser redirect, or a provider
dashboard setting alone.

## 21. Official references

- [Create a HitPay payment request](https://docs.hitpayapp.com/apis/payment-request/create-request)
- [Get a HitPay payment-request status](https://docs.hitpayapp.com/apis/payment-request/get-payment-status)
- [List and search HitPay payment requests](https://docs.hitpayapp.com/apis/payment-request/get-payment-requests)
- [HitPay event webhooks](https://docs.hitpayapp.com/apis/guide/events)
- [HitPay online payment flow](https://docs.hitpayapp.com/apis/guide/online-payments)
- [HitPay saved payment methods](https://docs.hitpayapp.com/apis/guide/save-payment-method)
- [HitPay FPX](https://docs.hitpayapp.com/payment-methods/fpx)
- [HitPay DuitNow](https://docs.hitpayapp.com/payment-methods/duitnow)
- [HitPay Touch 'n Go](https://docs.hitpayapp.com/payment-methods/touchngo)
- [HitPay Platform APIs](https://docs.hitpayapp.com/apis/guide/platform-apis)
