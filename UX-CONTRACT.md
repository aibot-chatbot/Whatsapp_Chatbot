# Platform portal behavior

Scope: the approved independent Admin and Super Admin portals, 7 September 2026.
This contract does not redefine tenant workspace behavior.

## Super Admin overview charts

Three current-state charts reuse the existing overview requests. The Super Admin
controller owns lightweight HTML/CSS bars and a CSS ring; no chart library, canvas,
polling, new API, persistent state or database change is needed. Refresh replaces
the snapshot through the existing cancellation/authorization lifecycle.

| Chart | Encoding and source | Interaction and fallback |
| --- | --- | --- |
| Subscriptions by plan | Zero-based horizontal count bars from `subscriptions.by_plan`; latest subscription per company across all statuses | Visible plan names/counts; link to subscriptions; empty and unavailable states remain distinct |
| Subscription status | Composition ring and directly labeled counts from all five `subscriptions.by_status` categories | Native status links open the existing filtered subscriptions route; unknown counts suppress the ring rather than implying zero |
| Payment follow-up | Separate zero-based count bars for pending, failed and reconciliation-required subscription orders | Link to payments; visible caveat that queues overlap; no combined total or percentage share |

Three panels share the approved dark tokens: violet for plan comparisons, semantic
green/amber/red/neutral status colors, and neutral tracks. Labels carry meaning
without color or hover. Desktop uses two columns with the plan chart beside status;
mobile at 390px and 320px stacks panels, wraps long labels, preserves page scrolling
and keeps status links at least 44px high. Reduced-motion uses the same static charts;
forced-colors retains textual values. Print/screenshot output retains labels and data.

Chart values must be non-negative safe integers. Missing, malformed or overflowed
totals are unavailable; zero data has an explicit empty state. One API failure must
not erase the other API's chart. Existing authorization failures clear every chart.
QA covers exact counts/scales, zero/missing/error data, escaped names, status links,
refresh, permission revocation and narrow-screen overflow. Current snapshots cannot
be presented as revenue or historical growth.

## Identity and permission boundaries

The existing active user and platform-admin mapping are the source of truth. Tenant
roles (`owner`, `admin`, `member`) never grant platform access. Platform roles are
`admin` and `super_admin`; Admin module grants are `billing`, `support`, `customers`.
Every platform request checks current database permissions. Unknown roles fail closed.
Login returns one allowlisted destination: `bots.html`, `admin.html`, `superadmin.html`.
Passwords, tokens and account identity are never hardcoded in portal source.

Admin sees only assigned sections and their data. Direct restricted URLs show an
access-denied state. Super Admin controls module assignments and staff activation;
permission changes name the affected staff member, require a reason and confirmation,
and preserve the final active Super Admin. Staff access is separate from customer
conversations and bot content.

## Canonical UI map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Authentication and requests | Shared auth, API and shell scripts | Current server identity and database grants | Domain-specific pages; no client privilege inference | Mocked login, denial and stale-response tests |
| Select/Listbox | Native HTML select | Browser owns popup geometry and keyboard behavior | Labeled native selects in both themes | Browser form and assignment tests |
| Date | `Intl.DateTimeFormat` | Source timestamp, Asia/Kuala_Lumpur | Unavailable for unknown timestamps | Browser rendering and source review |
| Form | Native form plus portal domain renderer | Server field validation; `novalidate` with associated errors | Domain-specific fields; input preservation and duplicate-submit protection | Browser mutation/error tests |
| Dialog | Native HTML dialog plus portal renderer | Modal title, inert background, Escape and focus restoration | Detail and reason-confirmation dialogs | Browser confirmation and narrow-screen tests |
| Scrollbar | Each portal's application stylesheet | Global thumb/track and forced-colors rules | Tables own horizontal overflow within panels | Desktop/mobile overflow checks |
| Toast | One live status region per portal | Confirmed server outcome | Success announcements; durable errors stay inline | Browser mutation tests |
| CRUD | Platform services plus portal router | Server pagination, grants and record state | Admin requests and Super decisions; no optimistic privileged success | API and browser workflow tests |

Table selection and bulk financial operations are not part of this scope. Distinct
Admin work queues and Super Admin control pages are intentional domain variants;
transport, server rules, state labels and error semantics remain shared.

## Domain operations

Billing recheck must use the stored company/order identity and existing idempotent
provider reconciliation. Refreshing stored records alone must not be called a gateway
recheck. Refund, manual payment, plan change, account change, suspension and escalation
requests record a requester, company, reason and server status. Admin can read only its
own requests. Super Admin can decide pending requests once with a reason. An approval
decision is not payment or account fulfillment; the interface must state this clearly.

Support case public replies and internal notes have distinct controls and histories.
A public reply may notify the customer through the existing backend; private notes
never use that send path. Assignment, status and escalation use the current server case.
Operations preserve backend validation and lifecycle rules.

## Navigation, resilience and review

Search and paging operate on the documented server dataset. Local filtering may only
claim to search the loaded page. Staff customer names and sensitive search text remain
transient rather than written into shareable URLs; route and record identity may be in
the URL. Every nonempty search has an accessible clear action.

No fake metrics or demo state is a fallback for a failed request. Loading, empty,
no-results, validation, 401, 403, unavailable and stale-response states must be handled.
Session expiry clears sensitive UI and returns to login. Reason/confirmation forms
preserve input after recoverable errors. Keyboard, focus restoration, narrow viewports,
native popup behavior and reduced motion require browser verification.

Verification evidence belongs in focused tests and the implementation status report;
static ownership audits cannot substitute for those checks.

## Tenant client journey — approved 7 September 2026

This additional section covers the tenant workspace and selected-bot setup. It does
not change the independent platform portal permissions above. The approved journey
is My bots → Add knowledge → Review instructions → Test replies → Publish.

| Capability | Canonical owner and behavior | Verification |
| --- | --- | --- |
| Workspace and bot navigation | bots.html owns workspace navigation; sidebar-component.js owns selected-bot navigation. Account controls stay in the bottom footer; the navigation area scrolls. More tools preserves advanced destinations and existing role gates. | Desktop/footer bounds, mobile navigation and role tests |
| Guided progress | bot-setup-journey.js links four existing pages, preserves bot_id and setup=1, and marks only the current step. Completion comes from each page's actual saved state. | Route context and current-step tests |
| Create and upload | Native form validation, associated errors and busy state; confirmed ready primary knowledge unlocks continuation. Failed uploads retain recovery and document management controls. | Mocked create, PDF upload, recovery and readiness tests |
| Instructions and testing | draft_profile_name owns the draft selection; applying uses the existing match/apply checks. Guided success offers explicit continuation. Test replies remains a real user action and does not imply publishing. | Fresh-bot sentinel, draft reload, apply gating and chat tests |
| Publishing | Four equal choices; new website connections start disabled. Enabling/disabling preserves the key. Saved connection state and address configuration never claim live availability without a probe. | Channel choice, reconnect/key, partial failure and full journey tests |

Forms preserve input after recoverable failures and prevent duplicate submissions.
Dialogs support Escape, keyboard focus containment and return focus to their trigger.
Channel read errors preserve known state and do not hide independently loaded channels.
Existing tenant ownership, plan entitlements and authentication remain authoritative.

See [the client review](docs/CLIENT_JOURNEY_REVIEW.md) for evidence and public hosting
gaps. Synthetic browser tests demonstrate UI behavior, not live document processing,
provider message delivery, public uptime or completed production deployment.
