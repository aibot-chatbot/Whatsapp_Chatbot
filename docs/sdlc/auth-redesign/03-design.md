# 03 - Design: Auth pages redesign (Volleo) + hardened frontend Sentry

Phase P3/P4. Gate 1 (requirements) and Gate 2 (prototype, via Stitch) were
approved earlier in the programme. This document records what was actually
built, and - more importantly - the constraints that shaped it, because those
constraints are invisible from the markup alone.

Scope: `frontend/login.html`, `frontend/register.html`, `frontend/forgot.html`,
`frontend/verify-email.html`, `frontend/accept-invite.html`, plus the shared
stylesheet and Sentry client.

Those five are the complete auth surface. There is only one sign-in page:
platform-admin and superadmin authenticate through `login.html` and are routed
to `admin.html` / `superadmin.html` by `platform_role`
(`tests/browser/platform-login-routing.spec.js`).

---

## 1. The governing constraint: the JavaScript is frozen

`tests/test_workspace_frontend.py` extracts whole function bodies out of the raw
HTML source with regexes of this shape:

```python
re.search(r"function clearGoogleCompanyForm\(\) \{.*?\n        \}", source, flags=re.S)
```

The trailing `\n        \}` pins the closing brace to **exactly eight spaces** of
indentation. Six functions are pinned this way in both `login.html` and
`register.html`:

`onGoogleCredentialResponse`, `submitGoogleWithCompany`, `sendGoogleCredential`,
`clearGoogleCompanyForm`, `closeCompanyModal`, `loadGoogleConfiguration`.

`tests/test_cross_tenant_chatbot_access.py` additionally counts occurrences of
`establishAuthenticatedSession(result.user, result.token)` - 2 in `login.html`,
1 in `register.html`.

**Consequence:** this was a re-skin, not a rewrite. Every page's `<script>`
region is preserved byte-for-byte; only `<head>` and body markup changed. Each
migration script asserts `output.endswith(original_tail)` before it is allowed
to succeed.

## 2. Names that are load-bearing at runtime

Renaming any of these breaks the page silently - no test catches them all, and
nothing errors in the console.

| Name | Where | Why |
|---|---|---|
| `.loading` | submit buttons, login/register/forgot | `classList.add/remove` |
| `.open` | `#company-modal` | `classList.add/remove` |
| `.disabled` | `#resend-link` | `classList.add/remove` |
| `.otp-inputs` | verify-email | `querySelectorAll('.otp-inputs input')` |
| `.alert` / `.alert-error` / `.alert-success` | `#alert-box`, forgot | see below |

`forgot.html` does ``alertBox.className = `alert alert-${type}` `` - an
**assignment**, not `classList.add`. It wipes every other class on that element
the first time an alert fires, so `#alert-box` must never depend on an extra
styling hook. The page would look correct until the first error, then lose its
styling.

Inline `display:none` is likewise load-bearing on `#email-error`,
`#password-match-error`, `#password-strength-container`, `#general-message` and
`#step-2-form`: the scripts toggle `.style.display`, so the initial hidden state
has to be inline, not in the stylesheet.

## 3. Design system

One new file, `frontend/assets/css/auth-volleo.css`. Tokens are copied verbatim
from `frontend/landing.html` `:root` - there is deliberately no second palette.

| Token | Value | Role |
|---|---|---|
| `--void` | `#060A12` | page ground |
| `--sunken` | `#070C15` | inputs, brand panel |
| `--panel` | `rgba(18,26,38,.62)` | modal surface |
| `--cyan` | `#22D3EE` | single accent: CTAs, focus, links |
| `--ice` | `#F1F5F9` | headings, input text |
| `--steel` | `#94A3B8` | secondary copy |
| `--danger` / `--success` | `#F87171` / `#34D399` | alert states |

Type: `Space Grotesk` for headings and buttons, `Geist` for body - matching the
landing page. The previous pages loaded `Outfit`, which matched nothing.

Layout is an asymmetric 46/54 split (brand aside left, form right), collapsing
to a single column with a compact brand strip below 900px. `taste-skill` bans
centred hero layouts above `DESIGN_VARIANCE 4`; this ran at **VARIANCE 6 /
MOTION 4 / DENSITY 4** - deliberately calmer than the marketing page, because an
auth screen should feel steady rather than showy.

## 4. Branding

The pages shipped as "AI CHATBOT" with a clock icon and a blue accent, while the
marketing page ships as Volleo with neon cyan. A user clicking "Start free
trial" arrived at what looked like a different company. All five now use the
Volleo wordmark and the same fan-out brand glyph as `landing.html`.

The two auth emails were the same mismatch and are fixed alongside:
`send_otp_email` and `send_reset_email` in `app/services/email_service.py` now
carry Volleo branding (dark header, cyan wordmark, `#0E7490` code text for
readable contrast on white). The invite, handoff and support-escalation emails in
that file still say "AI CHATBOT" and need their own pass.

## 5. Accessibility (WCAG 2.2 AA)

Fixed in this pass:

- Every visible label now has `for`, and every input a matching `id` - including
  `login.html`'s email input, which previously had **no `id` at all**.
- `autocomplete="current-password"` on sign-in (was `new-password`, which defeats
  password managers); `username`, `email`, `given-name`, `family-name`,
  `organization`, `new-password`, `one-time-code` applied throughout.
- Error regions are `role="alert"` + `aria-live="assertive"` + `aria-atomic`, and
  fields point at them with `aria-describedby`.
- The Google modal gained `role="dialog"`, `aria-modal="true"`,
  `aria-labelledby`, `aria-describedby` and a focusable `#company-modal-box`.
- `#resend-link` was an `<a>` with no `href` - not focusable, not keyboard
  operable. It is now a real `<button>`, which keeps `classList` toggling working.
- Focus indicator is a 3px `--cyan` outline at 2px offset, clearing the 3:1 bar
  for SC 2.4.11 / 2.4.13. Targets are >=44px, checkboxes >=24px (SC 2.5.8).

One conflict could not be resolved in markup: `tests/test_workspace_frontend.py`
asserts the literal strings `<label>Password</label>` and
`<label>Confirm Password</label>` in the Google modal, so adding `for` to those
two labels would fail the suite. The inputs carry `aria-label` instead, which
gives them an accessible name matching the visible text.

### The OTP change worth understanding

`verify-email.html` used six `maxlength="1"` boxes with no paste handler, so a
user could not paste the code from their email - SC 3.3.8 (Accessible
Authentication) failure. The fix is markup-only:

```js
const otp = Array.from(inputs).map(i => i.value).join('');   // frozen script
```

With one `maxlength="6"` input that is `["123456"].join('')` -> `"123456"`,
identical. The auto-advance guard `index < inputs.length - 1` becomes `0 < 0`,
false, so it no-ops rather than erroring. Six boxes became one, and **no
JavaScript changed**.

### Still open - needs JS changes, deferred

The frozen-script rule blocks these; they need their own approved change:
modal focus trap, Escape-to-close, focus restore on close, `inert` on background
content, `aria-invalid` toggling on failed fields, focus move into step 2 of
`forgot.html`, and `aria-busy` on submit buttons.

## 6. Reduced motion

The primary user runs Windows with reduced motion enabled, so that is the path
actually seen. All decorative transitions collapse to ~0ms and the static result
is the intended design, not an animation that failed to start. The button
spinner is kept but slowed to 1.6s - it is a genuine progress indicator and
falls under the SC 2.2.2 "essential" exception; a frozen spinner during a real
network wait reads as a hung page.

## 7. Sentry

New: `frontend/assets/js/auth-sentry.js` + `GET /api/auth/sentry-config`.

Mirrors `app/observability.py` exactly - an allowlist is built from scratch per
event (`event_id`, `timestamp`, `platform`, `level`, `release`, `environment`),
exception values are always `"[redacted]"`, and stack frames keep only
`function`, `module`, `lineno`, `in_app`, `filename`.

Auth-specific hardening on top of the server policy:

- `maxBreadcrumbs: 0` **and** `beforeBreadcrumb` returning `null` unconditionally.
  On a login page, `dom` and `ui.input` breadcrumbs record what was typed.
- Session Replay never loaded; `tracesSampleRate` and `profilesSampleRate` 0.
- URL query strings and fragments stripped - password-reset and email-verification
  tokens travel there (`GET /api/auth/verify-email?token=...`).
- Regex redaction of emails, JWTs, bearer tokens and 4-8 digit codes, all with
  the `/g` flag. Without `/g` only the first match is replaced, so a string
  carrying two OTPs would redact one and transmit the other.
- **Integrations are allowlisted by name** (`GlobalHandlers`, `Dedupe`,
  `FunctionToString`). Note that disabling default integrations *without*
  re-adding `GlobalHandlers` produces a Sentry that initialises cleanly and then
  reports nothing at all, because `GlobalHandlers` is what hooks `window.onerror`.
- **Fail open above all else.** No DSN, blocked CDN, or thrown error may affect
  the form. `/api/auth/sentry-config` returns 503 when `SENTRY_DSN` is unset,
  which is the normal local case.

Verified by an executed self-check (11/11), including that `user`, `request`,
`breadcrumbs` and `extra` never survive `beforeSend`.

No SRI hash is pinned on the CDN script, deliberately: a wrong hash makes the
browser refuse the file, which under fail-open is indistinguishable from "Sentry
isn't reporting". Pin one only after verifying it against Sentry's published value.

## 8. accept-invite specifics

The invite page swaps four states by writing `style.display = 'block'` on
`#loadingState`, `#invalidState`, `#formSection` and `#successState`, so each
must render correctly as a block and the initial paint must show loading only.

Three further traps, all handled:

- `showMessage()` does `el.className = 'message-box ' + type` - the same
  class-wiping assignment as `#alert-box`, so `#inviteMessage` may not carry an
  extra styling hook.
- `#googleInviteSection` is hidden by setting the `hidden` **property**, so the
  stylesheet needs an explicit `.google-invite-section[hidden]{display:none}`
  guard; a bare display rule would defeat it and leave the Google option showing.
- `tests/test_workspace_frontend.py` asserts the literal
  `id="acceptForm" onsubmit="return handleSubmit(event)"`, attribute order
  included, so that form tag is copied verbatim.

The migration script verifies all 16 script-referenced ids and that pinned
string survive, and refuses to write if any is lost.

## 9. Known gap: no CSP

The auth pages have **no Content-Security-Policy**. The only CSP in the app
applies to uploaded media (`app/__init__.py:170-184`); the widget sets
`frame-ancestors` only. A login page with no CSP means nothing constrains where
credentials could be exfiltrated if XSS ever lands there.

Not fixed here - adding a CSP header affects all 39 frontend pages and needs its
own review. Any policy must still permit `accounts.google.com/gsi/client`, Google
Fonts + gstatic, the Supabase Storage image origin, and the Sentry CDN + ingest.
