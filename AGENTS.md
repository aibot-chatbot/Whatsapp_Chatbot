# AGENTS.md

## Project Scope

This repository contains a multi-tenant AI chatbot management platform built with a Flask backend, Supabase data services, and a vanilla HTML/CSS/JavaScript frontend.

The system includes:

- User authentication and profile management
- Company and team management
- Chatbot creation and configuration
- Knowledge-file management and retrieval-augmented generation
- AI model selection and provider routing
- Telegram, Wasender, and Meta WhatsApp integrations
- Conversation history and CRM workflows
- Analytics, reports, and agent insights
- Subscription enforcement
- AI-credit balances, usage charging, and ToyyibPay top-ups

Treat the current repository as the source of truth. Do not assume that a feature is complete merely because related files exist.

## Technology

- Backend: Python and Flask
- Frontend: HTML, CSS, and vanilla JavaScript
- Database and RPC platform: Supabase PostgreSQL
- Authentication: application-managed JWT authentication
- Payment gateway: ToyyibPay
- Tests: Python test suite using mocks for external dependencies

Inspect the repository before assuming exact file names, route names, schema details, or commands.

## Architecture Rules

1. Follow the existing route-service-repository structure.
2. Keep HTTP request handling inside route modules.
3. Keep business logic inside service modules.
4. Keep Supabase access inside repository modules.
5. Do not place service-role credentials or integration secrets in frontend code.
6. Scope tenant-owned data using the authenticated company context.
7. Verify chatbot ownership before accessing chatbot-scoped data.
8. Preserve existing API response conventions unless a phase explicitly changes them.
9. Use integer micro-MYR for AI-credit and internal monetary calculations.
10. Preserve idempotency for payment callbacks, credit grants, and retryable workflows.
11. Do not add speculative abstractions or unrelated refactoring.
12. Do not silently change database schemas, RPCs, public routes, or authentication behavior.

## Required Working Process

### Before implementation

1. Read this file and relevant documentation in `docs/`.
2. Inspect all directly relevant routes, services, repositories, frontend callers, and tests.
3. Explain the current behavior.
4. Identify assumptions, dependencies, risks, and missing information.
5. Produce a concise implementation plan.

### During implementation

1. Make focused changes only.
2. Preserve tenant isolation and permission checks.
3. Add or update tests for changed behavior.
4. Reuse existing conventions and helpers.
5. Do not alter unrelated files.
6. Do not leave placeholder code, commented-out alternatives, or unexplained compatibility paths.
7. Continue through ordinary non-destructive implementation steps without requesting approval after every small change.

### Before completion

1. Run focused tests.
2. Run the broader safe test suite when practical.
3. Run syntax or compilation checks.
4. Run `git diff --check`.
5. Review the final diff for unrelated changes.
6. Update `docs/FEATURE_STATUS.md` when a meaningful feature status changes.
7. Update `docs/DEVELOPMENT_ROADMAP.md` when a phase is completed or materially changed.

## Safety Boundaries

Stop and request human approval before:

- Running destructive database commands
- Modifying production data
- Changing or deploying Supabase RPCs
- Changing row-level security policies
- Performing live payment actions
- Performing live messaging actions
- Changing authentication architecture
- Rewriting Git history
- Deleting large groups of files
- Changing production deployment configuration
- Introducing breaking public API changes

Never:

- Expose secret values in logs, reports, commits, or frontend code
- Use live credentials in automated tests
- Claim a test passed unless it was actually executed
- Mark a feature verified solely because files or routes exist
- Remove legacy files without checking references and confirming ownership with the team

## Verification Status Language

Use these statuses consistently:

- **Verified complete**: implementation exists and has current test or recorded end-to-end verification evidence
- **Implemented**: coherent implementation exists but verification is incomplete
- **Partially implemented**: required parts are missing or disconnected
- **On hold**: intentionally paused
- **Obsolete**: superseded and outside the current system
- **Needs investigation**: available evidence is conflicting or insufficient

## Completion Report

Return:

1. Summary
2. Current behavior found
3. Files changed
4. Behavior implemented
5. Tests and checks executed with exact results
6. Manual verification steps
7. Remaining limitations and risks
8. Documentation updates
9. Suggested commit message
10. Recommended next phase
