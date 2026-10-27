# HANDOFF

## 2026-08-27 — bots.html first-load failure, dashboard stability, error-leak sweep

### The reported bug and its actual causes

"After login, the first load of `bots.html` shows a failed-to-load error; reloading fixes it."
Three separate causes, all now closed:

1. **Icon CDN gated the data load.** `bots.html` loaded `lucide` as a render-blocking
   `<script>` and called `lucide.createIcons()` as the *first statement* of its inline
   block. A slow or blocked CDN threw `ReferenceError`, which aborts the **entire** script
   block — `requireLogin()` never ran and the `DOMContentLoaded` listener was never
   registered, so `fetchBots()` was never called. Reload "fixed" it because the CDN then
   came from HTTP cache. Fixed previously (`defer` + null-safe `refreshIcons()`).
2. **`resilientLoad` was used but never loaded** (regression from that same fix).
   `fetchBots()` called `resilientLoad.loadJson()` with no `<script src>` tag anywhere —
   an undefined global, so the call threw and the page sat on its skeleton forever, never
   issuing a request. Fixed: `frontend/bots.html` now loads `assets/js/resilient-load.js`.
   All 4 tests in `tests/browser/bots-resilience.spec.js` went from 4 failed to 4 passed.
3. **Server side, a transient 500.** `app/database/bot_repository.py:get_all_bots()` has
   no try/except and uses a module-level, process-lifetime Supabase client. A dropped
   keepalive surfaces as an uncaught exception, hits `bot_routes.py`'s outer handler, and
   returns HTTP 500 `{"status":"error"}` — which the old UI printed literally as
   "Failed to load bots". This is the textbook "first call fails, identical second call
   succeeds". Now absorbed client-side: `resilientLoad` retries 5xx with jittered backoff.

### What changed

**Frontend**

- `frontend/bots.html` — loads `resilient-load.js` (the actual fix for cause 2).
- `frontend/index.html` — loads `resilient-load.js`; three fixes:
  - `fetchSelectedBot()` used `window.location.href = "bots.html"` in its `catch`, so **any**
    network blip ejected the user from the dashboard back to the bot picker. It now
    redirects only on a `terminal` outcome (bot deleted, or not theirs) and retries otherwise.
  - The three dashboard reads shared one `try/catch`, so a failure fetching the *knowledge
    file* blanked a message-trend chart that had already rendered. They are now independent.
  - Added `scheduleDashboardRecovery()` — one shared 15s timer that keeps retrying after
    `resilientLoad` exhausts its attempts, so an outage that ends resolves with no user action.
- `frontend/integration.html` — loads `resilient-load.js`; `getJson` now routes **reads**
  through `resilientLoad` (writes stay single-shot: a retried POST could connect or
  disconnect a channel twice) and guards the bare fetch. `loadChannel()` no longer collapses
  a failed read into `[]` — that made a live WhatsApp number render as disconnected and
  invited the user to reconnect something that was never down. Failed kinds go into
  `state.loadErrors` and the header says "Some channels could not be checked - still trying".
- `frontend/assets/js/broadcast.js`, `frontend/assets/js/meta-templates.js` — their `api()`
  helpers had `await authenticatedFetch(...)` **outside** any try/catch. An offline, DNS or
  reset throw became an unhandled rejection, the caller never got a result, and the skeleton
  never cleared: a permanent spinner with no error and no way out but a reload. Now guarded,
  returning `{ok:false, status:0}`, which both callers already render as a retryable failure.
- `frontend/sidebar-component.js` — visual parity with `bots.html`'s rail (see below).

**Backend — security**

- New `app/utils/api_errors.py` exposing `server_error(context, exc)`.
- 57 `except Exception as e: return jsonify({... "message": str(e)}), 500` handlers across
  16 route files now log server-side and return a generic message. `str(e)` on a Supabase,
  httpx or PostgREST error routinely names tables, columns, hosts and paths — free recon for
  anyone able to provoke a 500. `tests/test_upload_pdf_error_logging.py:45` already asserted
  `assertNotIn('"message": str(e)', ...)`, so a test was already demanding this.
- **Deliberately untouched:** the 32 `except ValueError as e` handlers returning 4xx. Those
  carry domain messages the user is meant to read ("Company ID not found in token. Please
  login again."); blanking them would be a regression.

### Sidebar scoping — the premise was wrong, do not re-architect

`bots.html` (workspace scope) is the **only** page with inline `.side-rail` markup — N=1,
not a duplication problem. The other 14 pages already use `<chatbot-sidebar>`, which gates
bot-scoped nav on `!isBotsPage && botId` (`sidebar-component.js:413`). The separation is
correct **and test-enforced**: `tests/test_bots_chatbot_limit_frontend.py:272-275` asserts
`class="side-rail" aria-label="Primary navigation"` is present and that `conversations.html`,
`broadcast.html` and `reports.html` rail links are absent.

Replacing the inline rail with a `<workspace-sidebar>` component **breaks line 272**, which
matches raw source bytes rather than behaviour. Decision: visual parity only. Applied to
`sidebar-component.js`: width 280 to 260px; `'Outfit'` to `"Geist", "Outfit", sans-serif`
(Outfit retained as fallback — `media_attachments.html`, `profile.html` and `support.html`
do not load Geist); blue gradient active state to the product's teal (note `--primary` is
**undefined** on every host page, so `var(--primary, #3b82f6)` always fell back to blue);
brand "AI CHATBOT" to "Aveon"; lucide CDN pinned from `@latest` to `@1.31.0`.

### Verification

- `tests/browser/bots-resilience.spec.js` — 4/4 pass (were 0/4).
- Full pytest: **67 failures before and after, identical sets** (stash-diffed, not counted).
  Those 67 are pre-existing and unrelated.
- Full Playwright: 211 passed, 2 failed — both proven pre-existing or flaky by stash-diff.
  `team.spec.js:262` passes in isolation with or without the change (suite-ordering flake);
  `testbot-persona.spec.js:170` fails identically with the route changes stashed.

### Known issues NOT fixed (deliberately)

- `frontend/crm.html` does not load `assets/js/shared-ui.js`, failing
  `tests/test_tenant_account_menu_frontend.py::test_all_authenticated_sidebar_pages_load_shared_menu_dependencies`.
  Pre-existing. It also has no `<tenant-account-menu>` element, so adding the script alone
  is a half-fix — the page needs both.
- `app/database/*_repository.py` have unguarded Supabase calls. The client-side retry covers
  the symptom; a server-side retry or reconnect wrapper is the root fix but touches ~40
  repository functions.

### Next, highest value first (from a full page-by-page loading audit)

Dead-end failure states remaining, worst first: `widget-chat.html` (end-customer facing —
the composer is *removed* on failure), `new_prompt.html` (6 loaders, 5 swallow silently,
blank page, falsely reports 0 channels), `crm.html` / `insights-actions.js:176` (copy
literally says "Try refreshing this page."), `new_linkdocs.html:930` (a connection error is
rendered under the heading "No graph to show yet"), `media_attachments.html`,
`meta_templates.html` (banner has no Retry), `behaviour.html` ("Reload to try again." twice),
`profile.html` (4 of 8 sections have no retry), `support.html`, `accept-invite.html`
(a blip is indistinguishable from a dead invite).

**Endpoints NOT drop-in compatible with `resilientLoad` — check before migrating:**

- `/api/broadcast/*` returns `{status, campaigns}` / `{status, campaign}` / `{status, logs}`,
  **not** `{status, data}` — `loadJson` would hand back `undefined`.
- `/api/ai-models` carries sibling keys `read_only` / `access_allowed` / `denial_reason`
  alongside `data`; `loadJson` discards them, silently losing plan gating.
- `widget-chat.html` and the auth pages use bare `fetch` with `credentials:"omit"` against a
  public origin; `loadJson` hardcodes `authenticatedFetch`, which injects a Bearer token and
  calls `logout()` on 401.
- `platform-admin-*` already has a better typed error taxonomy plus AbortController and
  Retry. Migrating it would be a regression.

**Tests that must change in the same commit if these are migrated:**
`test_bots_chatbot_limit_frontend.py:20` pins `authenticatedFetch("/api/billing/usage")`;
`test_workspace_frontend.py:31` pins `authenticatedFetch("/api/workspace")`;
`test_team_member_limit_frontend.py:138-139` pins both `getJson("/api/workspace")` and
`await authenticatedFetch(url)`; `test_platform_admin_frontend.py:572-573` and
`test_tenant_account_menu_frontend.py:164-165` pin `support.html`'s exact call strings.
Safe to migrate with **no** test changes: `integration.html` (done), `new_prompt.html`,
`crm.html`, `media_attachments.html`, `meta-templates.js`, `new_linkdocs.html`.

---

## 2026-08-27 — Integrated with team and pushed (`adf3c9c`)

Local `main` had 0 commits and was 5 behind. Committed the outstanding work as
`d6e7a5d` (API error-leak hardening) and `4f17bb6` (frontend rebuild/resilience),
rebased onto `origin/main`, resolved 3 conflicts, pushed.

**Conflicts resolved (all "keep both intents"):**

- `app/routes/knowledge_routes.py` — import block only; both sides added imports.
- `docs/DEVELOPMENT_ROADMAP.md` — add/add of dated sections; kept both, order was
  already chronological (08-26 team, then 08-27 mine).
- `docs/FEATURE_STATUS.md` — both rewrote the same two CRM rows. Kept my
  workspace description but took the team's **Migration 047**; my draft said 046,
  which is wrong — `046` is `harden_knowledge_pdf_candidate_grants`, and
  `047_widen_crm_lead_status_check.sql` is the real file.

**The one that had no conflict and still broke — read this before the next merge:**

`tests/test_tenant_account_menu_frontend.py` (new, team commit `f6c6406`) asserts every
entry in `AUTHENTICATED_SIDEBAR_PAGES` renders `<chatbot-sidebar>`. My commit turned
`reports.html` into a redirect to `crm.html?view=performance`, which renders no sidebar.
The test file and `reports.html` share **no lines and no file** — git auto-merged silently
and the break only showed up in the test run. Removed the stale entry with a comment;
`crm.html` stays in the list and the redirect is covered by
`test_crm_frontend_status.py::test_reports_page_redirects_to_performance_view_and_preserves_bot_context`.

**Verification method (reuse this):** raw pass/fail counts are meaningless here — the suite
has a standing failure baseline. Ran `origin/main` in a throwaway worktree (must copy `.env`
in, or collection dies on missing `OPENAI_API_KEY`), diffed the failing-file sets, and
required the delta to be empty. Result: 0 regressions, 2937 passed vs baseline 2936.

Note: `scratch/test_ai.py` is untracked local junk that executes network code at import and
aborts collection — run `pytest tests/`, not bare `pytest`.

---

## 2026-08-28 — Render deploy preflight; the blueprint could not have booted

Goal was to publish bots to channels (Telegram / WhatsApp / Wasender / widget).
The finding that reframed the work: **the channel backend is not the blocker.**
`docs/CHANNEL_PUBLISHING_REDESIGN.md` was right — Telegram `setWebhook`
auto-registration, WhatsApp Embedded Signup and the hosted widget are all built.
What blocks publishing is the absence of a stable public HTTPS origin, because
Telegram only delivers to https on 443/80/88/8443 and ngrok URLs rotate. **The
deploy IS the feature unblock.** Cloudflare is not on that path at all — see
`docs/CLOUDFLARE_EDGE_PLAN.md`.

### Deploy-blocking, found and fixed

- **`render.yaml` omitted `CORS_ORIGINS`.** It sets `FLASK_DEBUG="false"`, so
  `app/config.py` is in production mode and raises `RuntimeError` on the missing
  key. Proven by booting `create_app()` with the blueprint's env and no `.env`:
  exit 1. **The blueprint as committed crash-looped 100% of the time.**
- **`ENABLE_DEV_BILLING_ROUTES` must be ABSENT, not `false`.** `app/config.py`
  tests the raw string for truthiness, so `"false"` is truthy and raises. The
  checklist told you to set it to false — that instruction alone would have
  failed the deploy. Doc corrected; blueprint carries a warning comment.

### Security, found and fixed

- **CRITICAL — the CORS allowlist was inert.** `app/__init__.py` called
  `CORS(app, origins="*")` *before* `load_configurations()`, plus the real
  config-driven call after. The wildcard won and every response reflected the
  caller's `Origin`. Removed. Before: `ACAO: https://evil.example.com`. After:
  `ACAO: None`. Pinned by `tests/test_cors_allowlist.py`.
- **HIGH — no `ProxyFix`.** `app/rate_limit.py` keys unauthenticated limits on
  `remote_addr`, which behind Render's router is the proxy — so every visitor on
  the platform shared one login/OTP bucket. That is an unauthenticated DoS, not
  just a bypass. Added `ProxyFix` with `TRUSTED_PROXY_HOPS` (default 1).
  **Do not raise it to 2 until Render ingress is locked to Cloudflare** — a
  higher count trusts forgeable `X-Forwarded-For` entries.
- **HIGH — Meta webhook now fails closed.** An unset `APP_SECRET` used to raise
  `TypeError` (500); an empty one made `hmac.new(b"", ...)` forgeable by anyone.
- **MEDIUM — webhook path secrets were logged in plaintext** in
  `telegram_routes.py` / `wasender_routes.py`. Now a SHA-256 prefix. For Wasender
  that secret is the *only* auth factor.
- **`.dockerignore` only excluded `.env`**, while `.env.bak-20260803`, `.env.txt`
  and `Company acc & pswd.txt` sit in the build context. Patterns widened.

### Data loss, found and fixed

**Media uploads were written outside the disk.** Render attaches one disk, at
`/app/data`, but `media_attachment_routes.py` wrote to `/app/media_uploads` —
wiped on every deploy while the rows holding its `/media/` URL survived.
`app/storage_paths.py` now owns both paths; reads fall back to the legacy
in-image directory so existing attachments still resolve.

### The post-deploy script was broken in exactly our scenario

`scripts/reregister_telegram_webhooks.py` is the bulk recovery path
`render.yaml` names. Two bugs:

1. Line 97 compared `status == "ok"`, but `check_telegram_webhook_delivery`
   returns `DELIVERY_STATUS_OK`, which is `"connected"`. Dead branch — it
   re-pointed every bot correctly and then wrote them all back as `failed`,
   exiting 2. Every working channel would have shown "Needs a fix".
2. It passed no `registered_since`, so the stale error from the *dead ngrok URL*
   condemned the fresh registration. This bites hardest precisely when you run it.

**The existing test hid bug 1** — its mock returned the literal `"ok"`, a value
production never produces. It now asserts against the imported constant.

### Verification

Method from the 2026-08-27 entry, reused: clean worktree at HEAD, `.env` copied
in, full-suite diff. **Baseline 15 failed / 2937 passed / 37 errors → final
19 failed / 2952 passed / 37 errors. Zero regressions; +15 passing tests.**
All 4 extra failures belong to the *other* uncommitted stream: two are its own
new untracked test files, and the migration-number tests fail `assert 49 == 47`
because its new `data/048_*` / `049_*` bump the count past a pinned constant.

**Do not diff truncated output.** Piping a background `pytest` through
`tail -30` produced a convincing but fake regression set.

### Next

1. Merge the branch, then Blueprint deeplink → fill secrets → Apply. Note MCP
   **cannot** create this service: `create_web_service` supports neither Docker
   nor disks.
2. Set `PUBLIC_BASE_URL` to the Render host, plus `APP_SECRET` / `VERIFY_TOKEN` /
   `VERSION` (`VERSION` is not optional — it is interpolated into the outbound
   WhatsApp send URL with no default).
3. Run `scripts/reregister_telegram_webhooks.py --apply` from a Render shell.
4. WhatsApp and Wasender have **no bulk re-point path**. WhatsApp is a manual
   Meta dashboard edit; Wasender needs disconnect+reconnect per tenant and a
   re-paste by the tenant. Budget for that.

### Diff review outcome — and one false positive worth remembering

A reviewer **blocked** this change on a CRITICAL: that tracked `.env.txt` holds
live secrets, inferred from value *lengths* (`APP_SECRET` len=20, `VERIFY_TOKEN`
len=24). It does not. Every one of those values begins with `your_` —
`APP_SECRET` is literally `your_meta_app_secret`, which is 20 characters. The
only populated values in the file are `v22.0`, two `http://` URLs, `production`
and `false`. An earlier agent that actually read the content across all 361
commits reached the correct conclusion; this one judged by length alone.

`.env.txt` is a tracked placeholder template — an `.env.example` by another
name. It appears in `.gitignore`, which does nothing for an already-tracked
file, and that mismatch is what makes it look alarming. **Do not spend another
session re-litigating this.** (The `docs/DEPLOYMENT_CHECKLIST.md` "credentials
found in Git history" claim was likewise unsubstantiated and is now marked as
such.)

Two genuine MEDIUM findings from the same review were fixed:

- `int(os.getenv("TRUSTED_PROXY_HOPS", "1"))` crash-looped with a bare
  `ValueError` on a typo. Now raises an actionable `RuntimeError`, and rejects
  negatives — `ProxyFix` treats a negative count as truthy and indexes
  `values[-n]`, silently trusting a *less* distant hop instead of failing.
- `reregister_telegram_webhooks.py` returned 0 when every bot came back
  `unverified`, so a run that confirmed nothing read as success to anything
  checking only the exit code. It now returns 3.

Also confirmed by reading flask-cors 6.0.5 and Flask's `process_response`:
blueprint `after_request` hooks run **before** app-level ones, and flask-cors
skips a response that already carries `Access-Control-Allow-Origin`. So the
widget's own CORS headers survive — removing the global wildcard does not break
third-party embeds.

## 2026-08-28 - Deployed to Fly.io (Render abandoned)

**Live: https://wa-chatbot-my.fly.dev** (app `wa-chatbot-my`, region `sin`, org `personal`).

Render was abandoned, not failed: creating the service is dashboard-only there
(MCP `create_web_service` supports neither Docker runtime nor disks, the CLI's
only blueprint subcommand is `validate`, and no `RENDER_API_KEY` exists). Fly is
fully CLI-drivable, which is the whole reason for the switch.

Deploy sequence that worked:
1. `flyctl apps create wa-chatbot-my` - `whatsapp-chatbot` was **taken**. Fly app
   names are globally unique, and the name IS the hostname that gets written into
   PUBLIC_BASE_URL, every Telegram setWebhook call and every widget embed.
2. `flyctl volumes create chatbot_data --size 10 --region sin` - encrypted, daily
   snapshots w/ 5-day retention.
3. Secrets: piped `.env` through `sed` quote-stripping straight into
   `flyctl secrets import --stage`. Never written to a file. 34 secrets.
4. `flyctl deploy --ha=false` - **the flag is load-bearing.** Fly defaults to TWO
   machines; a second one runs a second in-process Wasender retry loop (duplicate
   customer sends) and cannot attach the single-attach volume.

Verified in production: `GET /` 200 · foreign `Origin` gets **no** ACAO header
while the real origin is echoed (the CORS allowlist fix proven live) · 1 machine ·
volume mounted `/app/data` uid 1000 encrypted · `Wasender retry worker started`
and polling Supabase 200 · health check passing.

### Things found on the way

- **`CORS_ORIGINS` is absent from `.env`.** `app/config.py:30` *raises* in
  production when it is empty, but falls back to localhost in dev - so the gap is
  invisible locally. A naive `fly secrets import < .env` crash-loops. It is now
  set as a Fly secret, but **`.env` is still missing it** for anyone else.
- **Build context was 84MB of local agent artifacts**: `.omx` 53MB,
  `graphify-out` 17MB, `.understand-anything` 11MB - none in `.dockerignore`, all
  baked into the image by `COPY . .`. Now ignored. **Needs a redeploy to take
  effect**; the live image still contains them.
- **~7MB of real tenant media ships inside image layers** (`media_uploads/`).
  Recorded as gap 7 in docs/PRIVACY_AND_DATA_PROTECTION.md. Cannot just be
  ignored - `serve_media()` falls back to it, so it must be copied to the volume
  first or every legacy media URL 404s.
- Health check failed once at boot then passed 8s later: import-time cost of
  PyMuPDF + the GenAI client, inside the 20s `grace_period`. Do not lower it.
- Rate limiter is `storage=memory://` - counters reset every deploy, and it stops
  being correct the moment a second machine exists.

### NOT done

- **Channel webhooks are still pointing at the dead ngrok tunnel.** Re-pointing
  needs `fly ssh console -C "python scripts/reregister_telegram_webhooks.py"`,
  which the permission classifier blocked as an unrequested remote-exec into a
  live production app. It needs explicit authorization. Until then the deploy is
  live but **no channel delivers to it**.
- Uncommitted, and mixed in the tree with another developer's automation/langflow
  stream - do not blanket-commit. Mine: `.dockerignore`, `app/views.py`,
  `app/routes/wasender_routes.py`, `app/services/wasender_retry_service.py`,
  `tests/test_no_pii_in_logs.py`, `fly.toml`, `docs/PRIVACY_AND_DATA_PROTECTION.md`.

### CORRECTION (same day): the Fly machine does NOT stay up

The verification above was real but momentary. **Fly's trial tier stops any
machine after 5 minutes** unless the account has a payment method:

    runner [warn] Trial machine stopping. To run for longer than 5m0s,
    add a credit card by visiting https://fly.io/trial.

The machine booted 12:20:22Z and was SIGTERM'd 12:25:22Z. It stays stopped
because `auto_start_machines = false` - correct for this app, but it means the
host is simply gone until someone starts it. `flyctl machines list` showed
`STATE stopped, CHECKS 0/1`; a passing check at deploy time is not evidence of a
stable deploy. Cost to fix: ~$7.20/mo (shared-cpu-1x 1GB ~$5.70 + 10GB vol $1.50).

**Telegram webhooks were deliberately NOT re-pointed.** A webhook receiver that
dies every 5 minutes is worse than a dead tunnel: Telegram backs off on repeated
delivery failure, and the rows would falsely read `connected`. Do not run
`--apply` until the host stays up.

Dry run (run locally with PUBLIC_BASE_URL overridden - the script only talks to
Supabase and the Telegram API, so it does NOT need to run inside the container):

    PUBLIC_BASE_URL=https://wa-chatbot-my.fly.dev python scripts/reregister_telegram_webhooks.py

**It reported 5 active channels that are all the same bot, `UltraAvaShopBot`.**
A Telegram bot holds exactly one webhook, so `--apply` would call setWebhook five
times with five different secrets; only the last is live, yet all five rows get
written `connected`. Rows 1-4 would hold secrets Telegram never sends, and every
inbound message would route to the owner of row 5 - cross-tenant misrouting if
those rows belong to different chatbots. **The script needs to de-duplicate by
`telegram_bot_id` before it is safe to apply.** Ownership unconfirmed: the
`telegram_channels` read was blocked by the permission classifier.

Channel endpoint probes (Meta verify-token rejection, unsigned POST fail-closed,
bogus Telegram/Wasender secrets, widget, media) all returned 000 against the
stopped machine and remain UNTESTED.

---

## Langflow automation: runtime verified, repo state still blocks "runs completed" (2026-09-03)

The Langflow runtime side is **fixed and verified live**. What still blocks a
reproducible "the system runs completed" is entirely repo and database state.

### Server: canonical origin and the port-drift trap

The server runs on **`http://127.0.0.1:7860`**. Three things must agree on that
exact origin: `LANGFLOW_SERVER_URL` in `.env`, and both `langflow-*` MCP server
registrations.

**Always launch with `C:\Users\Vincent\bin\start-langflow.cmd`**, which pins
`--host 127.0.0.1 --port 7860`.

A bare `langflow run` auto-bumps to the next free port when 7860 is briefly held
(typically by a still-shutting-down previous instance) and comes up on **7861**.
This presents as success — healthy console, working web UI — while everything
bound to the canonical origin quietly stops working: `.env` still points at 7860,
so automations degrade to `skipped_because: unreachable`, and because the layer
is fail-open by design *no user-facing error is raised*. Both `langflow-*` MCP
servers also fail to dial their `/api/v1/mcp/project/.../sse` endpoints. The
pinned launcher converts this silent drift into a visible startup failure.

### API key shadow realigned

A **User-scope Windows `LANGFLOW_API_KEY`** overrides `.env`, because
`load_dotenv()` does not override real environment variables. That copy had
drifted and produced `403 Invalid or missing API key` while `.env` looked
correct. Both now hold the same value. Rotating the key requires changing
**both** places, or the stale User-scope copy silently wins again.

### Verified live

Both flows consulted end-to-end against the local server:

| Flow | Case | Result |
|------|------|--------|
| CRM Stage Automation | `new` → `contacted` | approved |
| CRM Stage Automation | `lost` → `contacted` | blocked |
| CRM Stage Automation | `qualified` → `won` | approved |
| Knowledge Document Follow-up | reviewer summary | returned |

`lost → contacted` blocking is the load-bearing check — `lost` is terminal in
`CRM_STAGE_TRANSITIONS`, so the flow's allowlist agrees with Flask. Because the
layer is fail-open, this proves reachability and contract conformance only; a
pass here would look identical if durable persistence were missing.

### BLOCKER 1 — main does not boot from a clean clone

`app/__init__.py` line 40 imports `app.routes.automation_routes`, but that module
and its whole dependency closure were never committed. Reproduced against a clean
`git archive HEAD` export:

    ModuleNotFoundError: No module named 'app.routes.automation_routes'
      File "app/__init__.py", line 40, in <module>

Corroborated three ways: `git ls-files --error-unmatch` on each path, absence
from `git ls-tree -r HEAD`, and a codebase-memory graph indexed at HEAD
(`d539431`) that contains **zero** langflow/automation nodes while control nodes
such as `flow_blueprint` resolve normally.

These eight paths are one atomic unit and **must be committed together** —
committing any subset leaves `main` unbootable:

    app/routes/automation_routes.py
    app/services/automation_service.py
    app/services/langflow_decision.py
    app/services/langflow_adapter.py
    app/database/automation_event_repository.py
    app/database/db_errors.py
    data/049_automation_events.sql
    data/049_automation_events_rollback.sql

Import closure confirming the set is exactly right: `automation_routes` →
`automation_service` + `automation_event_repository`; `automation_service` →
`langflow_decision` (→ `langflow_adapter`) + `crm_lead_repository` (tracked);
`automation_event_repository` → `db_errors` + `app.database.db` (tracked).

Their test files (`tests/test_automation_*.py`, `tests/test_langflow_*.py`,
`tests/test_knowledge_follow_up_hook.py`) are also untracked and should go in the
same commit.

### Migration 049 — applied and verified

Migration `data/049_automation_events.sql` was applied on 2026-09-03 to the
active Supabase project `parjsxypengvubziwwjp` (`AI Chatbot's Project`). The
recorded migration is `20260903101746 / 049_automation_events`. Read-only
verification found `public.automation_events` present with zero rows, RLS
enabled, the declared columns/constraints/indexes, and service-role-only table
privileges. No application rows were inserted, updated, or deleted.

The operator endpoint `GET /api/automation/health` now reports `ok` while the
table is queryable and `degraded` if it becomes unavailable. User workflows
remain fail-open in the latter case. Rollback remains
`data/049_automation_events_rollback.sql` and requires an explicit, separately
reviewed decision.

### Config reproducibility — fixed

`.env` is gitignored, so a fresh clone had no Langflow configuration at all and
none of the seven settings were documented anywhere a new developer would look.

The tracked template is **`.env.txt`** (gitignore line 59 lists it, but that came
after it was committed, which does not untrack it). It is secret-free — every
secret is `""` and the rest are literal placeholders. All seven `LANGFLOW_*`
settings have now been added to it with placeholder values, documented defaults,
and the User-scope override warning. **No real key was written to any file.**

Leaving the whole block unset remains supported: the app boots and behaves as it
did before the automation existed.

## Cross-channel closed loop and credential replacement — reviewed and corrected

WhatsApp Cloud API and WASender now have the same closed customer-service loop
Telegram had: inbound webhook, conversation resolution, AI reply, outbound send,
delivery record. A tenant binds a number, and can later replace it — a new
Telegram bot token, or a new WhatsApp/WASender number — while the old connection
keeps working until the replacement verifies.

A four-agent review team (security, database, backend correctness, frontend and
deploy config) read the change before it shipped. What they found, and what was
done about it:

### Corrected before shipping

**The deploy config switched off two live features.** `fly.toml` set
`BILLING_SCHEDULER_ENABLED = "false"` and `WASENDER_RETRY_WORKER_ENABLED =
"false"`. Both default to true in code, and the gunicorn process is their only
runner — there is no `[processes]` block, no cron, no worker machine. That would
have silently stopped subscription transitions, HitPay order reconciliation and
the owner notifications added in `b01dd75`, and stopped every WASender retry.
Both removed; the block now explains why a handover pause belongs on one machine
(`fly deploy --env ...`) and never in the committed default.

**Migration number 056 was already taken.**
`056_pending_registration_verification_token.sql` shipped in `75b9f3b` and is
applied live. The new file was renumbered to **058**, and `docs/` and
`tests/test_channel_lifecycle_postgres.py` repointed. This repo already carries
three number collisions (029, 030, 045) and renumbered 031-034 once; a fourth
was not worth it. `055_telegram_active_provider_owner.sql` is genuinely free, is
already applied live, and is now tracked.
`data/telegram_connection_lifecycle.proposed.sql` was a superseded draft and is
deleted.

**The migration would have taken every existing tenant offline.**
`validate_channel` refuses to deliver for a channel with no `verified_at`, and
`get_bound_channel` refuses a conversation with no `source_channel_id`. Both
columns were created empty. On apply, every already-connected channel would have
started raising on inbound webhooks, the routes would answer 500, Meta and
Telegram would back off, and nothing in the product would have reported it.
Migration 058 now grandfathers rows that were connected before it: they were
trusted by the code that connected them, so they stay trusted, and only new
connections go through the new verification. Open conversations are bound to
their channel wherever that channel is unambiguous — without that, every
returning customer would silently have got a second, empty thread.

**Telegram let the caller choose where its own bot delivers.**
`POST /api/telegram/connect` accepted `webhook_base_url` from the request body,
pushed it to `setWebhook`, and then verified it against itself — so it always
passed. A caller could point a tenant's inbound messages, and the webhook
secret, at a host they control, and the dashboard would still read "connected".
The destination now comes from `PUBLIC_BASE_URL` only, matching what WASender
and WhatsApp already did.

**Reconnect stopped rotating the webhook secret.** That value is both the URL
path segment and Telegram's `secret_token`, and anyone who has held the bot
token can read it back out of `getWebhookInfo`. Reusing it left a tenant with no
way to rotate a leaked channel secret. Reconnect mints a fresh one again.

**A revoked token made a channel unreleasable.** `deleteWebhook` returning 401
was treated as a failed disconnect, so `is_active` stayed true and the row held
the active-provider index for that bot id forever — nobody could connect a
replacement. That is exactly what happens after BotFather `/revoke`. A 401 or
404 now counts as released; a dead token cannot be delivering anything.

**An unverified WhatsApp attempt reserved a number globally.** The row is
created pending and active before verification runs, and the unique index keyed
on `is_active` alone — so any tenant could hold another tenant's number for the
length of the Graph round-trips, or permanently if the attempt died. The index
now requires `connection_status = 'connected'`, matching the WASender predicate.

**A transient Meta 5xx was read as a permanent credential verdict.** A
two-second Graph outage marked a brand-new connection failed and told the tenant
to redo Embedded Signup. 5xx and 429 now raise the retryable error that already
maps to "unable to verify, previous connection unchanged".

**WASender retries had been disabled in code.** A first-attempt failure was
written `permanent_failed` with no `next_retry_at`, and the retry worker passed
`retry_count=MAX_RETRIES`, forcing the permanent branch on the first miss.
`MAX_RETRIES` and `RETRY_DELAY_SECONDS` were decorative. Restored.

**A channel replaced mid-turn ate the customer's message.** `get_bound_channel`
raising inside the delivery lock propagated past a held dedup claim: 500, Meta
redelivers, the claim drops it as a duplicate, and the message disappears with
no bot row and no error anywhere. The failed reply is now recorded so staff see
a broken thread they can resend.

Also: Graph pagination is bounded (each page costs up to 15s inside a handler
gunicorn kills at 120s), `DROP INDEX` is attempted alongside `DROP CONSTRAINT`
for the WhatsApp uniqueness whose live form is unknown, the `conversations`
CHECK is added `NOT VALID` to shorten the lock, submitted phone numbers are
normalised to the E.164 string that was actually validated, and a successful
disconnect clears the stale "connection failed" banner.

### Known gaps — deliberately not closed here

These are pre-existing and were not introduced by this change. Shipping was the
explicit call; they are recorded so the next session does not rediscover them.

1. **WhatsApp has no outbound retry.** `get_retryable_failed_wasender_messages`
   (`app/database/message_repository.py:165`) filters
   `source_channel == "wasender"`, and there is no Meta retry worker. A failed
   Graph send is written `failed` and nothing ever picks it up, so the customer
   gets silence. Fix: drop the channel filter and dispatch on
   `conversation["source_channel"]` — `get_bound_channel` already abstracts the
   lookup for all three providers.
2. **WASender can finish Connect half-done.** `verify_wasender_connection`
   (`app/services/provider_connection_verification.py`) short-circuits to
   `next_action: configure_webhook` when `session_id` or the personal access
   token is missing, the row stays `pending`, and `get_wasender_channel_by_secret`
   requires `connected` — so every inbound message is swallowed with a 200 that
   WASender never retries. The UI (`connectWasender`) lets the operator walk
   away from that state. Fix: make `next_action` a blocking UI state and return
   4xx rather than 202 when those fields are absent.
3. **Stuck `pending` rows are permanent.** `claim_telegram_channel_operation`
   has no timeout and no release path, and several exits leave the row pending
   while `is_active` stays true — holding the provider identity globally and, if
   `connection_slot_reserved` was set, a plan slot. Fix: bound the reservation
   by `connection_attempted_at > now() - interval '15 minutes'` in both the
   quota predicate and the claim.
4. **`is_conversation_escalated` fans out on the webhook hot path.** One inbound
   WhatsApp text now calls it around seven times, each a Supabase round trip,
   and bound conversations add up to three more queries per call — on eight
   threads total. Fix: resolve pause state once per turn and pass it down, as
   the code already does for `conversation`.

Two smaller ones: `resolve_conversation_escalation` returns the whole
`agent_actions` row rather than `SAFE_AGENT_ACTION_FIELDS` (not exposed today,
but a future route change would leak `payload` and `reason`), and migration 058
has no paired `_rollback.sql` — note that two of its statements are one-way once
the feature runs, so a rollback must happen before the first released number or
bound conversation exists.

### Applying it

`data/058_unified_channel_lifecycle.sql` must be applied at the same time as the
deploy; the code reads columns it creates. It is a single transaction over
`conversations`, so inbound writes block until it commits — apply it in a short
window. After it commits, run the commented `VALIDATE CONSTRAINT` at the end of
the file; `VALIDATE` takes only `SHARE UPDATE EXCLUSIVE`, so messages keep
flowing while it scans.

## One palette across the product

Every tenant-facing surface now uses the landing page tokens. The authenticated
product and the page that sells it were two different visual systems: a visitor
signed up on cool navy with a cyan accent and landed in neutral black with a
muted green-teal one.

The survey found **five** palettes, not two - the landing page, the auth pages
(already correct), the control room, a third blue-and-green set on
`training.html` and `media_attachments.html` that nobody had mentioned, and the
staff portal. 133 colour values across 34 files moved onto one set.

Canvas and body text barely shift in lightness; they shift in temperature. The
accent is the real change, `#3e9c89` to `#22D3EE`.

**The retiring teal became a real token.** It was already carrying the
connected/healthy signal in nine places while also serving as the brand accent,
which is why the ambiguity existed. It is now `--success`, set to `#34D399` -
the value `auth-volleo.css` already defined - which also lifts it from 5.96:1 to
10.31:1 contrast. `--danger` and `--warning` moved with it: muted earth tones
chosen to sit beside a muted accent read as faded, not calm, beside vivid cyan.

**The contrast audit found a live bug rather than a migration risk.**
`--text-tertiary` had been failing WCAG AA on both pages all along at 3.07:1
against a 4.5:1 requirement. The obvious port of the landing ramp would have
left it failing at 4.16:1. It is `#75849A` now - 5.21:1 on canvas, 4.86:1 on
panel. Every other pair improved and none regressed.

### Deliberate exceptions - do not "fix" these

- **`widget-chat.html`** stays light with its indigo accent. It renders inside
  tenant websites via iframe, often on white pages. Consistency with the Omnexa
  landing page is the wrong goal for a component whose job is to blend into
  someone else's design.
- **`assets/css/platform-admin.css`** keeps its own ground. A distinct colour is
  a cheap guard against acting on the wrong surface, the same reason a production
  console does not look like staging.
- **`landing.html`** is the target and was not touched.

### What was deliberately left alone

The **type scale is not unified**, and should not be. Landing runs a fluid rem
scale with headings to 4.3rem; the app runs fixed px with 13px body. A dashboard
is operated, not read - forcing the marketing scale in would be a regression.
Only the rules unify: heading tracking `-.03em`, heading line-height `1.08`,
labels uppercase at `.14em`.

**Two token vocabularies still exist** for the same values - `--control-*` in
`dashboard-control-room.css` and bare `--canvas` / `--accent` inline in
`bots.html`. They agree; only the names differ. Unifying the names is the obvious
next step and was left out of scope to keep this diff to values only.

No DOM, ids, class names or function names moved, which is why only two test
assertions failed - the pinned hexes in
`tests/test_dashboard_control_room_frontend.py` and
`tests/test_bots_chatbot_limit_frontend.py`. They exist so a re-skin has to be a
deliberate act; they were updated to the new values rather than loosened.

**Not verified visually.** The Chrome extension was not connected and the
chrome-devtools MCP failed to start, so every claim here comes from source
analysis and computed contrast ratios, not from looking at the rendered pages.

## CHIP Pay MCP server (2026-09-15)

Added `mcp/chip-pay/` — a standalone stdio MCP server for CHIP (chip-in.asia),
the Malaysian payment gateway. Registered with Claude Code at **local scope**
(this project only). **Not wired into the Flask app**; it is a development tool
for driving the payment API, not the billing integration.

- Tools are **generated from vendored OpenAPI specs** in `mcp/chip-pay/spec/`,
  so they cannot drift from CHIP's published contract. To add an operation,
  refresh the spec — do not hand-write a tool.
- 58 operations exist (33 CHIP Collect, 25 CHIP Send); 19 are exposed as tools
  to keep the per-session tool list small. `chip_request` reaches the other 39,
  with `chip_list_operations` / `chip_describe_operation` for discovery.
- **Money guard:** refund / capture / charge / release / mark_as_paid and both
  Send payouts are refused unless `CHIP_ALLOW_MONEY_MOVEMENT=true` in
  `mcp/chip-pay/.env`. Default false. Applies to `chip_request` too.
- **CHIP Send is a separate API** with its own base URL and credentials, plus
  per-request `epoch`/`checksum` HMAC-SHA512 headers. A Collect key will not
  work for it. Send tools stay hidden until both Send vars are set.
- `python mcp/chip-pay/selfcheck.py` — offline checks, no network, no creds.
  Deliberately not named `test_*.py`: no pytest `testpaths` is configured, so a
  bare `pytest` would otherwise sweep it into the app suite.

Verified live against CHIP with a read-only call (`chip_public_key` -> 200) and
over a real MCP stdio handshake (22 tools). `pytest --collect-only mcp/` collects
nothing, so the 4049-test baseline is untouched.

**Open:** the supplied API key was pasted in chat and should be rotated in the
CHIP portal. `CHIP_BRAND_ID` is still blank — set it to let the server fill
`brand_id` automatically (`chip_payment_methods` requires one).

## 2026-10-27 — Landing pricing cards made consistent (uncommitted)

`frontend/landing.html` only (this worktree = live chain, 0ba9272). The four plan
cards were four heights (489-1064px) with CTAs at four heights, Free's features
started 72px above the paid cards', Advanced sat 8px lower (extra `.rec` padding)
and "/ month equivalent" broke mid-phrase.

- `.plan` is now a CSS **subgrid** spanning 5 parent rows: name, price, term line,
  CTA, features. Every card must keep exactly those 5 children in that order, or
  rows stop lining up. CTA moved above the feature list.
- Equal padding on every card; `.rec` is marked by border + glow only.
- Columns are 4 / 2 / 1 (breakpoints 1100px, 600px), never 3+1.
- No copy changed, so `landing-localization.js` keys are unaffected.

Verified: measured card boxes identical at 1440px; screenshots 1440/1024/390 in
dark + light. `pytest tests/test_landing_pricing_frontend.py tests/test_legal_pages.py`
32 passed. Browser specs landing-pricing, landing-localization, app-preferences,
tenant-account-menu: 45/49 passed; the 4 `tenant-account-menu` "shared placement"
failures (bots.html) also fail with this change stashed, so they were already broken.

**Next:** commit on `feat/bot-scoped-inbox-bookings` and `fly deploy` from this
worktree when the owner approves. Not committed, not deployed.

## 2026-10-27 — DEPLOYED as Fly v86 = `121ffc1`

The entry above said "not committed, not deployed"; both are now done. v85 (Oct 26)
had deployed origin/main, which lacked this release line and rolled back WhatChimp,
self-delete, per-bot inbox/bookings, the translation fix, the favicons and GEO-v8.
`1e7e0f4` merged origin/main in, taking main's 6 GEO files byte-for-byte, so GEO-v8
(0ba9272) stays dropped and its owner should decide whether to re-apply it on the
keyword input. pytest 6,554 passed + the 5 known baseline failures; all 120 live
frontend files hash-match `121ffc1`. **Next deploy must contain `121ffc1`**, and
main still needs a PR from this branch or the next main deploy rolls it all back again.
2 platform-admin browser tests (lines 970, 2026) fail on origin/main itself (from 728e9c5).
