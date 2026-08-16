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

`bot_configs` stores three persona values that were historically duplicated
across two column names each. Migration `039` makes `business_description`,
`tone`, and `custom_prompt` canonical and deprecates `business_objective`,
`response_style`, and `prompt_text`. Migration `040` adds a
`persona_provenance` jsonb column recording whether each persona value was typed
by the client or derived from an ingested document. Neither migration has been
applied to any environment; see
`docs/KNOWLEDGE_INGESTION_AND_DERIVED_PERSONA.md`.

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
- `conversation_graph_nodes` (migration `041`, unapplied)

`conversation_graph_nodes` holds conversation-scoped facts learned mid-chat. It
is deliberately separate from the document knowledge-graph tables, which are
uniquely keyed per chatbot and would collide across concurrent conversations.
Its write path is **not** tenant-filtered — the upsert conflict target excludes
`chatbot_id` — so no caller may accept a conversation identifier from a request
until the composite foreign key documented in the migration exists.

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

New `agent_actions` inserts resolve `company_id` from the authoritative chatbot
record in the shared chat pipeline, and the repository rejects inserts without a
valid company ID.

On 2026-07-25, staging migration 028 removed only the approved 36 orphan
`agent_actions` rows and two orphan `crm_leads` rows. Staging migration 027 then
verified the following hardening:

- `agent_actions.company_id` and `agent_actions.chatbot_id` are required;
- chatbot foreign keys cascade deletion and nullable conversation foreign keys
  use `ON DELETE SET NULL`;
- compatible Agent Action and CRM lead value checks are validated;
- the pending Agent Action query index and partial unique open-lead index exist;
- RLS is enabled but not forced, with no policies;
- `anon` and `authenticated` have no target-table or target-sequence privileges;
- `service_role` has only `SELECT`, `INSERT`, and `UPDATE` on both target tables,
  plus required sequence `USAGE`; and
- the permanent chatbot deletion RPC remains `SECURITY DEFINER` and executable
  by `service_role`, not browser roles or `PUBLIC`.

Production remains unchanged. Direct company foreign keys are intentionally
deferred until tenant/company deletion semantics are approved.

Application-level signal and CRM stabilization now also enforces:

- escalation queries and exact-ID resolution include chatbot and company scope;
- resolution updates require current `detected` status and repeated requests do
  not repeat the customer-facing AI-resumed message;
- automatic CRM conversion derives `company_id` from the chatbot and reloads
  any referenced conversation by chatbot before using it;
- handoff requests attempt a `staff_attention` lead before returning the
  customer handoff response, and handoff email ownership uses the same
  authoritative chatbot-derived company rather than conversation payload data;
- manual and automatic conversion reuse only open leads, leaving closed leads
  historical; and
- PostgreSQL unique-violation code `23505` triggers a lookup of the winning open
  CRM lead instead of message-text-based error handling.

Exact-action retries do not repeat the AI-resumed notification. However, the
remaining-escalation check and outbound notification are not one atomic
conversation-level database operation. Two different final escalation actions
resolved concurrently may both send the resume notification. Cross-action
notification deduplication remains deferred to the lifecycle transaction/RPC
phase.

These are repository and service behavior changes only. Reviewed/actioned/
dismissed states, reviewer and lifecycle timestamps, dispositions, transition
history, direct signal-to-lead linkage, and frontend signal actions remain
deferred.

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

Several tables in this system have no `CREATE TABLE` in the repository, so a
migration against them cannot assert the shape it is altering. Where that is the
case, the migration carries a mandatory SELECT-only preflight script under
`scripts/` whose output must be attached to the change record before the
migration is applied. Current examples:

- `scripts/bot_configs_persona_unification_preflight.sql` (migration `039`)
- `scripts/conversation_graph_nodes_preflight.sql` (migration `041`)

Preflight output can contain tenant business text. Route it to the restricted
archive used for migration 028 manifests, not into a ticket or chat transcript.

## Open Verification Items

- Exact live table definitions
- All indexes and foreign keys
- All active RPC SQL
- All active RLS policies
- Vector extension and embedding column configuration
- Storage strategy for uploaded files
- Backup and restore process
