# CHIP payment backend

## Status — 2026-09-15

**Deployed in LIVE mode on Fly release 20.**

The current `aibot-chatbot-my` Fly app runs release 20 with CHIP selected.
Public billing health returns HTTP 200, status `ok`, and all readiness checks
true, including a fresh scheduled reconciliation. The same Singapore Machine,
volume, R2 storage, and enabled worker settings are preserved.

The user supplied the separate live key privately and explicitly requested
"Change live mode" before the deployed top-up test was completed. Authentication,
brand and live mode are verified through one unpaid connection purchase,
cancelled immediately without a payment attempt. New subscription and top-up
checkouts now use the live key. No paid live transaction was performed.

New subscription and AI-credit purchases use CHIP Collect exclusively. The
ToyyibPay and HitPay clients, callback endpoints, and operational scripts are
retired. Historical payment records, migrations, receipts, and recovery of
already-confirmed legacy payments remain available.

The existing frontend design is preserved. Its top-up calls now target CHIP;
subscription checkout already used a gateway-neutral endpoint. Fake development
payment-completion endpoints now return 410: use CHIP's real test flow instead.

## HTTP contract

| Endpoint | Purpose |
| --- | --- |
| `POST /api/billing/subscription/checkout` | Authenticated company, server-priced plan |
| `POST /api/billing/chip/checkout` | AI-credit top-up; integer `amount_micro_myr`, UUID `Idempotency-Key` header |
| `GET /api/billing/chip/orders/<reference>` | Authenticated company-scoped top-up status |
| `POST /api/billing/chip/callback` | Purchase `success_callback`; company public key |
| `POST /api/billing/chip/webhook` | Optional event webhook; its separately configured public key |
| `GET /api/billing/health` | Configuration/storage readiness booleans only |

Checkout responses retain `order_reference`, `checkout_url`, amounts, and
`payment_gateway`; test responses include `is_test`. Status reads expose
`test_paid` so sandbox success is visible without implying real credit.

## Required configuration

Use private runtime environment settings; `.env.txt` contains placeholders only.

```dotenv
CHIP_ENABLED=true
CHIP_ENV=test
CHIP_TEST_API_KEY=<test key>
CHIP_BRAND_ID=<merchant brand UUID>
CHIP_REDIRECT_URL=https://<your-app>/billing.html
CHIP_WEBHOOK_URL=https://<your-app>/api/billing/chip/callback
CHIP_LIVE_ENABLED=false
CHIP_LIVE_API_KEY=
```

The company callback public key can be fetched from CHIP. For a separately
registered webhook, set `CHIP_WEBHOOK_PUBLIC_KEY` to that webhook's public key
and use `/api/billing/chip/webhook`. Do not interchange these keys. An optional
`CHIP_CALLBACK_PUBLIC_KEY` pins the company callback key locally.
Fetched company keys (including failed lookups) are cached for five minutes per
worker and configuration; concurrent refreshes are serialized. Purchase status
is always fetched afresh. Requests without a signature never fetch a key.

Register refund/chargeback events on the separate webhook to receive operator
alerts: `purchase.pending_refund`, `purchase.refund_failure`, `payment.refunded`,
`payment.charged_back`, and `payment.chargeback_reversed`. Payment events resolve
their `related_to` purchase, re-fetch it and validate the stored order. They
return retryable HTTP 500 with a Sentry `payment.reason=status_review` alert;
subscription orders receive a reconciliation flag and top-ups persist
`failure_reason=chip_status_review`. Later top-up reads stay held for review.
The marker does not cancel credit processing already in flight. No event in this group
grants entitlements, even when the current purchase is paid again. Refunds,
credit deductions and subscription revocation require an operator policy and
are not automated. Use CHIP's merchant portal to investigate; alerts contain
no customer or payment identifiers.

No test/live API key was added to tracked files. The approved test credential
and callback public key are active in Fly secrets.
No live key has been supplied. The server rejects mode/brand mismatches even
when an API key is put into the wrong environment variable.

Callback diagnostics share a thread-safe limit of one Sentry report per minute
per worker, including configuration failures. Checkout and fulfillment diagnostics
remain unaffected. This prevents anonymous callback traffic from exhausting the
monitoring quota.

## Payment integrity

1. Persist the order and its CHIP mode/brand before creating a purchase.
2. Verify RSA PKCS#1 v1.5/SHA256 `X-Signature` over the original callback bytes.
3. Fetch the purchase from CHIP and match ID, reference, brand, mode, MYR, and
   exact integer amount. Redirects and manually marked-paid purchases cannot
   authorize fulfillment.
4. For live purchases, require a durable paid claim before granting entitlements;
   retain existing idempotent credit and subscription operations.
5. For test purchases, record verified sandbox completion as a closed test order
   (`cancelled` plus `chip_test_paid`) and release the subscription attempt.
   Do not grant paid plans or AI credits.

An ambiguous purchase creation stays claimed. Never repeat it automatically:
the first request may already have created a payable purchase. If the purchase
ID could not be persisted, an operator must reconcile it in the merchant portal
against the internal reference before attempting a replacement. Stored IDs are
polled by the existing billing scheduler, with separate mode/brand queries and
rotating timestamps so old pending orders cannot block later orders. No new
scheduler process was started by this task.

## Database rollout

[Migrations 051](../data/051_unique_subscription_gateway_order.sql) and
[059](../data/059_chip_payment_environment.sql) were applied to the approved
`parjsxypengvubziwwjp` project through its authenticated Supabase SQL Editor.
Catalog readback confirmed both validated constraints, all three ready/valid
indexes, provider environment/brand columns, and MYR currency defaults.
The existing migration 018 checkout functions retain identical body hashes and
service-role execution grants. No payment history, balances, RPCs or RLS changed.

The user approved deactivating nine unpaid ToyyibPay bills. Provider operations
confirmed all nine inactive, with no successful payments found. With the old
Machine stopped, a fresh provider/database check passed; the guarded transaction
then cancelled six subscription orders and three top-ups, releasing four
activation keys while preserving two null keys. Independent comparison with the
private pre-migration backup found no unexpected changes to any existing row,
amount, provider reference, or payment history. No legacy pending/paid rows remain.
The retirement transaction passed 19 local PostgreSQL checks before execution.

The callable Supabase MCP account exposed three unrelated inactive projects,
so it could not operate this application's database. The user's authenticated
dashboard provided access to the correct project. Before production execution,
the schema passed 27 checks in a disposable local PostgreSQL database.

## Verification evidence

- CHIP MCP public-key lookup authenticated successfully.
- The isolated [sandbox probe](../scripts/chip_sandbox_probe.py) created one
  RM1.01 purchase. CHIP's hosted **Test Success** action was completed in a
  browser. API retrieval verified `paid`, `is_test=true`, MYR, amount 101 sen,
  and the expected brand at **2026-09-15 08:58:15 UTC**.
- Sandbox purchase: `1179df32-a657-48d4-8be4-33f5b878ef8c`.
- This standalone synthetic purchase had no database order. It proves provider
  connectivity, checkout and payment normalization; it does not prove deployed
  callbacks or production database fulfillment.
- Sentry synthetic event `aa98580a0c474b799078da53967674ad` was sent and read back:
  environment `development`, release `chip-backend-local-20260915`, gateway
  `chip`, operation `status`, mode `test`. Exception text was redacted and
  personal fields empty. This proves local reporting, not deployment coverage.
  Sentry's API returned the verified issue link:
  [WHASTAPP_CHATBOT_PROJECT-5](https://kaguyahouraisan.sentry.io/issues/7733037998/).
- Deployed Sentry event `cd4bc401b9a94d6ebfa18574abb5e962` was verified at
  **2026-09-15 11:17:58 UTC**, environment `production`, release
  `chip-test-20260915-234ee13`, CHIP/test/invalid-signature tags. A synthetic
  invalid callback returned 401; Sentry retained only redacted diagnostic data.
  [Deployed Sentry issue](https://kaguyahouraisan.sentry.io/issues/7733245216/).
- The deployed image is
  `sha256:234ee13621d954e5b3f6293d712d17eb5b6762e9a1976a6caac09ba68756353b`.
  All **274 runtime files** matched the 276-file release manifest (Dockerfile
  and `.dockerignore` are build-only). Deployment and start commands exited 0;
  SSH returned valid verification data before a Windows handle-shutdown exit 1.
  Both retired gateway callback routes return 404.
- LIVE Sentry event `9b44eda762eb462da791febbd3d6deb0` was received at
  **2026-09-15 12:24:51.778 UTC**, after the synthetic invalid-signature callback
  returned 401. Plugin readback verified production, release
  `chip-live-20260915-234ee13`, CHIP/live tags and every private-data removal check.
  [Live Sentry issue](https://kaguyahouraisan.sentry.io/issues/7733245216/).
  This confirms error reporting, not paid callback delivery.
- Real application subscription test **order 26** (`48fe08ec-7959-4fdb-82cb-acb00726b7de`)
  was paid in CHIP TEST mode at **2026-09-15 11:20:01 UTC**, MYR 3,900 sen.
  Provider identity, brand, mode, reference and exact amount match the order.
  The database closed it as `cancelled / chip_test_paid` at 11:20:03.725 UTC,
  released its activation key, and granted no plan or credit entitlements.
  The company remains Free/trialing with RM1 included credit, RM0 top-up,
  unchanged subscription periods, and no new credit transactions.
- The abandoned subscription attempt, **order 27**, was cancelled in CHIP test
  mode and closed locally as `cancelled / chip_cancelled` at **11:53:08 UTC**.
  Its activation key was released. Exact subscription, balance and complete
  credit-ledger hashes were unchanged; provider readback confirmed no payment
  attempts. Journal SHA256:
  `67b2749832be95165cc52d83cfc30703868df7f213c44b4efc1631ba1e3f4713`.
- A later unpaid sandbox attempt, **order 29**, was cancelled before the live
  switch at **12:22:38 UTC**, with the same `chip_cancelled` terminal handling
  and unchanged subscription, balance and ledger hashes. Journal SHA256:
  `18cc8286eb4fc050d51c359b899015dc0d1144ae9a1b34645f64fd3d72cac9b7`.
- Paid test **order 28** for MYR 16,900 sen was also closed as
  `cancelled / chip_test_paid`; its company remained Pro/active without new
  credit grants. Any existing paid plan, including Pro, qualifies for the RM2
  top-up test; the user does not need an Essential/RM39 account.
- Callback delivery remains a separate evidence limitation.
  The callback URL matches deployment, but the provider API exposes no delivery
  result and privacy-preserving access logs omit routes. Stored completion alone
  does not distinguish callback processing from redirect/status reconciliation.
- An application AI-credit top-up test still requires the user's existing
  paid-plan account. Sandbox subscription success intentionally keeps the Free
  account ineligible for paid-plan top-ups. This deployed test was not completed;
  the user explicitly requested the live switch. Local top-up tests passed.
- The separate live key authenticated with HTTP 200 for the configured brand
  and MYR payment methods; FPX and DuitNow QR were present, cards absent.
  The callback key is valid RSA-3072. One unpaid live connection purchase
  (`9419ab9f-902e-406d-a783-5e536e69870a`) returned HTTP 201 and
  `is_test: false`; cancellation returned 200 and fresh GET confirmed
  `cancelled`, no payment and zero attempts. No callback, receipt or checkout
  navigation was used. Proof SHA256:
  `05eebe844311faedca3469ff79dbc326c83b9600ab80dc1a2aabf9fa6fbc01f6`.
  This verifies live API connectivity, not a paid live transaction.
- LIVE release **20** was deployed using the same image and existing Machine
  `185de27f125998` with volume `vol_vwnl05wn2jxww88v`. All 274 runtime hashes
  match. Runtime readback confirms `CHIP_ENV=live`, `is_test=false`, live enabled,
  the correct live brand/key, and the pinned callback key. All five unused
  ToyyibPay Fly secrets were removed; no ToyyibPay/HitPay environment names remain.
  At **12:26:14 UTC**, billing health returned HTTP 200/status `ok`, all checks
  true including scheduled reconciliation. Both old callback routes return 404.
- Mocked tests cover signatures, payment mismatch, tenant isolation, duplicate
  claims, failed persistence, sandbox entitlement exclusion, reconciliation,
  frontend API contracts, and Sentry privacy. The full command
  `.venv\Scripts\python.exe -m pytest tests -q --tb=short` exited 0:
  **4,226 passed, 5 skipped, 2,296 subtests passed**, with two existing Supabase
  client deprecation warnings (222.72 seconds).
- Seven focused Playwright checks passed: staff pending/test-paid outcomes,
  both top-up/subscription test returns, and both customer retry controls for
  pending/test-paid responses. CHIP's queryless redirect now verifies the saved
  top-up reference. Run with
  `node node_modules/@playwright/test/cli.js test admin-portal.spec.js profile-billing-design.spec.js --grep 'provider recheck|CHIP .* return|CHIP .* retry' --reporter=line`.
- Changed Python parsing/compilation, JavaScript syntax, rollout links and Git
  diff checks passed. Codex Security verification is recorded below separately.

The Agents Orchestrator handled independent QA, with separate provider and
checkout workers and final integration by the main agent. The team used selected
ECC/Matt Pocock skills, CHIP/Context7/Supabase MCP capabilities, and the Sentry
plugin. Supabase account access was limited as described above.

Final independent review also verified fixes for a concurrent subscription
callback overwriting a completed order, incomplete fulfillment being acknowledged
as successful, and customer retries reporting activation for pending/test payments.

### Security review

The original 21-file scan completed with a sealed manifest, complete coverage,
verified artifact hashes and CLI readback. It reported six findings (three
medium, three low), with no high or critical findings. Exit 2 recorded that
source changed during the scan. The eight-file follow-up completed with exit 0,
a sealed manifest, complete coverage and verified hashes/readback. The remaining
13 files matched the original snapshot. Its five current findings comprised
three medium findings and the two retained low policy findings. The three
medium fixes below passed targeted Codex Security `verify-fix`: exit 0, all
three exact finding occurrences `fixed`, with 141 tests and 69 subtests. All
21 final source hashes matched the verification input. This is targeted
post-fix verification, not a new scan. The two low policy findings remain.

| Finding | Disposition |
| --- | --- |
| Callback key lookup amplification (medium) | Missing signatures rejected early; successful and failed key lookups cached, with serialized refresh |
| Unbounded public health DB probes (medium) | Storage probes cached for 30 seconds per app/worker across callers, including failures; configuration/scheduler checks remain fresh |
| Unpaid legacy recovery bypass (low) | Stored paid/credited status is now mandatory before historical activation or credit recovery |
| Refund/chargeback handling (medium) | Verified events now trigger manual review and Sentry; automatic entitlement reversal remains a separate policy decision |
| Company members can use billing routes (low) | Existing tenant-scoped billing policy retained; an owner/admin-only restriction requires an authorization policy change |
| Public readiness booleans (low) | Existing public health contract retained; no credentials or customer data are returned |
| Credited legacy order replay (medium, follow-up) | Credited orders cannot enter activation again; explicit credit-only recovery remains available |
| Callback Sentry amplification (medium, follow-up) | All webhook diagnostics share one report per minute per worker, including concurrent requests |
| Top-up reversal lacked a durable review record (medium, follow-up) | Exact order/provider-bound review marker is persisted and verified; later reads cannot fulfill a flagged top-up |

This is not a clean security certification. Remaining policy findings must be
reviewed before a live rollout.

Automatic approval review rejected cleanup of two stopped disposable PostgreSQL
data folders and the isolated scan's temporary `codex-home/auth.json` file.
They were not deleted through an alternate mechanism. No disposable database
server remains running; canonical and desktop authentication are unchanged.

## Live switch completion

1. Completed: selected Fly app, applied migrations, retired the nine approved
   old bills/orders, and deployed the reviewed image with private test credentials.
2. Subscription sandbox payments and local top-up tests passed. The deployed
   paid-account top-up test remains unperformed; the user directed the live switch.
3. Completed: the user selected the current Fly target and supplied the live
   key privately; the unpaid live API connection check passed and was cancelled.
4. Completed: stopped the sole Machine with autostart off, closed test order 29,
   verified no unresolved test orders, and staged live settings. Removed the
   five unused `TOYYIBPAY_*` Fly secrets while preserving private historical
   credentials and payment records.
5. Completed: deployed the pinned image with `CHIP_ENV=live`, the separate live
   key/brand, `CHIP_LIVE_ENABLED=true`, live callback key and Sentry release
   `chip-live-20260915-234ee13`. Runtime settings, billing health and fresh
   live-mode Sentry event readback passed.
   A paid live transaction requires separate explicit user action.

Preserve the existing Fly runtime/scheduler ownership settings. Current runtime
inspection found one Singapore Machine, Wasender retries enabled, and billing
scheduler configuration using the enabled default. This supersedes older
handoff notes about disabled workers. A local passing test cannot prove that
deployed reconciliation is healthy; check fresh completion after deployment.

Official references: [CHIP purchase API](https://docs.chip-in.asia/chip-collect/api-reference/purchases/create),
[webhook signatures](https://docs.chip-in.asia/chip-collect/overview/webhook-signatures),
[test/live key separation](https://blog.chip-in.asia/docs/how-to-get-api-key-api-host-brand-id/).
