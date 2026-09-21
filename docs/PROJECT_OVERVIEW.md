# Project Overview

Payment status (2026-09-15): CHIP replaces ToyyibPay and HitPay in the current code.
Local tests and a provider sandbox payment are verified; deployment is pending.
Use the [CHIP payment guide](CHIP_PAYMENT_GATEWAY.md) for current routes, configuration, and rollout.

## Purpose

This project is a multi-tenant platform for creating, configuring, operating, and monitoring AI chatbots across messaging channels.

Organizations can create chatbots, configure prompts and models, connect knowledge sources, integrate messaging channels, review conversations, manage leads, monitor analytics, and control usage through subscription and AI-credit rules.

## Main Users

### Company owners and administrators

They can:

- Manage company profile information
- Create and manage chatbots
- Configure chatbot behavior and AI models
- Upload and manage knowledge sources
- Connect communication channels
- Review conversations and CRM leads
- Manage team members and roles
- Review subscription limits and AI-credit balances
- Purchase additional AI credit through CHIP (deployment pending)

### Team members

Depending on their role, they can:

- Access company-scoped chatbots
- Review conversations
- Manage CRM leads
- View analytics
- Resolve escalations
- Use operational chatbot tools

### External customers

They interact with deployed chatbots through supported channels such as Telegram, Wasender-backed WhatsApp, and Meta WhatsApp Cloud API.

## Core Product Areas

### Authentication and account management

The application provides registration, login, profile management, password reset, email verification-related flows, and team invitation workflows.

Authentication is handled by the Flask application using JWTs. The authenticated token carries user, company, and role context used by backend guards.

### Company and team management

Each user belongs to a company. Company owners and administrators can invite members, manage roles, and deactivate members.

### Chatbot management

Users can create, view, edit, and delete chatbots. Chatbot settings include prompt behavior, profile information, model/provider selection, and deployed configuration.

### Knowledge and RAG

Chatbots can use uploaded files and discovered website content as knowledge sources. The retrieval pipeline stores and retrieves chunks for model context.

### AI routing

The platform supports multiple AI providers and models through a central routing layer. Model availability is exposed to the frontend through a catalog and API.

### Messaging integrations

The platform contains integration flows for:

- Telegram
- WasenderAPI
- Meta WhatsApp Cloud API

Integration behavior includes connection management, webhook processing, message deduplication, and outgoing reply handling.

### Conversations and CRM

The conversation workspace provides conversation history, message viewing, search, deep-linking, transcript copy, transcript download, and direct navigation from CRM records.

CRM functionality includes lead status, priority, assignment, follow-up information, filtering, and notes.

### Analytics and operational visibility

The dashboard and analytics modules provide message metrics, workflow status, health summaries, reports, and agent insights.

### Billing and AI credit

The platform applies subscription limits and tracks AI-credit balances. AI usage can deduct monetary-value credit, stored internally in micro-MYR.

The current backend supports additional credit purchases through CHIP; deployment remains pending. The backend manages checkout creation, callback processing, order status, idempotency, and credit granting.

## Current Maturity

The platform is in late-stage development.

Major product areas are implemented, but verification maturity differs across modules:

- Billing has historical automated coverage; current CHIP verification is recorded in the [payment guide](CHIP_PAYMENT_GATEWAY.md#verification-evidence).
- Several core product modules are implemented but need broader automated regression coverage.
- External integrations require controlled environment verification.
- Database RPC definitions and live Supabase security settings need stronger repository documentation.
- Deployment readiness still requires security, configuration, and operational checks.

## System Boundaries

The repository contains the application code and some SQL scripts, but certain operational components may live outside the repository:

- Live Supabase schema and row-level security configuration
- Deployed PostgreSQL RPC definitions
- External provider configuration
- Meta business and app review state
- CHIP merchant account and test/live configuration
- Messaging platform webhook configuration

These must be verified against the live environment before production release.

## Documentation Maintenance

This documentation describes the complete team repository.

Update it when:

- A major feature is added, removed, or replaced
- An integration flow changes
- Billing or database behavior changes
- A development phase is completed
- Verification status changes
- Deployment requirements change
