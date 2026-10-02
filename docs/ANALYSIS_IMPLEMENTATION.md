# Bot Analysis delivery

Prototype approved on 2026-09-22. Analysis belongs immediately below Conversations in the existing selected-Bot sidebar. Reports are for authenticated owners/admins.

## Latest deployment: Fly v38, 2026-09-23

- Runtime source: `c3282e1` on `codex/release-91542de-preserve-v37`, pushed to origin. It combines `91542de` with the 12 Cloudflare/pricing runtime files already running in v37. The owner explicitly chose to preserve those live changes. The main checkout and its unrelated unfinished work were not modified.
- The bot-update allowlist, industry reports and Pro-only automation gates are deployed. Existing execution flags remain unset/default-false; billing scheduling remains enabled. Deployment does not activate reports, trials, reminders, n8n or Langflow.
- Image: `registry.fly.io/aibot-chatbot-my@sha256:008f391f21d0b5df7a2e769f1ad746a2cf48b149d38745a01cbf5ab8fad38963`. Existing Singapore Machine `185de27f125998` is started and healthy, with the same `chatbot_data` volume mounted at `/app/data`.
- All 316 deployed runtime-file hashes match the exact build snapshot; the 12 retained v37 files are byte-for-byte unchanged. Sorted path/hash manifest SHA-256: `b2754337f6ee054411a515d7c31be1bde730320fac96aae022b1bd351eb8b8bd`. Windows line endings are included in this build evidence; do not compare it to normalized Git blobs without accounting for them.
- Public landing, Analysis, pricing and selected JavaScript reads returned 200. Unauthenticated `/api/chatbots/1/analysis` returned 401. No customer data was mutated, no customer message was sent, and no paid model call was made for verification.
- Combined backend suite: **5,380 passed, 35 skipped, 2,330 subtests passed, 6 failed**. All six failures reproduced against reconstructed v37 runtime files: legacy trial/provider expectations, model/pricing text and system-AI fixture expectations. Browser checks: **25 passed, 1 preexisting pricing-label expectation failed**, also reproduced against v37. The isolated `91542de` security/Analysis gate first passed **427 tests and 94 subtests**. Python/JavaScript syntax, container manifest, Fly config and diff checks passed. Independent integration review found no release-blocking incompatibility.
- Codex Security remains **incomplete**: its saved ChatGPT login could not refresh during preflight at 0/929 files. No successful security scan is claimed.
- Production readback confirms `automation_workflows=true` only for Pro, false for Free/Essential/Advanced. The n8n role has database/schema CREATE and no SELECT on `public.chatbots`.
- Original current-user DPAPI credentials were recovered without printing values. The existing `agent_n8n` password authenticated with certificate/hostname verification over TLS 1.3; **no password reset is needed**. The supplied dashboard password is a separate credential and was not used as a database password. Generated replacement `.omnexa-secrets` files are not the active credential source and must not be imported blindly.
- n8n and worker Fly apps do not exist; Langflow still has zero machines, secrets and public IPs plus its retained 2 GB volume. Their deployment, flow/credential setup, monitoring, recovery drills and activation remain outstanding.

The sections below retain the earlier v36 acceptance and migration evidence.

## Acceptance and progress

1. **Done:** clickable prototype and navigation approved.
2. **Deployed, report execution disabled:** tenant-scoped business records, durable report APIs, per-Bot industry/document context, Analysis page and private exports are in Fly v36.
3. **Deployed, trial/reminder execution disabled:** tuition capacity/confirmation APIs and website/Telegram controls are deployed. The independent worker and scheduler services are not running yet.
4. **Local tests and independent review complete:** full mocked suite, focused PostgreSQL concurrency checks and browser checks passed. Automated security verification remains incomplete: Codex Security could not refresh its saved ChatGPT login; Open Code Review has no configured provider. Neither is a passed scan.
5. **Database migration and Flask deployment complete; automation rollout pending.** The user chose to defer Codex Security login and keep report, trial and reminder flags off on 2026-09-23. Cloud workers, synthetic recovery and 24/7 verification remain incomplete.

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
| Isolated PostgreSQL n8n provisioning | 1 passed | Non-superuser CREATEROLE provisioning, removal of temporary privileges, password administration and full rollback on isolation-guard failure; added after the main feature suite |
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

## Production release evidence — 2026-09-23

- Commits: `bbd8a3f` removes the obsolete Toyyibpay test dependency; `f3f7f77` contains the tested feature; `cafbb06` fixes PostgreSQL 16+ n8n provisioning permissions.
- Supabase `parjsxypengvubziwwjp`: migrations `20260922233353` / `20260922233405` apply and validate 062 separately; `20260922233421`–`20260922233431` apply 063–067. Post-migration checks verified all ten new tables have RLS, browser roles have no data access, all 23 new functions have restricted execution and fixed search paths, constraints are validated, and the customer-message trigger is SECURITY INVOKER.
- The n8n account/schema migration also succeeded after reproducing and fixing `42501 must be able to SET ROLE` in isolated PostgreSQL. Production `agent_n8n` login passed certificate/hostname validation with TLS 1.3. It can create in its own schema, cannot read Analysis reports or call the worker-claim RPC, and the administrator has no residual SET/INHERIT access. No plaintext password is stored in Git or the migration; a SCRAM verifier was used.
- Fly **v36** is healthy on existing Singapore Machine `185de27f125998`, image `registry.fly.io/aibot-chatbot-my@sha256:a5ae44718bd1a754ab4f0b2fe2e86ec811be8d2e6dcc8a6643613d1b3d8b3b32`. All **313 application/frontend/flow file hashes** match commit `f3f7f77`. `/`, `/analysis.html` and the Analysis script returned 200; unauthenticated Analysis API access returned 401.
- Runtime checks confirm `AGENT_ANALYSIS_ENABLED`, `TUITION_TRIALS_ENABLED`, `TUITION_REMINDERS_ENABLED`, `HANDOFF_CONTROL_ENABLED` and `N8N_WORKER_ENABLED` are false. Report rows, active schedules, opted-in recording Bots and trial bookings were all zero at verification. The internal bearer is configured; no customer send or paid model smoke was run.
- Langflow app `aibot-agent-langflow-my` and encrypted 2 GB volume `vol_4qlkqqozjlpxzmwr` exist in `sin`; there are **zero Machines, public IPs and imported secrets**. Automatic approval rejected its secret upload with only `blocked by policy`, so it was not started and no alternate upload path was attempted. Local credential backups use current-user Windows DPAPI; they are not an off-machine recovery proof.
- The cancelled legacy build automatically created an unused builder and 50 GB cache volume. With explicit user approval, `fly-builder-wandering-bush-1031`, Machine `48e4d5db0197e8` and cache `vol_v3g577mxl95kyq14` were deleted and absence verified. The retained Langflow volume is approximately **US$0.30/month**; there are no new always-running compute charges. Use Depot and explicit Dockerfile paths when resuming.
- Supabase advisors report INFO for RLS-without-policies, expected for these server-only tables with browser grants revoked. Existing warnings concern two knowledge-search functions and the public vector extension; this feature did not modify those objects. See [RLS advisory](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy), [function search paths](https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable) and [extension schema](https://supabase.com/docs/guides/database/database-linter?lint=0014_extension_in_public).

## Known production verification gaps

- Supabase project listing can be stale after reconnection. Direct lookup and SQL access to the verified project work; do not reapply the completed migrations based on the old project list or earlier notes.
- Codex Security retry on 2026-09-23 exited 2 during preflight at 0/65 files because the stored ChatGPT sign-in could not refresh. A saved login status alone does not prove the required token refresh works. Open Code Review also lacks a configured provider.
- The Flask image build/deployment is verified. Langflow flow import, n8n runtime, the worker, paid report generation, reminders, restart recovery, backup restoration and alerts are not verified. Keep their execution flags off as the user requested.
- The local machine has 7.68 GiB RAM, only 0.58–0.92 GiB available during verification. Docker is installed but stopped; the 2 GiB Langflow runtime was not started. Flow import, real response envelope and memory requirements remain unverified.
- The reviewed feature includes the approved industry-template dependency. Independent staged-snapshot validation also found a baseline collection failure: the committed payment test still imported the removed Toyyibpay route. Its existing workspace cleanup is preserved as a separate prerequisite test commit. Other unrelated payment/media edits, user documents, secrets and local tool configuration remain excluded.
