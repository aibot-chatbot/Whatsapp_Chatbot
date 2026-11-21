# Privacy and Data Protection

Written 2026-08-28, against the live Fly.io deployment - app `wa-chatbot-my`,
region `sin`, `https://wa-chatbot-my.fly.dev` (`fly.toml`). This is an
engineering record of what the system actually does with personal data — not a
compliance certificate and not a customer-facing privacy policy. Where something
is missing it says so, because a document that overstates coverage is worse than
no document at all.

## The distinction that drives everything

There are **two** groups of people in this system, and they have very different
relationships with us.

| | Who | Our role | How they consented |
|---|---|---|---|
| **Tenant users** | The business that signs up — clinic, shop, tuition centre | **Controller** | Signed up, accepted terms |
| **Tenants' customers** | The member of the public messaging that business on WhatsApp/Telegram | **Processor**, on the tenant's behalf | **Never agreed to anything with us** |

The second group is the sensitive one. They messaged a shop; they have no idea
this platform exists. They cannot log in, cannot request deletion from us, and
did not accept our terms. Every decision touching their data should assume they
would be surprised to learn we hold it.

## What personal data the system holds

**About tenant users:** email, name, company, hashed credentials, Google OAuth
identity, billing records (ToyyibPay order references), support tickets.

**About tenants' customers:** message content (inbound and outbound), phone
number, WhatsApp/Telegram profile name, conversation history, CRM lead records,
any file or image they send, and anything a tenant's knowledge PDFs happen to
contain about them.

## Where it physically lives

| Store | Contents | Notes |
|---|---|---|
| Supabase (Postgres) | Everything relational: users, conversations, messages, CRM leads, channels | **Verify the project's region.** If it is not in-region, message content already crosses a border regardless of where the app runs. |
| Fly volume at `/app/data` | Knowledge PDFs, generated per-bot READMEs, uploaded media | Single-attach, pinned to `primary_region`. **Encryption verified at deploy**: `ENCRYPTED=true`, mounted uid 1000. |
| Fly volume snapshots | A copy of everything on the volume | **Daily, 5-day retention, on by default.** This is a retention floor: deleting a customer's file leaves it recoverable for 5 more days. Any erasure SLA must say so. |
| Published image layers | ~7MB of real tenant media (gap 7) | Immutable and content-addressed. Deleting the file later does not remove the layer. |
| Platform logs | Application logs | See "Logs" below — this was leaking until 2026-08-28. |
| Fly secrets | ~32 credentials | Encrypted, never baked into the image. Verified: the built image contains no `.env`. |

`primary_region = "sin"` in `fly.toml` is a **privacy setting**. Changing it
relocates customers' message content to another jurisdiction and may require a
transfer basis. It is commented as such so it is not changed for latency.

## Sub-processors — the part most easily overlooked

Inbound customer messages are sent to third parties for inference. This is a
disclosable transfer, and tenants must be told:

| Processor | What it receives | Why |
|---|---|---|
| DeepSeek | Message text + conversation context | Free-trial generation path |
| OpenRouter | Message text + conversation context | Paid-plan generation, routed to the tenant's chosen model |
| Google Gemini | Knowledge-base text and query text | Embeddings for semantic retrieval |
| Meta / Telegram | Message content | They are the channel — they already hold it |
| ToyyibPay | Tenant billing details only | No customer message data |
| SMTP provider | Tenant email addresses only | OTP, invites, password reset |

OCR runs **locally** (PaddleOCR) — scanned documents are not sent out for text
extraction.

If a tenant asks "does my customers' data leave the country", the honest answer
is yes: to the AI providers above, at minimum.

## Logs — fixed 2026-08-28

Three code paths wrote customers' personal data into application logs. Platform
logs are retained by the host and readable by anyone with dashboard access, so
this effectively created a second, unmanaged store of message content.

| Location | What it logged | Now |
|---|---|---|
| `app/views.py` | The entire Meta webhook body — message text, phone number, profile name | Entry count only |
| `app/routes/wasender_routes.py` | The entire Wasender payload | Top-level keys only, no values |
| `app/services/wasender_retry_service.py` | The whole message record — `message_text` **and** `customer_phone` | Names of the missing fields only |

Webhook path secrets were also logged verbatim; they are now SHA-256 prefixes.
The linked-device webhook verifies an HMAC-SHA512 signature over the raw request body.

`tests/test_no_pii_in_logs.py` fails the build if a payload is logged verbatim
again. It is a source-level invariant on purpose: the failure mode is someone
adding a convenient debug line, which is visible in the diff long before it is
visible in a response.

## Security controls relevant to privacy

- **TLS everywhere.** `force_https = true`; Fly terminates with a managed cert.
- **CORS allowlist actually enforced.** A stray `CORS(origins="*")` registered
  before config load meant every response reflected the caller's `Origin`. Fixed,
  and pinned by `tests/test_cors_allowlist.py`.
- **Webhook authenticity.** Meta callbacks verify `X-Hub-Signature-256` and now
  **fail closed** if `APP_SECRET` is unset — previously an empty secret made the
  HMAC forgeable by anyone.
- **Tenant isolation.** Inbound messages route to a tenant by `phone_number_id`
  or an unguessable per-channel path secret.
- **Rate limiting keys on the real client IP** via `ProxyFix`. Without it every
  visitor shared one bucket — a platform-wide lockout, not merely a bypass.

## Known gaps — do not describe these as done

1. **No automated retention or purge.** Conversations and message content are kept
   indefinitely. No scheduled deletion, no per-tenant retention setting.
2. **No customer-facing erasure path.** A tenant's customer cannot reach us to
   request deletion, and no tooling exists for a tenant to erase one customer's
   history on request.
3. **No formal DPA with tenants**, and no sub-processor list shown at signup. The
   table above is the raw material for one.
4. **Media filenames are guessable.** `/media/bot_<id>_<original_name>` is served
   with no authorization check; anyone who guesses a filename can fetch the file.
5. **Supabase region unverified.** Confirm before claiming data residency.
6. **No breach-notification runbook.**
7. **Tenant media is baked into published image layers.** The `Dockerfile` does
   `COPY . .` and `media_uploads/` (the legacy read-fallback in
   `app/storage_paths.py`) is not in `.dockerignore`, so ~7MB of real customer
   files ship inside every image pushed to the registry. It cannot simply be
   ignored - `serve_media()` still falls back to that directory, so excluding it
   would 404 every pre-existing media URL. The fix is ordered: copy the files to
   `/app/data/media_uploads` on the volume, verify the URLs still resolve, then
   add the ignore rule. Until then, an image layer is a third copy of customer
   data outside the two stores listed above.

Items 1, 2, 4 and 7 are the ones that would matter most in an actual complaint.

## Before onboarding real customers

- [ ] Confirm the Supabase project region and record it here
- [ ] Publish a customer-facing privacy policy naming the sub-processors above
- [ ] Add a DPA to tenant signup
- [ ] Decide a retention period and implement the purge
- [ ] Give tenants a way to delete one customer's conversation history
- [ ] Put an authorization check on `/media/<filename>`
- [ ] Migrate `media_uploads/` onto the volume, then `.dockerignore` it (gap 7)
- [ ] Decide whether 5-day volume snapshots are compatible with the erasure promise
- [ ] Confirm `TRUSTED_PROXY_HOPS` still matches the real proxy depth
- [ ] Re-run `pytest tests/test_no_pii_in_logs.py tests/test_cors_allowlist.py`
