# Analysis - app adopts the landing palette

**Decisions taken at GATE 1:** app adopts landing; depth is tokens plus type
scale; a real `--success` token is introduced so cyan can be brand-only.

## The type scale is NOT drift, and must not be flattened

Landing uses a fluid marketing scale; the app uses a compact px control scale.

| | landing.html | index.html / bots.html |
|---|---|---|
| Unit | `rem` with `clamp()` | fixed `px` |
| h1 | `clamp(2.4rem, 5.4vw, 4.3rem)` | 24px page title |
| Section head | `clamp(1.9rem, 3.6vw, 2.9rem)` | 17px |
| Body | `.9rem` (~14.4px) | 13px |
| Meta / label | `.75rem`, tracking `.14em` | 11-12px, tracking `.08em` |
| Heading tracking | `-.03em` | `-.02em` |
| Heading line-height | `1.08` | default |

A dashboard is a dense working surface and a landing page is a reading surface.
Forcing a 4.3rem hero heading into the Dashboard would be a regression, not
consistency. **So alignment here means unifying the RULES, not the sizes:**

- One heading typeface and one tracking rule (`-.03em`) across both.
- One heading line-height (`1.08`).
- One label treatment - uppercase, `.14em` tracking, Space Grotesk.
- The app keeps its 13px body and px scale. Density is a product requirement.

## Token mapping

Landing owns the vocabulary; the app gets the same values under the names it
already uses, so no DOM or class changes are needed.

| App token (Dashboard `--control-*` / Bots bare) | Today | Becomes | From |
|---|---|---|---|
| canvas | `#0e0f11` | `#060A12` | `--void` |
| panel | `#16181b` | `#0C1421` | derived from `--panel` over void |
| raised | `#1e2125` | `#152032` | one step up from panel |
| sunken | `#0a0b0d` | `#04070C` | one step below void |
| hairline | `#2b2f34` | `rgba(148,163,184,.14)` | `--line` |
| text-main | `#f2f3f4` | `#F1F5F9` | `--ice` |
| text-dim | `#8a9096` | `#94A3B8` | `--steel` |
| accent / primary | `#3e9c89` | `#22D3EE` | `--cyan` |
| primary-hover | - | `#38BDF8` | `--sky` |
| **success (new)** | - | `#3e9c89` | the retiring accent |

The outgoing green-teal is not deleted. It becomes `--success`, which is what it
was already doing implicitly in 9 places - so status and connected indicators
keep their colour and only the brand highlight changes.

## Saturation rebalance

`--danger: #a65648` and `--warning: #c4795a` are muted earth tones chosen to sit
beside a muted accent. Against `#22D3EE` they will read as faded rather than
calm. They move up in saturation to match the new accent energy while staying
distinguishable from it by hue:

| | Today | Becomes |
|---|---|---|
| danger | `#a65648` | `#F87171` |
| warning | `#c4795a` | `#FBBF24` |

Both are from the same Tailwind-family ramp as `--cyan`/`--sky`, which is where
the landing palette already comes from, so the set stays coherent.

## Files that change

1. `frontend/assets/css/dashboard-control-room.css` - `--control-*` block
2. `frontend/bots.html` - inline `:root` block
3. `frontend/index.html` - only if it carries literal colours outside tokens
4. `tests/test_dashboard_control_room_frontend.py:40-42` - pinned hexes
5. `tests/test_bots_chatbot_limit_frontend.py:238-240` - pinned hexes

No DOM, no ids, no class names, no function names. That is deliberate: the
structural source-grep suites stay green because nothing structural moves.

## Risks

| Risk | Handling |
|---|---|
| Contrast regressions on the new canvas | a11y pass at P5; every pair checked to WCAG AA |
| Green-teal still hardcoded somewhere as a literal | grep for `#3e9c89` outside the token block before edit |
| Two naming conventions drift again | out of scope now; noted as the obvious follow-up |
| Other 35 pages now inconsistent with these two | explicitly out of scope, recorded in HANDOFF |

## Slice order

1. Prototype both pages in the new palette - GATE 2.
2. Dashboard tokens + type rules, tests updated.
3. Bots tokens + type rules, tests updated.
4. a11y contrast pass and visual verification.
