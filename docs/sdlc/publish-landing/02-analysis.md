# 02 — Analysis: Publishing SaaS Marketing Landing Page

**Status:** complete — feeds P3 design
**Date:** 2026-09-11
**Inputs:** `01-requirements.md` (Gate 1 cleared), 2 research agents (GSAP/technique, AEO/GEO)

> Note: the root-level `docs/sdlc/01-requirements.md`, `02-analysis.md`, `03-design.md` belong to the **Help Desk** feature and are referenced by `app/services/help_article_service.py` and friends. This file is a separate project under `publish-landing/`.

---

## 1. Build-vs-adopt decisions

| Need | Decision | Reason |
|---|---|---|
| Animation engine | **Adopt GSAP 3.15.0 + ScrollTrigger** via cdnjs | Free for commercial use since Apr 2025; no credible alternative for scrub+pin |
| Scroll image-sequence | **Hand-roll (~60 lines)** | `gh api search/code` for `ScrollTrigger drawImage` returned 2,936 hits, **all hand-rolled**. No maintained library exists |
| Reduced-motion handling | **Adopt `gsap.matchMedia()`** | Built in; auto-reverts tweens and ScrollTriggers when the condition stops matching |
| Robot frames | **Higgsfield `nano_banana_pro`** from one locked reference | Per G1.3; 2 credits/image |
| Icons | **Keep Lucide** (already loaded by `landing.html:11`) | Zero new dependency (`ponytail` rung 2) |
| Theme toggle | **Hand-roll** (~15 lines, CSS custom properties + `localStorage`) | A library for this would be absurd |
| Pricing data | **Reuse the `assets/js/plan-catalog.js` pattern** | Already exists, used by `landing.html` only — safe to adapt |

## 2. Licensing verdict — GSAP

| | |
|---|---|
| Status | **Free for commercial use**, including a SaaS public marketing site |
| Scope | Core **and** ScrollTrigger **and** all former Club plugins (SplitText, MorphSVG, DrawSVG, Draggable, ScrollSmoother). **No plugins remain paid** |
| License name | *"Standard 'no charge' license"* — verbatim `license` field in `gsap@3.15.0` npm metadata |
| History | Webflow acquired GreenSock Oct 2024; library freed Apr 2025 |
| Prohibitions | Narrow: no reverse-engineering to build a **competing animation product**, no redistribution as a competing library. A marketing page is squarely inside the grant |
| CAVEAT | **Not OSI-approved** — proprietary-but-free, not MIT. Raise if OSI-only dependencies are a policy requirement (see R8) |

Sources: gsap.com/community/standard-license/, gsap.com/pricing/, webflow.com/updates/gsap-becomes-free

### Pinned CDN tags (SRI from cdnjs API; 3.15.0 is latest, next newest 3.14.2)

```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.15.0/gsap.min.js"
  integrity="sha512-oJ8QbaQThQoJZ7oEv+29jfPM6CcP+zUxh3PKJs1vyOhx0UraUrE7PQgeItu3dOuCJyrzWpoYMsVjkkPEBzbUqw=="
  crossorigin="anonymous" referrerpolicy="no-referrer"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.15.0/ScrollTrigger.min.js"
  integrity="sha512-OaIE7ud4P04EhnBuhEcm0wQSceIxbi2pV03oBLS/+F6ampfxsnxcIxOp7H2eF9G7N0kEht0VAzOLG+dTLSo17Q=="
  crossorigin="anonymous" referrerpolicy="no-referrer"></script>
<script>gsap.registerPlugin(ScrollTrigger);</script>
```

Order matters — ScrollTrigger must load after core.

## 3. Scroll-scrub technical design

**Pattern:** canvas + preloaded `Image[]` + `gsap.to(playhead, {frame, snap:{frame:1}, scrollTrigger:{scrub, pin, end}})`, drawing in `onUpdate`.

Non-obvious constraints from the research:

1. **Guard the draw.** `onUpdate` fires far more often than the integer frame changes. Redraw only when `Math.round(playhead.frame)` actually changes.
2. **Do NOT add a custom `requestAnimationFrame` throttle.** ScrollTrigger's `scrub` already batches into GSAP's rAF ticker; a second throttle double-buffers and makes it worse.
3. **Stride preloading.** Fetch every 8th frame at `fetchPriority:'high'` so the scrub is usable immediately, then backfill the rest at `'low'`. Draw the nearest-loaded frame when there's a gap.
4. **CLS avoidance.** Measure the *container*, not the canvas. Set `canvas.width = rect.width * dpr` with `dpr = Math.min(devicePixelRatio, 2)`, plus explicit CSS px height. Use a function-based `end` and `invalidateOnRefresh: true` so pin distance recomputes on resize.
5. **LCP protection.** Frame 0 only is eager (`fetchpriority="high"`). Every other frame defers until after `load`/idle. The sequence must never compete with the hero LCP element.

### Reduced motion

```js
const mm = gsap.matchMedia();
mm.add({
  motionOK: "(prefers-reduced-motion: no-preference)",
  reduce:   "(prefers-reduced-motion: reduce)"
}, (ctx) => {
  if (ctx.conditions.reduce) { drawFrame(0); return; }  // static, no pin, no sequence fetch
  preloadFrames();
  gsap.to(playhead, {
    frame: FRAMES - 1, snap: { frame: 1 }, ease: "none",
    scrollTrigger: { trigger: ".seq", start: "top top",
      end: () => "+=" + FRAMES * 30, scrub: 0.5, pin: true, invalidateOnRefresh: true },
    onUpdate: () => drawFrame(playhead.frame)
  });
});
```

Under `reduce` the preload is skipped entirely — which also saves the multi-MB payload. This satisfies the WCAG 2.2 AA "designed static alternative" requirement rather than merely disabling animation.

### Image format

- **AVIF: 95.36% global support** (caniuse). Chrome 85+, Firefox 93+, Safari 16.4+, Edge 121+. Gaps: iOS Safari <16, Opera Mini.
- Serve `<picture>` with AVIF + WebP fallback.
- **Payload estimate — NOT measured:** ~1600px frames approx. 60–120 KB AVIF each, so roughly **1.1–2.2 MB for 18 frames**. Must be benchmarked against the real generated frames in slice 2 before the perf budget is accepted.

## 4. GEO / AEO implementation plan

Ranked by effort vs real impact. **Corrections to `01-requirements.md` §7 are marked.**

| # | Item | Effort | Impact | Notes |
|---|---|---|---|---|
| 1 | `robots.txt` allow-list | trivial | **blocking floor** | Repo has none. `Google-Extended` and `Applebot-Extended` are *control tokens*, not crawlers — blocking them removes you from AI Overviews / Apple Intelligence without affecting search indexing |
| 2 | JSON-LD: `Organization`, **`SoftwareApplication`**, `BreadcrumbList` | low | moderate | **CORRECTION:** requirements said `Product`. Google scopes `Product` to physical/merchant listings. Use `SoftwareApplication` + `applicationCategory: "BusinessApplication"` + `offers` as **`AggregateOffer`** |
| 3 | Answer-shaped copy | medium | **highest** | Ahrefs (15k queries): only **12% overlap** between AI citations and Google's top 10. Extraction favours self-contained, numeric, definitional claims |
| 4 | `llms.txt` | trivial | **~zero** | **Not a standard.** Sept 2024 proposal; **Google stated July 2025 it does not support it and has no plans to.** Ship it because it is cheap, not because it works |
| 5 | `FAQPage` JSON-LD | low | low-moderate | **CORRECTION:** Google removed FAQ rich results **2026-05-07**. Keep the markup for AI parsing; expect no SERP snippet |
| 6 | Markdown mirrors | medium | skip for now | Real practice for *docs* sites (Mintlify, Stripe, Vercel). No evidence it helps a single marketing page. Revisit if a `/docs/` section appears |
| 7 | Paid citation tracking | ongoing cost | premature | Ahrefs Brand Radar, Semrush, Profound, Peec, Otterly all work by firing sampled prompts and scraping. No engine exposes a citation API; answers are non-deterministic |

**Free measurement signal:** grep Fly access logs for `GPTBot` / `ClaudeBot` / `PerplexityBot` / `OAI-SearchBot` user-agents. That is crawl activity, not citation — but it is real and costs nothing.

**Routing:** `robots.txt`, `llms.txt` and `sitemap.xml` need routes. `app/__init__.py:190` auto-serves `frontend/*` by path, so dropping the files there may suffice — **verify**, because that fallback is written for HTML and these must serve as `text/plain` / `application/xml` (see R9).

### Answer-shaped rewrite examples

| Before | After |
|---|---|
| "Our platform helps you manage messaging at scale." | "Sends broadcast messages to WhatsApp and Telegram audiences from one dashboard; Instagram, Facebook, X and LinkedIn are in development." |
| "We offer flexible pricing for teams of any size." | "Pricing has four tiers, billed per workspace with no per-seat fee." *(figures TBC per G1.2)* |
| "Trusted by businesses worldwide." | **Do not ship.** No customer base yet — replaced by the metrics band per requirements §6 |

## 5. Vertical slice ordering

Slice 1 proves the architecture end to end before anything else is built.

| Slice | Content | Proves |
|---|---|---|
| **1** | Page skeleton + design tokens (dark/light) + hero shell + GSAP CDN + **one hard-coded 3-frame scrub** | The whole risky path: CDN loads, scrub works, pin does not break layout, tokens flip, `.dockerignore` + `test_container_release.py` accept the new assets |
| 2 | Real 18-frame sequence + reduced-motion branch + LCP measurement | R3, R4, R6 |
| 3 | Hero robot + mouse interaction | The signature interaction |
| 4 | Features, How it works, Use cases | Bulk content |
| 5 | Integrations (live + roadmap) + metrics band + founder's note | Honesty-constrained sections |
| 6 | Pricing (TBC placeholders) + FAQ | Rewrites the pinned pricing tests |
| 7 | SEO + GEO layer, `robots.txt`, `llms.txt`, JSON-LD, sitemap | Items 1–5 above |
| 8 | Full test rewrite + a11y audit + Lighthouse | The ~100 assertions, WCAG 2.2 AA |

Slice 1 is deliberately ugly. Its only job is to fail fast on the container-release allowlist and the pin/CLS behaviour — the two things that would force a redesign if discovered late.

## 6. Risk register updates

| # | Change |
|---|---|
| R2 | **Confirmed scope.** Pinned assertions rewritten per-slice, not in one pass (slice 6 for pricing, slice 8 for the rest) |
| R3 | **Quantified.** ~1.1–2.2 MB AVIF for 18 frames — *estimate only, must be benchmarked* in slice 2 |
| R4 | Mitigated by locked reference; **verify on the first 3 frames before spending the remaining credits** |
| R6 | Binding: 38 of 40 credits. No budget for a second art direction |
| **R8 (new)** | GSAP is **not OSI-licensed**. Blocker only if policy requires OSI deps — raise before slice 1 |
| **R9 (new)** | `robots.txt` / `llms.txt` may be served with the wrong Content-Type by the `app/__init__.py:190` HTML fallback. Verify in slice 7 |

## 7. Open blocker

**Brand name is still required before P3.** It determines the logo, nav, hero H1, `<title>`, Open Graph tags, JSON-LD `Organization.name`, and the footer. Run RDAP `.com`/`.io`/`.ai` plus a trademark smell test on the user-supplied name before committing it to the design.
