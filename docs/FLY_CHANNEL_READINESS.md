# Fly channel publishing readiness

Checked 10 September 2026 against this checkout, the live Fly deployment,
Supabase records and provider status. Public hosting, callback configuration
and real message delivery are reported separately below.

## Current deployment status

**Public application live:** [login](https://aibot-chatbot-my.fly.dev/login.html).
The user corrected the billing target to **aibot EMAIL**, organization slug
`personal`, signed in as `aibot@iomaths.com`. The earlier IOMaths (`iomaths`)
payment rejection is superseded by this target change. The old app name
`wa-chatbot-my` was globally taken; `aibot-chatbot-my` was created in `personal`.

One Machine `185de27f125998` runs in `sin` with one shared CPU and 1024 MB RAM.
Encrypted 1 GB volume `vol_vwnl05wn2jxww88v` (`chatbot_data`) is mounted at
`/app/data`. Public IPv4/IPv6, normal DNS, HTTPS and Fly health checks were
verified. Compute is in Singapore; the existing Supabase project remains in
Seoul (`ap-northeast-2`).

Password login was verified through both the public API and Chrome:
`aibot@iomaths.com` lands on `admin.html`; `superadminaibot@iomaths.com` lands on
`superadmin.html`. Admin billing access succeeds and Superadmin-only endpoints
return 403 to Admin. Both dashboards populate; Superadmin charts render.
Google sign-in separately returns an origin-not-allowed error: the existing
Google OAuth client still needs this canonical origin added.

Website pages and public configuration endpoints for enabled bots **35, 50 and
53** return 200 without an admin session. Bot 38 remains disabled. No synthetic
conversation or outgoing message was created during these checks.

The user selected **all eligible configured destinations**, then selected
**OlympicEdu Assistant (bot 53, company 1)** as the sole owner of the shared
Telegram provider bot. Rows 5 (bot 20), 7 (bot 35), and 8 (bot 53) reused one
Telegram token; archived bot 29 also retained active row 6. Initial per-row
readiness missed that shared identity. The migration guard caught the conflict
before a second registration overwrote the first. The temporary row-5 callback
was removed; provider readback confirmed an empty callback, zero pending updates
and `drop_pending_updates=false`. The user then chose bot 53. Rows 5, 6 and 7
were disabled with scoped compare-and-set updates; row 9 stayed inactive. All
five rows, credentials and conversation history were retained. Row 8 is the only
active owner and is now connected to the canonical Fly callback.
Migration [055](../data/055_telegram_active_provider_owner.sql), recorded live as
`20260910130516 / telegram_active_provider_owner`, now enforces one
active row per Telegram provider ID. The live index is unique and valid; its
key and partial predicate were read back from the catalog. The guarded image is
deployed. Provider readback confirms the exact stored callback, zero queued
updates and no delivery error. One queued update was preserved and cleared after
activation. The user subsequently confirmed that bot 53 replies to a short test
message. Broader knowledge accuracy and other channel delivery remain untested.
Public bot:
[UltraAvaShopBot](https://t.me/UltraAvaShopBot).

The sole Wasender row belongs to missing bot 1 in company 1 and was not activated
by this release.
A read-only official provider status call at 13:34 UTC accepted its stored key
but reported `logged_out`, despite the stored connected state. No session ID is
stored. The user selected **Travel Bot (50)** in the same company for Wasender,
then explicitly deferred setup until registration is ready. Telegram stays on
bot 53. No Wasender connection row has been reassigned, created or deactivated.
There are zero Meta WhatsApp rows; no configured eligible session/phone exists
to publish.

Read-only bot-50 preflight found a resolved deployed profile and 44 nonempty
embedded chunks in primary knowledge file 59. Its generated summary exists on
Fly; the original PDF is missing. The runtime retrieves the stored chunks, so
PDF absence alone does not prove reply failure. Company 1's Pro monthly period
is 28 July to 28 August 2026 at 16:38:37 UTC: a valid month, now expired. The
runtime entitlement resolver returns expired/not entitled and will reject a new
Wasender connection. Existing renewal order 23 is pending past its saved expiry;
provider payment status was not queried before the user's deferral. Resolve that
status before requesting another payment or extending entitlement. Fly billing
does not renew the application's company subscription.

On resume, inspect the existing Wasender session, resolve the subscription through
the supported billing flow, and prepare the bot-50 callback before QR relinking.
The orphan row still has an active stored callback pointing to the former ngrok
host. Disable that callback and conditionally deactivate only row 1 before the
new connection becomes active; preserve credentials, history and queued work.
Do not move bot-1 conversations/retries to bot 50. The normal disconnect endpoint
cannot manage the orphan because bot 1 no longer passes ownership lookup.
Provider settings need dashboard access or a documented account token and numeric
session ID. The application's connect response alone is not provider verification.
Only the Telegram ownership index was added; no RPC or RLS change was made.
No payments or direct test messages were sent.

## Publish flow and supported destinations

Line references in the initial assessment below describe the pre-ownership-patch
snapshot; the final Telegram behavior is recorded in the ownership release section.

The bot's Publish screen is `frontend/integration.html`, reached from the setup
journey (`frontend/assets/js/bot-setup-journey.js:24`). Its implemented choices
are website/share link, Telegram, Meta WhatsApp Business, and WhatsApp via
Wasender (`frontend/integration.html:825`). No additional channel adapter was
identified in the current Publish flow; “other channels” requires an explicit
provider selection rather than treating an unimplemented provider as available.

Applying a bot profile is a separate operation:
`PUT /api/settings/apply-profile?chatbot_id=...`; ownership and tenant role checks
precede the change (`app/routes/settings_routes.py:109`). It copies the draft
profile and PDF references into deployed settings
(`app/services/settings_service.py:313`). Hosting the app or connecting a channel
does not itself choose which draft should become the customer's live bot.

| Destination | Existing setup and callback | What still establishes readiness |
| --- | --- | --- |
| Website/share link | `GET/PUT /api/bots/<id>/widget`; URLs generated from `PUBLIC_BASE_URL`, otherwise request origin; `/chat/<key>`, `/widget/<key>`, `/widget.js` (`app/routes/widget_routes.py:391`, `:415`). | Enable only the selected bot; open without an admin session; test external embed origin and the selected knowledge response. The API explicitly reports reachability `not_checked` (`:375`). |
| Telegram | `POST /api/telegram/connect`, `PUT /api/telegram/channels/<id>/reconnect`; callback `/telegram/webhook/<secret>` (`app/routes/telegram_routes.py:314`, `:590`, `:836`). | Validate stored token via `getMe`, register canonical HTTPS URL and secret, inspect `getWebhookInfo`, then selected test-account inbound/reply proof. |
| Meta WhatsApp | Embedded Signup config/complete endpoints; shared callback `/webhook` (`app/routes/whatsapp_routes.py:125`, `:255`; `app/views.py:99`). | Correct Meta app/config/token/phone; callback verification; WABA app subscription and phone registration confirmed; a real selected-number inbound/reply test. |
| Wasender | `POST /api/wasender/connect` saves API key/session/phone; callback `/wasender/webhook/<secret>` (`app/routes/wasender_routes.py:57`, `:256`). | Provider session connected; saved generated URL pasted into that session's settings; subscribe to `messages.received`; confirm actual inbound and reply. Current connect endpoint does not register or validate the session with Wasender. |

The UI reads channel counts from billing and applies plan limits; the server also
checks limits before creating connections (`frontend/integration.html:351`,
`:436`; `app/routes/telegram_routes.py:340`; `app/routes/wasender_routes.py:127`;
`app/routes/whatsapp_routes.py:192`). Website/share link does not consume a paid
channel slot (`frontend/integration.html:58`).

## Deployment invariants

The configured and verified live target is `aibot-chatbot-my` in `sin`, owned by
`personal` (aibot EMAIL). Deployment used an immutable reviewed image and the
existing single Machine, with no additional HA Machine.

1. One application Machine and one Gunicorn worker; eight threads are already
   configured. Wasender retry and billing scheduler ownership are process-local
   (`Dockerfile:54`; `wsgi.py:31`, `:47`).
2. Mount `chatbot_data` at `/app/data`; verify write permissions and preserved
   knowledge/media files. The image filesystem alone is ephemeral
   (`fly.toml:43`; `Dockerfile:34`, `:45`).
3. Keep the Machine running; `auto_stop_machines=false` is required by the
   in-process retry loop (`fly.toml:48`; `app/services/wasender_retry_service.py:135`).
4. Set the chosen canonical HTTPS `PUBLIC_BASE_URL` before new registrations.
   Telegram/Wasender store callback URLs when connected; changing the environment
   does not update existing provider registrations
   (`app/routes/telegram_routes.py:375`; `app/routes/wasender_routes.py:113`;
   `scripts/reregister_telegram_webhooks.py:1`).
5. Verify actual production secrets and flags without logging their values.
   Meta receive uses `APP_SECRET`; signup uses `WHATSAPP_META_APP_SECRET`; outbound
   WhatsApp uses `VERSION` with no default. The two app-secret settings must refer
   to the same Meta app, and `VERSION` must match the selected supported Graph
   version (`app/decorators/security.py:15`; `app/routes/whatsapp_routes.py:36`;
   `app/utils/whatsapp_utils.py:99`).

The Fly `/` check proves static frontend availability, not Supabase, AI, provider
delivery, or successful background work (`fly.toml:65`; `app/views.py:23`). Existing
broader deployment operations and rollback guidance are in
[PUBLIC_DEPLOYMENT_PLAN.md](PUBLIC_DEPLOYMENT_PLAN.md).

## Concrete blockers and minimum follow-up

| Priority | Finding at inspection | Smallest next step |
| --- | --- | --- |
| Telegram ownership and queue preservation implemented | Set/delete webhook helpers preserve pending updates. A partial unique index allows one active owner per provider ID; conditional pending claims serialize provider mutations. Inactive duplicates cannot disconnect the live owner or send staff replies. | Keep migration 055 installed. Do not clear a pending operation until its provider outcome is reconciled; verify real inbound/reply behavior separately. |
| Before declaring Meta connected | Embedded completion exchanges the code, reads phone metadata, and stores `connection_status=connected` (`app/routes/whatsapp_routes.py:172`, `:194`, `:210`). No `subscribed_apps` or provider phone `/register` call exists in the inspected flow. | Confirm these two provider prerequisites for the selected assets; implement/verify missing onboarding steps if not already configured. Until then, saved connection state is not delivery proof. |
| Logging and container fixes deployed | Wasender logs omit callback secrets, customer payloads, provider bodies, exception values and retry phone numbers. Docker access logs emit method/status/duration only. The build context admits 268 literal tracked files. | The live Fly mount restored 41 available runtime files with exact hash and write-permission checks. Missing original PDFs elsewhere in database metadata remain a separate recovery gap. |
| Before claiming Wasender provider authentication | Callback route has no `X-Webhook-Signature` validation and authenticates through active stored path-secret lookup (`app/routes/wasender_routes.py:257`; `app/services/wasender_service.py:224`). | Configure and validate the provider shared-secret header for the selected session. Provider documentation uses direct shared-secret comparison, not HMAC. Avoid silently breaking existing sessions while adding enforcement. |
| Event selection | Parser expects object-shaped `data.messages`; arrays raise at `.get("key")` (`app/services/wasender_service.py:67`). Filtering happens after parsing and only accepts `messages.received` (`:240`, `:252`). | Subscribe only to documented object-shaped `messages.received`. Supporting `messages.upsert` requires array handling and event logic; do not advertise it as supported today. |

Meta's own collection states that the app must be subscribed to the WABA for
notifications, and that the phone must be registered before sending. Those are
provider prerequisites, not evidence that any existing account is misconfigured.
[Meta Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api?entity=request-13382743-071cfa60-0704-41d2-bca2-36ba6bd33dfe).

Wasender's setup requires a public HTTPS callback, session event selection and
its configured header secret. Its `messages.received` example uses an object;
the `messages.upsert` example uses an array. The source currently implements the
first shape only.
[Wasender setup](https://wasenderapi.com/api-docs/webhooks/webhook-setup),
[received event](https://wasenderapi.com/api-docs/webhooks/webhook-message-received),
[upsert event](https://wasenderapi.com/api-docs/webhooks/webhook-message-upsert).

## Delivery and durability limits

- Telegram registers `secret_token` and rejects a mismatched header, but deliberately
  accepts an absent header for legacy channels (`app/routes/telegram_routes.py:839`).
  `getWebhookInfo` URL/error checks are implemented (`:266`, `:750`). No reported
  error before a real update does not prove successful delivery or AI response.
  Telegram's API distinguishes webhook registration from webhook status and
  delivery errors. [Telegram Bot API](https://core.telegram.org/bots/api#setwebhook).
- Telegram asks for a phone number before the normal AI path; include that step
  in the selected bot's acceptance test (`app/utils/telegram_utils.py:370`). Text,
  contacts and interactive replies have handling; this is not a claim of general
  inbound-media support (`:256`, `:330`, `:418`).
- All three messaging callback handlers process before returning their HTTP
  response (`app/views.py:66`; `app/routes/telegram_routes.py:885`;
  `app/routes/wasender_routes.py:267`). Slow AI/DB/provider work can therefore keep
  provider callbacks open. No durable inbound worker is wired in these handlers.
- Existing processed-ID checks occur before work and marks after sends; concurrent
  deliveries or a crash between send and persistence are not proven exactly-once
  (`app/utils/telegram_utils.py:196`, `:518`; `app/utils/whatsapp_utils.py:160`,
  `:302`; `app/services/wasender_service.py:265`, `:380`). A Telegram atomic-claim
  helper exists but has no call sites in `app` at inspection
  (`app/database/processed_telegram_update_repository.py:9`). Reuse that seam only
  with failure/retry semantics verified; do not infer durability from its presence.
- Wasender outbound failure metadata is persisted and the singleton worker retries
  one due message per cycle (`app/services/wasender_service.py:363`;
  `app/services/wasender_retry_service.py:32`). Telegram/Meta send paths do not have
  that same durable retry loop. Their stored `sent`/processed flags alone are not
  a customer-delivery receipt (`app/utils/telegram_utils.py:490`, `:514`;
  `app/utils/whatsapp_utils.py:300`).

## Bounded verification performed

Read the shared test setup before running: `tests/conftest.py` disables local
dotenv loading and Sentry, substitutes the Supabase client and AI imports; selected
provider HTTP seams are mocked in the test modules.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_publish_frontend.py tests/test_telegram_webhook_secret.py tests/test_telegram_delivery_verification.py tests/test_reregister_telegram_webhooks.py tests/test_telegram_sensitive_logging.py tests/test_meta_webhook_body_limit.py -q
```

Result: **129 passed, 4 subtests passed in 7.51 seconds**, exit 0. This includes
Publish source contracts, Telegram secret/delivery/redaction behavior, re-registration
with fake providers, and Meta callback body limits. It is not browser, deployment,
live Supabase, or real-provider-message evidence.

A separate pure-parser synthetic probe, after loading the mocked test setup,
passed an array as Wasender `data.messages`: it reproduced
`AttributeError: 'list' object has no attribute 'get'` at
`app/services/wasender_service.py:69`, exit 1. This confirms the unsupported upsert
shape; the documented `messages.received` object is not implicated by that probe.

The initial channel assessment was read-only. No credentials were read from live
rows, no channels were registered/reconnected, and no messages/payments were sent.
Subsequent release changes and security evidence are recorded below.

### Independent review of the Wasender logging patch

Read the Matt Pocock `code-review` skill and pinned the baseline to
`b1010923350b6699cc20cfd3f7ee75d8ae118544` (`HEAD` at review time). Reviewed its
working-tree diff for `app/routes/wasender_routes.py`,
`app/services/wasender_service.py`, and `app/services/wasender_retry_service.py`,
plus the new `tests/test_wasender_logging.py`. This bounded reviewer lane performed
both review axes itself under the parent's no-further-delegation instruction.

**Standards: no material findings.** The change removes private values from logs,
uses the existing safe `server_error` helper, keeps DB/service/route boundaries,
and adds no dependency or abstraction. Shared-helper callers retain the same
`success/data/error` result keys and status-derived success checks; provider
response data is still returned to the existing internal callers, while errors
persisted for retries no longer copy response bodies or exception values.

**Spec: no material regression found.** The change satisfies the requested
deployment-preparation privacy fix while preserving outbound request URL, auth,
payload, timeout, routing, channel lookup, deduplication, retry scheduling and
success/failure updates. The older provider authentication, event coverage and
delivery-proof gaps listed above remain separate unmodified limitations.

Independent execution: `python -m pytest tests/test_wasender_logging.py -q`
using `.venv/Scripts/python.exe` returned **16 passed in 0.17 seconds**, exit 0.
`py_compile` of the three changed runtime modules and scoped `git diff --check`
also completed successfully. The tests mock provider HTTP and persistence; no
real session, customer recipient, payment or provider registration was touched.

## Release integration verification — 10 September 2026

The parent ran:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_container_release.py tests/test_wasender_logging.py tests/test_storage_paths.py tests/test_media_serving_security.py tests/test_langflow_decision.py -q
```

**76 passed in 7.93 seconds**, exit 0. Combined with the distinct six-module
channel suite above: **205 tests and 4 subtests passed**. Provider and database
calls in these tests use synthetic/mocked seams. The container regression checks
enforce the exact tracked-file manifest and metadata-only access format.
Documentation links and `git diff --check` passed.

The Sentry plugin's read-only production query returned no unresolved issues
in the preceding 24 hours, exit 0. This does not prove that a Fly deployment or
production reporting exists.

The local Docker build subsequently completed, exit 0, as
`codex-wa-fly-release:20260910`, image ID
`sha256:28a79e771d60b5fb7eed579a46efb985cff47e0a425a5f863e68b3ae3b38e53d`.
An isolated container smoke check also completed, exit 0:

- Network disabled, synthetic credentials only, background jobs disabled.
- `/`, `/login.html`, the since-retired Platform Admin page, and `/superadmin.html` returned 200.
  This proves page availability, not authenticated login or live database access.
- Both tested crashdump paths returned 404. All 266 runtime files matched the
  approved source hashes; no extra runtime files were present.
- The container ran as UID 1000 and could write its local `/app/data` volume.
- A synthetic callback health request returned 200; its private path/query canary
  was absent from Gunicorn logs, which contained method/status/duration only.
- The temporary container and its anonymous volume were removed. At that stage
  the image was local; the later registry push and Fly release are recorded below.

Safe machine-readable evidence is stored outside the repository at
`C:/Users/Vincent/.codex/security-private/fly-container-check-20260910/result.json`.
The earlier IOMaths app-creation retry was rejected for payment information
(request `01M25BPHDPS2RX3K79GPPG1TS3-sin`). That historical block was superseded
when the user selected the paid aibot EMAIL organization.

### Live deployment verification

The first public release pushed the reviewed image to
`registry.fly.io/aibot-chatbot-my:20260910` and deployed its AMD64 digest
`sha256:890387cc9b0668fa31ffb753300b7b6d445907430faee97fe556a93b5de371df`.
Registry push, private bootstrap, private application boot and public deployment
all exited 0. The initial image index digest is the local image ID above; the
AMD64 child digest is the value verified in the live Machine configuration.

Storage was restored before exposing the application: 41 non-SQL runtime files,
including legacy media relocated under `/app/data/media_uploads`, were copied
through a private archive. Traversal, links, duplicate paths and overwrites were
rejected. Every file hash, UID 1000 ownership and write access were checked;
the aggregate manifest hash remained
`66c5209cb4b0324bbf2e84e3f6cc147a049eae65a5e10dd9cc0bb28737bc1016`
after the public restart. These are all available selected local runtime files,
not recovery of every original document recorded in Supabase. Most referenced
original PDFs were absent locally; bot 53's active knowledge has 67 stored chunks
and supporting knowledge has 57, which remain available to the existing RAG path.
Bot 35 has stored chunks but no deployed profile; none was invented or applied.

Thirty-four selected deployment secrets were read in memory and imported through
stdin, without uploading the whole developer environment or printing values.
Signing keys were retained; callback/return origins use the canonical Fly host.
The existing payment environment was preserved; no payment was executed.
Wasender retry, billing scheduling and Langflow automation remain disabled until
their existing owner is handed over and the necessary hosted runtime is reachable.

The first public check encountered a cached negative DNS response after IP
allocation. Verified-IP checks retained TLS validation; subsequent normal DNS
and Chrome checks succeeded. No hosts file or DNS-server setting was changed.
Public `/`, login, both staff pages and `widget.js` return 200; `.env` and both
crashdump paths return 404; unauthenticated staff overview returns 401. Successful
staff API login and Chrome navigation establish the role-specific redirects and
permissions stated above. No browser exceptions or failed dashboard requests were
observed. Google OAuth is excluded from the successful password-login result.

Safe local evidence includes `public-api-login-result.json`,
`portal-live-qa.md`, `website-publish-result.json`, and the tenant file manifest
under `C:/Users/Vincent/.codex/security-private/fly-container-check-20260910/`.
No Git commit or push was performed by this deployment continuation.

### Telegram ownership release

Three runtime files changed: the Telegram channel repository, Telegram routes
and staff agent routes. New connections check global active provider ownership;
reconnect claims the row conditionally before calling Telegram, and disconnect
holds that claim until confirmed deletion. Competing requests receive safe 409
responses. Both staff outbound paths select active channels only; history views
retain inactive records. Valid existing webhook secrets are reused. Both
`setWebhook` and `deleteWebhook` preserve pending updates.

Unsuccessful or uncertain provider changes retain an active pending claim.
Recovery is deliberately operator-only: inspect the provider identity, current
callback and pending queue, reconcile to the intended owner without dropping
updates, then finalize the saved state only after the outcome is known. Do not
clear pending blindly or release a claimant while its provider request may still
be in flight. No lease, background recovery process or new dependency was added.

The affected mocked suite passed **276 tests and 4 subtests**, exit 0, covering
ownership, delivery, logging, callback secrets, staff routes, dashboard health,
entitlements, re-registration and tenant access. After the final one-boolean
queue-preservation change, the narrower ownership/secret/logging suite passed
**97 tests**, exit 0. Syntax and diff checks passed. Independent review found
and resolved competing-operation and pre-claim failure races before release.

The final image index is
`sha256:8f261867a9e1e7b94e07eed52a5e1123e1748ca8f253de5e350804e977b10031`;
the deployed AMD64 digest is
`sha256:61c1659a49d07bbf7f4e2a410e49baf8cdf1803513b65fddcd5834fd2005314e`.
The final isolated smoke check verified all 266 runtime file hashes, seven HTTP
checks, non-root writes and no private values in access logs. Build, registry
push and rolling deployment exited 0. The existing Machine's live hashes match
all three changed runtime files. All 41 volume files retain their original
manifest hash; all three background-job flags remain false. Both staff logins
and role-specific API permissions passed again after this release.

Bot 53 / channel 8 was registered with its existing secret and
`drop_pending_updates=false`. Subsequent provider/DB readback agrees on the exact
callback and connected state; the queue fell from 1 to 0 with no provider delivery
error. This establishes provider callback status. The user additionally confirmed
"Yes, it replies" after testing the public Telegram bot. Broader knowledge and
conversation scenarios were not checked. No agent-sent synthetic provider message
was sent.

The initial registry upload failed after its short-lived credential expired;
refreshing with `fly auth docker` restored the authorized push. Supabase SQL
queries are read-only through this connector; the selected data changes used
bounded authenticated REST compare-and-set operations, while DDL used the
available `apply_migration` MCP. The Supabase CLI was absent, so the repository's
numbered SQL convention and callable migration tool were used without installing
another package.

The authenticated Sentry CLI (`--fresh`) reported zero error events in project
`kaguyahouraisan/whastapp_chatbot_project` for
`2026-09-10T13:13:00Z <= timestamp < 2026-09-10T13:22:41Z`, across all
environments/releases, exit 0 with no additional results. The production/release
issue query was also empty. No private event contents were queried. Ingestion
lag and uncaptured warning/browser/Logs paths remain limits; this is not proof
of a successful bot reply or telemetry delivery from every request.

### Codex Security status: incomplete invocation; identified issue fixed locally

Scan `0719dd42-e93d-4378-8795-a5133e291360` analyzed seven source/config/test paths
and saved a sealed report at `2026-09-10T10:35:28.620554Z`. CLI readback reports
complete scoped coverage and one medium finding, with no deferred paths or
truncated findings. However, the scan process exited **1** because documentation
elsewhere in the checkout changed during execution. The seven selected source
hashes were unchanged. Saved results describe the original snapshot and are
**not a successful scan of the current checkout**.

Finding `csf_1ae5bc81b1f3747fb6fdde04` identified recursive Docker context
re-inclusions admitting ignored runtime artifacts. The existing ignored
`frontend/bash.exe.stackdump` demonstrated the boundary failure; no actual
secret or customer-data exposure was established. The file remains untouched
locally. The fix replaced wildcard/directory exceptions with 268 literal tracked
regular-file exceptions. A regression test, independent peer review and the
actual image inventory/HTTP checks above verify its exclusion locally.

The original report remains unchanged. No fresh seven-path Codex Security scan
ran after the packaging fix, and the managed finding has not been marked verified
fixed. Publication must not be described as a whole-release security pass.
Future scans must freeze the entire checkout or use an immutable isolated
checkout, even when specifying paths.

The subsequent configuration-only scan `a748ea8f-e3a2-423f-bf8c-d4270118b941`
completed with exit 0, zero findings, complete coverage of exactly `fly.toml`,
no deferred items and no CLI warnings. It sealed at `2026-09-10T12:50:32.817046Z`.
All 271 isolated context files were unchanged; current `fly.toml` matched SHA256
`8476262caf8834f4b7695f7596e7abf2ee2ad56a69ef21044c979f660ca26872`.
The sealed artifact hashes and CLI readback were verified. This configuration
result does not supersede the earlier incomplete source scan.

The final Telegram ownership scan `7ed8555a-940b-452d-9da6-89ff8d0ee249`
completed with CLI exit 0 and readback exit 0, sealed at
`2026-09-10T13:49:16.355735Z`. Coverage is complete for exactly eight paths:
three changed runtime files, migration 055 and four relevant test files, with
no deferred files or CLI warnings. All 275 immutable context files were unchanged;
the eight current source hashes and sealed artifact hashes matched.
Its evidence directory is
`C:/Users/Vincent/.codex/security-private/telegram-owner-20260910T131119Z/results`.

The report retains one low-severity, medium-confidence finding,
`csf_b305de0fc05e8464446f2cba`: staff outbound selection would accept an active
legacy row lacking a provider identity. Current connect/reconnect paths do not
create that state. The live inventory contains five provider-identified rows;
only channel 8 is active, and its stored identity matches the actual token's
`getMe` result. The finding's required malformed active row is absent from the
verified deployment. No speculative hardening was added after this scan; the
sealed finding remains intact as a latent malformed-data limitation. This
completed scoped scan does not supersede the earlier incomplete source scan.

The initial scan launcher rejected the repository Python interpreter; a verified
standalone Python 3.11 interpreter allowed analysis without persistent
configuration changes. The report is retained at
`C:/Users/Vincent/.codex/security-private/wasender-fly-release-20260910/report.md`.

## Remaining input and acceptance boundary

The user has selected all eligible configured destinations and bot 53 as the
exclusive owner of the shared Telegram provider identity. Wasender is deferred
at the user's request, with bot 50 selected for setup after registration. Preserve unrelated
channels, archived bots, stored history and pending provider updates. A new
provider bot/session must be configured for companies without a unique eligible
connection. For real-message proof, identify one owned test recipient/account
and synthetic test content; registration alone is not that proof.

Acceptance per selected channel: canonical HTTPS endpoint reachable; provider
registration/config matches; authenticated inbound event accepted; selected
deployed bot knowledge used; exactly one observed reply for the test; record
provider errors and repeat-delivery behavior separately. Keep “public app live,”
“callback configured,” and “real conversation verified” as separate results.

## Skills, MCP, plugins and limitations

- Read and applied ECC `verification-loop` and `documentation-lookup` from
  `C:/Users/Vincent/.codex/skills/`, plus Matt Pocock `research` at the same root.
  Parent-assigned research fulfilled the delegated-research lane; no nested agent.
  The follow-up independent review also read Matt Pocock `code-review` there;
  the task itself supplied the specification and fixed baseline, with no issue
  creation or issue-tracker setup required.
- Used the **Context7 plugin MCP** `context7_resolve_library_id` and
  `context7_query_docs`: official Telegram API, Wasender docs, and Meta sample repo.
  Meta samples did not establish all onboarding requirements, so Meta's first-party
  Postman collection supplied the missing evidence.
- Read Agent Reach and its web reference; used its Jina Reader backend for full
  public Wasender setup/event pages. Used web search/open for Meta's first-party
  collection. No authenticated social browsing or provider account actions.
- The initial research lane did not use a Supabase schema MCP query. Subsequent
  parent checks used the enabled Supabase MCP and bounded REST reads; the Fly
  plugin MCP and CLI verified actual infrastructure. Chrome/Playwright supplied
  live portal proof after the in-app browser was unavailable. Each live result
  above has its own scope; none establishes untested real AI/provider delivery.
