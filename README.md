# Omnexa SaaS Platform

Payment status (2026-09-15): CHIP replaces ToyyibPay and HitPay in the current code.
Local tests and a provider sandbox payment are verified; deployment is pending.
Use the [CHIP payment guide](docs/CHIP_PAYMENT_GATEWAY.md) for current routes, configuration, and rollout.

Multi-tenant AI chatbot management platform built with Python Flask and Supabase PostgreSQL.
Organizations can create chatbots, configure AI models, connect knowledge sources, integrate
messaging channels, manage conversations and CRM leads, and control usage through subscription
limits and AI-credit billing with CHIP top-ups.

## Features

- **Authentication & Teams** — JWT login, OTP flows, Google OAuth, password reset; company-scoped teams with owner/admin/member roles; email invitations
- **Chatbot Management** — Create and configure chatbots with custom prompts, data extraction, and auto-generated menus
- **Channel Integrations** — WhatsApp Cloud API (Meta), Telegram, optional WhatsApp linked devices; separate credential storage per channel
- **Website Chat Widget** — Embeddable chat bubble installed with one `<script>` tag, inline iframe embed, and a public share link; per-bot branding (colours, avatar, welcome message, suggested questions), in-chat lead capture, domain allowlist, and a per-session message cap
- **Conversations & CRM** — Multi-channel inbox; CRM lead tracking with status, assignment, and follow-up
- **Knowledge Management** — PDF upload, website scraping, batch ingestion; RAG retrieval; knowledge graph exploration
- **AI Routing** — OpenRouter and DeepSeek providers; model-level access policies per subscription plan; trial-to-paid gating
- **Subscription Billing** — Plan-based limits (chatbots, team, channels, knowledge, AI); CHIP checkout; callback verification; activation with included AI-credit allocation
- **AI Credit** — Included credit (per subscription period) and top-up credit (separate); usage-based consumption; idempotent allocation; expiry and carry-forward rules
- **Renewal & Grace Period** — Manual CHIP renewal; configurable grace period after expiry; idempotent expiry processing job
- **Notifications** — In-app billing notifications: renewal reminders, grace alerts, payment confirmation, AI-credit low/critical/depleted alerts
- **Reporting** — Monthly billing summaries, AI-credit usage trends, plan-usage against limits; CSV exports of billing, credit transactions, and reports
- **Production Hardening** — Rate limiting (flask-limiter), CORS validation, isolated development billing routes, invite URL configuration

## Technology Stack

- **Backend:** Python 3.12, Flask 3.x
- **Database:** Supabase PostgreSQL with row-level security (via Python client)
- **Frontend:** Vanilla HTML, CSS, JavaScript (no framework); served by Flask
- **Authentication:** Application-managed JWT (PyJWT)
- **Payment Gateway:** CHIP Collect (manual checkout; no automatic recurring billing)
- **Rate Limiting:** Flask-Limiter 4.x (in-memory dev; Redis recommended for production)
- **AI Providers:** OpenRouter, DeepSeek
- **Tests:** pytest (~1,084 tests)

## Quick Start

1. Clone the repository and set up a Python virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in required values.
4. Review the [current database rollout](docs/CHIP_PAYMENT_GATEWAY.md#database-rollout) before applying migrations; the earlier baseline was (003–014).
5. Start the application: `python run.py`
6. Open `http://localhost:8000` in a browser.

Local startup binds to localhost and does not start a public tunnel.
External callbacks require a separately deployed public HTTPS server.

## Key Environment Variables

### Core
| Variable | Required | Description |
|---|---|---|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Service-role key (server-side only) |
| `SECRET_KEY` | Yes | Flask secret key |
| `JWT_SECRET` | Yes | JWT signing secret |
| `FRONTEND_URL` | Yes | Frontend base URL (for invite links, CORS) |
| `CORS_ORIGINS` | Yes | Comma-separated allowed CORS origins |

### CHIP Collect

Use the [required CHIP configuration](docs/CHIP_PAYMENT_GATEWAY.md#required-configuration).
Start with `CHIP_ENV=test`; test payments do not grant subscriptions or AI credit.

### Rate Limiting
| Variable | Default | Description |
|---|---|---|
| `RATELIMIT_ENABLED` | `true` (prod), `false` (dev) | Enable/disable rate limiting |
| `RATELIMIT_STORAGE_URI` | `memory://` | Redis URI for production (`redis://...`) |

### AI Providers
| Variable | Description |
|---|---|
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `DEEPSEEK_API_KEY` | DeepSeek API key |

### Notification Thresholds
| Variable | Default | Description |
|---|---|---|
| `AI_CREDIT_LOW_THRESHOLD_MICRO_MYR` | `500000` (RM5) | Low-credit alert threshold |
| `AI_CREDIT_CRITICAL_THRESHOLD_MICRO_MYR` | `100000` (RM1) | Critical-credit alert threshold |

### Billing
| Variable | Default | Description |
|---|---|---|
| `BILLING_GRACE_PERIOD_DAYS` | `3` | Days after expiry before subscription is fully expired |
| `ENABLE_DEV_BILLING_ROUTES` | `false` | Legacy flag; payment-completion endpoints return HTTP 410 |

### Email (optional)
| Variable | Description |
|---|---|
| `SMTP_SERVER` | SMTP host |
| `SMTP_PORT` | SMTP port |
| `SMTP_USERNAME` | SMTP username |
| `SMTP_PASSWORD` | SMTP password |
| `SMTP_SENDER` | From address |

## Important Notes

- **Automatic recurring billing is NOT supported.** CHIP purchases in this integration use manual checkout for each renewal.
- **Rate limiting uses in-memory storage by default.** Configure `RATELIMIT_STORAGE_URI=redis://...` for production.
- **Billing data is company-scoped**, not bot-scoped. All payment history, credit, and reports belong to the company.
- **Development payment-completion routes are retired** and return HTTP 410. Use the CHIP test flow.
- **Migrations 003–014** describe an earlier billing baseline. CHIP additionally requires the [database rollout](docs/CHIP_PAYMENT_GATEWAY.md#database-rollout), including unapplied proposal 059.
- **The website widget requires migration `029_web_widget_support.sql`.** Until it is applied, the Web Widget card in Integrations will fail to load. Configure and enable the widget per chatbot under **Integrations -> Web Widget**; the embed snippet only works once the widget is enabled.
- **Widget embed URLs use `PUBLIC_BASE_URL`** when set, otherwise the request host. Set `PUBLIC_BASE_URL` to your public HTTPS origin so generated snippets are correct.

## Running Tests

```bash
python -m pytest tests -q
```

## Project Structure

```
app/
  __init__.py          # Application factory, blueprint registration
  config.py            # Configuration loading from environment
  rate_limit.py        # Flask-Limiter integration
  routes/              # Flask blueprints (26 registered)
  services/            # Business logic
  database/            # Supabase repository layer
  jobs/                # Background job entry points
  decorators/          # Auth and security decorators
  utils/               # JWT, Telegram, WhatsApp utilities
data/                  # SQL migrations 003–029
docs/                  # Documentation and runbooks
frontend/              # HTML, JS, CSS (served by Flask)
  widget.js            # Embeddable widget loader (public, cross-origin)
  widget-chat.html     # Widget chat UI (iframe + share link)
scripts/               # CLI tools and smoke tests
tests/                 # pytest test suite (35 files, ~1,084 tests)
```

## Documentation

Further documentation is available in `docs/`:

- `PROJECT_OVERVIEW.md` — High-level system description
- `ARCHITECTURE.md` — Route-service-repository pattern
- `BILLING_AND_AI_CREDIT.md` — Subscription and AI-credit system
- `SECURITY_AND_TENANCY.md` — Authentication, JWT, tenant isolation
- `DEPLOYMENT_CHECKLIST.md` — Production deployment steps
- `DEVELOPMENT_ROADMAP.md` — Feature roadmap
- `FEATURE_STATUS.md` — Phase-by-phase completion status

## License

See LICENCE.txt
