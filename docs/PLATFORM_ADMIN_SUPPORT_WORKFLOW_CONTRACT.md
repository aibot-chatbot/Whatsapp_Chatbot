# Platform-admin Support Workflow Contract

## Status and scope

The current Platform-admin Support Workspace is a read-only investigation hub.
It reuses `GET /api/platform-admin/overview` and
`GET /api/platform-admin/companies`, then links to the existing company-detail
investigation page. Support Cases Phase 1 is an internal platform-admin
workflow. Its migration is applied and verified in the main shared testing
Supabase with fake/team testing data; this is not staging or production
verification. The feature adds a bounded internal
case tracker with case creation, listing, detail, redacted internal
notes, status/priority updates, and append-only case events. It has no customer
messaging, impersonation, billing actions, exports, charts, or other write
controls outside the case workflow.

This document remains the safety and approval contract for the internal
platform-admin support-case workflow. Tenant submission is separate and is
defined only in `docs/TENANT_SUPPORT_SUBMISSION_CONTRACT.md`. The current platform-admin
surface is now 15 endpoint paths (17 Flask method registrations): the original
12 GET-only investigation routes plus three support-case paths with GET/POST/PATCH
methods. The latest extensions remain unverified in staging; the 12-route
investigation stack remains localhost-verified only; production remains blocked.

## Deferred future support-case concepts

The following concepts require separate product, privacy, and operational
approval before implementation:

- assignment UI and reassignment workflow;
- customer contact link and customer-facing communication;
- formal SLA target and escalation workflow;
- richer case search, queues, exports, and reporting.

Support case, case status, priority, internal notes, and append-only audit trail
behavior are covered by the bounded application contract and the main shared
testing Supabase verification with fake/team data. This does not establish
staging verification or production readiness. No current
behavior provides the deferred concepts above.

## Safety principles

Support-case writes are internal-only and must preserve the following boundary:

- impersonation or session takeover;
- password reset or credential changes;
- billing retry, reconciliation, manual credit, or payment actions;
- plan changes or subscription mutation;
- customer message sending or contact workflows;
- exports or bulk downloads;
- raw customer content in a case summary.

Case summaries should use concise, redacted operational context and safe
company references only. Secrets, tokens, cookies, provider payloads, payment
references, and unnecessary customer data must remain excluded.

## Phase 1 data model

Migration 029 is applied and verified in the main shared testing Supabase with
fake/team data. It provides:

- `platform_support_cases`: case identity, safe `company_id` reference, status, priority,
  timestamps, and approved ownership fields;
- `platform_support_case_events`: append-only case history for approved status,
  note, and audit events;
- optional `assigned_platform_admin_user_id`: an approved active platform-admin
  mapping reference, never a shared account identity;
- safe references to `company_id` only for tenant scope.

The model must not store raw secrets, tokens, cookies, provider payloads,
payment gateway data, or unredacted customer content. This verification does
not establish staging verification or production readiness.

## Approval gates before implementation

Before extending or staging the support-case implementation, confirm:

- support process owner;
- privacy review;
- retention policy;
- audit metadata and evidence approval;
- customer communication policy;
- confirmed staging environment;
- approved access lifecycle and revocation procedure;
- focused tests and redaction cases.

The staging environment and latest platform-admin extensions must be verified
before any staging claim is made. Production access remains blocked.

## Localhost boundary

Phase 1 has localhost application evidence and main shared testing Supabase
DB/browser evidence with fake/team data. This contract does not claim staging
verification or production readiness. It authorizes no migration execution,
mapping change, customer communication capability, impersonation, billing
operation, export, or chart.
