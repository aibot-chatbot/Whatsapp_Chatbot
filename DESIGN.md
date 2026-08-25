# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-08-21
- Primary product surfaces: bot list, selected-bot dashboard, bot configuration and operations pages, channel publishing, and the conversations/lead pipeline
- Evidence reviewed: `frontend/bots.html`, `frontend/index.html`, `frontend/integration.html`, `frontend/conversations.html`, `frontend/sidebar-component.js`, `frontend/assets/css/dashboard-control-room.css`, `app/routes/conversation_routes.py`, `app/routes/crm_routes.py`, `app/routes/agent_routes.py`, `app/database/crm_lead_repository.py`, and a read-only inspection of the live `conversations`, `messages`, `crm_leads` and `agent_actions` tables
- Visual source of truth: the control-room system in `frontend/assets/css/dashboard-control-room.css`. Stitch remains the historical reference for the dashboard shell only.

## Brand
- Personality: calm, precise, operational, trustworthy
- Trust signals: clear bot/workspace context, explicit statuses, readable timestamps, restrained semantic color, and never showing a number the backend did not produce
- Avoid: decorative glass gradients, neon glows, emoji controls, oversized cards, hidden primary actions, and ambiguous status-only color

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

## Open questions
- [x] Should the control-room shell roll out to every selected-bot subpage? Yes. `integration.html` and now `conversations.html` join `index`, `behaviour`, `new_prompt` and `new_linkdocs`. `bots.html`, `crm.html`, `support.html`, `reports.html` and `profile.html` remain legacy and are the remaining migration debt.
- [ ] Should a conversation ever close automatically after inactivity, so `conversation_status` and `ended_at` become meaningful? / owner: product / impact: unlocks open-vs-closed reporting and a real capture rate
- [ ] Do `crm.html` and `support.html` get migrated to the new stage vocabulary in this pass, or pinned to a compatibility mapping until they are redesigned? / owner: product / impact: two screens show stale stage names until resolved
- [ ] Wasender conversations report `connected` with no validation anywhere in the stack. Should the pipeline visually distinguish a lead that arrived over an unverified channel? / owner: product / impact: trust in channel attribution
