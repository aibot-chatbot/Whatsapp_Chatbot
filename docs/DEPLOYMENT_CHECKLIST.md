# Deployment Checklist

Payment status (2026-09-15): CHIP replaces ToyyibPay and HitPay in the current code.
Local tests and a provider sandbox payment are verified; deployment is pending.
Use the [CHIP payment guide](CHIP_PAYMENT_GATEWAY.md) for current routes, configuration, and rollout.

## 1. Pre-Deployment

### Environment Configuration

| Variable | Status | Notes |
|---|---|---|
| `SUPABASE_URL` | Required | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Required | Service-role key (server-side only) |
| `SECRET_KEY` | Required | Flask session signing key |
| `JWT_SECRET` | Required | JWT signing secret |
| `FRONTEND_URL` | **Required** | Production frontend URL; startup raises RuntimeError if missing |
| `CORS_ORIGINS` | **Required** | Comma-separated production origins; startup raises if missing/empty |
| `RATELIMIT_STORAGE_URI` | Optional | No code requires it; `app/config.py:63` silently defaults to `memory://`. Note `redis` is **not** in `requirements.txt`, so a `redis://` value cannot work in the image as built. Acceptable only because the service is pinned to one instance and one worker. |
| `RATELIMIT_ENABLED` | `true` | Enable rate limiting in production |
| `CHIP_*` | Required before enabling payments | Use the [CHIP configuration and staged rollout](CHIP_PAYMENT_GATEWAY.md); start in test mode. |
| `OPENROUTER_API_KEY` | Required | Paid-plan generative AI routing key for tenant-selected supported models |
| `OPENAI_API_KEY` | Optional / legacy | Direct OpenAI helper key; not the normal current chatbot/RAG generative path |
| `GEMINI_API_KEY` | Required | Gemini embedding infrastructure key for vector generation and semantic retrieval |
| `DEEPSEEK_API_KEY` | Required | Direct DeepSeek key for Free trial policy (`deepseek-v4-flash`) |
| `PUBLIC_BASE_URL` | Required (channels) | Public backend URL baked into Telegram/Wasender webhook registrations. Nothing raises if unset - webhook registration just returns HTTP 400 and widget embed URLs silently fall back to `request.host_url`. Must be `https://`. |
| `APP_SECRET` | **Required (WhatsApp)** | Meta app secret used to verify `X-Hub-Signature-256` on every inbound WhatsApp message (`app/decorators/security.py`). Must be the **same Meta app** whose secret is in `WHATSAPP_META_APP_SECRET` - nothing in the code enforces that, and a mismatch 403s every delivery. If unset the webhook now fails closed and rejects deliveries. |
| `VERIFY_TOKEN` | **Required (WhatsApp)** | Compared against `hub.verify_token` at `app/views.py:78`. If it does not match what you type into the Meta dashboard, the callback URL cannot be saved at all. |
| `VERSION` | **Required (WhatsApp)** | Graph API version interpolated into the *outbound* send URL (`app/utils/whatsapp_utils.py:99`) with no default. Unset produces `https://graph.facebook.com/None/...` and every reply fails. Distinct from `WHATSAPP_GRAPH_API_VERSION`; set both to the same value, e.g. `v22.0`. |
| `AI_CREDIT_ENFORCEMENT_ENABLED` | `true` | Master switch for AI-credit charging. Requires `AI_RETAIL_MARKUP_BPS` and `AI_USD_TO_MYR_RATE_MICRO_MYR_PER_USD`. |
| `AI_RETAIL_MARKUP_BPS` | Required (enforcement) | Retail markup in basis points (100 bps = 1%). Required when `AI_CREDIT_ENFORCEMENT_ENABLED` is true. |
| `AI_USD_TO_MYR_RATE_MICRO_MYR_PER_USD` | Required (enforcement) | USD to MYR exchange rate in micro-MYR per USD. Example: 4500000 = RM 4.50 per USD. Required when enforcement is enabled. |
| `DEEPSEEK_V4_FLASH_CACHE_HIT_INPUT_PRICE_MICRO_USD_PER_MILLION_TOKENS` | Required (enforcement) | DeepSeek cache-hit pricing (micro-USD per 1M tokens). Checked at first AI request; startup succeeds without it. |
| `DEEPSEEK_V4_FLASH_CACHE_MISS_INPUT_PRICE_MICRO_USD_PER_MILLION_TOKENS` | Required (enforcement) | DeepSeek cache-miss pricing (micro-USD per 1M tokens). Checked at first AI request. |
| `DEEPSEEK_V4_FLASH_OUTPUT_PRICE_MICRO_USD_PER_MILLION_TOKENS` | Required (enforcement) | DeepSeek output pricing (micro-USD per 1M tokens). Checked at first AI request. |
| `AI_CREDIT_LOW_THRESHOLD_MICRO_MYR` | `5000000` | RM5.00 (RM1 = 1,000,000 micro-MYR) |
| `AI_CREDIT_CRITICAL_THRESHOLD_MICRO_MYR` | `1000000` | RM1.00 |
| `BILLING_GRACE_PERIOD_DAYS` | `3` | Grace period after expiry |
| `ENABLE_DEV_BILLING_ROUTES` | **Must be absent** | Do NOT set it to `false`. `app/config.py:52` tests the raw string for truthiness, so the *string* `"false"` is truthy and raises RuntimeError in production. Unset (or empty) is the only safe state. |

### Application Server

For local development, use the Flask dev server:

```
python run.py
```

For production, use a production-grade WSGI server. The repository includes a
`wsgi.py` entry point compatible with Gunicorn and Waitress:

```
# Gunicorn (Linux/macOS)
gunicorn wsgi:app --bind 0.0.0.0:8000 --workers 1 --threads 8

# Waitress (Windows-friendly)
pip install waitress
waitress-serve --host 0.0.0.0 --port 8000 wsgi:app
```

Do NOT use `python run.py` in production; it is the local Flask development
server. It binds to localhost by default and does not start a public tunnel.
External callbacks require a separately deployed public HTTPS server.

### Security Verification Checklist

- [ ] `.env` is NOT tracked in Git
- [ ] Exposed secrets have been rotated (see below)
- [ ] `ENABLE_DEV_BILLING_ROUTES` is **not set at all** (setting it to `false` crash-loops the deploy)
- [ ] `CORS_ORIGINS` contains only production domains (no wildcard)
- [ ] `FRONTEND_URL` matches the production frontend
- [ ] Rate limiting is enabled with Redis backend
- [ ] JWT secret is strong and unique
- [ ] SECRET_KEY (Flask session) is strong and unique
- [ ] Weak or missing JWT_SECRET or SECRET_KEY blocks production startup (RuntimeError)
- [ ] OTP values are not logged (confirmed by code audit)
- [ ] CHIP raw-body signature verification and authoritative purchase validation are enabled

### Exposed Credentials Requiring Rotation

**This claim could not be substantiated (re-audited 2026-08-28).** `git log --all
--full-history -- .env` is empty - `.env` was never tracked. `.env.txt` *is*
tracked, but every one of its revisions across all 361 commits on all 6 branches
holds placeholders (`APP_SECRET=""`, `SUPABASE_URL=""`).
Pickaxe searches of the full history for `eyJ...`, `AIza...`, `sk-...` and
populated `SUPABASE_SERVICE_ROLE_KEY=` / `JWT_SECRET=` /
`TOYYIBPAY_USER_SECRET_KEY=` assignments returned nothing real.

Either name the specific commit this item was written about - so it can be
purged with `git-filter-repo` before anyone treats the public repo as sensitive
- or delete this section. Do not ship a checklist item nobody can act on.

Categories originally listed, kept for reference:

- WhatsApp/Meta access tokens
- Supabase service-role key
- JWT secret
- ToyyibPay user secret key
- OpenRouter API key
- SMTP credentials
- Telegram bot tokens

### Database Migrations

Historical billing baseline (003 through 019). Review the [current CHIP database rollout](CHIP_PAYMENT_GATEWAY.md#database-rollout) for additional requirements, including unapplied proposal 059, before changing the approved target.
Migration 019 (`data/019_set_trial_ai_credit.sql`) initialises a trial AI-credit
allowance for new Free plan companies. Apply it before registering trial users.
Back up the database before applying migrations.

### Dependency Installation

Before deployment, install runtime dependencies:

```
pip install -r requirements.txt
```

For multi-worker production with shared rate limiting, also install Redis:

```
pip install redis>=5.0,<6.0
```

Development dependencies (testing only):

```
pip install pytest
```

### requirements.txt Contents

The file contains verified runtime packages:
- **flask**, **flask-cors**, **werkzeug** --- core web framework
- **PyJWT** --- authentication
- **supabase** --- database
- **flask-limiter** --- rate limiting
- **python-dotenv** --- environment configuration
- **requests** --- HTTP client
- **openai** --- AI provider SDK used by DeepSeek's OpenAI-compatible client and legacy/direct OpenAI helpers
- **google-genai** --- Gemini client used by embedding infrastructure for vector generation and semantic retrieval

Optional: **redis** --- required only for multi-worker Redis-backed rate limiting

## 2. Scheduled Jobs

| Job | Command | Schedule | Purpose |
|---|---|---|---|
| Lifecycle | `python -m app.jobs.process_subscription_lifecycle` | Every 10 minutes by default through the in-process billing scheduler | Persist Active -> past_due -> expired transitions |
| Reconciliation | `python -m app.jobs.reconcile_subscription_orders` | Every 15 minutes | Process paid incomplete orders |
| Notifications | `python -m app.jobs.generate_billing_notifications` | Daily | Generate renewal/credit alerts |

The billing scheduler currently runs inside the single production web process.
That singleton assumption depends on one Gunicorn worker and one Render instance.
If workers or instances are increased, revisit the scheduler architecture because
there is no cross-process leader lock. Subscription renewal correctness does not
depend on the scheduler timing: UI and checkout use `effective_status`; the
lifecycle job persists the raw database lifecycle state for reporting,
notifications, and audit clarity.

## 3. Monitoring

### Alert Thresholds

| Condition | Severity | Action |
|---|---|---|
| Callback HMAC verification failures | High | Investigate possible callback forgery |
| Paid orders stuck incomplete for >1 hour | High | Run reconciliation manually |
| Reconciliation failure rate >5% | High | Investigate and rerun |
| Negative AI-credit balance detected | Critical | Investigate and correct |
| Job failures (lifecycle, reconciliation, notifications) | Medium | Check logs and rerun |
| HTTP 429 rate-limit breaches | Low | Monitor; adjust limits if legitimate |
| HTTP 500 errors on billing endpoints | Medium | Investigate and fix |

## 4. Smoke Test Checklist

After an authorized test deployment, verify CHIP callbacks and stored `test_paid` completion without granting plans or credits.
The entitlement checks below apply only to a separately approved live payment verification; deployment is currently pending.

### A. New Subscription
- [ ] Create checkout via pricing page
- [ ] Complete payment via CHIP in the approved mode
- [ ] Callback received and verified
- [ ] Subscription activated with correct plan
- [ ] Included AI credit granted
- [ ] Payment history visible
- [ ] Printable receipt works

### B. Callback Replay
- [ ] Replay same callback
- [ ] No duplicate activation
- [ ] No duplicate included credit
- [ ] Idempotent success response

### C. Renewal
- [ ] Renewal status shows correct period end
- [ ] Pending renewal order prevents duplicate
- [ ] Payment and activation complete
- [ ] Old included credit expires; top-up preserved
- [ ] New included credit granted

### D. Grace and Expiry
- [ ] Active transitions to past_due at period end
- [ ] Grace warning appears
- [ ] Expired transition occurs after grace period
- [ ] Plan guards enforce restrictions

### E. Top-Up
- [ ] AI-credit top-up checkout
- [ ] Callback processes correctly
- [ ] Balance increases
- [ ] Duplicate callback idempotent

### F. Tenant Isolation
- [ ] Second company cannot access first company's data

### G. Exports and Reports
- [ ] CSV downloads with correct data
- [ ] Receipt prints correctly
- [ ] Report totals match source records

### H. Free Trial
- [ ] Free trial company can create first bot (DeepSeek V4 Flash enforced)
- [ ] Free trial cannot create second bot (chatbot-limit message)
- [ ] Free trial top-up section hidden (upgrade CTA shown instead)
- [ ] Free trial depleted AI credit blocks generation with upgrade message
- [ ] Free trial model settings page shows DeepSeek V4 Flash only (read-only)

### I. AI-Credit Notifications
- [ ] AI-credit low notification appears when balance drops below threshold
- [ ] AI-credit critical notification appears when balance drops below critical threshold
- [ ] AI-credit depleted notification appears when balance reaches zero
- [ ] Trial notifications use upgrade wording (not top-up wording)
- [ ] Paid notifications use top-up wording

### J. Security
- [ ] Security headers present on all responses (X-Content-Type-Options, X-Frame-Options, Referrer-Policy)
- [ ] Weak or missing JWT_SECRET blocks production startup (RuntimeError)
- [ ] Weak or missing SECRET_KEY blocks production startup (RuntimeError)
- [ ] Profile page JavaScript parses without syntax errors

## 5. Rollback Procedures

- **Database:** Restore from backup taken before migrations
- **Application:** Deploy previous working version
- **Payments:** Disable checkout endpoint if needed; paid orders remain safe
- **Callbacks:** Disable callback processing temporarily if needed
