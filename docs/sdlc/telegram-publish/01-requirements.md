# P1 Requirements - Publish bot to Telegram on Fly.io

Gate 1 confirmed 10 September 2026. Supersedes nothing; this is a new workstream
alongside the support/help-desk docs in `docs/sdlc/`.

## Goal

Establish the first working Telegram webhook connection for one selected chatbot,
served from the Fly.io deployment, and prove a real inbound message produces one
reply. Fly billing was the prior blocker and is now reported active.

## Confirmed decisions (Gate 1)

| Decision | Value | Consequence if changed |
| --- | --- | --- |
| Channel | Telegram | Meta WhatsApp lacks `subscribed_apps` and phone `/register` in code; Wasender lacks provider header auth. Both are larger builds. |
| Owning row | `telegram_channels.id = 8` - company 1, chatbot 53 "OlympicEdu Assistant" | Telegram allows exactly ONE webhook per bot. Registering a different row makes a different tenant's bot answer. |
| Losing rows | ids 5, 6, 7 set `connection_status='disconnected'` | Left alone they keep reading "connected" while being structurally unable to receive. |
| Canonical host | `https://wa-chatbot-my.fly.dev` | The hostname is written into every registration and widget embed. Changing it later means re-pointing by hand. |
| Scope | Register + verify + fix Telegram Gap A and Gap B | Register-only ships a callback that accepts unauthenticated updates. |

## Verified starting state (not assumed)

- Fly CLI authenticated as `aibot@iomaths.com`; orgs `personal` and `iomaths`;
  **zero apps exist**. `fly.toml` targets `wa-chatbot-my` in `sin`.
- `telegram_channels` holds 5 rows (ids 5-9). All five carry an **identical**
  `bot_token` (confirmed by SHA-256 digest) for one bot: `@UltraAvaShopBot`,
  `telegram_bot_id` 8934033330, `getMe.first_name` "test bot".
- `getWebhookInfo` returns `url=""` and `pending_update_count=0`.
  **Nothing is registered with Telegram.** Every stored `webhook_url` is a dead
  ngrok tunnel, so `connection_status='connected'` is stale on all four active rows.
- All five `webhook_secret` values satisfy Telegram's `secret_token` charset rule
  `^[A-Za-z0-9_-]{1,256}$`.
- `telegram_channels` columns: id, company_id, chatbot_id, bot_token, bot_username,
  telegram_bot_id, webhook_secret, webhook_url, connection_status, last_error,
  is_active, created_at, updated_at. **No column records whether `secret_token`
  was registered.**
- Highest migration on disk is 054, so 055 is free.

## Functional requirements

1. FR1 - The Fly application `wa-chatbot-my` exists in org `iomaths` with the
   `chatbot_data` volume mounted at `/app/data` and exactly one machine.
2. FR2 - `PUBLIC_BASE_URL` equals the canonical host **before** any registration.
3. FR3 - Row 8's webhook is registered with Telegram against the canonical host,
   with a freshly minted `secret_token`, and verified via `getWebhookInfo` rather
   than trusting `setWebhook`'s return.
4. FR4 - Rows 5, 6, 7 report `disconnected`.
5. FR5 - Re-pointing a webhook no longer discards queued updates by default (Gap A).
6. FR6 - The callback rejects a request whose secret-token header is absent when
   that channel is known to have a registered `secret_token` (Gap B).
7. FR7 - One real inbound Telegram message to `@UltraAvaShopBot` yields exactly
   one reply drawn from chatbot 53's deployed knowledge.

## Non-functional requirements

- NFR1 - Secret rotation is mandatory, not optional: the current `webhook_secret`
  of row 8 was exposed in plaintext inside `webhook_url` during this session's
  inventory. Registration must mint a new one (the existing script already does).
- NFR2 - No secret value appears in logs, committed files, or `fly.toml [env]`.
- NFR3 - Test coverage floor 80% on changed code; existing 205-test channel and
  release suites must stay green.
- NFR4 - Region stays `sin` (PDPA/GDPR data-residency decision, not latency).
- NFR5 - One machine only, `auto_stop_machines=false`: the Wasender retry loop and
  billing scheduler are in-process and process-local.

## Data

- Entity touched: `telegram_channels` (existing) plus one new marker column.
- Message content is tenant customers' personal data; it must stay in-region and
  out of logs.
- No new personal-data entity is introduced.

## Integrations

- Telegram Bot API: `getMe`, `setWebhook`, `getWebhookInfo`.
- Fly.io: app, volume, secrets, deploy (via `flyctl`; no Fly MCP exists).
- Supabase: channel rows via the service-role client.

## Constraints

- `context7` and `codebase-memory-mcp` MCP servers failed to connect this session;
  provider facts come from first-party docs via WebFetch, code navigation via Grep.
- `plugin:supabase:supabase` MCP is installed but unauthenticated.
- Migration numbering below 055 has known duplicate numbers; only 055 is claimed here.

## Out of scope (explicit)

- Meta WhatsApp onboarding (`subscribed_apps`, phone `/register`).
- Wasender provider header auth and `messages.upsert` array handling.
- Durable/off-request inbound processing and exactly-once delivery proof.
- Custom domain and TLS certificates.
- Giving rows 5, 6, 7 their own bot tokens.
- A fresh Codex Security scan of the whole checkout.

## Acceptance boundary

"Fly app live", "callback registered", and "real conversation verified" are three
separate results and are reported separately. `setWebhook` returning ok is not
delivery proof; `getWebhookInfo` with no error after a real update is.
