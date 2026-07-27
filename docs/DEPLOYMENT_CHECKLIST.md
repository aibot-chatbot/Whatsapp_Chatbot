# Deployment Checklist

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
| `RATELIMIT_STORAGE_URI` | **Required (prod)** | Redis URI (`redis://localhost:6379/0`). Memory backend (`memory://`) safe only for single-process dev. Use Redis for multi-worker production. |
| `RATELIMIT_ENABLED` | `true` | Enable rate limiting in production |
| `TOYYIBPAY_ENV` | `production` | Switch from sandbox to production |
| `TOYYIBPAY_CATEGORY_CODE` | Required | Production ToyyibPay category |
| `TOYYIBPAY_USER_SECRET_KEY` | Required | Production ToyyibPay secret |
| `TOYYIBPAY_CALLBACK_URL` | Required | Public HTTPS URL where ToyyibPay sends payment callbacks (`/api/billing/toyyibpay/callback`). Must be a deployed production URL. |
| `TOYYIBPAY_RETURN_URL` | Required | URL where customers are redirected after payment. Must be a production URL. |
| `OPENROUTER_API_KEY` | Required | AI provider key |
| `OPENAI_API_KEY` | Required | OpenAI API key (used for guide/RAG) |
| `GEMINI_API_KEY` | Required | Gemini API key (used for RAG and Gemini provider) |
| `DEEPSEEK_API_KEY` | Required | DeepSeek AI provider key |
| `PUBLIC_BASE_URL` | Required | Public backend URL for Meta WhatsApp webhook callbacks |
| `AI_CREDIT_ENFORCEMENT_ENABLED` | `true` | Master switch for AI-credit charging. Requires `AI_RETAIL_MARKUP_BPS` and `AI_USD_TO_MYR_RATE_MICRO_MYR_PER_USD`. |
| `AI_RETAIL_MARKUP_BPS` | Required (enforcement) | Retail markup in basis points (100 bps = 1%). Required when `AI_CREDIT_ENFORCEMENT_ENABLED` is true. |
| `AI_USD_TO_MYR_RATE_MICRO_MYR_PER_USD` | Required (enforcement) | USD to MYR exchange rate in micro-MYR per USD. Example: 4500000 = RM 4.50 per USD. Required when enforcement is enabled. |
| `DEEPSEEK_V4_FLASH_CACHE_HIT_INPUT_PRICE_MICRO_USD_PER_MILLION_TOKENS` | Required (enforcement) | DeepSeek cache-hit pricing (micro-USD per 1M tokens). Checked at first AI request; startup succeeds without it. |
| `DEEPSEEK_V4_FLASH_CACHE_MISS_INPUT_PRICE_MICRO_USD_PER_MILLION_TOKENS` | Required (enforcement) | DeepSeek cache-miss pricing (micro-USD per 1M tokens). Checked at first AI request. |
| `DEEPSEEK_V4_FLASH_OUTPUT_PRICE_MICRO_USD_PER_MILLION_TOKENS` | Required (enforcement) | DeepSeek output pricing (micro-USD per 1M tokens). Checked at first AI request. |
| `AI_CREDIT_LOW_THRESHOLD_MICRO_MYR` | `5000000` | RM5.00 (RM1 = 1,000,000 micro-MYR) |
| `AI_CREDIT_CRITICAL_THRESHOLD_MICRO_MYR` | `1000000` | RM1.00 |
| `BILLING_GRACE_PERIOD_DAYS` | `3` | Grace period after expiry |
| `ENABLE_DEV_BILLING_ROUTES` | Must be `false` | Production rejects this flag with RuntimeError |

### Application Server

For local development, use the Flask dev server:

```
python run.py
```

For production, use a production-grade WSGI server. The repository includes a
`wsgi.py` entry point compatible with Gunicorn and Waitress:

```
# Gunicorn (Linux/macOS)
gunicorn wsgi:app --bind 0.0.0.0:8000 --workers 4

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
- [ ] `ENABLE_DEV_BILLING_ROUTES` is not set (or set to false)
- [ ] `CORS_ORIGINS` contains only production domains (no wildcard)
- [ ] `FRONTEND_URL` matches the production frontend
- [ ] Rate limiting is enabled with Redis backend
- [ ] JWT secret is strong and unique
- [ ] SECRET_KEY (Flask session) is strong and unique
- [ ] Weak or missing JWT_SECRET or SECRET_KEY blocks production startup (RuntimeError)
- [ ] OTP values are not logged (confirmed by code audit)
- [ ] ToyyibPay callback signature verification is enabled

### Exposed Credentials Requiring Rotation

The following credential categories were found in Git history and should be rotated:

- WhatsApp/Meta access tokens
- Supabase service-role key
- JWT secret
- ToyyibPay user secret key
- OpenRouter API key
- SMTP credentials
- Telegram bot tokens

### Database Migrations

Apply in order (003 through 019). Each migration is safe to run sequentially on the Supabase project.
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
- **openai** --- AI provider SDK (DeepSeek via OpenAI-compatible API)
- **google-genai** --- Gemini API client for RAG

Optional: **redis** --- required only for multi-worker Redis-backed rate limiting

## 2. Scheduled Jobs

| Job | Command | Schedule | Purpose |
|---|---|---|---|
| Lifecycle | `python -m app.jobs.process_subscription_lifecycle` | Daily (02:00 UTC) | Active -> past_due -> expired transitions |
| Reconciliation | `python -m app.jobs.reconcile_subscription_orders` | Hourly | Process paid incomplete orders |
| Notifications | `python -m app.jobs.generate_billing_notifications` | Daily before lifecycle | Generate renewal/credit alerts |

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

Perform these tests after deployment on a staging/production environment:

### A. New Subscription
- [ ] Create checkout via pricing page
- [ ] Complete payment via ToyyibPay
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
