# 02 - Analysis: Support page redesign + Help Desk escalation

Phase P2. Gate 1 approved 2026-09-04. Inputs: `01-requirements.md`.

---

## 1. The finding that changes the design

`support.html` is not an ordinary page. It is a **hardened page under a
27-assertion contract** in
`tests/test_tenant_account_menu_frontend.py::test_support_page_is_authenticated_static_and_uses_safe_account_rendering`.
P1 recorded four pins; the real number is 27, and several of them directly
forbid the way the control-room system is normally wired up.

| Assertion | What it forbids | Consequence for this build |
|---|---|---|
| `"<script src=\"https://" not in page` | Any external script tag | **Cannot load lucide from unpkg**, which is exactly how `profile.html` gets its icons. Icons must be inline SVG. |
| `'authenticatedFetch("/api/support/requests?limit=25&offset=0"' in page` | - | The fetch calls must stay **literally inside support.html**. The JS cannot be fully extracted to `assets/js/support.js`. |
| `".innerHTML" not in page` | The substring, anywhere | All DOM built with `createElement` + `textContent`. No template strings injected as HTML. |
| `"console." not in page` | Any console call | No debug logging left in the page, ever. |
| `"company_id" not in page` and `"user_id" not in page` | Those identifiers | The FAQ feedback call **cannot send `company_id`** from the client. The server derives tenancy from the JWT. |
| `"mailto:" / "tel:" / "support@" not in page` | Direct contact details | The "talk to a human" path must stay in-app. No support email address on the page. |
| `"http://" not in page` | Insecure URLs | (`https://fonts.googleapis.com` is fine - different substring.) |
| `<a class="quick-link" href="x.html" data-support-link>` | Any other markup shape | Quick links keep that exact shape; hrefs must be `[a-z_]+\.html` and the file must exist. |
| `"Tenant-visible replies"`, `"internal notes are not exposed"` | - | Both strings must survive the redesign. |
| `"platform-admin" not in page` | The substring | No links or references to the staff console from the tenant page. |

**Decision: honour all 27. Do not rewrite the test.** These are not style
preferences - they encode real security properties (no XSS sink, no external
script supply chain, no PII identifiers in client code, no support-address
harvesting). A redesign that "frees" itself by editing the assertions would
quietly remove the page's hardening. The visual freedom granted is exercised
inside this contract, not against it.

## 2. Stack decisions, with reasons

| Decision | Choice | Why |
|---|---|---|
| Design system | Reuse `shared-glass.css` + `dashboard-control-room.css` + `control-room-motion.css`, plus a new `assets/css/support.css` | Same stack `profile.html` uses. New CSS files are unconstrained by the contract; only the HTML/JS is. |
| Icons | **Inline SVG**, hand-placed in markup | The CDN lucide route is banned. Inline SVG is also faster (no extra request) and cannot be blocked. |
| JS location | **Stays inline in `support.html`** | Two assertions read the fetch calls out of the page file. Extracting to `assets/js/support.js` breaks them. Accept the file being long. |
| FAQ search | **Fetch all published articles once, filter client-side** | Instant, no debounce, no per-keystroke API chatter. `ponytail:` ceiling - correct up to a few hundred articles; past that add a server-side `ilike`/full-text endpoint. Documented, not hidden. |
| Article writes | Plain service-role insert/update | The existing `create_tenant_support_request` RPC exists for a multi-table atomic write (request + event). Article CRUD is single-table; an RPC would be ceremony. |
| Migration number | **050** (and its rollback) | Verified free. 029-049 contain ten colliding numbers; 050 is the first clean slot. |
| Build-vs-adopt | **Build** | No help-centre library survives contract section 1 - every hosted widget (Intercom, Crisp, HelpScout) injects an external script, which assertion 1 forbids outright. There is nothing to adopt here. |

## 3. Domain model

```
help_articles
  id            bigint identity pk
  category      text      -> same 7 values as support categories
  title         text
  body          text      -> plain text, rendered via textContent
  slug          text      unique
  is_published  boolean   default false
  sort_order    int       default 0
  created_at    timestamptz
  updated_at    timestamptz

help_article_feedback
  id           bigint identity pk
  article_id   bigint -> help_articles(id) on delete cascade
  company_id   bigint -> companies(id) on delete cascade   (server-derived)
  was_helpful  boolean
  created_at   timestamptz
  unique (article_id, company_id)   -- one vote per tenant per article

tenant_support_requests           (existing - additive only)
  priority   -> now written: 'low' | 'normal' | 'urgent'
  source     -> now written: 'faq_dead_end' | 'direct'
  escalation_context  jsonb  -- NEW, bounded: searches[], viewed[], unhelpful[], from_page
```

`escalation_context` is a **separate bounded JSONB column**, not smuggled into
`redacted_description`: the description is user-authored prose that staff read,
and appending machine data to it would corrupt the one field the redaction rules
already govern.

## 4. Tenancy and authorization

| Endpoint | Who | Note |
|---|---|---|
| `GET /api/help/articles` | any authenticated tenant user | published only; no tenant filter - articles are global platform content |
| `POST /api/help/articles/{id}/feedback` | any authenticated tenant user | tenancy from the JWT, never from the body (contract section 1) |
| `POST /api/support/requests` | existing | gains `priority`, `source`, `escalation_context` |
| platform-admin help article CRUD | platform admin only | reuses the existing platform-admin auth decorator |

## 5. Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Redesign breaks the 27-assertion contract | **High** | Run that one test after every markup change, not just at the end. Fastest feedback loop in this build. |
| R2 | Migration 050 cannot be auto-applied | Medium | Hand over the SQL with a read-only verification probe, same method that verified 049. |
| R3 | Half-built staff-notification code is unproven | Medium | Red-green it in slice 4 before extending it. Its author reported a surviving mutation. |
| R4 | Client-side search stops scaling | Low | Documented ceiling with a `ponytail:` comment naming the upgrade path. |
| R5 | Article body rendered unsafely | **High** | `textContent` only, enforced by the existing `".innerHTML" not in page` assertion. The contract defends this for free. |
| R6 | Feature ships with an empty FAQ and looks broken | Medium | Seed 15-20 real articles in the migration, derived from the 7 topic cards already on the page. |

## 6. Slice order (unchanged from P1, now with the contract folded in)

1. **Migration 050 + `GET /api/help/articles` + FAQ search UI.** Proves the
   architecture end to end. Contract test must stay green.
2. Article feedback (helped / didn't help) + the dead-end detector.
3. Escalation: trail capture, urgency -> `priority`, `source`.
4. Verify the half-built staff notification, then add the user-facing
   "you have a reply" email.
5. Platform-admin article CRUD screens.

## 7. What P3 must decide

The design phase owns: page composition (what replaces the 7 static cards), the
search and article-reading interaction, where the "Talk to a human" action lives
so it is always reachable but never nagging, and how the auto-offer appears
without hijacking the user. Icons are inline SVG - the design must specify them
as shapes, not as lucide names.

---

Proceeding to **P3 - Design**, which ends at Gate 2. No implementation code
before that gate clears.
