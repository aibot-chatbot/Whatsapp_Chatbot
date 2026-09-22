# Bot Analysis delivery

Prototype approved on 2026-09-22. Analysis belongs immediately below Conversations in the existing selected-Bot sidebar. Reports are for authenticated owners/admins.

## Acceptance and progress

1. **Done:** clickable prototype and navigation approved.
2. **Implemented locally:** tenant-scoped business records, durable report jobs, per-Bot industry/document context, Analysis page and private exports.
3. **Implemented locally:** tuition trial capacity/confirmation, report schedules and Telegram reminder worker. Website and Telegram customer booking flows are connected; the Bot gives truthful instructions for these explicit confirmation controls.
4. **Local tests and independent review complete:** full mocked suite, focused PostgreSQL concurrency checks and browser checks passed. Automated security verification remains incomplete: Codex Security could not refresh its saved ChatGPT login; Open Code Review has no configured provider. Neither is a passed scan.
5. Pending: target-project migration, cloud deployment within US$50 incremental monthly budget, synthetic recovery and 24/7 verification. Keep feature flags off until their production checks pass.

## Product and data contract

- Support different reports for restaurant, tuition, clinic administration and general businesses. Each Bot uses its own role and actual authorized documents. Automatic industry identification proposes a template; the merchant confirms before activation.
- Business requests, confirmed bookings, cancellations and completed actions are distinct states. A model reply is never proof of a booking, enrollment or payment. Unsupported integrations can record an application, not fabricate successful execution.
- Supabase holds company/Bot/conversation-scoped records, report requests, immutable snapshots, schedules and job leases. RLS denies browser access; Flask verifies current identity, role, company, Bot and plan. Internal workers use fenced leases.
- Report files use private R2 report keys. Downloads pass through authenticated authorization; no public media URL. Exports share the same snapshot. Unavailable merchant revenue remains unavailable.
- Model calls use the real Bot and existing billing gateway. Two durable steps at most (plan and analyze). An uncertain provider result requires review, not an automatic charged retry.
- Non-clinic operations reports may include bounded, contact-redacted customer text with message/conversation IDs. These samples are not guaranteed anonymous or representative; sample limits, missing sources and truncation remain visible in all formats. Clinic administration excludes free text.
- Before a report model step, the current confirmed industry must still match the frozen snapshot's industry and version. A changed context requires a new report instead of sending an old non-clinic snapshot under a newly confirmed clinic role.

## Verification evidence — 2026-09-23

| Check | Observed result | Scope / limit |
|---|---|---|
| Final staged-snapshot application suite | 5,255 passed, 34 skipped, 2,303 subtests passed | Project `.venv` Python; `-m pytest tests -q` in an independent index snapshot, excluding unrelated working-tree changes; opt-in database checks run separately |
| Latest report/export regressions | 117 passed | Industry-transition guard and all seven final cases also included in the final staged-snapshot suite |
| Chromium browser checks | 20 passed | Analysis, tuition and existing visitor/staff replies; mocked APIs, desktop/mobile interactions |
| Isolated PostgreSQL report checks | 6 passed | Tenant permissions, queue cap, partial publication and missing-field fail-closed behavior |
| Isolated PostgreSQL worker queue | 1 passed | Reclaim, stale callbacks and type isolation; rerun after adding migration lock/statement timeouts |
| Isolated PostgreSQL trials | 3 passed | Capacity races, replay, rescheduling and versioned cancellation |
| Isolated PostgreSQL observations | 9 passed | Trigger scope, source authority and duplicate handling |
| Isolated PostgreSQL reminders | 8 passed | Consent, lease fencing, late-reminder behavior and concurrent reschedule protection |
| Syntax / diff | Passed | 70 staged Python files compiled, Analysis/trial JavaScript parsed, `git diff --check` clean |
| Independent Security Architect review | No remaining confirmed High/Medium finding reported | Manual review is not a substitute for the blocked automated scan or production verification |

Local completion logs: `%TEMP%/analysis-staged-pytest-20260923.log` and `%TEMP%/analysis-final-browser.log`. The earlier working-tree run remains recorded separately in `%TEMP%/analysis-final-pytest.log` (5,251 passed); it is not the final staged artifact. All database drills create fresh loopback-only PostgreSQL clusters; they do not use production credentials. Mocked tests do not establish Langflow runtime compatibility or successful real delivery.

## Team ownership

- Agents Orchestrator: integration, routes, sidebar/Analysis UI, private download boundary and final verification.
- Backend Architect: migration 063, report repository and business-record domain service.
- AI Engineer: source-backed snapshots, industry-aware reports and PDF/XLSX exports.
- DevOps Automator: migration 064, leased queue, isolated worker and deployment workflows.
- Security Architect: independent permission/concurrency review after implementation.

Each lane reads its Agency role, Prompt Master and the smallest relevant installed skills, and uses a callable MCP/plugin within scope. No live credentials in tests.

## Known production verification gaps

- Supabase access was restored on 2026-09-23: direct project lookup and SQL access to `parjsxypengvubziwwjp` succeed. The project list still returns old entries; direct verified project access is authoritative. Live schema/ACL preflight passed (52 referenced columns match, no conflicting RPCs, observation trigger privileges present). Existing migration history ends at 061; 062–067 await application. Migration 062 must be applied as two transactions to release the column-add lock before validation.
- Codex Security retry on 2026-09-23 exited 2 during preflight at 0/65 files because the stored ChatGPT sign-in could not refresh. A saved login status alone does not prove the required token refresh works. Open Code Review also lacks a configured provider.
- Local tests do not prove a successful image build, cloud delivery, reminders, restart recovery or backups. Feature flags remain off until each capability is verified.
- The local machine has 7.68 GiB RAM, only 0.58–0.92 GiB available during verification. Docker is installed but stopped; the 2 GiB Langflow runtime was not started. Flow import, real response envelope and memory requirements remain unverified.
- The reviewed feature includes the approved industry-template dependency. Independent staged-snapshot validation also found a baseline collection failure: the committed payment test still imported the removed Toyyibpay route. Its existing workspace cleanup is preserved as a separate prerequisite test commit. Other unrelated payment/media edits, user documents, secrets and local tool configuration remain excluded.
