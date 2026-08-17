# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-08-11
- Primary product surfaces: bot list, selected-bot dashboard, bot configuration and operations pages
- Evidence reviewed: `frontend/bots.html`, `frontend/index.html`, `frontend/sidebar-component.js`, shared glass styles, and Stitch project `14712560405171617868` (Bots and Dashboard Home screens)
- Visual source of truth: Stitch. The current `bots.html` still contains legacy Outfit, gradient, and glass styles; it remains the navigation/behavior contract until that screen is migrated.

## Brand
- Personality: calm, precise, operational, trustworthy
- Trust signals: clear bot/workspace context, explicit statuses, readable timestamps, restrained semantic color
- Avoid: decorative glass gradients, neon glows, emoji controls, oversized cards, hidden primary actions, and ambiguous status-only color

## Product goals
- Goals: make the selected bot and its readiness immediately obvious; guide clients toward the next useful action; keep bot operations scannable
- Non-goals: change backend behavior, invent analytics, or replace established bot-scoped routes
- Success signals: clients can identify the selected bot, understand readiness, and reach configuration/testing/operations without guessing

## Personas and jobs
- Primary personas: company owners, admins, and team members operating customer-facing bots
- User jobs: verify bot readiness, inspect activity, configure knowledge and behavior, test replies, and monitor conversations
- Key contexts of use: desktop operations with responsive mobile access for quick checks

## Information architecture
- Primary navigation: My Bots, Dashboard, Build & Configuration, Operate & CRM, Team, Billing
- Core routes/screens: `bots.html`, `index.html`, configuration pages, inbox, reports
- Content hierarchy: selected-bot context, metrics, guided next steps, health, live workflow, analytics/history

## Design principles
- Context before controls: always show which bot the data belongs to.
- One clear next step: guidance describes outcomes in client language.
- Dense but calm: borders and surface shifts establish hierarchy without glow or heavy elevation.
- Preserve truth: display only metrics and statuses supplied by existing APIs.

## Visual language
- Color: canvas `#0E0F11`, panel `#16181B`, raised `#1E2125`, text `#F2F3F4`, secondary `#8A9096`, accent `#3E9C89`
- Typography: Space Grotesk for headings, Geist for UI/body, JetBrains Mono for metrics and timestamps
- Spacing/layout rhythm: 4px base with 8/12/16/20/24/32px steps; 32px desktop canvas padding
- Shape/radius/elevation: 8/10/12px radii; hairline borders; no decorative shadows
- Motion: 120/180/280ms functional transitions; reduced-motion support
- Imagery/iconography: consistent 18–20px outlined icons; no emoji used as interface icons

## Components
- Existing components to reuse: `chatbot-sidebar`, shared authentication/session helpers, bot health, workflow, analytics, and history renderers
- New/changed components: control-room metric strip, dashboard guide links, normalized status pills, quieter chart and table treatments
- Variants and states: loading, ready, needs setup, unavailable, active workflow, completed workflow, empty history
- Token/component ownership: dashboard-specific tokens live in `frontend/assets/css/dashboard-control-room.css`

## Accessibility
- Target standard: WCAG 2.1 AA fundamentals
- Keyboard/focus behavior: visible focus on links and chart bars; 40px minimum navigation targets
- Contrast/readability: high-contrast text with non-color labels for statuses
- Screen-reader semantics: descriptive section headings, labelled time status, accessible data-bar labels
- Reduced motion and sensory considerations: honor `prefers-reduced-motion`; no flashing or decorative animation

## Responsive behavior
- Supported breakpoints/devices: desktop, tablet, and mobile web
- Layout adaptations: metric and guide strips collapse from four columns to two and then one; health and content grids stack
- Touch/hover differences: persistent actions and full-row targets; no hover-only essential information

## Interaction states
- Loading: preserve existing checking/loading text
- Empty: retain explicit no-chat state
- Error: retain human-readable unavailable states and warnings
- Success: use labelled Ready/Completed states with restrained accent
- Disabled: use semantic text plus muted surfaces
- Offline/slow network: keep stale layout visible while individual regions report unavailability

## Content voice
- Tone: direct, calm, instructional
- Terminology: say “bot,” “knowledge,” “channel,” and “test” consistently
- Microcopy rules: explain the outcome of an action; avoid internal implementation terms unless needed for diagnosis

## Implementation constraints
- Framework/styling system: existing Flask-served HTML, vanilla JavaScript, and CSS
- Design-token constraints: extend existing pages without adding dependencies or changing shared backend contracts
- Performance constraints: no large decorative assets or animation libraries
- Compatibility constraints: preserve `bot_id`, `selectedBotId`, API endpoints, sidebar behavior, and authentication redirects
- Test/screenshot expectations: static contract test plus desktop/mobile browser screenshots against the Stitch reference

## Open questions
- [ ] Decide whether the Stitch control-room shell should later be rolled out to every selected-bot subpage.

