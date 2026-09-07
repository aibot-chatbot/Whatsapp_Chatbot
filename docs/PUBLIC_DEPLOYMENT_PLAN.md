# Public deployment: Fly.io application, Cloudflare domain

Date: 2026-09-07. Status: **researched plan; not deployed**.
Scope: document the first public release and its verification before changing hosting.

## Decision

**Use the existing Fly.io deployment for the Flask application.** Keep Cloudflare
for DNS and, optionally, the HTTPS proxy/cache. Keep Supabase for the database.
This follows the existing Docker deployment and avoids a hosting rewrite.

```text
Customer / website visitor / channel provider
                    |
          Permanent HTTPS hostname
          Cloudflare DNS / optional proxy
                    |
          Fly.io: wa-chatbot-my, Singapore
          Flask + Gunicorn + background jobs
             |                     |
         Supabase            /app/data volume
      tenant records       PDFs and uploaded media
```

Deploy the platform once. A client creates a bot inside that platform, uploads
knowledge, tests replies, and explicitly connects a channel. Each bot does not
need a separate Fly application or Cloudflare deployment.

Cloudflare's subscription and Fly's compute billing are separate. R2 is a later
storage option, not a prerequisite for this release. Render remains an alternate
configuration in the repository; this plan does not use it as the primary host.

## What exists, and what is not verified

| Area | Repository evidence / current limitation |
| --- | --- |
| App host | [fly.toml](../fly.toml): `wa-chatbot-my`, region `sin`, port 8000, 1 GB VM configuration. This does not prove a running deployment or adequate capacity. |
| Server | [Dockerfile](../Dockerfile): Gunicorn, one worker, eight threads, 120-second worker timeout, non-root user. |
| Persistent files | Fly mount `chatbot_data` at `/app/data`; knowledge files use that directory and media defaults to its `media_uploads` subdirectory. Verify the actual volume and any environment override before release. |
| Background jobs | [wsgi.py](../wsgi.py) starts Wasender retries and billing scheduling by default. These must have one owner. |
| Availability | Automatic stop and start are disabled. `min_machines_running = 1` does **not** enforce a maximum of one Machine. Inspect actual Machine count. |
| Health | Fly and Docker checks request `/`. HTTP 200 there does not prove database access, upload processing, AI replies, channel delivery, or background-job success. |

Earlier read-only checks in the same 2026-09-07 review reported an ended Fly
trial requiring billing action; they could not establish current Machine state.
The connected Cloudflare account exposed zero zones and an R2 enablement error;
subscription access was denied, so the reported paid plan was not verified.
These are dated observations, not a fresh account inspection for this document.
See [client journey evidence](CLIENT_JOURNEY_REVIEW.md).

## Keep the public link stable

Choose one canonical hostname before distributing links, preferably
`https://app.<your-owned-domain>`. The existing
`https://wa-chatbot-my.fly.dev` is an alternative if a custom domain is not ready;
its availability must first be verified. Changing hostname later requires
updating distributed links and provider callback registrations.

Use that canonical origin for `PUBLIC_BASE_URL`, `FRONTEND_URL`, and the explicit
`CORS_ORIGINS` allowlist. Keep existing widget keys when disabling/re-enabling a
website channel. The implemented key has no automatic expiry; availability also
depends on tenant entitlement, channel state, DNS, TLS, hosting and upstream services.
A stable URL is therefore not a promise of uninterrupted service.

Do not publish a `trycloudflare.com` address. Cloudflare describes Quick Tunnels
as development/testing infrastructure without an uptime guarantee.
[Quick Tunnels documentation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).

## Release gates

1. **Confirm the release target and billing.** Verify the Fly organization owns
   `wa-chatbot-my`, billing allows it to run, and the domain belongs to the intended
   Cloudflare account. Inspect existing Machines, IPs, volume attachment and backups.
2. **Prepare one reviewed release artifact.** This workspace contains unrelated
   dirty changes. Do not deploy its entire working directory. Use an isolated
   release checkout containing the approved application changes and dependencies.
3. **Protect tenant files.** The current [.dockerignore](../.dockerignore) explicitly
   retains legacy `media_uploads/`, so `COPY . .` can include customer media in an
   image. Inventory privately, migrate required files to durable storage, verify
   old URLs, and exclude tenant files from the release build context. Do not simply
   delete legacy files or exclude them before preserving referenced content.
4. **Verify schema and configuration.** Audit the selected release against the
   actual applied migrations/RPCs, including relevant changes through 053. Older
   instructions ending at migration 019 or declaring only 050/052 pending are not
   a current migration ledger. Prepare required changes and backups for approval;
   do not blindly replay SQL or rollback files.
5. **Complete release validation.** The UI journey has mocked/local evidence, not
   production proof. Its latest Codex Security scan failed without a completed
   report following an automated prompt-policy rejection. Resolve that verification
   gap through the supported workflow before declaring the release ready.

## Operator sequence: prepare, deploy, verify

Commands below are a runbook, **not commands executed by this document task**.
Production changes need authorization for the concrete release and target.

### 1. Inspect the existing Fly application

```powershell
fly status -a wa-chatbot-my
fly machine list -a wa-chatbot-my
fly volumes list -a wa-chatbot-my
fly ips list -a wa-chatbot-my
fly checks list -a wa-chatbot-my
```

Resolve billing/access failures before interpreting missing results as missing
resources. Do not run `fly launch` to replace the existing app. Verify exactly one
application Machine and the intended volume in `sin`; do not reuse a historical
Machine ID without checking it. Record the current image and configuration for rollback.

### 2. Prepare storage, secrets and job ownership

| Item | Required verification |
| --- | --- |
| Volume | Existing `chatbot_data` is mounted at `/app/data`, has enough free space, and is writable by the container's actual `appuser` UID/GID. Mount permissions can differ from image-directory permissions. |
| Recovery | Take a suitable backup and prove restoration of files and matching database references. A single attached volume is not replicated application storage. |
| Secrets | Validate required names against the selected release's configuration and provider paths. Include Supabase service credentials, signing secrets, AI infrastructure, email and only the channels/payment gateway in use. Never put values in this document, frontend, image, logs or shell history. |
| Production flags | Keep debug off, rate limiting on, and `ENABLE_DEV_BILLING_ROUTES` absent; the string `false` still fails production startup. Memory rate limits reset on restart; do not configure Redis without its supported dependency and service. |
| Jobs | Keep one Gunicorn worker and one owner of retry/billing loops. Do not also schedule the same billing jobs externally. Monitor successful work, not just thread startup. |

Use Fly's secret facility through an approved secure input process. Setting secrets
normally updates/restarts Machines; staged secrets can be applied with a coordinated
deployment. Do not bulk-import the developer environment.
[Fly secrets](https://fly.io/docs/apps/secrets/).

### 3. Prepare the permanent hostname

1. Add the chosen hostname to the existing Fly application's certificates and
   follow Fly's returned DNS ownership/certificate instructions, including the
   prescribed `_fly-ownership` TXT record when using proxied Cloudflare DNS.
2. Configure the domain's DNS in the correct Cloudflare zone. Validate the Fly
   origin certificate before enabling proxying; follow the Fly Cloudflare guide
   for certificate validation and renewal records.
3. If proxying, use **Full (strict)** with a valid matching origin certificate.
   Verify HTTPS without redirect loops before changing the canonical app URLs.
4. Review forwarding headers and origin access. Do not blindly increase
   `TRUSTED_PROXY_HOPS` from 1 to 2: verify the real chain and reject forged headers
   on direct-origin traffic before changing trust.
5. Preserve application security while configuring edge rules: bypass caching for
   authenticated/API, upload, chat/widget runtime and callback responses; avoid
   interactive challenges on provider callbacks. Test actual selected-provider paths.

Full (strict) requires an unexpired, trusted certificate matching the requested
or target hostname. [Cloudflare Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/).
Use the returned records rather than guessing IPs or validation values.
[Fly custom domains](https://fly.io/docs/networking/custom-domain/).

Do not blanket-cache tenant HTML or mirror the entire frontend to a public bucket.
For mutable asset filenames, retain revalidation unless release-versioned URLs
are implemented. A CDN purge does not evict fresh browser caches. R2 and edge
caching are separate later work; neither fixes a stopped Flask origin.

### 4. Deploy the approved artifact

Keep the repository's single-process topology. Choose a deployment method that
does not overlap owners of background jobs; a brief maintenance interruption is
preferable to duplicate sends. Do not use blue/green or add a second Machine to
claim high availability while storage and job ownership remain process-local.

From the reviewed release checkout, the intended command is:

```powershell
fly deploy --app wa-chatbot-my --config fly.toml --ha=false --strategy rolling
```

Before executing, verify the installed CLI supports these options and the actual
Machine inventory contains one app Machine. `--ha=false` prevents creation of
extra HA Machines on initial deployment or when scaled to zero; it is not a
cleanup command for pre-existing Machines. Rolling deployment of the single
Machine still has downtime; communicate the maintenance window. Fly does not
support canary or bluegreen deployment with attached volumes.
[Deployment strategies](https://fly.io/docs/reference/configuration/#picking-a-deployment-strategy),
[redundancy behavior](https://fly.io/docs/apps/app-availability/#turn-off-redundancy-on-deploy).

A Fly `release_command` runs on a temporary Machine without the attached volume;
do not use it to migrate `/app/data`. Volume preparation needs a separately
reviewed procedure against the correct attachment.

After deployment, verify the recorded image is the approved release, inspect
checks and sanitized logs, and confirm the mounted volume remains attached.
Do not treat a successful CLI exit as completed client-journey verification.

### 5. Verify the real client journey

Use an authorized test tenant and a synthetic document; provider sends, AI usage
and payments must stay within the approved test scope.

1. Open the canonical HTTPS URL in a fresh browser, sign in, create a bot, upload
   the synthetic PDF, and confirm extraction/knowledge readiness.
2. Apply instructions and test a factual reply from that document. Verify relevant
   limits and credit behavior using the selected plan without buying a live plan.
3. Explicitly choose a channel. For website publishing, enable it and test the
   public link without an admin session plus the embed from an allowed external origin.
4. For each selected messaging channel, verify its stored callback uses the
   canonical hostname and perform an authorized inbound/reply test. Confirm
   signatures, retry behavior and absence of duplicate replies.
5. Disable website publishing and verify the old link stops serving the bot;
   re-enable and verify the same key works. In a planned restart test, confirm
   documents remain and background jobs resume without duplicate ownership.

## Operations and rollback

Monitor external HTTPS availability, TLS expiry, memory/OOM events, disk space,
database/AI failures, webhook failures and job last-success evidence. The configured
1 GB and request limits are starting settings, not measured capacity guarantees.
Set an accountable alert recipient and restoration procedure before client rollout.

Fly health checks route traffic away from unhealthy Machines; they are not a
complete repair system. With one Machine there is no healthy peer during failure.
Do not promise zero downtime or "always online" under this topology.
[Fly health checks](https://fly.io/docs/reference/health-checks/),
[volume limitations](https://fly.io/docs/volumes/overview/).

Before release, add and test a bounded readiness check for essential application
dependencies, with separate worker-success monitoring. This is a proposed
implementation task; the current `/` check has not been replaced by this document.

Rollback means redeploying the recorded previous image with compatible settings,
then repeating availability and channel checks. It does not automatically undo
schema changes or restore volume contents. Prefer compatible forward database
repairs; any restore needs a separately approved plan that accounts for writes
made since the backup. Preserve stable keys and the canonical hostname.

Before scaling out, introduce shared file storage, durable job ownership/claims
and shared rate limiting, with tenant-isolation and duplicate-delivery tests.
Moving files to R2 alone is insufficient. Singapore hosting alone also does not
establish the data residency of Supabase, AI providers or messaging providers.

## Documentation precedence

Use this document for the deployment target and release sequence. The older
[edge plan](CLOUDFLARE_EDGE_PLAN.md) is historical: its Render-first instructions,
R2 subscription assumptions, static-asset performance claims and R2-only scale-out
steps are not verified release instructions. The
[deployment checklist](DEPLOYMENT_CHECKLIST.md) remains a configuration reference,
but its migration range and external scheduling instructions need reconciliation
against the chosen release and current `wsgi.py`.

This task changed documentation only. No hosting, DNS, secrets, billing, database,
Machine state or production deployment was changed.

Agents Orchestrator independently researched the official Fly documentation and
reviewed the deployment sequence. Local source inspection established the app,
storage and scheduler constraints; platform documentation established the hosting
behavior. Neither establishes a healthy live release.
