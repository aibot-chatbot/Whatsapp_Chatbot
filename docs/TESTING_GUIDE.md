# Testing Guide

## Goals

The test strategy should:

- Prevent regressions
- Verify tenant isolation
- Verify role and permission enforcement
- Avoid live external API calls
- Verify billing idempotency and monetary correctness
- Support focused local testing and broader regression runs

## Current State

The strongest recorded automated coverage is around:

- ToyyibPay service behavior
- Checkout routes
- Callback routes
- Callback processing
- AI-credit top-up order references
- Order status
- Smoke-test helpers
- Reconciliation helpers

The latest recorded full suite passed:

```text
136 tests passed
```

A later audit environment could not rerun the suite because its virtual environment referenced a missing Python installation.

## Environment Setup

Use a valid local Python environment.

Recommended workflow:

```powershell
python -m venv venv
.env\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If development-only test dependencies are not already included, document and install them separately.

Do not use a copied virtual environment from another machine.

## Safe Test Rules

Tests must not:

- Call live ToyyibPay
- Call live messaging APIs
- Call live AI providers
- Modify production Supabase data
- Use production credentials
- Depend on local tunnels
- Send real emails

Mock:

- Supabase clients
- External HTTP calls
- Email sending
- AI providers
- Messaging providers
- ToyyibPay

## Recommended Test Order

### 1. Syntax and import checks

```powershell
python -m compileall app tests
```

### 2. Focused tests

Examples:

```powershell
python -m pytest tests/test_billing_routes.py -q
python -m pytest tests/test_toyyibpay_service.py -q
python -m pytest tests/test_ai_credit_topup_callback_service.py -q
```

### 3. Full safe suite

```powershell
python -m pytest tests -q
```

### 4. Diff validation

```powershell
git diff --check
```

Line-ending warnings should be distinguished from actual whitespace errors.

## Required Coverage Areas

### Authentication

Cover:

- Registration validation
- Duplicate email
- Login success and failure
- Inactive users
- Expired or invalid JWT
- Forgot-password request
- OTP verification
- Reset-password completion
- Role guards
- Invite acceptance

### Tenant isolation

For each company-owned resource:

- Same-company success
- Cross-company denial
- Missing resource
- Invalid resource ID

### Chatbots and knowledge

Cover:

- CRUD
- Plan limit enforcement
- Chatbot ownership
- File validation
- Active knowledge switching
- Supporting knowledge toggles
- Scraping validation
- Retrieval behavior with mocks

### Conversations and CRM

Cover:

- Conversation list scoping
- Message access scoping
- CRM update validation
- Assignment permissions
- Lead status and priority validation
- CRM-to-conversation linking

### Integrations

Cover with mocked HTTP calls:

- Connect
- Invalid credentials
- Disconnect
- Webhook authentication
- Duplicate message handling
- Outgoing delivery failure
- Retry behavior

### Billing and AI credit

Cover:

- Amount conversion
- Amount validation
- Order creation
- Checkout claim
- Gateway failure
- Callback verification
- Amount mismatch behavior
- Duplicate callback
- Already-paid order
- Already-credited order
- Atomic credit grant
- Order status scoping
- Expiry and cancellation behavior

## Manual Frontend Regression

Verify:

### Authentication

- Login
- Registration
- Forgot password
- Reset password
- Password visibility
- Logout

### Team

- Invite
- Accept invite
- Change role
- Deactivate member
- Permission restrictions

### Conversations

- Load conversation list
- Open messages
- Search messages
- Copy link
- Open deep link
- Copy transcript
- Download transcript
- Navigate from CRM

### Billing

- Load plan
- Load usage
- Load balance
- Load transactions
- Select fixed top-up amount
- Enter custom amount
- Create checkout
- Handle payment return
- Poll order status
- Display success and failure states

## Test Completion Report

Every development phase should report:

- Exact commands
- Exit codes
- Passed count
- Failed count
- Error count
- Skipped count
- Warnings
- Environment limitations
- Tests not run and why
