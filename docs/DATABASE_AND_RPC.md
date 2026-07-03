# Database and RPC Guide

## Overview

Supabase PostgreSQL is the primary persistence platform.

The backend accesses Supabase through repository modules under `app/database/`.

The application uses privileged server-side credentials. Database access must remain on the backend.

## Main Data Areas

### Identity and organization

- `companies`
- `users`
- `invites`
- `password_reset_otps`
- Registration-related pending-user records or RPC-managed state

### Chatbots and configuration

- `chatbots`
- `bot_configs`
- `profiles`

### Knowledge

- `knowledge_files`
- `knowledge_chunks`
- Knowledge-graph-related data where active

### Conversations and CRM

- `conversations`
- `messages`
- `chat_history`
- `crm_leads`
- `agent_actions`

### Messaging channels

- `telegram_channels`
- `wasender_channels`
- `whatsapp_channels`
- `processed_messages`
- `processed_telegram_updates`
- `processed_wasender_messages`

### Subscription and AI credit

- `subscription_plans`
- `company_subscriptions`
- Usage-related records
- `company_ai_credit_balances`
- `ai_credit_transactions`
- `ai_credit_topup_orders`
- AI-usage logging records

## Tenant Scoping

Company-owned tables should contain or resolve to `company_id`.

Rules:

- Read company context from the authenticated token.
- Never trust a frontend-provided company ID.
- Scope direct resource lookups by company where possible.
- For chatbot-owned records, verify that the chatbot belongs to the current company.
- Add cross-company access tests for every high-risk repository.

## Monetary Units

Internal AI-credit and top-up amounts use integer micro-MYR.

```text
1 MYR = 1,000,000 micro-MYR
1 sen = 10,000 micro-MYR
```

Do not use floating-point values for stored monetary calculations.

Gateway conversion must be explicit and tested.

## AI-Credit Balance Model

The credit balance separates:

- Included subscription balance
- Purchased top-up balance

Credit transactions record deltas and charging metadata.

Usage charging should:

1. Resolve the active subscription and credit period.
2. Calculate provider cost.
3. Apply configured markup and currency conversion.
4. Deduct balance atomically.
5. Record a transaction.
6. Prevent duplicate charging of the same usage record.

## Top-Up Orders

Top-up orders track:

- Internal order reference
- Company
- Subscription
- Creating user
- Amount
- Currency
- Payment gateway
- Gateway order identifier
- Checkout URL
- Idempotency key
- Status
- Payment reference
- Credit transaction reference
- Expiry and processing timestamps

Expected statuses include:

- pending
- claimed
- paid
- credited
- failed
- expired
- cancelled

Exact allowed values must be confirmed against the live schema and RPC definitions.

## RPC Functions

Repository evidence shows application use of RPCs for operations such as:

- Initializing an AI-credit period
- Charging AI usage
- Applying top-up credit
- Claiming checkout creation
- Completing checkout creation
- Failing checkout creation
- Marking an order paid
- Marking an order credited

The exact production SQL definitions must be exported and version-controlled.

## Required Database Documentation Work

The repository should contain:

```text
database/
├── schema/
├── migrations/
├── functions/
└── policies/
```

or an equivalent structure.

At minimum, version-control:

- Table creation
- Constraints
- Indexes
- Status checks
- RPC functions
- Row-level security policies
- Seed data required by the application

## Row-Level Security

Repository evidence does not confirm the live RLS state.

Required action:

1. Review RLS in the Supabase dashboard.
2. Export active policies.
3. Document which tables rely on RLS and which rely only on backend access.
4. Add policies to version control if RLS is enabled.
5. Do not assume that missing repository SQL means RLS is disabled.

## Schema Change Rules

Before changing schema:

1. Identify affected routes, services, repositories, frontend, and tests.
2. Create a reversible migration.
3. Review tenant and permission implications.
4. Test against a non-production environment.
5. Document deployment order.
6. Obtain human approval.
7. Apply production changes separately from application code deployment when necessary.

## Open Verification Items

- Exact live table definitions
- All indexes and foreign keys
- All active RPC SQL
- All active RLS policies
- Vector extension and embedding column configuration
- Storage strategy for uploaded files
- Backup and restore process
