# Phase 4G — Billing Support Runbook

## Authorization Model

The project currently supports company-scoped roles only:

| Role | Scope | Billing Access |
|------|-------|----------------|
| `owner` | Company | Own company only |
| `admin` | Company | Own company only |
| `member` | Company | No billing access |

There is **no platform-level admin role** in the current schema, code, or migrations.
Cross-company admin endpoints have been intentionally deferred until a secure
server-side authorization framework is implemented.

## How to Find an Order

### Via the Admin Billing API (company owner/admin only)

```http
GET /api/admin/billing/orders?limit=20&offset=0
```

Optional filters:
- `payment_status` — e.g. `paid`, `pending`, `credited`
- `activation_status` — e.g. `not_started`, `claimed`, `credited`, `completed`, `conflict`
- `reconciliation_required` — `true` or `false`

### By order reference

```http
GET /api/admin/billing/orders/<order_reference>
```

Only returns results if the order belongs to the requesting company.

### Direct SQL (read-only, production only)

```sql
SELECT * FROM company_subscription_orders
WHERE order_reference = '<reference>';
```

## How to Identify Paid-But-Incomplete Orders

Orders that are payment-confirmed but not fully activated:

1. **Status = paid, activation_status = not_started/claimed**
   → Payment confirmed, awaiting activation

2. **Activation_status = credit_pending, reconciliation_required = true**
   → Credit grant failed, needs retry

3. **Activation_status = conflict**
   → Source subscription changed or activation already claimed by another order

Use the admin API with `reconciliation_required=true` or `activation_status=credit_pending`.

## When Reconciliation Is Safe

Reconciliation is safe when:

- The order status is `paid`
- Or activation_status is one of: `not_started`, `claimed`, `activated`, `credit_pending`
- The payment was previously confirmed via callback
- The order has a valid `activation_sequence_key` (or is a legacy pre-v2 order)

Reconciliation is **idempotent** — running it multiple times on a completed order
returns success without duplicating credit or activation.

## When NOT to Retry

Do **not** retry when:

- The order status is `pending` (payment not yet confirmed)
- The order status is `failed` (payment gateway reported failure)
- The order status is `expired` (checkout session expired)
- Activation_status is `conflict` (requires manual support review)
- The order is `credited` and activation_status is `completed` (already done)
- The company no longer owns the order

## How to Inspect AI-Credit Balances

### Via Admin API (company owner/admin)

```http
GET /api/admin/billing/ai-credit
```

Returns:
- `included_balance_micro_myr`
- `topup_balance_micro_myr`
- `total_balance_micro_myr`
- `period_start`
- `period_end`

### Via Admin API — Transaction History

```http
GET /api/admin/billing/ai-credit/transactions?limit=20
```

Returns recent transaction records with type, description, delta, balances, and timestamps.

### Direct SQL (read-only)

```sql
SELECT * FROM company_ai_credit_balances WHERE company_id = <id>;
SELECT * FROM company_ai_credit_transactions
WHERE company_id = <id>
ORDER BY created_at DESC
LIMIT 50;
```

## How to Reconcile an Order

### Via Admin API

```http
POST /api/admin/billing/orders/<order_reference>/reconcile
```

Only accessible to the order's owning company (admin/owner role).

Success response:
```json
{"status": "success", "data": {"outcome": "credit_retry_completed", ...}}
```

Conflict response (manual review required):
```json
{"status": "error", "code": "manual_review_required", "message": "..."}
```

### Via CLI

```bash
python -m app.jobs.reconcile_subscription_orders \
    --order-reference <reference> \
    --company-id <id>
```

### Via CLI — Batch

```bash
python -m app.jobs.reconcile_subscription_orders \
    --batch-size 50
```

Use `--dry-run` to preview without making changes.

## How to Handle Duplicate-Credit Incidents

1. **Do not** directly edit `company_ai_credit_balances` or delete ledger rows.
2. **Do not** manually insert a credit reversal without an auditable transaction.
3. Follow the procedure in `docs/repair_duplicate_credit.sql` (reviewed by a second
   person before execution).
4. After executing the repair, run the admin credit inspection API to verify balances.
5. Record the incident and resolution in the support system.

## Auditable Adjustments

No platform-admin adjustment endpoint exists because no secure platform-admin
authorization framework exists. Credit adjustments must currently be performed
via the reviewed `docs/repair_duplicate_credit.sql` workflow, reviewed by a
second person before execution.

## Required Evidence Before Changing Credit

- Order reference
- Payment gateway transaction ID
- Payment status confirmation
- Current included and top-up balances
- Current activation_status
- Proof that the credit was genuinely duplicated (two ledger rows, same idempotency key)
- Engineering or management approval

## Escalation Steps

1. Verify the issue using the admin API or read-only SQL.
2. Check whether the order is reconcilable (payment confirmed, incomplete activation).
3. Attempt reconciliation via the admin API.
4. If reconciliation fails with `manual_review_required`, inspect activation_status.
5. If conflict: contact engineering for review.
6. If duplicate credit: follow the reviewed repair SQL procedure after approval.

## Actions That Must NEVER Be Performed Manually

- **Never** delete ledger transactions.
- **Never** directly edit `company_ai_credit_balances.included_balance_micro_myr`
  or `topup_balance_micro_myr`.
- **Never** mark unpaid orders as paid.
- **Never** generate a new activation key during retry.
- **Never** re-run one-time repair SQL without reviewing the target data first.
- **Never** modify `company_subscriptions` status directly.
- **Never** expose secret keys, tokens, or full gateway payloads in support logs.

## Production SQL Queries (Read-Only Diagnosis)

### Find paid-but-incomplete orders

```sql
SELECT order_reference, company_id, status, activation_status,
       reconciliation_required, reconciliation_attempt_count,
       payment_reference, gateway_order_id, created_at, paid_at
FROM company_subscription_orders
WHERE status = 'paid'
  AND (activation_status IS NULL OR activation_status NOT IN ('completed'))
ORDER BY created_at DESC
LIMIT 50;
```

### Find reconciliation-required orders

```sql
SELECT order_reference, company_id, status, activation_status,
       reconciliation_required, reconciliation_attempt_count,
       activation_error_code, last_reconciliation_error
FROM company_subscription_orders
WHERE reconciliation_required = true
ORDER BY last_reconciliation_at ASC
LIMIT 50;
```

### Check company AI credit

```sql
SELECT company_id, included_balance_micro_myr, topup_balance_micro_myr,
       (included_balance_micro_myr + topup_balance_micro_myr) AS total_micro_myr,
       period_start, period_end
FROM company_ai_credit_balances
WHERE company_id = <id>;
```

### Check recent credit transactions

```sql
SELECT id, transaction_type, description, net_delta_micro_myr,
       included_balance_after_micro_myr, topup_balance_after_micro_myr,
       idempotency_key, payment_reference, created_at
FROM company_ai_credit_transactions
WHERE company_id = <id>
ORDER BY created_at DESC
LIMIT 50;
```
