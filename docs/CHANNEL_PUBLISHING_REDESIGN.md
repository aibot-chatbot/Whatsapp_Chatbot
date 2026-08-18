# Channel Publishing: Research and Redesign Plan

Planning document. **Nothing here is implemented yet.**

## Why this exists

A beginner client — a clinic, a shop, a tuition centre with no technical staff —
cannot get their bot published to a channel. `frontend/integration.html` offers
WhatsApp (Meta Cloud API), Telegram, Wasender API and a Web Widget, and asks the
owner to understand all four. The request is to make publishing something a
non-technical owner can understand and control, and to **replace** the UI rather
than patch it.

## Method and coverage

- Vendor claims come from **primary sources only** — Meta, Telegram, Wasender,
  Intercom, Crisp, Google, and the actual source of `chatwoot/chatwoot`. Every
  vendor claim below carries its URL.
- Codebase claims are first-hand reads with `file:line` references.
- **Coverage gap, stated honestly:** two of three research agents died mid-run
  (one hit a session limit, one stopped without reporting). The backend and
  frontend findings below are my own targeted reads, not an exhaustive sweep.
  Before implementation starts, `integration.html` (2,458 lines) should get a
  full line-by-line pass — there may be behaviour I have not seen.

---

## Finding 1 — The backend is not the problem

This was the surprise, and it changes the size of the work. The hard parts are
already built.

**Telegram is already fully automated** (`app/routes/telegram_routes.py`):

| What | Where | Status |
|---|---|---|
| Live token validation via `getMe` | `:34-47` | Built |
| `setWebhook` with `drop_pending_updates` | `:51-75` | Built |
| `deleteWebhook` on disconnect | `:87-97` | Built |

This is exactly the pattern Chatwoot uses in production
(`app/models/channel/telegram.rb` — `ensure_valid_bot_token` calling `getMe`,
then `setup_telegram_webhook`). We already do the right thing. The user never
needs to see a webhook URL, and does not.

**WhatsApp Embedded Signup is already implemented**
(`app/routes/whatsapp_routes.py`): `get_embedded_signup_config` (`:260-274`)
reads `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID`, `complete_embedded_signup`
(`:128-`) and `exchange_embedded_signup_code` (`:35-`) handle the callback, and
`integration.html:1778,1888` already listens for `WA_EMBEDDED_SIGNUP` and calls
`FB.login` with the `config_id`. There is a "Connect with Meta" button at
`integration.html:920`.

So the vendor-blessed one-popup path for WhatsApp exists in code. Whether it is
*enabled* depends on two environment variables and on Meta approval — see
"What the vendors allow" below.

**Web Widget is a complete hosted channel** (`app/routes/widget_routes.py`):

- `GET /chat/<public_key>` (`:154`) — a **hosted chat page**. No website, no
  snippet, no developer account, nothing to install.
- `GET /widget/<public_key>` (`:148`) — iframe embed.
- `GET /widget.js` (`:133`) — script loader.
- `web_widget_service.ensure_widget()` (`:89`) auto-creates it with a generated
  `public_key`. The client configures nothing.

## Finding 2 — The UI hides everything that works

The whole setup lives inside one modal (`integration.html:811-931`), and the
modal ends with this:

```html
<button class="btn btn-primary" onclick="closeSetup()">I've Completed Setup</button>
```
— `integration.html:928`

**The user tells the system it worked.** That is backwards, and it is the single
clearest symptom of the problem. We already call `getMe` and `setWebhook` and
know the answer with certainty; instead of showing the bot's real name and a
green state, we ask a non-technical owner to self-certify a thing they cannot
verify. Every later "why isn't my bot replying?" ticket starts here.

Other UI facts:

- The page is still on the **legacy glass design system** — `Outfit`,
  `shared-glass.css`, `--bg:#050b18`, `--primary:#3b82f6`
  (`integration.html:8-22`). Every other core tenant screen (dashboard, bot
  config, knowledge, Behaviour Studio) is on control-room. This is the last page
  that looks like a different product.
- Emoji in page chrome — `<h2>🌐 Web Widget</h2>` (`:655`). The control-room
  contract test forbids this (`tests/test_dashboard_control_room_frontend.py`).
- Only three top-level headings exist for the whole page: `Channel Status`
  (`:542`), `Web Widget` (`:655`), `Setup Connection` (`:814`). There is no
  visible journey — the journey is inside a modal.
- Layout is inline `style="..."` attributes throughout (e.g. `:828`, `:852`,
  `:881-891`), so there is no reusable component vocabulary to build on.

## Finding 3 — The instant channel exists and is buried

`integration.html:678-700` presents the Web Widget in this order:

1. **"1. Install on your website"** — a `<pre>` block of JavaScript, Copy button
2. "Or embed it inline as an iframe:" — a second `<pre>` block, Copy button
3. **"Or just share the direct link:"** — the hosted chat URL

The one option requiring **zero technical skill** is third, phrased as an
afterthought, after two blocks of code. A shop owner with no website is shown
JavaScript first and the thing that would actually work for them last.

This inversion is the highest-leverage fix in the whole document, and it costs
almost nothing: the capability is built and already serving.

## Finding 4 — Publishing by widget does not count as publishing

`app/services/dashboard_health_service.py:44-74` builds the channel list from
**telegram, wasender and whatsapp only**. There is no widget branch, and
`connected_count` (`:74`) sums those three.

Consequence: a client who publishes by widget link still sees the dashboard step
"Connect a channel to reach customers — **Not connected**" forever
(`index.html:105-110`, `:671-676`). The product tells them they have not
published when they have. This is a bug today, independent of any redesign.

## Finding 5 — Wasender is the only real automation gap

`app/services/wasender_service.py` has **no session or QR support** (grep for
`session|qr` returns nothing). The UI asks the owner to paste an API key
(`integration.html:852`), a phone number (`:867`), a session name (`:882`) and
an optional session ID (`:896`).

Per Wasender's own docs this is unnecessary work: `POST /api/whatsapp-sessions`
creates a session and returns the `api_key` and `webhook_secret` in one call,
and accepts `webhook_url` / `webhook_events` in the same request
(https://wasenderapi.com/api-docs/sessions/create-whatsapp-session). Then
`POST .../connect` followed by `GET .../qrcode` yields a QR string the owner
scans with their phone
(https://wasenderapi.com/api-docs/sessions/get-whatsapp-session-qr-code).

So the owner's entire job could be "scan this with your phone" — instead of
pasting four technical values they must first obtain elsewhere.

---

## What the vendors actually allow

Only what is sourced. Where something is impossible, that is stated.

### Telegram — cheapest win, one irreducible step

- `getMe` "requires no parameters… returns a User object" including `username`
  and `first_name` — a live token validator that also gives us display data.
  https://core.telegram.org/bots/api#getme
- `setWebhook` accepts a `secret_token` sent as the
  `X-Telegram-Bot-Api-Secret-Token` header on every request.
  https://core.telegram.org/bots/api
  **We do not currently use `secret_token`** (`telegram_routes.py:51-75`) —
  worth adding, it is a few lines.
- Deep links exist: `https://t.me/<bot_username>` opens a chat, and
  `?start=<payload>` passes up to 64 characters.
  https://core.telegram.org/bots/features
- **Not possible:** there is no OAuth, no one-tap authorization, and no
  BotFather deep link that hands a token to a third party. `/newbot` plus
  copy-paste is irreducible. Mitigate with a picture walkthrough, not code.
- Constraint: webhooks must be HTTPS on ports 443/80/88/8443 only.
  https://core.telegram.org/bots/webhooks

### WhatsApp Cloud API — the code is ours, the approval is not

- Embedded Signup returns the WABA ID, phone number ID and an exchangeable code
  to the spawning window.
  https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview/
- **It does not subscribe webhooks or register the phone number** — those are
  our server-side Graph calls afterwards.
  https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider
- The exchangeable code expires in about **30 seconds**.
  https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation
- `extras.setup` can **pre-fill** business name, email, website, address,
  timezone and phone, "reducing the amount of input and interaction required by
  your customers". We already hold most of this in the bot profile.
  https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/pre-filled-data
- **Gated on Meta, not on us:** Business Verification, then App Review for
  Advanced Access to `whatsapp_business_messaging` and
  `whatsapp_business_management` (separate justification and screen recording
  each), then Tech Provider status, then a Facebook Login for Business config to
  obtain `config_id`.
  https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers
- As a Tech Provider we **cannot** pay on the client's behalf; they must add a
  payment method in WhatsApp Manager themselves.
- **Deadline worth noting:** Embedded Signup v2 is deprecated on
  **15 October 2026**; the current version is v4.
  https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/versions
- **Coexistence flow** matters for Malaysian SMEs already running the WhatsApp
  Business *app* on their number: they tap Connect inside the app and keep using
  it. Costs: fixed 20 messages/second, one-time history sync inside a 24-hour
  window.
  https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/

### Web widget — stop leading with a code snippet

Every first-party vendor now leads with a copy-button or a no-code route, not
raw HTML:

- Intercom publishes an official **Google Tag Manager Community Template** where
  the user types only a Workspace ID and pastes no code at all.
  https://www.intercom.com/help/en/articles/2631808-install-intercom-with-google-tag-manager
- Crisp ships an official WordPress.org plugin whose setup is a "Link with
  Crisp" button. https://wordpress.org/plugins/crisp/
- Chatwoot surfaces the snippet on a Configuration tab with a Copy button, plus
  per-platform guides rather than expecting hand-edited HTML.
  https://www.chatwoot.com/hc/user-guide/en/categories/website-live-chat

### Cross-cutting: connection status must be a first-class object

Chatwoot models this explicitly — a `reauthorization_required` flag on the
inbox API, a `HealthService`, and a dedicated `Reauthorize.vue` screen. Tokens
rot, numbers fall into pending states, and Wasender sessions drop. A
beginner-friendly product is not one that hides configuration once; it is one
that says "Your WhatsApp disconnected, tap here to reconnect" before the
customer notices.

---

## Decisions taken during planning

Confirmed while this was being researched. Flagged here so they can be corrected
before any code is written:

1. **Public APIs and GitHub are research material, not a deliverable.** We copy
   what works; we are not shipping our own public API this round.
2. **The Web Widget is the instant hosted channel.** WhatsApp and Telegram stay
   the client's own account, with the system doing every technical step for them.
   This avoids the identity clash of a shared number and any per-number cost.
3. **The widget is free and does not consume a plan channel slot.** Entry plans
   allow only 1–2 channels (`plan-catalog.js:14,38,62,86`), so this keeps the
   paid slot for WhatsApp or Telegram and gives every client one working channel
   from day one.
4. **Publishing by widget marks the dashboard's "Connect a channel" step done.**

---

## Proposal

The shape follows from the findings: **most of this is surfacing what already
works, not building new capability.**

### A. Replace the page with a "Publish your bot" screen

Rebuild `frontend/integration.html` on the control-room system, reusing the
existing `kw-*` component vocabulary from `assets/css/dashboard-control-room.css`
(panels, buttons, pills, step marks, modal, inputs) — the same set bot config and
the Behaviour Studio use, so the screen reads as one product. Add
`assets/css/publish.css` for the `pub-*` components this screen needs,
namespaced under `.dashboard-page` exactly as `dash-*`, `bc-*` and `bh-*` are.

Structure, in reading order:

1. **"Your bot is live here"** — the channels already published, each with a
   real state (Connected / Needs attention / Disconnected) derived from a live
   check, not from self-certification.
2. **"Publish it somewhere new"** — ranked, not a grid of four equals. Since a
   plan allows 1–2 channels, the screen's job is to help the owner *choose*:
   - **Share a link — ready now.** The hosted `/chat/<key>` page, with a QR code
     and a Copy link button. No account, no install; works from an Instagram
     bio, a Google Business Profile, or a printed sticker. This becomes the
     default.
   - **Put it on your website.** Copy-button snippet, demoted to this position.
   - **Telegram — about 2 minutes.** Three illustrated steps for BotFather, then
     one field. On paste we call `getMe`, show the bot's real name and
     `@username`, register the webhook silently, and offer a `t.me/<username>`
     button plus a QR.
   - **WhatsApp.** Embedded Signup ("Connect with Meta") when configured, with
     the manual path behind it as a fallback.
3. **Everything else is progressive disclosure.** Widget appearance, lead
   capture, domain allow-listing and session limits (currently ~20 fields at
   `integration.html:706-788`) move behind a "Customise appearance" disclosure,
   collapsed by default.

### B. Delete "I've Completed Setup"

Replace it with a real verification result. We already know the truth from
`getMe` / `setWebhook` / the widget record — show it. This one change removes the
largest source of "I set it up but it doesn't work".

### C. Never show a technical word on the default path

`webhook`, `verify token`, `phone number ID`, `session ID`, `bearer token` and
`App ID` are all currently on screen. None should be on the default path. Keep
them in an "Advanced" disclosure for the minority who have a developer.

### D. Close the two real gaps

- **Widget counts as a channel** — add a widget branch to
  `dashboard_health_service.py:44-74` so an enabled widget reports as connected,
  and exclude it from `billing_guard.can_add_channel` (`:306-316`) per decision 3.
- **Wasender QR pairing** — implement session create → connect → QR poll so the
  owner scans instead of pasting four values. Needs a QR renderer; the repo has
  none today (grep for `qrcode` returns nothing), so this adds one dependency.
  Also investigate Wasender's pairing-code path, which removes the two-screen
  problem entirely.

### E. Small hardening while we are here

Add `secret_token` to `setWebhook` (`telegram_routes.py:51-75`) so Telegram
webhook calls are authenticated.

### Explicitly out of scope

- Building our own public API or GitHub SDK (decision 1).
- Any hosted or shared WhatsApp / Telegram number (decision 2).
- Meta Business Verification and App Review. These are **business tasks with
  multi-week lead times**, not engineering tasks. They should start in parallel
  now, because Embedded Signup cannot serve real clients until they land.

---

## Suggested phases

| Phase | Content | Depends on |
|---|---|---|
| 1 | Widget counts as a channel; share-link + QR promoted to default; delete "I've Completed Setup" | nothing |
| 2 | Full page replacement on control-room, ranked publish list, progressive disclosure | phase 1 |
| 3 | Telegram guided flow with live `getMe` identity, `t.me` QR, `secret_token` | phase 2 |
| 4 | Wasender QR pairing | phase 2 |
| 5 | WhatsApp Embedded Signup enabled with `extras.setup` pre-fill | Meta approval |

Phase 1 is small, independent, and fixes a live bug — worth shipping alone.

## Verification

1. `npx playwright test publish.spec.js` — new spec: the share link and QR render
   with no account; the widget reports as connected on the dashboard; a valid
   Telegram token shows the bot's real `@username` and never shows the word
   "webhook"; an invalid token shows a plain-language error; the Advanced
   disclosure stays collapsed by default.
2. `npx playwright test` — full suite. Current baseline is 147 passing plus 3
   known `testbot-persona` failures.
3. `python -m pytest tests/ --ignore=tests/browser` — compare the sorted `FAILED`
   set against a `git stash` baseline; the raw count is unreliable.
4. Screenshots at 1440 / 768 / 390 to confirm the page reads as one system with
   bot config and the Behaviour Studio, and no horizontal overflow at phone width.
5. Manual: publish a bot using **only** the share link, on a phone, without
   touching a keyboard beyond one tap. That is the real acceptance test for
   "a beginner can publish".

## Risks and open questions

- **Coverage.** `integration.html` was not read line by line (see Method). Do
  that before phase 2.
- **Wasender is unsanctioned WhatsApp automation.** It is the easiest channel to
  automate and carries account-ban exposure for the client. Present it as a
  deliberate risk tier, not as the easy default.
- **Embedded Signup may already be dark.** It is gated on
  `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID` and an app ID; if those are unset in
  production the "Connect with Meta" button is decorative today. Confirm before
  promising it in the UI.
- **Wasender docs are internally inconsistent** on the auth header format and
  the canonical base URL — verify empirically before phase 4.
- **v2 deprecation on 15 October 2026** — confirm which Embedded Signup version
  our implementation targets.
