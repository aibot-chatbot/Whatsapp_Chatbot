# Cloudflare Edge Plan

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
