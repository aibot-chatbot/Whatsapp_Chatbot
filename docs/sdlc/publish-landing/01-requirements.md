# 01 — Requirements: Publishing SaaS Marketing Landing Page

**Status:** awaiting GATE 1 confirmation
**Date:** 2026-09-11
**Methodology:** Agile (P1–P3 once, P4 in vertical slices), 3 gates
**Source:** 6-round requirements interview (`grilling`), plus 3 fact-finding agents

---

## 1. Product & positioning

| | Decision |
|---|---|
| Product | **Multi-channel publishing SaaS** — compose once, publish/broadcast to many messaging channels |
| Relationship to repo | A **repositioning** of the existing platform, not a description of what ships today |
| Existing brand | "AI CHATBOT" — *"Automate Customer Relationship Across WhatsApp & Telegram"* (`frontend/landing.html:1191,1212`) |
| Brand decision | **New brand name, publishing-first** — distinct name and logo; page will visually diverge from the logged-in app |
| Underlying capability | Real: `app/routes/broadcast_routes.py`, Telegram channel publishing, meta templates, `automation_routes.py` |

**Open decision — brand name.** RDAP-verified 2026-09-11 (Verisign for `.com`, Identity Digital for `.io`/`.ai`, control-tested both directions, corroborated by NS lookups):

| Name | .com | .io | .ai | Trademark smell test |
|---|---|---|---|---|
| **Salvix** | taken | free | free | Cleanest — only a non-software Italian entity; no software brand |
| **Siaro** | taken | free | free | Malay *siar* = "to broadcast"; only namesake is a deadpooled UK legal-tech startup |
| **Sebaro** | taken | free | free | Malay *sebar* = "to disseminate"; UK retail co. dissolved 2023 |

All 42 strings tested had a registered `.com` — zero exceptions. "Free" = absent from registry; does not rule out premium pricing at checkout. `.my` and MyIPO records could not be checked. Not legal advice.

## 2. Functional requirements — 11 sections (conversion set)

1. **Hero** — AI robot, full viewport, mouse-interactive
2. **Trusted-by logos** — *replaced* (see §6)
3. **Scroll-video story** — GSAP-scrubbed robot assembly sequence
4. **Features grid**
5. **How it works** — 3 steps
6. **Use cases**
7. **Integrations** — live + roadmap channels
8. **Pricing**
9. **Testimonials** — *replaced* (see §6)
10. **FAQ** — answer-shaped for AI citation
11. **Final CTA + footer**

**Primary CTA (every section points here):** Start free trial → self-serve signup.

## 3. Channels claimed

- **Live:** WhatsApp Cloud API, Telegram, Wasender
- **Clearly marked "Coming soon":** Instagram, Facebook, X, LinkedIn
- Overclaiming rejected — the integrations do not exist in the codebase.

## 4. Visual direction

| | Decision |
|---|---|
| Palette | **Framer-style neon cyan on dark** — deep charcoal, electric cyan/blue, glassmorphism, bloom |
| Theme mode | **Dark default + light toggle** (doubles token work; required for a11y) |
| Robot | **Chunky friendly droid** — rounded, toy-like, big expressive eyes, cyan accents |
| Scroll technique | **Image-sequence scrub** — ~30 Higgsfield stills on canvas, GSAP ScrollTrigger (Apple-style). Chosen over video scrubbing, which stutters on iOS Safari |
| Scroll narrative | **Robot assembles itself** — parts converge, each labelled with a capability |
| Fonts | From `C:\Users\Vincent\fonts` (43 commercial-safe, Windows-registered) |

## 5. Pricing — proposed ladder

Benchmarked against live pricing pages fetched 2026-09-11. Across 8 products, **6 of 8 meter on connected channels**, 1 on seats (Hootsuite), 1 on contacts (Respond.io).

| Tier | USD/mo | Limits | Anchor |
|---|---|---|---|
| Free | $0 | 2 channels, 1 bot, 50 AI replies, 20 scheduled posts, 1 seat | Buffer Free (3ch/10 posts), Metricool Free (20/mo) |
| Starter | $9 | 3 channels, 500 contacts, 1 seat, unlimited posts | Publer Pro $5/acct, Buffer Essentials $5 |
| Growth | $29 | 10 channels, 2,500 contacts, 3 seats | Postiz Standard $29, SocialBee Bootstrap $29 |
| Business | $79 | 30 channels, 10,000 contacts, 10 seats, $12/100 overage | Respond.io Starter $79 |

**WARNING — departure from live billing.** Current plans are MYR 39/89/169 (approx. USD 8/19/36). Tier 1 is consistent (+13%); **Growth is +53% and Business +119%**. The page would advertise prices the billing system does not charge. **Requires explicit sign-off on the numbers.**

## 6. Honesty constraints

- **No customers yet** → Trusted-by and Testimonials sections are **replaced** with a live product-metrics band (messages delivered, channels connected, uptime) and a founder's-note block. Fabricated testimonials will not be generated.
- **Screenshots:** real app captures via Playwright against `aibot-chatbot-my.fly.dev`, credentials supplied in `screenshots-credentials.txt` (already gitignored by `.gitignore:115` `*credentials*.txt`). **Do not use `.env.screenshots`** — `.gitignore:58` is the literal `.env` only.

## 7. Non-functional

| Area | Requirement |
|---|---|
| Performance | **Strict budget:** LCP < 2.5s, CLS < 0.1, initial JS < 150KB gzipped. Frame sequence lazy-loads after first paint, AVIF/WebP, degrades to a static hero on slow connections |
| Accessibility | **WCAG 2.2 AA + genuine reduced-motion path** — scroll-scrubbing swaps for designed static states, not merely disabled animation. Contrast verified against the neon palette |
| Market / language | **Global English**, no regional framing |
| SEO | Meta, Open Graph, sitemap, canonical, heading hierarchy, Core Web Vitals, alt text |
| GEO | **Full AEO foundations** — `llms.txt`, AI-aware `robots.txt`, JSON-LD (Organization, SoftwareApplication, FAQPage, Product), Markdown mirrors, answer-shaped copy |

## 8. Technical constraints (verified in codebase)

- **Stack: Flask template in this repo.** No build step — `package.json` holds only `@playwright/test`. Flask serves `frontend/` (`app/__init__.py:190-195`); vanilla JS + CDN.
- **GSAP/ScrollTrigger arrive via CDN** — no GSAP, three.js, Lottie or anime.js exists anywhere in `frontend/` today.
- **Target file: replace `frontend/landing.html` outright** (user's explicit choice over the lower-risk options).
- **Test rewrite is in scope — roughly 100 assertions:**
  - `tests/test_landing_pricing_frontend.py:242-291` — raw-source greps: `id="landing-pricing-grid"`, `src="assets/js/plan-catalog.js"`, six verbatim feature labels, a banned-string list, `requireLogin()`/`authenticatedFetch(` must be absent
  - `tests/browser/landing-pricing.spec.js:133-373` — live DOM: exactly 4 `[data-plan-code]`, `.price-card > h3/.price-val/.price-desc`, `#hero-primary-cta` href by auth state, viewport containment
  - `tests/browser/tenant-account-menu.spec.js:449-451` — zero `tenant-account-menu` elements on the page
  - `tests/test_system_guide_removal.py:38` — rglobs all `frontend/**` forbidding 8 guide-bot strings
- **Container release test:** `tests/test_container_release.py:45-50` asserts the `.dockerignore` allowlist exactly equals the git-tracked `frontend/**.{html,css,js}` set, and `:28` requires it sorted and unique. Any new asset file must be added there, in sorted position, and git-tracked.
- **`assets/js/plan-catalog.js` is used by `landing.html` only** — safe to change or replace.
- **Route:** `app/views.py:25` serves `/` -> `landing.html`; `app/__init__.py:190` auto-serves any `frontend/*.html`.

## 9. Hosting & deployment

- Served from the **current Fly app** — `aibot-chatbot-my.fly.dev`, region `sin`, 1GB VM (`fly.toml`).
- **SEO/GEO caveat:** authority accrues to a `.fly.dev` subdomain and AI citations will name Fly's domain. Revisit at handoff.

## 10. Out of scope

- Building the actual Instagram/Facebook/X/LinkedIn integrations
- Changing billing code or subscription entitlements to match the new pricing
- Rebranding the logged-in application
- Purchasing a domain or migrating hosting
- Rewriting `refs/pull/*` history on GitHub (not possible client-side)

## 11. Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Advertised USD pricing differs from billed MYR pricing | **HIGH** | Requires sign-off; or show "from $X" with a regional note |
| R2 | ~100 pinned assertions rewritten in one pass | **HIGH** | Rewrite tests slice-by-slice alongside each section |
| R3 | 30-frame sequence blows the LCP budget | MEDIUM | Lazy-load after first paint, AVIF, static fallback |
| R4 | Frame-to-frame inconsistency across AI-generated stills | MEDIUM | Lock robot design, single seed, one generation batch |
| R5 | `.fly.dev` domain caps SEO/GEO return | MEDIUM | Flag at handoff; custom domain later |
| R6 | 40 Higgsfield credits may not cover 30 frames | MEDIUM | Cost-check before batch; reduce frame count or top up |
| R7 | Old Meta credentials remain in `refs/pull/1-9/head` and on 5 personal branches | MEDIUM | **Rotate the Meta app** — the only real fix |

## 12. Security finding (resolved in-session, one action outstanding)

Live Meta credentials were committed in `.env.txt` (15 commits). Verified stale — every value differed from the live `.env`, and the committed `WHATSAPP_META_APP_ID` belongs to a **different Meta app**. Repo is private, 0 forks, 6 collaborators.

| Step | State |
|---|---|
| Sanitise `.env.txt` (5 values -> `""`, 56 keys intact) | done |
| Backup bundle `Desktop\wa-chatbot-backup-20260911-092147.bundle` (19MB) | done |
| History rewrite via `git-filter-repo` | done — 0 of 15 commits still carry a secret |
| Force-push `main` (`b101092` -> `e25f82a`) | done |
| Repair regression: unscoped regex blanked an `APP_SECRET` test fixture -> fixed in `3711e6d` | done — `5 passed` |
| **Rotate/delete the leaked Meta app** | **OUTSTANDING — user action** |

Blast radius audited: across all 382 commits only 3 files ever matched the redaction pattern — `.env.txt`, `docs/DEPLOYMENT_CHECKLIST.md` (harmless), `tests/test_meta_webhook_body_limit.py` (fixed).

Personal branches `vince`, `jackhan`, `meiyie`, `deeying`, `yeexuen` retain the old history by choice and will reintroduce the values on merge.

---

## GATE 1 — CLEARED 2026-09-11

Requirements confirmed by the user; proceed to P2 analysis and the P3 prototype.

### Decisions taken at the gate

| # | Decision | Effect |
|---|---|---|
| G1.1 | **Brand name: user-supplied** — none of Salvix/Siaro/Sebaro chosen | **BLOCKS the P3 prototype.** Name is required for logo, nav, hero H1, `<title>`, OG tags, JSON-LD `Organization`, footer. Run RDAP + trademark smell test on the supplied name before committing it |
| G1.2 | **Pricing: design now, numbers later** | Build the 4-tier structure with figures rendered as visibly-marked **TBC** placeholders. Nothing ships with an unapproved price. Resolves R1 for now, does not close it |
| G1.3 | **Frame sequence: fewer, better frames** | ~18 frames on `nano_banana_pro` generated from **one locked character reference**, not 18 independent prompts. Slower scrub compensates for the lower frame count |

### Credit budget (measured 2026-09-11 via `higgsfield generate cost`)

| Model | Credits/image |
|---|---|
| `nano_banana_2_lite` | 1 |
| `nano_banana_flash` | 1.5 |
| `nano_banana_pro` | **2** |
| `gpt_image_2` | 6.5 |

Plan: 1 reference (2) + 18 frames (36) = **38 of 40 credits**, 2 spare for one retry.
Image-to-image pricing must be re-verified empirically before the batch — a reference-conditioned generation may not cost the same as text-to-image.

### Risk updates

- **R4 (frame inconsistency)** — mitigated by the locked-reference approach, not eliminated. Verify consistency on the first 3 frames before spending the remaining budget.
- **R6 (credit budget)** — quantified and now binding: there is no budget for a second art direction. A rejected robot design means topping up.

---

## BRAND NAME — RESOLVED 2026-09-11: **Volleo**

### How it was decided

Four names were RDAP-checked (method control-tested: `google.com`→200, random string→404) and put through a public-source trademark smell test. **56 candidate strings were tested in total; every single `.com` was registered — zero exceptions.**

| Name | .com | .io | .ai | Verdict | Reason |
|---|---|---|---|---|---|
| **Volleo** | taken | **free** | **free** | **GREEN — CHOSEN** | Zero records on Justia and Trademarkia. Only exact user is `volleo.co.uk`, a UK sportswear shop (class 25, unrelated). Brand query is winnable |
| Beacona | taken | free | taken | AMBER | No exact mark, no active software user, but sits in a crowded BEACON family in class 9/42 (incl. Beacons AI in creator publishing) |
| Castia | taken | free | taken | AMBER-RED | Three live software companies, incl. `castia.ai` (circuly GmbH) doing **AI multi-channel outbound** — direct sector collision |
| Siaran | taken | free | free | **RED — rejected** | See below |
| Omnexa | taken | free | taken | AMBER — rejected | `omnexa.co.uk` actively sells AI customer-agent/automation software. Same word, same sector |

### Why Siaran was rejected (it was briefly chosen, then reversed on evidence)

1. **It is the ordinary word for "broadcast."** [Kamus Dewan](https://prpm.dbp.gov.my/cari1?keyword=siaran), Malaysia's official language authority: *"sesuatu yg disiarkan atau diterbitkan"*. Cambridge Indonesian–English: *siaran = broadcast*. The brand would literally be the word "Broadcast" in its home market.
2. **Descriptive → weak or unregistrable** in class 9/38/42 in MY/ID, which is exactly where protection is needed. The clean US register is false comfort — it is clean only because English speakers do not use the word.
3. **SEO unwinnable, confirmed.** Bare SERP returns 100% Indonesian broadcast/streaming content (vidio.com ×3, tvri.go.id ×2, goal.com, YouTube) with zero brand slots. Worse, **"siaran pers" is standard Indonesian for "press release"** and a permanent URL path on Indonesian ministry sites (Kemlu, Kemhan, Setneg, Kemendag).

### Outstanding on Volleo

- Register `volleo.io` (and `volleo.ai` defensively).
- **Not verified:** MyIPO (Malaysia) and DJKI (Indonesia) registers — login/bot-walled, and for a Malaysian company they matter more than USPTO. USPTO TSDR, WIPO, EUIPO and UKIPO were also unreachable; Justia and Trademarkia are mirrors, not primary sources.
- Content must beat the **"did you mean volley"** autocorrect reflex — a content problem, not a structural one. Publish early.
- Phonetically adjacent to **Volleto** (connected-commerce SaaS, NY/Israel). Different spelling, but worth a verbal-confusion gut-check.
- **This is a smell test, not legal advice.** A lawyer-run clearance search in MY/ID class 9/42 is the only authoritative answer before any filing or serious marketing spend.

## R4/R6 UPDATE — robot reference obtained free

Stitch generated a usable character reference during hero generation at **zero Higgsfield credits**: chunky rounded droid, matte charcoal panels, glowing cyan seams, large expressive cyan eyes, cyan light ribbons from the chest core, floating on the void-navy canvas.

- Stored at `scratchpad/stitch/robot-reference.png` (1024×1024 source).
- **Effect on R6:** budget improves from 38/40 to roughly 36/40 — the 2-credit reference generation is no longer needed.
- **Effect on R4:** consistency risk drops substantially, since all 18 frames can be conditioned on this single reference rather than re-prompted from text.
- Still to verify: image-to-image pricing on `nano_banana_pro`, and whether 1024×1024 is enough source resolution for ~1600px frames.
