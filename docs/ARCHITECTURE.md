# Architecture

## Overview

The system uses a layered Flask architecture with a static vanilla frontend and Supabase-backed persistence.

Typical request flow:

```text
Frontend page
    ↓
Flask route or blueprint
    ↓
Service layer
    ↓
Repository layer
    ↓
Supabase table or PostgreSQL RPC
```

Not every route requires a dedicated service, but business rules should remain outside repository modules.

## Application Startup

The Flask application is created through the application factory in `app/__init__.py`.

The startup flow includes:

1. Loading environment configuration
2. Creating the Flask application
3. Configuring templates and static assets from the `frontend/` directory
4. Applying CORS and logging configuration
5. Registering feature blueprints
6. Starting optional development or retry helpers from the runtime entry point

`run.py` is the primary runtime entry point.

## Backend Layers

### Routes

Route modules are located under `app/routes/`.

Responsibilities:

- Parse request input
- Apply authentication and role guards
- Resolve authenticated user and company context
- Perform request-level validation
- Call service functions
- Map exceptions to HTTP responses
- Return JSON responses

Routes must not trust a company identifier supplied by the frontend when the authenticated company context is available.

### Services

Service modules are located under `app/services/`.

Responsibilities:

- Implement business workflows
- Coordinate multiple repositories
- Enforce domain rules
- Call external providers
- Maintain idempotency and state transitions
- Format domain-level results

Examples include:

- AI routing
- RAG
- Billing enforcement
- AI-credit charging
- ToyyibPay checkout and callback processing
- Messaging-channel handling
- CRM lead automation
- Analytics and reports

### Repositories

Repository modules are located under `app/database/`.

Responsibilities:

- Query Supabase tables
- Call PostgreSQL RPC functions
- Apply company and resource scoping
- Return database records
- Avoid embedding presentation or route-specific behavior

The application uses a server-side Supabase client with privileged credentials. This makes repository scoping and route authorization security-critical.

## Frontend

The frontend is stored under `frontend/`.

It uses:

- HTML pages
- Inline and shared CSS
- Vanilla JavaScript
- Shared frontend helpers under `frontend/static/`

The frontend calls Flask APIs using authenticated requests and stores the application JWT in browser storage.

Important frontend areas include:

- Authentication
- Dashboard
- Profile and billing
- Team management
- Chatbots
- Knowledge management
- Conversations
- CRM
- Integrations
- Model settings
- Reports and insights

## Authentication

The application uses application-issued JWTs.

The authentication flow generally works as follows:

1. User submits login or registration data.
2. The backend validates the account.
3. The backend issues a JWT containing user, company, and role context.
4. The frontend stores the token.
5. Authenticated requests send the token in the `Authorization` header.
6. `token_required` validates the token and loads authenticated context into Flask `g`.
7. Role guards and resource-access checks enforce permissions.

Logout is implemented by removing the token from browser storage. There is no documented server-side token revocation or denylist.

## Tenant Isolation

Tenant isolation is based on company context.

Key rules:

- Use `g.company_id` or equivalent authenticated context.
- Do not trust a frontend-supplied company ID.
- Scope company-owned records by `company_id`.
- Verify chatbot ownership before chatbot-scoped actions.
- Restrict privileged team and configuration operations by role.
- Treat all repository functions using privileged Supabase access as security-sensitive.

Repository evidence supports application-level tenant scoping. The live Supabase RLS state is not confirmed by the repository and must be checked separately.

## Data Storage

Supabase PostgreSQL is used for:

- Companies and users
- Chatbots and configuration
- Knowledge files and chunks
- Conversations and messages
- CRM leads
- Channel configurations
- Processed-message deduplication
- Subscription and usage data
- AI-credit balances and transactions
- AI-credit top-up orders
- Agent actions
- Password reset and invitation records

Certain balance and payment operations use PostgreSQL RPC functions to provide atomic state changes.

## AI and RAG Flow

A typical chatbot response flow is:

1. Receive a message from a test interface or messaging webhook.
2. Resolve company, chatbot, and conversation context.
3. Deduplicate the inbound message when applicable.
4. Load chatbot configuration and active knowledge settings.
5. Retrieve relevant knowledge chunks.
6. Build model context.
7. Route the request to the configured model/provider.
8. Record usage.
9. Apply AI-credit charging when enabled.
10. Save the response.
11. Send the response back through the originating channel.

## Messaging Integration Flow

Each channel integration has:

- Connection configuration
- Credential persistence
- A webhook endpoint
- Incoming message validation
- Deduplication
- Chatbot and conversation resolution
- AI response generation
- Outgoing message delivery
- Failure handling

Wasender includes a retry worker for failed delivery processing.

## Billing Architecture

Billing contains two related systems:

### Subscription enforcement

Subscription plans define limits and feature access. Guards enforce limits such as chatbot, team, channel, knowledge, or feature availability.

### AI credit

AI-credit balances represent monetary value in micro-MYR.

The flow includes:

- Initializing a company credit period
- Recording provider usage
- Calculating customer charge
- Deducting included or top-up balance
- Recording transactions
- Purchasing top-up credit through ToyyibPay

Payment and credit mutations use repository functions and PostgreSQL RPCs to reduce duplicate or partial processing.

## Error Handling

Routes generally return JSON with a status, message, and optional data.

Expected mappings include:

- Validation errors → 400
- Authentication failures → 401
- Permission failures → 403
- Missing resources → 404
- Billing limit failures → 403
- Unexpected errors → 500

Production responses should avoid exposing raw exception details.

## Background and Runtime Helpers

The repository contains optional runtime helpers such as:

- Wasender retry processing
- Development tunnel support

Development-only utilities must be disabled in production unless explicitly required.

## Architectural Risks

- Privileged Supabase access makes application-layer tenant checks critical.
- Live RLS configuration is not documented in the repository.
- Database RPC definitions are not fully version-controlled.
- Browser-stored JWTs require strong XSS prevention.
- External integration credentials are stored server-side and require secure secret handling.
- Some modules have limited automated coverage.
