# AI Chatbot SaaS Platform

Multi-tenant AI chatbot management platform built with Python Flask and Supabase PostgreSQL.
Organizations can create chatbots, configure AI models, connect knowledge sources, integrate
messaging channels, manage conversations and CRM leads, and control usage through subscription
limits and AI-credit billing with ToyyibPay top-ups.

## Features

- **Authentication & Teams** — JWT login, OTP flows, Google OAuth, password reset; company-scoped teams with owner/admin/member roles; email invitations
- **Chatbot Management** — Create and configure chatbots with custom prompts, data extraction, and auto-generated menus
- **Channel Integrations** — WhatsApp Cloud API (Meta), Telegram, Wasender (WhatsApp API); separate credential storage per channel
- **Conversations & CRM** — Multi-channel inbox; CRM lead tracking with status, assignment, and follow-up
- **Knowledge Management** — PDF upload, website scraping, batch ingestion; RAG retrieval; knowledge graph exploration
- **AI Routing** — OpenRouter and DeepSeek providers; model-level access policies per subscription plan; trial-to-paid gating
- **Subscription Billing** — Plan-based limits (chatbots, team, channels, knowledge, AI); ToyyibPay checkout; callback verification; activation with included AI-credit allocation
- **AI Credit** — Included credit (per subscription period) and top-up credit (separate); usage-based consumption; idempotent allocation; expiry and carry-forward rules
- **Renewal & Grace Period** — Manual ToyyibPay renewal; configurable grace period after expiry; idempotent expiry processing job
- **Notifications** — In-app billing notifications: renewal reminders, grace alerts, payment confirmation, AI-credit low/critical/depleted alerts
- **Reporting** — Monthly billing summaries, AI-credit usage trends, plan-usage against limits; CSV exports of billing, credit transactions, and reports
- **Production Hardening** — Rate limiting (flask-limiter), CORS validation, isolated development billing routes, invite URL configuration

## Technology Stack

- **Backend:** Python 3.12, Flask 3.x
- **Database:** Supabase PostgreSQL with row-level security (via Python client)
- **Frontend:** Vanilla HTML, CSS, JavaScript (no framework); served by Flask
- **Authentication:** Application-managed JWT (PyJWT)
- **Payment Gateway:** ToyyibPay (manual checkout; no automatic recurring billing)
- **Rate Limiting:** Flask-Limiter 4.x (in-memory dev; Redis recommended for production)
- **AI Providers:** OpenRouter, DeepSeek
- **Tests:** pytest (~1,084 tests)

## Quick Start

1. Clone the repository and set up a Python virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in required values.
4. Run Supabase migration scripts from `data/` in sequential order (003–014).
5. Start the application: `python run.py`
6. Open `http://localhost:8000` in a browser.

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

### ToyyibPay
| Variable | Required | Description |
|---|---|---|
| `TOYYIBPAY_CATEGORY_CODE` | Yes | ToyyibPay bill category |
| `TOYYIBPAY_USER_SECRET_KEY` | Yes | Payment gateway secret |
| `TOYYIBPAY_ENV` | Yes | `sandbox` or `production` |

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
| `ENABLE_DEV_BILLING_ROUTES` | `false` | Enable development billing routes (never in production) |

### Email (optional)
| Variable | Description |
|---|---|
| `SMTP_SERVER` | SMTP host |
| `SMTP_PORT` | SMTP port |
| `SMTP_USERNAME` | SMTP username |
| `SMTP_PASSWORD` | SMTP password |
| `SMTP_SENDER` | From address |

## Important Notes

- **Automatic recurring billing is NOT supported.** ToyyibPay requires manual checkout for each renewal.
- **Rate limiting uses in-memory storage by default.** Configure `RATELIMIT_STORAGE_URI=redis://...` for production.
- **Billing data is company-scoped**, not bot-scoped. All payment history, credit, and reports belong to the company.
- **Development billing routes** (enabled via `ENABLE_DEV_BILLING_ROUTES`) simulate payment callbacks without real payments. Never enable in production.
- **Migrations 003–014** must be applied in order to the Supabase project before billing features work.

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
  utils/               # JWT, ngrok, Telegram, WhatsApp utilities
data/                  # SQL migrations 003–014
docs/                  # Documentation and runbooks
frontend/              # HTML, JS, CSS (served by Flask)
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
