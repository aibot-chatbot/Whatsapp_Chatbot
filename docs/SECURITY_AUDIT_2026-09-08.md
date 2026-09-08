# Client-data security audit — 2026-09-08

Status (2026-09-09): local repairs implemented and verified; comprehensive security scan incomplete and skipped at user request. Deployment and Sentry instrumentation remain unverified.
This is a bounded review of the current checkout, not a guarantee that the system
has no vulnerabilities. All exploit fixtures use synthetic data and mocked
providers. No production deployment, credential rotation, database migration,
customer message or live payment was performed.

## Repairs

| Boundary | Confirmed defect and local repair | Evidence |
| --- | --- | --- |
| Password reset and signup | Reset verification lacked a guess limit. Account budgets now cover normalized email aliases and changing IPs; reset verification/final reset share one budget. Signup has an account OTP budget and registration has an IP limit. OTP generation uses `secrets`. | `tests/test_password_reset_guessing.py`; independent 20-request concurrent test permitted only 3 comparisons with a 3/hour budget |
| Signup credential integrity | A second registration could substitute its password before the first browser verified an email, including across expiry. Atomic insert-if-absent preserves pending credentials; resend renews the original OTP. | `tests/test_registration_challenge_integrity.py`: concurrent requests, expiry, actual resend/verify lifecycle using installed SDK and MockTransport |
| Untrusted uploads | HTML/SVG could execute on the application origin; repeated filenames replaced earlier files. Media serving now applies CSP sandboxing, downloads active/doc formats, and assigns UUID names to new uploads. | `tests/test_media_serving_security.py`; synthetic Chromium HTML/SVG execution-before/download-after plus PNG/WAV compatibility proof |
| CRM input | Both mutation routes parsed unbounded JSON. A shared bounded read rejects bodies above 128 KiB before parsing, including chunked requests. | `tests/test_crm_routes.py`: four oversized-body regressions and ordinary mutation controls |
| Credentials and private errors | Redis URLs, Telegram request errors/provider bodies and auth failures could disclose secrets or client details. Safe operation/type/status messages replace raw contents, with generic client-facing errors. | `tests/test_sensitive_logging.py`, `tests/test_telegram_sensitive_logging.py` |

Additional confirmed repairs before commit:

- Media keyword rendering reuses HTML escaping, preventing stored keywords from creating active elements, including historical rows.
- Subscription downgrade, clear-downgrade, cancel and undo-cancel require owner/admin roles. Authoritative member identities cannot invoke these company-wide mutations.
- Meta webhook bodies are limited to 1 MiB before signature validation, with an extra byte to detect oversized streaming requests. Exact bytes remain cached for downstream JSON parsing.
- Multipart media upload requests are limited to 32 MiB and return HTTP 413 before saving oversized files. This is a per-request bound; cumulative media storage quota remains open.

## Control coverage

| Control | Current evidence and limit |
| --- | --- |
| Authentication and RBAC | Database identity/role refresh, staff allowlists, active-company checks and cross-tenant denial suites were inspected/tested. Existing JWT sessions are not revoked by password reset; changing the session contract requires a separately reviewed rollout. |
| Tenant and child ownership | Sampled conversation, CRM, chatbot, staff and billing paths derive company context from authentication and check resource linkage. No bypass was confirmed in these sampled paths; this does not establish every database policy. |
| Payment/webhook integrity | Existing HitPay, subscription callback and AI-credit callback tests exercise provider verification, ownership and replay behavior. No real payment was made and no live provider setup was verified. |
| SSRF and browser boundaries | Public-page fetching pins validated public addresses, checks redirects and bounds response size. CORS and security-header tests plus the media attack proof were exercised. |
| Database permissions | Read-only live metadata: 49 public tables; 21 lack RLS but none grant anon/authenticated table or column access. Four client-granted tables have RLS and no allow policies. Inspected SECURITY DEFINER functions deny client execution. The pending-registration email unique index exists. Backend service-role access still makes application tenant checks essential. See limits below. |
| Error monitoring | Replacement Sentry token successfully authenticated through the read-only plugin helper. Organization `kaguyahouraisan` returned zero accessible projects, with no next page. No project events could be inspected. No Sentry SDK integration was found in application, frontend, dependency or deployment files. The exposed token was never used or stored by this audit; the user confirmed replacement, and the Windows variable now differs. Revocation of the original was not independently tested. |
| Runtime | The prior Windows Langflow startup work remains intact. Insecure local HTTP can be impersonated by another local account; socket timeouts are not hard total deadlines. These remain open and need a reviewed runtime change. |

## Compatibility and operating limits

- Pending signup credentials cannot be replaced by resubmitting the signup form,
  even after expiry. Submitting the original signup password from a fresh browser
  resumes verification without changing the saved profile, password or OTP and
  without sending another email; use the verification page's resend control if
  the code expired. Different passwords remain rejected. Password checks have
  both IP and normalized-email budgets. Forgotten pending-signup passwords or
  credentials preclaimed by another person still require a separate recovery
  flow that proves email ownership; they are not silently replaced.
- PDFs and other documents now download. Raster images/audio/video stay inline;
  existing primary/legacy public media URLs still resolve. These are public delivery
  assets, not a private-document storage system.
- Logs retain operation names, exception classes and HTTP statuses. Raw error text
  and chained traceback details are omitted from the repaired paths.
- OTP counters use the existing limiter backend. Multi-worker deployments need
  shared storage such as Redis. The Dockerfile declares one worker/eight threads. Render CLI v2.16.0 rejected read-only service discovery because its token expired, so actual deployment configuration and deployed commit remain unknown.
- CRM JSON is limited to 128 KiB. File-upload routes retain their own behavior.

## Verification record

Audit verification before the final signup-resume compatibility fix:

| Check | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest tests -q --tb=short` | Exit 0; 3,603 passed, 1 skipped, 2,145 subtests passed; 152.56 seconds. Two existing Supabase deprecation warnings. |
| Focused auth, registration, logging, CRM and media regression suite | Exit 0; 134 passed in 12.36 seconds. |
| Tenant, staff, SSRF, payment callback, CORS and security controls | Exit 0; 192 passed plus 8 subtests in 10.61 seconds. |
| Independent follow-up reviews | Auth: 21 tests plus concurrent shared-budget proof. Privacy: 81 tests/4 subtests plus 33 historical-error projection checks. Review findings were repaired before final verification. |
| Syntax, whitespace and browser proof | All nine repaired application files compile; `git diff --check` passes. Chromium confirms HTML/SVG execute against the original handler but download after the fix; PNG/WAV remain usable. |

The original handler used by the browser proof was extracted from baseline commit
`106d5da843f26a19be70254b66b19ae59ed7a51b`. The proof used isolated loopback
routes and synthetic tokens; its browser/server were shut down afterward.

## Live database findings and limits

The configured Supabase project was confirmed through the management API as active.
Queries read permission, policy, function, role and index metadata only. No customer
rows, live-user impersonation, payment calls or database writes were used.

- The 21 tables without RLS remain a defense-in-depth gap despite revoked client
  privileges. Four tables with client grants deny access through RLS with no allow
  policies. An informational warning for missing policies is not a reason to add
  public access. See [Supabase RLS behavior](https://supabase.com/docs/guides/database/postgres/row-level-security).
- Two SECURITY INVOKER functions, `match_knowledge_chunks` and
  `match_knowledge_chunks_by_file`, have mutable search paths. Client execution
  does not bypass their underlying table RLS. A reviewed migration should pin
  their search paths: [search-path advisory](https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable).
- The `vector` extension is installed in `public`; relocation needs a dependency
  review before migration: [extension advisory](https://supabase.com/docs/guides/database/database-linter?lint=0014_extension_in_public).

The advisor returned three warnings and seventeen informational RLS/no-policy
entries. Metadata did not establish an exploitable client-access path for these
warnings. No RPC, RLS, extension or production configuration change was applied.

## Local Langflow runtime

Installed Langflow 1.11.5 runs backend-only on `127.0.0.1`. A request to
`/api/v1/users/whoami` with no credentials returned HTTP 403; the installed
endpoint uses `CurrentActiveUser`. This verifies anonymous denial on that
protected route, not the exact AUTO_LOGIN setting or every public endpoint.
See [Langflow authentication](https://docs.langflow.org/api-keys-and-authentication).

The installed version is outside the affected ranges in these sampled upstream
advisories: [public-flow RCE](https://github.com/langflow-ai/langflow/security/advisories/GHSA-vwmf-pq79-vjvx),
[file-write RCE](https://github.com/langflow-ai/langflow/security/advisories/GHSA-g2j9-7rj2-gm6c),
[Agentic Assistant RCE](https://github.com/langflow-ai/langflow/security/advisories/GHSA-v8hw-mh8c-jxfc),
[cross-user flow execution](https://github.com/langflow-ai/langflow/security/advisories/GHSA-qrpv-q767-xqq2),
[weak credential encryption](https://github.com/langflow-ai/langflow/security/advisories/GHSA-jxw3-mjmx-3pqm),
and [TAR symlink RCE](https://github.com/langflow-ai/langflow/security/advisories/GHSA-ccv6-r384-xp75).
This was a targeted advisory review, not a complete installed-dependency scan.
No package upgrade or runtime change was needed from these checks.

## Source scan

Codex Security's desktop scan tools are unavailable in this session. The installed
CLI is the available scan route. Its access advisory connector returned
`USER_NOT_LOGGED_IN`; protected scan-output access is unverified and this advisory
does not authorize or prevent scanning. The last saved checkpoint reports 228 of 340 scoped files reviewed, `scan.complete=false`, and no sealed final result. The user requested skipping the long scan on 2026-09-09. Its original execution session no longer exists. Scan ID: `3b088492-119a-4fe2-84bf-56fcc89b0f2e`. This is not a passed scan and does not cover the final follow-up edits.

Confirmed checkpoint candidates were independently reproduced and repaired where bounded local changes were available. Public billing health exposes only intentionally public readiness metadata. Widget session rotation matches the existing anonymous new-chat behavior; changing it requires a defined shared visitor/widget budget.

## Remaining release work

Pre-publication verification on 2026-09-09: the staged changes passed the full
mocked backend suite (3,635 tests and 2,145 subtests; one optional skip and two
existing warnings, 294.58 seconds). Peer review then identified the fresh-browser
pending-signup regression described above. Its bounded compatibility fix passed
41 focused tests and 12 subtests, plus two mocked Chrome flows covering recovery
and mismatched-password denial. The full suite was not rerun after that narrow
fix. Windows PowerShell 5.1 supervisor tests passed mutex isolation, occupied-port
handling, duplicate suppression, launch retry and crash recovery. Python syntax,
dependency consistency and whitespace checks passed. Security scan status remains
incomplete; these checks do not establish deployment or comprehensive clearance.

1. Add atomic cumulative media-byte accounting, including unattached uploads and concurrent admissions. Knowledge-file billing usage currently excludes media; the 32 MiB request cap does not close repeated-upload disk exhaustion.
2. Finish comprehensive security coverage and triage remaining deferred candidates before claiming security clearance.
3. Configure a Sentry project and privacy-controlled application instrumentation; the authenticated organization currently lists no accessible projects.
4. Review JWT session revocation, database hardening warnings and the existing Langflow transport/deadline limitations documented above.
5. Verify the deployed commit/configuration. GitHub publication does not prove a successful production deployment.
