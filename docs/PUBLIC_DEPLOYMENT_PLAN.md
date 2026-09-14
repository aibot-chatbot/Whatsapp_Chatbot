# Public deployment: Fly.io application, Cloudflare domain

Date: 2026-09-07; updated 2026-09-10. Status: **public application live; channel rollout partial**.

[Live login](https://aibot-chatbot-my.fly.dev/login.html) runs in the paid
**aibot EMAIL** organization (`personal`), following the user's correction from
IOMaths. One Singapore Machine and an encrypted 1 GB volume are running; public
DNS/TLS, both staff password logins, authorization, dashboard charts and three
enabled website bots were verified. Forty-one available runtime files were
restored and hash-checked on the volume. The remaining operational and channel
gaps are recorded in [current release evidence](FLY_CHANNEL_READINESS.md).
The configuration-only security scan passed; it does not supersede the earlier
incomplete source scan.
The eight-path Telegram scan completed with one low-severity legacy-data finding;
the required malformed active record is absent from the live channel inventory.

## Decision

**Use the existing Fly.io configuration for the Flask application.** Keep Cloudflare
for DNS and, optionally, the HTTPS proxy/cache. Keep Supabase for the database.
This follows the existing Docker deployment and avoids a hosting rewrite.

```text
Customer / website visitor / channel provider
                    |
          Permanent HTTPS hostname
          Fly hostname (Cloudflare optional later)
                    |
          Fly.io: aibot-chatbot-my, Singapore
          Flask + Gunicorn (background jobs off)
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
| App host | [fly.toml](../fly.toml): `aibot-chatbot-my`, region `sin`, port 8000, 1 GB VM. Live single-Machine deployment verified; adequate capacity is not load-tested. |
| Server | [Dockerfile](../Dockerfile): Gunicorn, one worker, eight threads, 120-second worker timeout, non-root user. |
| Persistent files | Fly mount `chatbot_data` at `/app/data`; knowledge files use that directory and media defaults to its `media_uploads` subdirectory. The live mount, UID 1000 write access and 41 restored file hashes were verified after deployment; missing source PDFs remain a recovery gap. |
| Background jobs | [wsgi.py](../wsgi.py) defaults are overridden in `fly.toml`: Wasender retries, billing scheduling and Langflow automation remain disabled until runtime ownership is handed over. |
| Availability | Automatic stop and start are disabled. `min_machines_running = 1` does **not** enforce a maximum of one Machine. Inspect actual Machine count. |
| Health | Fly and Docker checks request `/`. HTTP 200 there does not prove database access, upload processing, AI replies, channel delivery, or background-job success. |

Earlier read-only checks in the same 2026-09-07 review reported an ended Fly
trial requiring billing action; they could not establish current Machine state.
The connected Cloudflare account exposed zero zones and an R2 enablement error;
subscription access was denied, so the reported paid plan was not verified.
These are dated observations, not a fresh account inspection for this document.
See [client journey evidence](CLIENT_JOURNEY_REVIEW.md).

## Keep the public link stable

The verified canonical origin is `https://aibot-chatbot-my.fly.dev`.
A future custom domain requires updating distributed links, allowed origins and
provider callback registrations; it is not needed for the current live release.

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
   `aibot-chatbot-my`, billing allows it to run, and the domain belongs to the intended
   Cloudflare account. Inspect existing Machines, IPs, volume attachment and backups.
2. **Prepare one reviewed release artifact.** Recheck the working tree for unrelated
   changes. Do not deploy its entire working directory. Use an isolated
   release checkout containing the approved application changes and dependencies.
3. **Protect tenant files.** The [.dockerignore](../.dockerignore) now allowlists
   runtime inputs; neither `data/` nor legacy `media_uploads/` is sent to the builder.
   Local tenant files remain preserved. Restore required knowledge files under
   `/app/data` and legacy media under `/app/data/media_uploads` on the volume,
   verify owner write access and old URLs, and only then enable application traffic.
   Do not treat the image as a tenant-file backup.
4. **Verify schema and configuration.** Audit the selected release against the
   actual applied migrations/RPCs, including relevant changes through 053. Older
   instructions ending at migration 019 or declaring only 050/052 pending are not
   a current migration ledger. Prepare required changes and backups for approval;
   do not blindly replay SQL or rollback files.
5. **Complete release validation.** Staff password login and dashboards have live
   browser/API proof; real channel conversations still require verification. Read
   the dated tests and scoped Codex Security result in
   [current release evidence](FLY_CHANNEL_READINESS.md). An incomplete scan or
   a scoped result does not certify the entire application or a live deployment.

## Operator sequence: prepare, deploy, verify

Commands below are a reusable runbook. The actual authorized first deployment
and its verification are recorded in [release evidence](FLY_CHANNEL_READINESS.md).
Future production changes need authorization for their concrete scope and target.

### 1. Inspect Fly application inventory

```powershell
fly status -a aibot-chatbot-my
fly machine list -a aibot-chatbot-my
fly volumes list -a aibot-chatbot-my
fly ips list -a aibot-chatbot-my
fly checks list -a aibot-chatbot-my
```

Resolve billing/access failures before interpreting missing results as missing
resources. Current inventory confirms no app; create the configured app in
`iomaths` once billing permits. Do not replace resources from historical assumptions.
Verify exactly one
application Machine and the intended volume in `sin`; do not reuse a historical
Machine ID without checking it. Record the current image and configuration for rollback.

### 2. Prepare storage, secrets and job ownership

| Item | Required verification |
| --- | --- |
| Volume | The target `chatbot_data` volume is mounted at `/app/data`, has enough free space, and is writable by the container's actual `appuser` UID/GID. Mount permissions can differ from image-directory permissions. |
| Recovery | Take a suitable backup and prove restoration of files and matching database references. A single attached volume is not replicated application storage. |
| Secrets | Validate required names against the selected release's configuration and provider paths. Include Supabase service credentials, signing secrets, AI infrastructure, email and only the channels/payment gateway in use. Never put values in this document, frontend, image, logs or shell history. |
| Production flags | Keep debug off, rate limiting on, and `ENABLE_DEV_BILLING_ROUTES` absent; the string `false` still fails production startup. Memory rate limits reset on restart; do not configure Redis without its supported dependency and service. |
| Jobs | Keep one Gunicorn worker and one owner of retry/billing loops. Do not also schedule the same billing jobs externally. Monitor successful work, not just thread startup. |

Preserve the currently selected customer payment-gateway environment during this
hosting release. Keep retry and billing workers disabled during initial storage
restoration; enable them only after their existing runtime owner and queued work
have been checked. Local-only Langflow URLs require a reachable hosted runtime
before enabling automation on Fly.

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
fly deploy --app aibot-chatbot-my --config fly.toml --ha=false --strategy rolling
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

The original 7 September review changed documentation only. The authorized
10 September continuation created the live Fly application, restored its volume,
imported selected secrets securely and verified public staff access. Current
channel changes and security scope are recorded in the release evidence.

Agents Orchestrator independently researched the official Fly documentation and
reviewed the deployment sequence. Local source inspection established the app,
storage and scheduler constraints; platform documentation established the hosting
behavior. Later live checks establish only the dated outcomes explicitly recorded
in the release evidence; they do not establish real provider delivery.
