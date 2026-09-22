# Human handoff Phase A/B release — 2026-09-22

## Scope and activation

Phase A adds the dashboard waiting card, a filtered queue link, browser-tab
counts, and an unavailable state that does not claim zero waiting customers.
Phase B adds persistent control state, atomic claim/assign/resolve/reopen/
resume commands, internal notes, and seven staff API routes.

`HANDOFF_CONTROL_ENABLED` remains unset (false). This is a deployment of the
prepared API and schema, not activation of the complete new handoff workflow.
Customer requests still write legacy `agent_actions`; the existing reply route
does not enforce the new assignee; automatic send callers do not yet carry the
control/dispatch epoch; the frontend does not call the seven new APIs. These
connections must be completed and verified before enabling the flag. Existing
legacy human replies retain their current behavior. No real customer message
was sent as part of this release verification.

The current user explicitly authorized migration, deployment and commits. The
older attached implementation briefs are requirements context; their earlier
no-deployment instructions do not revoke that current authorization.

## Database evidence

Target: `parjsxypengvubziwwjp` / `AI Chatbot's Project`, PostgreSQL 17.6.
Migration 060 was applied through Supabase `apply_migration` in separate calls
with 3-second lock and 30-second statement timeouts, avoiding reliance on
embedded transaction boundaries inside an API wrapper.

| Version | Migration |
| --- | --- |
| 20260922034846 | handoff_control_core_060 |
| 20260922034856 | handoff_message_actor_column_060 |
| 20260922034903 | handoff_message_actor_fk_060 |
| 20260922034946 | validate_handoff_message_actor_fk_060 |

Readback verified both tables, their indexes/checks, version default 1, both
SECURITY INVOKER functions with empty search paths, and the validated message
actor foreign key. RLS is enabled; anon/authenticated have no table access or
function execution. Service-role note INSERT works while UPDATE/DELETE are
revoked. Service-role SQL TRUNCATE privileges are inherited; these tables are
not an immutable audit store against privileged database operations.

Supabase advisors reported INFO for the intentionally policy-free, backend-only
new tables. Existing warnings concern two knowledge-search functions and the
public vector extension; they are outside this change. See the official
[RLS advisor explanation](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).

An isolated PostgreSQL 18.3 drill verified first writes, concurrent claims with
one winner, winner readback, version/source checks, cross-tenant refusal, epoch
monotonicity, note permissions, repeat application, FK validation and lock
timeout behavior. This is local SQL evidence on a different major version,
separate from the production schema/permission readback.

## Review fixes and tests

- Added the four new Python modules to the explicit Docker file allowlist.
- Fixed all seven new routes to bind the requested chatbot ID to the loaded
  conversation control. Before the fix, all seven same-company/wrong-bot
  regressions returned 200; after it, all return 403 without writes/disclosure.
- Focused Python checks: 286 passed, 3 subtests; syntax and diff checks passed.
- Browser checks: 21 of 22 passed on the first run; the one navigation timeout
  passed on a targeted rerun. All five new waiting-card/queue cases passed.
- Full Python suite: **4771 passed, 5 skipped, 2303 subtests**, exit 0, 191.95s.
  A temporary Git index included the new runtime files for the manifest test;
  the user's real index was preserved. The full suite ran on the working tree,
  including pre-existing unrelated test fixture repairs left outside these
  commits; it is not a claim that an otherwise pristine checkout has the same
  full-suite result.

Codex Security was attempted for ten handoff runtime/schema/frontend paths.
It exited 1 during preflight because the stored ChatGPT sign-in could not be
refreshed. Coverage was 0/10; no completed/sealed security pass is claimed.

## Release integrity

The existing Fly v33 already contained four uncommitted n8n runtime files.
Remote SHA-256 matched the working files for all four. They are included in a
separate production-reconciliation commit so this release does not revert
existing production code. `N8N_WORKER_ENABLED` remains unset/false. Review
identified pre-existing stale-claim and concurrent callback races in that
disabled worker; this release does not change or activate it.

The build uses a copied, explicit allowlist: 291 Docker input files plus
`fly.toml`. Secrets, uploaded documents, local outputs, unrelated MCP directories
and other untracked files are excluded. The built image is
`registry.fly.io/aibot-chatbot-my@sha256:df8b3719606211aa7240315877e1276b6641e9b695ec0331acda9a16a0bf9613`.

Fly **v34** deployed successfully to the existing Machine `185de27f125998` in
`sin`, retaining volume `vol_vwnl05wn2jxww88v` at `/app/data`. Deployment smoke,
Machine health and DNS checks passed. All **289 runtime files** matched the
release snapshot SHA-256 values, with no missing or unexpected runtime files.
Public `/`, `/index.html` and `/conversations.html` returned 200; the two HTML
responses contain the new queue UI. The new state endpoint rejected an
unauthenticated request with 401. These checks do not claim an authenticated
live claim/reply round-trip.

Runtime readback confirmed the existing Wasender retry, billing, ingest queue,
Cloudflare queue, AI Search, AI credit enforcement and CHIP switches remain
true; R2 remains authoritative with initial migration 0. Handoff and n8n worker
switches remain unset/false.

## Team and tools

The main agent used the local Agents Orchestrator role, with Database
Reliability Engineer, API Tester, and DevOps Automator subagents, each reading
its role file under `C:/Users/Vincent/agency-agents`. All used the requested
Prompt Master and relevant verification/code-review/Supabase skills. Actual
MCP/plugin use included Supabase project/SQL/migrations/docs/advisors, Fly
runtime reads, Codex App artifacts, and Codex Security metadata plus its CLI
scan. Review roles and file ownership were bounded; the parent integrated and
verified the fixes.

## Recovery

Keep the handoff flag false and revert the application image if necessary.
The previous image is
`registry.fly.io/aibot-chatbot-my@sha256:81d04e9df6745af82ec1de745dd40b66f8fc8e577527255402beb7c94b757374`.
Preserve the new database tables and column; dropping them would destroy any
new control/note records. Maintain the single Singapore Machine and `/app/data`
volume. A single-Machine update can briefly interrupt requests.
