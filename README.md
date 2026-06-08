# AI Chatbot SaaS Platform

This project is a Flask + Supabase AI chatbot platform for companies that want to create, configure, and connect customer-service chatbots across messaging channels.

The system supports multiple companies and multiple chatbots. Each chatbot can have its own AI profile, model provider, knowledge sources, channel connections, conversation history, analytics, and readiness status.

## Main Features

- User authentication and company-scoped access control
- Multiple chatbot support per company
- Dashboard analytics and Bot Health / Readiness Summary
- Conversation history and message status tracking
- AI provider and model selection
- RAG knowledge system
- PDF as the active primary knowledge source
- Website/URL sources as supporting knowledge
- Enable/disable controls for supporting website sources
- Telegram integration
- WasenderAPI integration with retry handling
- WhatsApp Cloud API backend groundwork
- AI report generation from recent conversation logs
- Frontend pages served through the Flask backend

## Tech Stack

- Backend: Flask
- Database: Supabase
- Frontend: HTML, CSS, JavaScript, React-in-HTML pages where used
- AI/RAG: Gemini embeddings plus configurable AI provider routing
- Channels: Telegram, WasenderAPI, WhatsApp Cloud API
- Local development tunnel: ngrok when needed for webhooks

## Project Structure

```text
app/
  database/          Supabase repository functions
  routes/            Flask API route blueprints
  services/          Business logic, AI, RAG, reports, retries
  utils/             Channel helpers and shared utilities
  views.py           Frontend/static serving and legacy upload route
frontend/            Main web UI pages
data/                Local PDF processing folder for development/current flow
docs/                Additional documentation
run.py               Local Flask startup entrypoint
requirements.txt     Python dependencies
```

## Environment Variables

Create a local `.env` file for development. Do not commit real secrets.

Common required variables:

```env
SUPABASE_URL=<your-supabase-url>
SUPABASE_KEY=<your-supabase-key>
JWT_SECRET=<strong-random-secret>
CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

AI provider variables depend on which providers you enable:

```env
GEMINI_API_KEY=<your-gemini-key>
OPENROUTER_API_KEY=<your-openrouter-key>
DEEPSEEK_API_KEY=<your-deepseek-key>
GROQ_API_KEY=<your-groq-key>
```

Channel/integration variables may include:

```env
PUBLIC_BASE_URL=<your-public-backend-url>
NGROK_ENABLED=false
NGROK_DOMAIN=<your-ngrok-domain>
WASENDER_BASE_URL=<wasender-api-base-url>
WHATSAPP_META_APP_ID=<meta-app-id>
WHATSAPP_META_APP_SECRET=<meta-app-secret>
WHATSAPP_GRAPH_API_VERSION=v20.0
WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID=<meta-embedded-signup-config-id>
```

Local startup controls:

```env
FLASK_HOST=0.0.0.0
FLASK_PORT=8000
FLASK_DEBUG=false
WASENDER_RETRY_WORKER_ENABLED=true
```

## Local Setup

1. Create and activate a Python virtual environment.

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Create `.env` with the required placeholders above, replacing values locally.

4. Make sure Supabase tables, indexes, and RPC functions used by the app have been created.

5. Start the Flask app.

```bash
python run.py
```

6. Open the frontend through Flask.

```text
http://localhost:8000/login.html
```

For Telegram, WasenderAPI, or WhatsApp webhook testing, expose the Flask backend with a stable public HTTPS URL such as ngrok and set `PUBLIC_BASE_URL` accordingly.

## Supabase / Database Notes

The app uses Supabase for users, companies, chatbots, profiles, knowledge metadata, knowledge chunks, conversations, messages, channel connections, analytics, and password reset state.

Important tables include:

- `companies`
- `users`
- `chatbots`
- `bot_configs`
- `knowledge_files`
- `knowledge_chunks`
- `conversations`
- `messages`
- `telegram_channels`
- `wasender_channels`
- `whatsapp_channels`
- `password_reset_otps`

The knowledge system expects `knowledge_files.is_enabled` for supporting website enable/disable behavior.

Tenant isolation is important. Backend routes and repository calls should always scope user-facing data by `chatbot_id` and/or `company_id` as appropriate.

## Knowledge System

The current product rule is:

- PDF is the primary/main active knowledge source.
- Website/URL sources are supporting knowledge only.
- Multiple supporting websites are allowed.
- Supporting websites can be enabled or disabled.
- RAG uses the active primary PDF first, then enabled supporting website chunks when the PDF is missing, incomplete, or not detailed enough.

PDF behavior:

- Uploaded PDFs are saved locally in `data/` for processing.
- PDF metadata is saved in `knowledge_files` with `file_type = "pdf"`.
- PDF chunks are saved in `knowledge_chunks`.
- `knowledge_files.is_active` applies to PDF primary selection.

Website behavior:

- Website sources are saved in `knowledge_files` with `file_type = "url"`.
- Website chunks are saved in `knowledge_chunks`.
- Website sources do not replace the active PDF.
- Website sources do not update `draft_pdf_file_name` or `draft_pdf_path`.
- Website participation in RAG is controlled by `is_enabled`.

Long-term production storage should move original files from local `data/` to Supabase Storage or S3.

## Channel Integrations

### Telegram

Telegram channels are connected per chatbot. The backend stores channel metadata, webhook URL, and webhook secret. Telegram webhook handling should remain inside Flask so messages, conversations, AI replies, and delivery tracking stay tenant-scoped.

### WasenderAPI

WasenderAPI channels are connected per chatbot. The system includes send handling, message persistence, delivery status, and retry logic for failed sends.

### WhatsApp Cloud API

WhatsApp Cloud API backend groundwork exists, including per-channel storage for Cloud API credentials and Embedded Signup completion/config routes.

Current status: WhatsApp Cloud API / Meta Embedded Signup is paused or limited while Meta business portfolio / Tech Provider review is pending. Do not rely on global `PHONE_NUMBER_ID` or global access tokens for multi-user production sending.

## AI Provider / Model Selection

The system supports configurable AI provider and model selection per bot/profile flow. Provider files and routing logic live under `app/services/`.

Current provider-related areas include:

- AI router
- RAG prompt building
- DeepSeek/OpenRouter/Gemini-related service logic
- Model catalog/settings routes

Customer-service safety rules are enforced in the prompt path. The bot should avoid inventing company-specific facts such as prices, dates, policies, contacts, availability, or registration steps when the information is not in provided knowledge.

## Dashboard and Reports

The dashboard includes:

- Usage analytics
- Recent conversation history
- Bot Health / Readiness Summary
- Active profile and active primary knowledge status
- Channel health
- Delivery health
- AI report generation

AI reports are generated from recent conversation logs and should remain scoped by `chatbot_id`.

## Development Notes

- Never commit real API keys, access tokens, webhook secrets, Supabase keys, JWT secrets, WABA IDs, phone number IDs, or passwords.
- Keep `.env` local.
- Keep tenant scoping strict. Protected routes should require explicit `chatbot_id` where data is bot-specific.
- Use `verify_chatbot_access(chatbot_id)` for authenticated bot-scoped routes.
- Do not default protected SaaS routes to `chatbot_id = 1`.
- The `data/` folder is currently used for PDF processing, but it should not be used for long-term production customer file storage.
- Channel webhooks should be processed by Flask, not external automation tools, so message storage and tenant isolation remain consistent.
- If optional automation is added later, treat it as outbound event delivery only.

## Current Limitations / Future Improvements

- Meta Embedded Signup / WhatsApp Cloud API production onboarding depends on Meta business portfolio or Tech Provider review.
- Local `data/` PDF storage should be migrated to Supabase Storage or S3.
- Website scraping currently runs through the Flask request flow and may need a background worker for large sites.
- Optional n8n integration could be added as an automation layer for alerts, reports, CRM sync, lead forwarding, and admin notifications.
- More production hardening is still recommended: monitoring, backups, billing/subscriptions, role management, and formal privacy/compliance pages.

## Optional n8n Automation Layer

n8n can be useful as an optional outbound automation layer, not as a backend replacement.

Safe use cases:

- Failed message alerts
- Weekly report delivery
- Lead summary forwarding
- CRM or Google Sheets sync
- Admin notifications

Unsafe use cases:

- Replacing Flask channel webhooks
- Storing duplicate full conversation history
- Handling live AI replies
- Receiving API keys or channel tokens

Flask and Supabase should remain the source of truth.
