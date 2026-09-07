# 01 - Requirements: Support page redesign + Help Desk escalation

Phase P1 of the agent-router SDLC. Status: **awaiting Gate 1 confirmation**.
Interview conducted 2026-09-04. No implementation code has been written.

---

## 1. Goal

Two things, in one page:

1. **Redesign `frontend/support.html`** - full freedom over icons, sections and
   components.
2. **Add a Help Desk escalation path**: when self-service cannot answer the
   user's question, hand the conversation to a real human on the platform
   support team, carrying enough context that the human does not have to start
   from zero.

The page today has no FAQ at all - seven hardcoded topic cards with no search,
no links and no feedback - so "when the FAQ can't help" describes a flow that
does not yet exist on either side.

## 2. Confirmed decisions

| # | Question | Decision |
|---|---|---|
| 1 | Who is the human? | **The platform team** (our staff). Tenant admins/owners escalate to us, not to their own agents. |
| 2 | Escalation trigger | **Button + auto-offer.** A "Talk to a human" action is always available, and the page proactively offers it when the FAQ dead-ends. |
| 3 | Reply delivery | **In-app thread + email alert.** The reply lands in Support History; an email tells the user it arrived. |
| 4 | Visual direction | **Control-room**, matching the redesigned `profile.html`. Reuse that system; do not invent a third visual language. |
| 5 | FAQ storage | **Database-backed with platform-admin CRUD.** Staff author and edit articles without a deploy. |
| 6 | Escalation context | **Auto-attach the trail** - searches run, articles opened, articles marked "didn't help", originating page. |
| 7 | Urgency | **User picks Low / Normal / Urgent** (fills the existing unused `priority` column). Guidance text only - **no contractual SLA, no countdown, no breach tracking.** |

## 3. What already exists (verified, not assumed)

- `frontend/support.html` - 741 lines, self-contained: submit form, support
  history list + detail, account card, 10 quick links, static topic cards.
- `app/routes/support_routes.py` - exactly three endpoints: submit, list, detail.
- `app/services/tenant_support_service.py` - validation, redaction, tenant-safe
  serialisation.
- `tenant_support_requests` table already carries **`priority` and `source`
  columns that nothing currently writes**. Statuses: `new`, `reviewed`,
  `converted`, `closed`.
- `frontend/platform-admin-support.html` - the staff-side "Support Workspace"
  already exists, so decision 1 needs no new console from scratch.
- **No FAQ table, article table, or search exists anywhere in the repo.**

### Half-finished work found in the working tree

A background agent was interrupted by a rate limit and left uncommitted,
**unverified** changes that overlap this feature:

| File | Change |
|---|---|
| `app/services/tenant_support_service.py` | +92 lines: `_platform_support_inbox()`, `_run_in_background()`, `_notify_platform_support()` |
| `app/services/email_service.py` | +94 lines |
| `tests/test_tenant_support_notification.py` | new, untracked, 11 KB |

It notifies **staff when a ticket arrives**, which is the complement of decision
3 (notify **the user when staff reply**). Its own last note was that a mutation
survived - one guard is untested. **Decision: keep it, but treat it as
unproven.** It must pass a real red-green check before anything is built on top
of it, and it is verified in P4 slice 4, not assumed working.

## 4. Functional requirements

### FR-1 Help centre (tenant-facing)
- Search across FAQ articles by title and body.
- Browse by category, matching the support request categories.
- Open an article; read it without leaving the page.
- Mark an article **"this helped"** or **"this didn't help"**.

### FR-2 Escalation trigger
- A persistent "Talk to a human" action, always reachable.
- An **auto-offer** when self-service dead-ends. Dead-end is defined as any of:
  a search returning zero results, or an article marked "didn't help".
- The auto-offer is an offer, never a forced redirect.

### FR-3 Context capture
- The escalation carries: search terms used, article IDs opened, article IDs
  marked unhelpful, and the originating page.
- Trail is bounded in size and redacted to the same standard as the description.

### FR-4 Ticket submission
- Existing fields (category, subject, redacted description) plus **urgency**
  (Low / Normal / Urgent) writing to `priority`, and `source` recording whether
  the ticket came from the FAQ dead-end or a direct button press.

### FR-5 Reply delivery
- Staff reply appears in the in-app Support History thread (already built).
- The user receives an email saying a reply is waiting. The email carries **no
  ticket content** - it is a nudge to open the app, matching the existing
  notification's deliberate design.

### FR-6 Platform-admin article CRUD
- Staff create, edit, publish/unpublish, reorder and delete FAQ articles.
- Article feedback counts ("helped" / "didn't help") visible to staff, so bad
  articles are findable.

## 5. Non-functional requirements

- **Accessibility**: keyboard-navigable search and article list, visible focus
  states, `aria-live` on async regions. The existing page already does this; do
  not regress it.
- **Security**: tenant isolation on every new endpoint; articles are readable by
  any authenticated tenant user, writable only by platform admins. No secrets,
  tokens or customer conversation content in the trail.
- **Performance**: article search must feel instant. Server-side search is
  acceptable if debounced; a full page reload per keystroke is not.
- **Coverage**: 80% floor per `rules/common/testing.md`.

## 6. Data changes

New migration (number to be assigned in P2 - see the migration-collision
constraint below):

- `help_articles` - id, category, title, body, slug, is_published, sort_order,
  created_at, updated_at.
- `help_article_feedback` - article_id, company_id, was_helpful, created_at.
- `tenant_support_requests` - add a bounded JSONB column for the escalation
  trail, or reuse the description. **Decided in P2**, not here.

## 7. Constraints

1. **Test pins.** Four assertions pin `support.html` markup by raw source text
   and must keep passing, or be updated deliberately:
   - `test_tenant_account_menu_frontend.py:242-244` - `id="support-request-form"`,
     `id="support-history-list"`, `id="support-history-detail"`
   - `test_tenant_account_menu_frontend.py:267` - the exact shape
     `<a class="quick-link" href="..." data-support-link>`
   - `test_platform_admin_frontend.py:548` - `id="support-request-form"`
   - Plus ~6 Playwright tests in `tests/browser/tenant-account-menu.spec.js`
     that open `/support.html`.
   This is far smaller than the ~100 assertions the profile redesign broke, but
   it is not zero. **Keep those four ids and that link shape.**
2. **No migration runner.** SQL under `data/` is applied by hand in the Supabase
   SQL editor. Any migration this project adds needs an explicit apply step.
3. **Migration numbering collides** in this repo (029-034 each name two files).
   P2 picks a safe number.
4. **Single process.** Notification threads rely on `--workers 1` +
   `min_machines_running = 1`. Do not introduce work that breaks under that.
5. **SMTP is configured** (`SMTP_SENDER_EMAIL`, `SMTP_APP_PASSWORD` present), so
   email is a real option, not a stub.
6. Python 3.11 - no PEP 701 nested same-type quotes in f-strings.

## 8. Out of scope

Written down explicitly, because this is the cheapest scope control there is:

- Real-time live chat, agent presence, typing indicators, business-hours logic.
- Contractual SLAs, countdown timers, breach detection or escalation-on-breach.
- Escalating the **bot's end-customers** to the tenant's own human agents. This
  build is dashboard-user to platform-staff only (decision 1).
- AI-suggested answers or auto-drafted replies.
- Attachments or screenshots on tickets.
- Multi-language FAQ content.
- Rebuilding the platform-admin Support Workspace beyond the article CRUD
  screens FR-6 needs.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Scope is large - article CRUD is effectively a small CMS | Slice it. Slice 1 ships the tenant-facing read path against seeded articles; admin CRUD is a later slice. |
| Migration cannot be auto-applied | Hand the exact SQL over at the end, with a verification probe, as done for 049. |
| Redesign breaks pinned tests | The four pins are listed above; the design must keep them. |
| Half-finished notification code is unproven | Red-green verify before building on it. |

## 10. Slice order (thin vertical slices)

1. `help_articles` migration + read API + FAQ search UI on the redesigned page.
2. Article feedback ("didn't help") + the auto-offer dead-end trigger.
3. Escalation with trail capture + urgency into `priority`/`source`.
4. Verify the half-built staff notification, then add the user-facing
   "you have a reply" email.
5. Platform-admin article CRUD screens.

Slice 1 proves the architecture end to end.

---

**GATE 1.** Confirm this is right, or tell me what to change, before P2 begins.
