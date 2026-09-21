# Phase 4F — Production Operations Runbook

Payment status (2026-09-15): CHIP replaces ToyyibPay and HitPay in the current code.
Local tests and a provider sandbox payment are verified; deployment is pending.
Use the [CHIP payment guide](CHIP_PAYMENT_GATEWAY.md) for current routes, configuration, and rollout.

## Required Migrations

Historical Phase 4F migration baseline (current CHIP additions are in the guide above):

1. data/001_seed_subscription_plans.sql
2. data/002_update_company_subscriptions_plan_id.sql
3. data/003_add_subscription_plan_fields.sql
4. data/004_add_company_subscription_status.sql
5. data/005_create_ai_credit_tables.sql
6. data/006_create_company_subscription_orders.sql
7. data/007_subscription_lifecycle_support.sql
8. data/008_subscription_renewal_support.sql
9. data/009_subscription_activation_atomicity.sql
10. data/010_subscription_order_schema_version.sql
11. data/011_subscription_reconciliation_support.sql
12. data/012_subscription_reconciliation_rpc.sql
13. data/013_subscription_included_credit_rpc.sql

Review the target schema and the [current CHIP database rollout](CHIP_PAYMENT_GATEWAY.md#database-rollout) before applying migrations.
This original Phase 4F list does not include later payment migrations.

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| SUPABASE_URL | Yes | Supabase project URL |
| SUPABASE_SERVICE_ROLE_KEY | Yes | Service-role key for admin DB access |
| SECRET_KEY | Yes | JWT signing secret |
| CHIP_* | Yes, before enabling CHIP | Follow the [CHIP configuration](CHIP_PAYMENT_GATEWAY.md#required-configuration); start in test mode |
| AI_CREDIT_ENFORCEMENT_ENABLED | No | Set 'true' to enforce credit checks (default false) |

## Webhook Configuration

The purchase success callback uses `POST /api/billing/chip/callback`.
Set `CHIP_WEBHOOK_URL` to the deployed public HTTPS URL for that endpoint.
An optional registered event webhook uses `POST /api/billing/chip/webhook`
and its separate webhook public key. See the [CHIP HTTP contract](CHIP_PAYMENT_GATEWAY.md#http-contract).

Callbacks verify the original bytes and fetch the purchase before matching the
stored identity, mode, brand, currency and exact amount. Test payments never grant entitlements.

## Reconciliation Command

python -m app.jobs.reconcile_subscription_orders

Options:
- --batch-size N (default 100)
- --dry-run (no changes)
- --order-reference UUID (single order)
- --company-id N (single company)

### Historical Schedule Example

The existing billing scheduler includes subscription and CHIP top-up reconciliation when enabled.
Retain one authorized scheduler runtime; do not enable a second process.
The original subscription-only cron example below does not include top-up recovery:

*/15 * * * * cd /app && venv/bin/python -m app.jobs.reconcile_subscription_orders --batch-size 50

For low-traffic periods, every hour is sufficient.

## Identifying Stuck Paid Orders

Query Supabase:

SELECT order_reference, company_id, status, activation_status, reconciliation_required, created_at, updated_at
FROM public.company_subscription_orders
WHERE status = 'paid'
  AND (activation_status IS NULL OR activation_status NOT IN ('completed', 'conflict'))
  AND updated_at < now() - interval '1 hour'
ORDER BY updated_at;

## Retrying Activation Safely

Use the customer retry endpoint:

POST /api/billing/subscription/orders/<order_reference>/retry

This reuses the same ctivation_sequence_key and never duplicates credit.
Only the owning company can retry their own orders.

For support/admin: use the CLI with --order-reference:

python -m app.jobs.reconcile_subscription_orders --order-reference <uuid>

## Inspecting Company AI Credit

GET /api/billing/ai-credit/summary

Returns:
- included_balance_micro_myr
- topup_balance_micro_myr
- total_balance_micro_myr
- period_start
- period_end

## Handling Duplicate-Credit Incidents

If duplicate included credit is suspected:

1. Query the AI credit ledger for the company/order:
   SELECT * FROM company_ai_credit_ledger WHERE order_reference = '<uuid>';

2. Look for duplicate "subscription_included" transaction type rows.

3. For repair, use the reviewed SQL in docs/repair_duplicate_credit.sql.
   Do NOT run without reviewing the exact balances first.

## Verifying Plan-Limit Enforcement

Use the billing guard check endpoint:

GET /api/billing/health

Or call can_create_chatbot() / can_upload_knowledge_file() etc. directly
in a Python shell to test specific limits.

To verify limits for a specific company:
  from app.services.billing_guard import check_company_limit
  result = check_company_limit(company_id)
  print(result)

## Rollback Considerations

- Migrations are additive only — no destructive ALTERs.
- To roll back a deployment, deploy the previous code version.
- Existing orders and subscriptions remain valid.
- Downgrade/cancellation schedules are stored as nullable timestamps.
- Clearing scheduled fields via UPDATE is safe.

## Production Smoke-Test Checklist

Pre-deployment:
- [ ] Historical Phase 4F migrations and current CHIP migration requirements reviewed/applied to the approved target
- [ ] Service role grants verified on all tables/RPCs
- [ ] CHIP callback URL and the appropriate public key configured
- [ ] Redirect URL points to profile page
- [ ] Reconciliation service importable (no circular deps)
- [ ] Environment variables set

Post-deployment:
- [ ] GET /api/billing/health returns {"status": "ok"}
- [ ] Subscription plans load on pricing page
- [ ] Checkout creates pending order
- [ ] Callback marks order as paid
- [ ] Activation completes and subscription status changes
- [ ] AI credit allocated correctly
- [ ] Payment history section shows completed order
- [ ] Reconciliation handles incomplete orders
- [ ] Cancellation and downgrade affect profile display correctly