# Design

## Guided client setup — approved 2026-09-07

The first-client path is My bots → Add knowledge → Review instructions → Test
replies → Publish. A newly created bot opens document setup directly. Preserve
`bot_id` and `setup=1` through the path; current-step markers describe navigation,
not completed backend work. The first PDF must be confirmed active before the
next action appears. Instructions use the bot's `draft_profile_name`; deployed
settings remain a separate runtime state. Applying instructions does not publish
a channel.

Keep the established Omnexa palette and typography. The signature is a quiet
four-step navigation strip, one dominant next action, and optional advanced tools.
`dashboard-control-room.css` remains the token owner; the shared strip lives in
`assets/css/bot-setup-journey.css` and `assets/js/bot-setup-journey.js`.

Workspace navigation on `bots.html` contains company-wide tasks. Selected-bot
navigation shows the bot name, direct setup destinations and secondary tools.
Both place account controls at the bottom; navigation owns its scroll area so
account controls remain reachable on shorter screens. Preserve role restrictions.

Publishing offers Website & share link, Telegram, WhatsApp Business and Wasender
with equal visual emphasis. Website and share link share a single connection.
New website records start off until explicitly enabled. Existing connections and
public keys are preserved. Show plan/provider restrictions beside the relevant
choice; distinguish saved connection state, configured address and verified
availability. A temporary hostname must never receive a Working label.

Acceptance and current evidence: [client journey review](docs/CLIENT_JOURNEY_REVIEW.md).

## Source of truth
- Status: Active
- Last refreshed: 2026-08-26
- Primary product surfaces: bot list, selected-bot dashboard, bot configuration and operations pages, channel publishing, the conversations/lead pipeline, the combined Insights & Actions workspace, team administration, and plans/billing
- Evidence reviewed: `frontend/bots.html`, `frontend/index.html`, `frontend/integration.html`, `frontend/conversations.html`, `frontend/sidebar-component.js`, `frontend/assets/css/dashboard-control-room.css`, `app/routes/conversation_routes.py`, `app/routes/crm_routes.py`, `app/routes/agent_routes.py`, `app/database/crm_lead_repository.py`, and a read-only inspection of the live `conversations`, `messages`, `crm_leads` and `agent_actions` tables. The 2026-08-26 pass added `frontend/team.html`, `frontend/pricing.html`, `app/routes/billing_routes.py`, `app/services/billing_service.py`, `app/services/workspace_service.py`, `app/database/billing_usage_repository.py`, `app/routes/invite_routes.py`, `app/routes/user_routes.py`, `tests/browser/landing-pricing.spec.js`, `tests/test_team_member_limit_frontend.py` and `tests/test_workspace_frontend.py`
- Visual source of truth: the control-room system in `frontend/assets/css/dashboard-control-room.css`. Stitch remains the historical reference for the dashboard shell only.

## Brand
- Personality: calm, precise, operational, trustworthy
- Trust signals: clear bot/workspace context, explicit statuses, readable timestamps, restrained semantic color, and never showing a number the backend did not produce
- Avoid: decorative glass gradients, neon glows, emoji controls, oversized cards, hidden primary actions, and ambiguous status-only color
- Commercial surfaces (scoped exception, added 2026-08-26): `pricing.html` is the one screen whose job is a purchase decision rather than an operation. It keeps every control-room token, type ramp and spacing step, and gains exactly three extra affordances: tier emphasis on the recommended plan, comparative weight between tiers, and entrance choreography over the usage meters. It gains no new colors, gradients, glow, or decorative imagery. Another screen inheriting these affordances is a violation, not a precedent.

## Product goals
- Goals: make the selected bot and its readiness immediately obvious; guide clients toward the next useful action; keep bot operations scannable; turn recorded conversations into worked sales leads
- Non-goals: invent analytics, display columns no code writes, or replace established bot-scoped routes
- Success signals: clients can identify the selected bot, understand readiness, reach configuration and testing without guessing, and see which conversations are worth money and who owns them

## Personas and jobs
- Primary personas: company owners, admins, and team members operating customer-facing bots
- User jobs: verify bot readiness, inspect activity, configure knowledge and behavior, test replies, work conversations as leads, and take over from the bot when a customer asks for a human
- Key contexts of use: desktop operations with responsive mobile access for quick checks

## Information architecture
- Primary navigation: My Bots, Dashboard, Build & Configuration, Operate & CRM, Team, Billing
- Core routes/screens: `bots.html`, `index.html`, configuration pages, `integration.html` (publishing), `conversations.html` (lead pipeline), `crm.html`, reports
- Content hierarchy: selected-bot context, metrics, guided next steps, health, live workflow, analytics/history
- Conversations is company-scoped, not bot-scoped. It is the one operational screen that spans every bot the tenant owns, because a lead is a lead regardless of which bot caught it.

## Design principles
- Context before controls: always show which bot the data belongs to.
- One clear next step: guidance describes outcomes in client language.
- Dense but calm: borders and surface shifts establish hierarchy without glow or heavy elevation.
- Preserve truth: display only metrics and statuses supplied by existing APIs. A column no code writes is not shown, and is recorded here as a gap instead.
- Confidence is context, not decoration: when the model reports how sure it was, show it next to the answer it produced.

## Visual language
- Color: canvas `#0E0F11`, panel `#16181B`, raised `#1E2125`, sunken `#0A0B0D`, text `#F2F3F4`, secondary `#8A9096`, tertiary `#A1A6AB`, accent `#3E9C89`, warning `#C4795A`, danger `#A65648`
- `--control-danger` is 3.42:1 on panel and is never used as text. It is permitted only as a dot, a border, or a fill behind lighter text.
- Typography: Space Grotesk for headings, Geist for UI/body, JetBrains Mono for metrics, timestamps, confidence values and identifiers
- Spacing/layout rhythm: 4px base with 8/12/16/20/24/32px steps; 32px desktop canvas padding
- Shape/radius/elevation: 8/10/12px radii; hairline borders; no decorative shadows
- Motion: 120/180/280ms functional transitions; reduced-motion support
- Imagery/iconography: consistent 18-20px outlined icons; no emoji used as interface icons

## Components
- Existing components to reuse: `chatbot-sidebar`, shared authentication/session helpers, and the `kw-*` control-room vocabulary (`kw-page`, `kw-header`, `kw-panel`, `kw-pill`, `kw-dot`, `kw-badge`, `kw-btn`, `kw-field`, `kw-input`, `kw-label`, `kw-banner`, `kw-modal`, `kw-empty`, `kw-advanced`, `kw-visually-hidden`, `kw-spinner`)
- New/changed components: a `conv-*` layer for the pipeline board, the conversation row, the transcript, and the lead panel. Namespaced under `.dashboard-page`, following `pub-*`, `dash-*`, `bc-*` and `bh-*`.
- Variants and states: pipeline stage, priority, assignment, follow-up due/overdue, AI intent, confidence band, escalated/awaiting-human, loading, empty, error
- Token/component ownership: shared tokens in `dashboard-control-room.css`; page classes in `frontend/assets/css/conversations.css`

## Accessibility
- Target standard: WCAG 2.1 AA fundamentals
- Keyboard/focus behavior: visible focus on every control; the conversation list is arrow-navigable; 40px minimum targets, 44px under `pointer: coarse`
- Contrast/readability: high-contrast text with a word on every state, never color alone. Pipeline stage, priority and confidence band all carry text labels.
- Screen-reader semantics: the transcript is a labelled log; new messages announce politely; the lead panel is a labelled form, not a div soup
- Reduced motion and sensory considerations: honor `prefers-reduced-motion`; no flashing or decorative animation

## Responsive behavior
- Supported breakpoints/devices: 320, 375, 768, 1024, 1440
- Layout adaptations: three panes (pipeline, transcript, lead) collapse to two at 1024 and to a single stacked column with an explicit back control at 768. The current fixed `height: 1000px` mobile hack is removed.
- Touch/hover differences: full-row targets; no hover-only information

## Interaction states
- Loading: skeleton rows in the list, not a bare "Loading..." string
- Empty: distinguish "no conversations yet" from "no conversations match these filters", and offer to clear filters in the second case
- Error: a `kw-banner` naming what failed and a retry, never a silent console log
- Success: inline confirmation on the control that caused it, cleared after a short delay
- Disabled: semantic text plus muted surface, with the reason available
- Offline/slow network: keep the last good data visible and mark the region stale rather than blanking it

## Content voice
- Tone: direct, calm, instructional
- Terminology: "bot", "knowledge", "channel", "test", "conversation", "lead", "stage", "owner". Say "share link" for the web widget channel, never "web".
- Microcopy rules: explain the outcome of an action; avoid internal implementation terms unless needed for diagnosis

## Implementation constraints
- Framework/styling system: Flask-served HTML, vanilla JavaScript, and CSS. No build step, no framework, no new runtime dependency.
- Design-token constraints: extend existing pages without adding dependencies or changing shared backend contracts beyond those listed below
- Performance constraints: no large decorative assets or animation libraries. The page is sized for hundreds of conversations per tenant, so filtering and search stay client-side; the list must not re-render wholesale on a poll tick.
- Compatibility constraints: preserve `bot_id`/`selectedBotId` handling, sidebar behavior, and authentication redirects. `?conversation_id=` deep links must keep working.
- Test/screenshot expectations: a static contract test plus Playwright coverage at 1440/768/390

### Pinned API contract for the conversations redesign

Frontend and backend are built against exactly this. Anything not listed is out of scope.

- `GET /api/conversations?company=1` - company-scoped list across every non-archived bot the caller owns. Each row adds `chatbot_id`, `bot_name`, and `message_count`. The existing `?chatbot_id=` form keeps working unchanged.
- `GET /api/conversations/<id>/messages?chatbot_id=` - unchanged.
- `GET /api/conversations/<id>/intents?chatbot_id=` - `agent_actions` rows for the conversation: `message_id`, `intent`, `confidence`, `action_type`, `reason`, `status`.
- `GET /api/company/members` - `id`, `name`, `email` for the caller's company, for the assignee picker. Backed by the existing `get_users_by_company`.
- `GET /api/crm/leads`, `POST /api/crm/leads/upsert` - unchanged shape, new status vocabulary.

### Known data gaps, recorded rather than rendered

- `conversations.ended_at`, `conversations.phone_requested` and `conversations.conversation_status` are never written by any code in `app/`. All 16 live rows read `open` with a null `ended_at`. Session information is therefore derived from `started_at`, `updated_at` and message count only. Making these real is backend work outside this redesign.
- `conversations.customer_username` is never populated, and the old page read `conversation.username`, a key `select("*")` never returns. Both the display fallback and its search filter were dead.
- `source_channel` is `web` on the majority of live rows. The old filter offered only WhatsApp/Wasender/Telegram and `normalizePlatform` defaulted unknown values to `whatsapp`, so share-link conversations were unfilterable and wore a WhatsApp badge.
- `setStatusFilter()` and the four `.status-tab` CSS rules had no markup anywhere. The escalation filter was styled and wired but never built.

### Lead status migration

`OPEN_CRM_LEAD_STATUSES` and `ALLOWED_CRM_LEAD_STATUSES` at `app/database/crm_lead_repository.py:13-14` are enforced on write and filtered on read at `:121`, `:256` and `:300`. Moving to `new / contacted / qualified / won / lost` changes behaviour for every reader; `frontend/support.html` still displays the old vocabulary and remains migration debt. `in_progress` maps to `contacted`; `closed` maps to `lost` when no outcome is known. Three live rows are affected, all `new`, so the data migration is trivial; the code blast radius is not.

### Pinned API contract for the team and pricing redesign

Verified 2026-08-26 by direct source audit of `app/`. Anything not listed is out of scope.

- `GET /api/billing/usage` - the authoritative usage source. `data.usage.{chatbots, team_members,
  knowledge_files, knowledge_storage_bytes, channels}` each carry `used` and `limit` (`limit: null`
  means unlimited); `team_members` also carries `pending_invitations`; `data.usage.ai_tokens` carries
  token counts only. `data.period.{start, end}` bound the window. Returns `data: null` at HTTP 200
  when the company has no resolvable subscription. Already consumed by `bots.html` and
  `integration.html`; new to both redesigned pages.
- `GET /api/billing/ai-credit/summary` - `included_balance_micro_myr`, `topup_balance_micro_myr`,
  `total_balance_micro_myr` (null when uninitialised), `period_start`, `period_end`, `currency`,
  `unit`. The only truthful source of remaining credit. Read-only; never initialises or charges.
- `GET /api/billing/plans` - 15 fields per plan. `price` is a **string**; parse before arithmetic.
- `GET /api/billing/subscription` - `status`, `current_period_start`, `current_period_end`,
  `trial_ends_at`, `trial_days_remaining`, `cancellation_effective_at`, `pending_plan`, `can_renew`,
  `renewal_required`. The nested `plan` key is **absent entirely** when the plan row cannot resolve.
- `GET /api/billing/subscription/downgrade-check/<code>` - used only at the downgrade confirm step.
  `blocking_items[].resource` is one of six values, and `team_members` and
  `team_members_including_pending` can both appear for one underlying cause; de-duplicate first.
- `GET /api/workspace` - `active_member_count`, `pending_invitation_count`, `plan_member_limit`,
  `remaining_seats`, `current_user_role`, `can_edit_company`, `can_manage_team`.
- `GET /api/users` - 9 fields per user. Readable by `member`; every mutation requires admin/owner.
- `GET /api/invites?status=pending` - 6 whitelisted fields. `POST /api/invites` returns `invite_link`
  and **no `data` key**; `POST /api/invites/resend` takes `invite_id` in the **body** and returns no
  fresh link; `DELETE /api/invites/<id>` takes the id in the **URL**.

### Truth constraints recorded rather than rendered

- **There is no annual billing.** `SUPPORTED_BILLING_INTERVALS` is monthly-only and the period math
  raises `ValueError` on any other value. Every seeded plan is monthly. No monthly/annual toggle.
- **`feature_flags` fails open in the backend, but the pricing table shows a cross.** The guard
  treats an absent key as GRANTED; `pricing.js` renders an absent key as `data-enabled="false"`,
  because `landing-pricing.spec.js` deletes a key and asserts exactly that. The two disagree, so
  the plan table can show a capability as unavailable that the API would in fact allow. Recorded
  as an open question below rather than resolved unilaterally.
- **Invites have only two written statuses**, `pending` and `accepted`. Expiry is derived by
  comparing `expires_at` to now, never read from `status`. Cancellation hard-deletes the row.
- **Two different pending-invite counts exist.** `/api/workspace` excludes invites whose `expires_at`
  is null or malformed; `/api/billing/usage` includes them. One screen picks one source, never both.
- **`subscription_status` from `/api/billing/reports/plan-usage` is always the literal `unknown`**
  because it reads a key that endpoint never sets. Status comes from `/api/billing/subscription`.
- **Web widget channels are not counted** toward `channel_limit`, so the channel meter is not a count
  of every reachable surface and is not labelled as one.
- **AI tokens are not money.** `usage.ai_tokens` is a token count; credit is MYR from the credit
  summary endpoint. The two are never merged into one figure.

### Components added in this pass

- `team-*` under `.dashboard-page` - roster row, seat rail, entitlement meter, invite row. Styles in
  `frontend/assets/css/team.css`, behaviour in `frontend/assets/js/team.js`.
- `pri-*` under `.dashboard-page` - usage meter, tier row, upgrade diff, feature disclosure. Styles in
  `frontend/assets/css/pricing.css`, behaviour in `frontend/assets/js/pricing.js`.
- `ia-*` under `.dashboard-page` - daily brief, action queue, lead pipeline/table, performance chart,
  report output, role-gated signals and lead detail dialog. Styles live in
  `frontend/assets/css/insights-actions.css`, behaviour in `frontend/assets/js/insights-actions.js`.
- Motion vocabulary extended in `control-room-motion.css` with meter fill and numeric count-up. Both
  are entrance-only, run once, animate `transform`/`opacity` only, and resolve instantly under
  reduced motion.

### Test contracts these pages must satisfy

- `tests/browser/landing-pricing.spec.js` pins `pricing.html` to four `.plan-card` elements, each with
  `.plan-name`, `.plan-price`, `.plan-desc` and twelve `[data-feature-key]` rows whose final five are
  the approved customer-facing flags in order. Collapsed tiers therefore stay in the DOM and are
  hidden visually, never omitted. The spec also asserts HTML-like plan text renders as text, so plan
  strings keep using `textContent`.
- `tests/test_team_member_limit_frontend.py` and `tests/test_workspace_frontend.py` assert against the
  raw source text of `team.html`, including exact indentation, inline `onclick=` attributes and
  function order. Extracting behaviour to `assets/js/team.js` is incompatible with them, so they are
  rewritten in this pass to assert behaviour rather than source text. Every entitlement rule they
  protect is preserved.

## Open questions
### Approved platform staff portals (7 September 2026)

The approved Admin and Super Admin prototypes establish two dedicated platform-staff
surfaces, separate from the tenant control-room theme. Admin uses the compact light
Linear application layout at `frontend/admin.html`; Super Admin uses the dark Stripe
Dashboard composition at `frontend/superadmin.html`. The shared tenant identity and
existing tenant routes retain their current purpose.

Runtime CSS remains canonical (token ownership model B): `admin-portal.css` and
`superadmin-portal.css` under `frontend/assets/css/` own the respective portal themes.
Their `:root` variables feed every route in that portal; no page-level token copies.
Admin canvas/sidebar/text/accent map to `--canvas: #fff`, `--sidebar: #f7f7f6`,
`--ink: #25252b`, `--accent: #5c5bc7`. Super Admin's approved dark canvas, navy sidebar
and violet action palette are defined in its stylesheet. Both use a system sans-serif
stack with tabular numerals and monospace identifiers, native labeled controls, thin
borders and restrained semantic status colors. Keep the approved density and sidebar
composition while substituting real records for illustrative prototype content.

`frontend/assets/js/auth.js` owns session transport; `platform-admin-api.js` owns the
shared platform API client; `platform-admin-shell.js` owns cancellation, stale response
handling and authorization lifecycle. The new portal renderers own their domain pages.
The production behavior map is in `UX-CONTRACT.md`. Unavailable data is not represented
as zero or replaced with fabricated totals, trends, success messages or sample users.

Super Admin overview charts reuse these same tokens: violet horizontal plan bars,
a status ring with directly labeled green/violet/amber/red/neutral categories, and
separate payment follow-up bars. Two-column desktop panels stack at narrow widths.
Counts remain readable without hover, status labels link to existing filtered lists,
and each source carries its own update timestamp. Payment queues can overlap and
must never be combined into a percentage or total. These are current snapshots,
not revenue or historical trend reports.

- [x] Should the control-room shell roll out to every selected-bot subpage? Yes. `integration.html`, `conversations.html`, and the combined `crm.html` Insights & Actions workspace join `index`, `behaviour`, `new_prompt` and `new_linkdocs`. `reports.html` is now a compatibility redirect; `support.html` and `profile.html` remain migration debt.
- [ ] Should a conversation ever close automatically after inactivity, so `conversation_status` and `ended_at` become meaningful? / owner: product / impact: unlocks open-vs-closed reporting and a real capture rate
- [x] `crm.html` now uses the canonical five-stage vocabulary in the combined Insights & Actions workspace. `support.html` remains compatibility/migration debt.
- [x] Should `team.html` and `pricing.html` join the control-room shell? Yes, resolved
      2026-08-26. `bots.html`, `support.html` and `profile.html`
      remain the migration debt.
- [ ] `/api/billing/reports/plan-usage` reports `subscription_status` as a hardcoded literal.
      Fix the service or drop the field? / owner: backend / impact: the endpoint ships a value
      no code writes, which the Preserve-truth principle forbids rendering
- [ ] Should the seat rail read `/api/workspace` or `/api/billing/usage`, given their
      pending-invite counts can disagree? / owner: product / impact: team and pricing can
      otherwise show different seat totals for the same tenant
- [ ] `feature_flags` disagrees between enforcement and display: the backend guard treats an
      absent key as granted, the pricing table shows it as a cross. Which is correct?
      / owner: product / impact: a plan may advertise less than it actually delivers
- [ ] Wasender conversations report `connected` with no validation anywhere in the stack. Should the pipeline visually distinguish a lead that arrived over an unverified channel? / owner: product / impact: trust in channel attribution
