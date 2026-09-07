# Cloudflare Edge Plan

> Deployment update, 2026-09-07: start with
> [Public Deployment Plan](PUBLIC_DEPLOYMENT_PLAN.md) for the current Fly.io
> target, release gates and verification sequence. This file contains historical
> Render instructions and unverified account/R2 assumptions; do not execute its
> older runbook without reconciling them against that plan and live state.

Companion to `render.yaml` and `docs/DEPLOYMENT_CHECKLIST.md`. Written
2026-08-28 against the live Cloudflare account
`1a382cd701e57fc2a4cf409a844dc4b6` (Aibot@iomaths.com).

## The short version

**Cloudflare cannot host this application.** It can sit in front of it, and it
can eventually hold its files. Those are two separate, optional pieces of work,
and neither one blocks getting the bot published to a channel.

## Why Cloudflare is not the origin

The app is a Flask process that (a) runs a background retry thread and (b)
writes uploaded PDFs to a mounted volume. Neither survives the Workers model:

| Cloudflare product | Verdict | Reason |
|---|---|---|
| Workers | No | Not a Python WSGI host. No persistent local filesystem. |
| Pages | No | Static hosting; the frontend is served by Flask itself (`app/__init__.py:46-48`), not built separately. |
| Containers | No, for now | Runs the image, but gives no persistent volume. `DATA_FOLDER` would be wiped on every restart. |

Render stays the origin. The `Dockerfile` header already says the image is
provider-portable, and that remains true — this is a "not yet", not a "never".

## Account state as found

Two things are false today, and both are dashboard actions no CLI or API can do
for you:

1. **There are zero zones.** `GET /zones` returns `total_count: 0`. There is no
   domain in this Cloudflare account, so there is nothing to proxy. A custom
   domain must be added to Cloudflare and its nameservers repointed at the
   registrar before any of Part A below can happen.
2. **R2 is not enabled.** `r2_buckets_list` returns `403 code 10042 — "Please
   enable R2 through the Cloudflare Dashboard."` Part B is blocked until it is
   switched on.

One unrelated Worker (`ranklytic`) exists in the account. Leave it alone.

## Part A — Cloudflare as the edge (needs a domain)

Once a zone exists, front the Render origin with it:

- `CNAME app → <service>.onrender.com`, proxied (orange cloud).
- SSL/TLS mode **Full (strict)**. Render serves a valid cert, so there is no
  reason to accept anything weaker. "Flexible" would make Cloudflare talk plain
  HTTP to the origin and is the classic way to create a redirect loop.
- Add the custom hostname as a Render custom domain too, or Render answers with
  its default cert and Full (strict) fails.

Then update, in this order, or channels break:

1. `PUBLIC_BASE_URL`, `FRONTEND_URL`, `CORS_ORIGINS` → the Cloudflare hostname.
2. Re-run the channel re-registration steps in `docs/DEPLOYMENT_CHECKLIST.md`.
   Every provider stores the callback URL it was given; none of them re-resolve.

### Rules that must NOT be applied to webhook paths

Provider callbacks are unauthenticated POSTs from datacentre IPs. Every generic
protection Cloudflare offers is designed to block exactly that traffic shape.
Bot Fight Mode, "Under Attack" mode, a challenge on `/*`, or a blanket rate
limit will silently eat customer messages — the provider sees a challenge page,
records a delivery failure, and retries into the same wall.

Exempt the callback paths from challenges and bot rules:

- `/telegram/webhook/*`
- the Meta WhatsApp webhook path
- the Wasender callback path
- the ToyyibPay callback path

Rate limiting at the edge is fine, but scope it to the authenticated app paths,
not to the callbacks.

### The hop count must change when Cloudflare goes in front

`app/__init__.py` wraps the app in `ProxyFix` with a hop count from
`TRUSTED_PROXY_HOPS`, default **1**. That is correct for Render alone. Adding
Cloudflare inserts a second proxy, so `X-Forwarded-For` grows by one entry and
a count of 1 resolves `remote_addr` to Cloudflare's edge IP rather than the
visitor - every visitor behind the same Cloudflare PoP then shares one
rate-limit bucket.

Raising it to `2` is only safe **after** the origin stops accepting direct
traffic. While `<service>.onrender.com` is still reachable, anyone can send
`X-Forwarded-For: <anything>, <anything>` straight to it and a hop count of 2
will trust the forged entry - handing them an unlimited rate-limit bypass and
the ability to poison any IP-based logging.

So the order is fixed:

1. Put Cloudflare in front and confirm it works.
2. Restrict the Render origin to Cloudflare's published IP ranges (or require a
   shared secret header that only Cloudflare sends).
3. Only then set `TRUSTED_PROXY_HOPS=2`.

Doing step 3 before step 2 is strictly worse than leaving it at 1.

### HSTS

The origin sets `X-Content-Type-Options`, `X-Frame-Options` and
`Referrer-Policy` but **no `Strict-Transport-Security`**. Turn on "Always Use
HTTPS" and HSTS at the Cloudflare edge as part of the cutover; the origin
enforces nothing of its own if Cloudflare is ever bypassed.

### Caching

Default-cache the static frontend assets under `/static/*` and leave everything
else uncached. `/api/*` responses are tenant-scoped and per-user; caching one is
a cross-tenant data leak, not a performance win.

## Part B — R2 for uploaded files (needs R2 enabled)

This is the change that lifts `numInstances: 1`.

Today two directories hold customer data on local disk:

- `DATA_FOLDER` = `/app/data` (`app/services/knowledge_service.py:19`, 23 refs)
  — knowledge PDFs and generated per-bot READMEs. Covered by the Render disk.
- `/app/media_uploads` (`app/__init__.py:121`,
  `app/routes/media_attachment_routes.py:61`) — **not** covered by the disk.

Moving both to R2 removes the single-instance constraint, makes deploys
stateless, and deletes the disk line from `render.yaml`. It is a real change
across ~25 call sites and should not be bundled into the first deploy.

## Recommended order

1. Deploy to Render. Publish channels against the `onrender.com` HTTPS URL —
   it is a stable cert on port 443, which is all Telegram and Meta require.
2. Add a domain to Cloudflare, then Part A.
3. Enable R2, then Part B, then raise `numInstances`.

Nothing in step 1 depends on Cloudflare. Treating the Cloudflare work as a
prerequisite would delay channel publishing for no functional gain.

---

# Revision 2026-09-05 — what has changed since the above

Three facts in the plan above are now stale. The reasoning still holds; the
targets moved.

| Written above | Actually true on 2026-09-05 |
|---|---|
| Render is the origin | **Fly.io is the origin** — app `wa-chatbot-my`, volume `chatbot_data` mounted at `/app/data` (`fly.toml:41-43`). `render.yaml` is a fallback, not the deployment. |
| "R2 is not enabled" | **Cloudflare is now subscribed.** Part B is unblocked. |
| Part B is about uploaded files only | Uploads are the *third* priority. Two bigger wins were missed — see §R2.1 and §R2.2. |

Unchanged and still correct: **Cloudflare cannot host this application.** Nothing
below proposes moving Flask to Workers.

## Nothing is live right now, and R2 will not change that

`auto_start_machines = false` (`fly.toml:52`), and the machine is stopped
pending payment. Everything that depends on `PUBLIC_BASE_URL` is therefore down:
the share link and QR code (`widget_routes.py:303`), and the Telegram
(`telegram_routes.py:330`), WhatsApp (`whatsapp_routes.py:101`) and Wasender
(`wasender_routes.py:115`) webhooks.

`integration.html` will still show a channel as "Working" while this is true,
because `channelState()` reads the last stored `connection_status` and
`loadChannel()` deliberately refuses to treat an unreadable answer as
"disconnected". That is the right behaviour — it stops a network blip inviting
someone to reconnect a healthy channel — but it means the page reads healthier
than reality while the origin is down.

**Fix the host first. R2 optimises a server people can reach.**

### Go-live runbook

```bash
# 1. Settle the Fly payment in the dashboard, then:
fly machine start 7845322b441798 -a wa-chatbot-my

# 2. Confirm it serves, not merely that it "started"
fly status -a wa-chatbot-my
curl -sS -o /dev/null -w "%{http_code}\n" https://wa-chatbot-my.fly.dev/

# 3. Confirm it booted rather than crash-looped
fly logs -a wa-chatbot-my | tail -40
```

Then, per bot, in `integration.html`: press **Check again**; repair anything
showing "Needs a fix" with **Set it up again** (that re-registers the webhook);
then open the share link and send one real message before trusting the page.

**Two migrations are pending, and one is order-sensitive.** No migration runner
exists — paste into the Supabase SQL editor:

| File | Ordering |
|---|---|
| `data/050_help_articles.sql` | any time |
| `data/052_support_escalation_context.sql` | **before deploying the new code** |

052 replaces the 5-argument `create_tenant_support_request` RPC with an
8-argument one. Old code against the new function is fine (the new params carry
SQL defaults). New code against the old function is not — every support
submission would 503.

## R2, in priority order

### R2.1 Frontend static assets — the biggest win, and it was missed above

`app/__init__.py:51` sets `static_folder=frontend`, and the Dockerfile runs
`gunicorn --workers 1`. **One** worker process serves every stylesheet, font and
script, competing with real API traffic for the same process. Every CSS request
is a request an API call waits behind.

The caching note above ("default-cache `/static/*`") gets the edge half right
but leaves the origin still generating those responses. Mirroring `frontend/`
into R2 removes the work entirely.

### R2.2 The embeddable widget bundle

The script customers paste into *their* sites (`embed.script_snippet`). Served
from your origin today, so your customers' page speed depends on your Fly
machine. It needs `Access-Control-Allow-Origin: *`, which is a bucket rule
rather than something to thread through Flask.

### R2.3 Uploaded files — as Part B above, with the numbers confirmed

Still 24 `DATA_FOLDER` references, still `MEDIA_FOLDER` (`app/storage_paths.py:23`;
`LEGACY_MEDIA_FOLDER` at :18 records an earlier path that sat outside the
volume). On Fly these live on the `chatbot_data` volume, which is why
`min_machines_running = 1` and why a second machine cannot simply be added.

The extra prize with presigned uploads: a PDF uploaded through Flask occupies
the single worker for the whole transfer. Presigned PUT sends the browser
straight to R2 and the worker never sees the bytes.

## Buckets

Two, because the access policy differs fundamentally.

```
wa-chatbot-static     PUBLIC, custom domain + CDN
  /support.html                    (frontend/ mirrored)
  /assets/css/*.css
  /assets/js/*.js
  /widget/embed.js                 -> Access-Control-Allow-Origin: *

wa-chatbot-uploads    PRIVATE, presigned access only
  /company/{company_id}/bot/{chatbot_id}/{uuid}.pdf
```

Upload keys are tenant-scoped **first**, so a guessed key cannot cross a company
boundary and a company's data is deletable by prefix.

## Cache strategy

No build step exists, so content-hashed filenames would mean introducing
bundling. Not worth it.

| Object | `Cache-Control` |
|---|---|
| `*.html` | `no-cache` — always revalidate; a 304 is a few hundred bytes |
| `assets/**` with unchanged filenames | `public, max-age=0, must-revalidate` until release-versioned URLs are implemented |
| `widget/embed.js` | `public, max-age=3600` — customers must pick up fixes |

Purge the CDN cache on every deploy if assets are cached there. A CDN purge does
not remove files already cached in customers' browsers. Do not set a one-year
immutable lifetime on filenames whose contents change between releases.

Release-prefixed asset URLs (`/{git-sha}/assets/...`) can use immutable caching
when HTML references that release explicitly. Keep mutable HTML revalidated.

## Configuration

Names only. Values go in Fly secrets and `.env` (gitignored at `.gitignore:58`);
`.env.txt` is the tracked template and gets placeholders.

```
R2_ACCOUNT_ID   R2_ACCESS_KEY_ID   R2_SECRET_ACCESS_KEY
R2_BUCKET_STATIC   R2_BUCKET_UPLOADS
R2_PUBLIC_BASE            https://cdn.<your-domain>
ASSET_BASE_URL            same, or EMPTY to serve from Flask as today
```

**Do not use the `*.r2.dev` URL in production** — it is rate-limited and
explicitly not for production traffic. A custom domain on the bucket is free and
is what actually puts the CDN in front of it.

`ASSET_BASE_URL` empty must serve everything from Flask exactly as today. That
is the rollback: unset one variable, redeploy. No code revert.

**Still required, and still only doable in the dashboard:** a domain must be
added to the Cloudflare account. As of 2026-08-28 `GET /zones` returned
`total_count: 0`. Without a zone there is no custom domain, and without a custom
domain there is no production-grade R2 URL.

## Work items

| # | Item | Depends on |
|---|---|---|
| 1 | Go-live runbook above | Fly payment |
| 2 | Add a domain to Cloudflare; create both buckets | your dashboard access |
| 3 | `scripts/deploy_static_to_r2.py` — mirror `frontend/`, set per-type cache headers, purge CDN. Idempotent, `--dry-run` first | 2 |
| 4 | `ASSET_BASE_URL` wiring, empty = today's behaviour. Must not break the ~47 raw-source assertions pinning `support.html` | 3 |
| 5 | Widget bundle + CORS rule; verify from a real third-party origin, not curl | 3 |
| 6 | Presigned PDF upload; browser uploads direct; indexer reads back from R2 | 2 |
| 7 | Tenant-isolation tests — company A cannot read or write company B's prefix | 6 |
| 8 | Drop the volume, raise machine count | 6, 7 |

Items 3–5 are independent of 6–8 and can ship first. **Item 7 is not optional**
and ships red-green with item 6.

## Not proposed

- Flask on Workers. Unchanged from the original verdict above.
- Caching `/api/*` at the edge. Tenant-scoped and authenticated; a caching
  mistake there is a cross-tenant data leak, not a performance win.
- Moving QR codes to R2. Generated client-side as SVG; they cost nothing.
