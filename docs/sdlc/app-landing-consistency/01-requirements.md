# Visual consistency: Dashboard and Bots against the landing page

**Agent:** Design Agent (designer, a11y-architect, vision, code-reviewer)
**Status:** GATE 1 - awaiting confirmation
**Date:** 2026-09-14

## What was asked

Make the Dashboard and bots.html consistent with the landing page: colour, text
style, and so on.

## Facts established from the code, not assumed

**There is no dashboard.html.** The Dashboard is `frontend/index.html`
(`<title>Dashboard | Omnexa</title>`, 1149 lines). The landing page is
`frontend/landing.html` (579 lines). `frontend/bots.html` is 1392 lines.

**Typography already matches.** All three load the same families from Google
Fonts - Space Grotesk and Geist, with JetBrains Mono additionally on the two app
pages. Only the requested weights differ:

| Page | Space Grotesk | Geist | JetBrains Mono |
|---|---|---|---|
| landing.html | 500, 700 | 400, 500 | - |
| index.html | 500, 600, 700 | 400, 500, 600 | 400, 500 |
| bots.html | 500, 600, 700 | 400, 500, 600 | 500, 600 |

So "text style" is not a font-family problem. Any inconsistency is in scale,
weight and colour, not in which typeface is loaded.

**Colour is the real gap, and it is a hue difference, not a shade difference.**

| Role | landing.html | index.html + bots.html |
|---|---|---|
| Canvas | `--void: #060A12` (blue-black) | `--canvas: #0e0f11` (neutral black) |
| Panel | `--panel: rgba(18,26,38,.62)` | `--panel: #16181b` |
| Accent | `--cyan: #22D3EE`, `--sky: #38BDF8` | `--accent: #3e9c89` |
| Body text | `--ice: #F1F5F9` | `--text-main: #f2f3f4` |
| Muted text | `--steel: #94A3B8` | `--text-dim: #8a9096` |

Canvas and text are near-identical in lightness; they differ only in temperature.
The accent is the actual break: vivid cyan against muted green-teal.

**The two app pages already agree with each other.** They carry the same values
under two naming conventions - `--control-canvas` etc. in
`assets/css/dashboard-control-room.css` for the Dashboard, and bare `--canvas`
etc. inline in bots.html. The inconsistency is app-versus-landing, not
Dashboard-versus-Bots.

**Saturation is a second-order problem.** The app semantics are deliberately
desaturated: `--danger: #a65648`, `--warning: #c4795a`. There is no `--success`
token; the green-teal accent is carrying that signal implicitly in 9 places.
Dropping a vivid `#22D3EE` beside a muted `#a65648` will make the semantic
colours read as faded rather than calm, so the palette has to be rebalanced as a
set - the accent cannot simply be swapped in isolation.

**The current colours are pinned by tests, by exact string.**

- `tests/test_dashboard_control_room_frontend.py:40-42` asserts
  `--control-canvas: #0e0f11`, `--control-panel: #16181b`, `--control-accent: #3e9c89`
- `tests/test_bots_chatbot_limit_frontend.py:238-240` asserts
  `--canvas: #0e0f11;`, `--panel: #16181b;`, `--primary: #3e9c89;`

These will fail the moment the palette moves. That is correct and expected - they
exist so a re-skin is a deliberate act rather than a silent drift - but it means
the change is visible in the test diff and must be approved, not slipped in.

## Constraints carried in from prior work

- Several Python suites assert frontend structure by raw HTML source text - exact
  element ids, function names, and in these two cases literal CSS declarations.
  **Changing token values is safe; changing DOM structure or ids is not.**
- A raw-source test forbids componentising the bots.html sidebar rail.
- Brand is Omnexa. Certain brand-shaped strings must never be renamed.
- Local font library at `C:\Users\Vincent\fonts` (43 commercial-safe families) is
  available if a typeface change is ever wanted - not needed here, since the
  families already match.

## Out of scope unless said otherwise

- The other 35 HTML pages. This covers Dashboard and Bots only.
- Any DOM restructuring, component extraction, or markup rewrite.
- Light mode. All three pages are dark-only today.
- Copy, content and information architecture.

## Open decisions for GATE 1

1. **Direction** - the request says match the landing page, which means the
   authenticated product adopts cool navy and cyan. Confirm, because the
   alternative (landing adopts the app palette) is a smaller change to a page
   that already converts.
2. **Depth** - tokens only, or tokens plus spacing, radius, elevation and the
   type scale.
3. **Accent semantics** - whether the green-teal must survive somewhere as a
   success or connected signal, or whether cyan takes over that role too.
