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
