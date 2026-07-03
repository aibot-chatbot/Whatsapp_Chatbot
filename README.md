# AI Chatbot SaaS Platform

Multi-tenant AI chatbot management platform built with Flask and Supabase.
Organizations can create chatbots, configure prompts and AI models, connect knowledge sources, integrate messaging channels, manage conversations and CRM leads, monitor analytics, and control usage through subscription limits and AI-credit billing with ToyyibPay top-ups.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, Flask |
| Database | Supabase (PostgreSQL) |
| Frontend | HTML, CSS, vanilla JavaScript, React (new_linkdocs.html) |
| AI / RAG | Gemini embeddings, configurable provider routing (OpenRouter, DeepSeek) |
| Payments | ToyyibPay |
| Channels | Telegram, WasenderAPI, Meta WhatsApp Cloud API |

## Quick Start

```
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy `.env.txt` to `.env` and fill in your credentials. See `.env.txt` for the full list of required environment variables.

```
python run.py
```

Open http://localhost:8000/login.html in your browser.

## Running Tests

```
python -m pytest tests -q
```

Tests use mocks for all external services. No live API calls are made.

## Project Structure

| Path | Purpose |
|------|---------|
| app/ | Flask application (routes, services, repositories, utils) |
| frontend/ | Web UI pages and static assets |
| tests/ | Automated test suite |
| data/ | SQL migrations and PDF training files |
| scripts/ | Utility and smoke-test scripts |
| docs/ | Project documentation |

## Documentation

Detailed documentation is maintained under docs/:

| Document | Description |
|----------|-------------|
| AGENTS.md | Agent/LLM instructions and safety boundaries |
| CODING_GUIDELINES.md | Coding behavior and review guidelines |
| docs/PROJECT_OVERVIEW.md | Full project description and user roles |
| docs/ARCHITECTURE.md | System architecture and request flow |
| docs/FEATURE_STATUS.md | Feature-by-feature implementation status |
| docs/DEVELOPMENT_ROADMAP.md | Phase-based development plan |
| docs/TESTING_GUIDE.md | Test strategy, setup, and coverage targets |
| docs/DATABASE_AND_RPC.md | Database schema, RPCs, and tenant scoping |
| docs/SECURITY_AND_TENANCY.md | Security model and tenant isolation |
| docs/INTEGRATIONS.md | External integration flows and verification |
| docs/BILLING_AND_AI_CREDIT.md | Subscription, AI-credit, and ToyyibPay billing |
| docs/DEPLOYMENT_CHECKLIST.md | Production deployment checklist |

## Key Environment Variables

See `.env.txt` for the complete list. Important groups:

- **Supabase**: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
- **JWT**: JWT_SECRET
- **AI Providers**: OPENROUTER_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY
- **ToyyibPay**: TOYYIBPAY_ENV, TOYYIBPAY_USER_SECRET_KEY, TOYYIBPAY_CATEGORY_CODE, TOYYIBPAY_CALLBACK_URL, TOYYIBPAY_RETURN_URL
- **AI Credit**: AI_CREDIT_ENFORCEMENT_ENABLED, AI_RETAIL_MARKUP_BPS, AI_USD_TO_MYR_RATE_MICRO_MYR_PER_USD
- **Email**: SMTP_SENDER_EMAIL, SMTP_APP_PASSWORD
- **Messaging**: PUBLIC_BASE_URL, WHATSAPP_META_APP_ID, WHATSAPP_META_APP_SECRET, WASENDER_BASE_URL

## License

See LICENCE.txt.