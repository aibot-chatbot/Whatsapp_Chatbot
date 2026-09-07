# 03 - Design: Support page redesign + Help Desk escalation

Phase P3. **Gate 2 approved 2026-09-04.** Prototype:
https://claude.ai/code/artifact/7892824f-cdf1-4f5d-96b5-b68579660074

Produced with a clickable HTML preview (DESIGN-GATE step 2, fallback 3) rather
than Figma, by explicit choice: the control-room design system already exists as
CSS, so a preview built on the real token values is truer than a Figma
re-creation of them.

---

## 1. Approved screen list

One page, `frontend/support.html`, with five states. No new routes, no modals.

| # | Region | Purpose |
|---|---|---|
| 1 | Page header | Title, one-line orientation, and the quiet always-present "Talk to a human" pill |
| 2 | Search hero | Full-width search field plus 7 category chips |
| 3 | Results | Article list -> article reader with a helpfulness vote |
| 4 | Dead-end card | Appears only when self-service fails; offers the handoff |
| 5 | Escalation form | Trail preview, urgency, category, subject, description |
| 6 | Your requests | Ticket list + detail with tenant-visible replies |
| 7 | Footer note | Carries the two contract-mandated strings |

States: **normal**, **loading** (skeleton rows), **dead-end**, **empty**
(new user, no tickets), **error** (articles API unreachable, escalation still
works and becomes the primary action).

## 2. Navigation model

No tabs, no routing. The page is a single scroll column; regions 3-5 swap in
place by toggling `hidden`. The article reader replaces the list rather than
expanding inline, so the reading column keeps its measure.

The dead-end card appears **below** the article, never as a modal - it does not
interrupt, and "Keep looking" dismisses it and returns focus to search.

## 3. Design tokens

Inherited unchanged from `frontend/assets/css/dashboard-control-room.css`
`:root`. No new palette is introduced.

| Token | Value | Role here |
|---|---|---|
| `--control-canvas` | `#0e0f11` | page ground |
| `--control-panel` | `#16181b` | article rows, cards, history panels |
| `--control-raised` | `#1e2125` | row hover, ticket buttons |
| `--control-sunken` | `#0a0b0d` | inputs, vote bar, trail panel |
| `--control-text` | `#f2f3f4` | headings, article titles |
| `--control-text-secondary` | `#8a9096` | labels, eyebrows, meta |
| `--control-text-tertiary` | `#a1a6ab` | body copy |
| `--control-accent` | `#3e9c89` | primary action, `new` pill, reply rule |
| `--control-warning` | `#c4795a` | dead-end card, `reviewed` pill, redaction notice |
| `--control-danger` | `#a65648` | error card, `urgent` pill |
| `--control-border` | `rgba(255,255,255,.08)` | hairlines |

Type: `--font-heading` Space Grotesk (h1 30px / h2 21px / h3 17-18px),
`--font-body` for prose, `--font-mono` JetBrains Mono for eyebrows, category
labels, ticket refs and counts. `font-variant-numeric: tabular-nums` on every
ref and count.

Radii: 6px controls, 10px panels, 14px search field. Single-theme dark by
design - the app is a control room and has no light mode.

## 4. Component inventory

New, in `frontend/assets/css/support.css`:

`.search-field` - `.chip` - `.articles` / `.art` - `.reader` + `.vote` -
`.deadend` - `.esc` + `.trail` + `.urgency`/`.u-opt` - `.tick` + `.pill`
(new/reviewed/closed/urgent) - `.skel` - `.empty` - `.errbox` - `.human-link`

Reused as-is: `shared-glass.css`, `dashboard-control-room.css`,
`control-room-motion.css`, `chatbot-sidebar`, `shared-ui.js`, `auth.js`,
`kw-a11y.js`.

**Icons are inline SVG**, hand-authored paths. The CDN lucide route used by
`profile.html` is forbidden by the page contract.

## 5. API contract for slice 1

```
GET /api/help/articles
  auth: token_required (any authenticated tenant user)
  200 -> { "status": "success",
           "data": { "articles": [
             { "id": 1,
               "category": "integration",
               "title": "Connect a WhatsApp number",
               "body": "Open Integrations ...",
               "slug": "connect-a-whatsapp-number",
               "sort_order": 10 } ] } }
  500 -> { "status": "error", "message": "Unable to load help articles." }
```

Published articles only. No tenant filter - articles are global platform
content. Envelope matches `support_routes.py`.

## 6. The contract this page must keep

Every assertion in
`tests/test_tenant_account_menu_frontend.py::test_support_page_is_authenticated_static_and_uses_safe_account_rendering`
stays green. Specifically the redesign must keep:

- ids `support-request-form`, `support-history-list`, `support-history-detail`
- the literal strings `authenticatedFetch("/api/support/requests?limit=25&offset=0"`
  and `authenticatedFetch("/api/support/requests/" + String(requestId)`
- quick links shaped `<a class="quick-link" href="x.html" data-support-link>`
- the strings `Tenant-visible replies` and `internal notes are not exposed`
- and must contain none of: `.innerHTML`, `console.`, `company_id`, `user_id`,
  `mailto:`, `tel:`, `support@`, `http://`, `<script src="https://`,
  `XMLHttpRequest`, `platform-admin`

## 7. Assumptions carried into build

1. Dead-end card renders below the article, not as a modal.
2. "Keep looking" dismisses and refocuses search.
3. Escalation remains available - and becomes primary - when the articles API fails.
4. Article bodies are short prose paragraphs. Steps, images and code blocks are
   **not** supported in slice 1.
5. Space Grotesk is kept because it is the project's existing heading face.

## 8. Deferred, by design

Admin authoring screens (slice 5) are not designed yet. History pagination past
25 tickets is not designed. Both return to P3 before they are built.
