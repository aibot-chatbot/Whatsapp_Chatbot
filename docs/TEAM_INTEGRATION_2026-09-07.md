# Team integration - 7 September 2026

## Scope

Integrated the current checkout and the active GitHub branch histories for `main`,
`deeying`, `jackhan`, `meiyie`, `vince`, `yeexuen`, and `deploy/render-preflight`.
Three independent native Codex reviewers inspected incoming changes and local
features; the parent integrated and verified their fixes. This is an automated
peer review, not a claim that the human branch authors approved this release.

The revision used for the full application suites and security scans is
`aa6ef5921d6bf95caa16df75961ffab96ebf9313`. A subsequent small HitPay webhook
body-limit fix received focused tests and independent peer review, described below.

## Review fixes

| Area | Result |
| --- | --- |
| Scraping | Public-IP pinning, TLS hostname validation, redirect checks, proxy isolation and response bounds; relative links use the final URL. |
| Shared runtime | Preserved automation routes and the Gemini helper removed by incoming code. |
| Payments | Pending HitPay polls rotate without changing checkout expiry; configuration failures are retryable; health checks include valid URLs and order storage. |
| Webhook request bounds | HitPay bodies over 1 MiB return 413 before configuration, signature verification, or provider work; both declared lengths and bounded streaming reads are covered. |
| Plan gates | Explicit server flags control refinement, CRM assignment and report actions; preserved modular pricing and renewal behavior. |
| Knowledge UI | Refinement mounts only with granted access; no conditional hook ordering or catalog authorization fallback. |
| Support and staff | Sensitive searches are omitted from escalation context, staff see escaped trails, and article order remains editable. |
| Navigation | Mobile navigation scrolls without covering its account footer. |
| Tests | Repaired outdated contract assertions and isolated credential/session fixtures without weakening permission checks. |

Generated tenant history/readme artifacts were removed from tracking and retained
on the local disk. Existing Git history was not rewritten. The abandoned detached
OMX snapshot `b7dc4ca` was excluded: it would serve an active draft profile without
explicit deployment, which the current contract still defers.

## Verification

- Full backend suite: **3,474 passed; 2,143 subtests passed; 1 optional test skipped**.
  The optional third-party QR decoder is unavailable. Two existing Supabase-client
  deprecation warnings remain. Runtime: 232.95 seconds.
- Full Chrome suite: **344 passed**, including the real Flask persona harness with
  mocked Supabase/AI boundaries. Runtime: 12.9 minutes.
- JavaScript session/API tests: **2 passed**. Python/JavaScript syntax and full
  revision whitespace checks passed; `pip check` reports no broken requirements.
- Migration 054 passed actual PostgreSQL 18 checks in a new disposable loopback
  cluster: default values, preservation, repeated application and scoped rollback.
  The cluster was stopped after verification.
- Final webhook fix: **27 focused HitPay tests and 4 subtests passed**. Tests prove
  the declared oversized body is not read, a stream without Content-Length reads
  at most the limit plus one byte, and an accepted body retains exact signature
  bytes. Independent peer review found no blocker.
- Codex Security: **incomplete, not passed**. Scan
  `12906cb3-8553-4887-91e0-85a64ed8fb41` reviewed all 93 inventory items and
  reported zero findings, but its sealed coverage retained stale deferred
  metadata for the validated, suppressed billing-health candidate. CLI exit: 2.
  A fresh follow-up verified the prior target and artifact hashes but was blocked
  by the security service's cybersecurity-risk flag at 48/93 review items.
  Its additional body-size concern prompted the tested webhook fix above.
  The original sealed result remains unchanged. The final webhook patch has
  peer review and focused test evidence, but no completed Codex Security scan.

The backend test runner cleared inherited credentials, disabled dotenv loading and
blocked non-loopback socket connections. Browser suites used synthetic services or
mocked provider/database boundaries. No live messages, charges or schema changes
were performed. GitHub had no configured check runs at inspection.

## Deployment prerequisites

No deployment command or live migration was run. Deployment status and any
downstream automation triggered by GitHub are not verified. Check the intended
environment before release. In particular, migration 052 is required for
support escalation context, migration 054 for the new refinement defaults, and
migration 051 must complete its duplicate-order preflight before enabling HitPay.
Preserve explicit feature overrides; the 054 rollback requires the IDs returned
by the forward migration. Confirm the remaining existing migration prerequisites
from the staff and payment rollout documents.

The scheduler's last-run timestamp means a sweep completed; its established exit
contract permits individual order failures. Historical migration 037 retains its
Phase 6 activity breakdown; the current audit log carries later staff events.

## Synchronization

The seven active GitHub branches are to be advanced atomically with ordinary
fast-forward updates, preserving every remote head's ancestry. The final push
and local/remote equality readback are recorded in the local validation artifact.
This source publication does not constitute a passed security gate or production
readiness certification.
Team members should run `git pull --ff-only` on their own clean checkout. Their
other computers cannot be updated by synchronizing this checkout and GitHub.
