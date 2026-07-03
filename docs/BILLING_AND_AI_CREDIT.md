# Billing and AI Credit

## Overview

The platform includes:

1. Subscription plan enforcement
2. AI-credit balance and usage charging
3. ToyyibPay top-up checkout
4. Payment callback processing
5. Atomic credit granting
6. Frontend billing and transaction display

## Subscription Plans

Plans may define:

- Chatbot limits
- Team member limits
- Knowledge file limits
- Knowledge storage limits
- Channel limits
- Feature flags
- Included AI credit
- Model access tier

The billing guard layer checks limits before protected operations.

## Default Subscription

A default free subscription is created during company onboarding when required.

This behavior must remain idempotent.

## AI-Credit Units

AI credit is stored as integer micro-MYR.

```text
1 MYR = 1,000,000 micro-MYR
1 sen = 10,000 micro-MYR
```

Do not store or calculate money using floating-point arithmetic.

## Balance Structure

The balance includes:

- Included balance from the subscription period
- Purchased top-up balance

The summary should expose:

- Included balance
- Top-up balance
- Total available balance
- Current period
- Related subscription information

## Usage Charging

A typical charge flow is:

1. Confirm AI-credit enforcement is enabled.
2. Confirm company and subscription context.
3. Record provider usage.
4. Calculate provider cost.
5. Apply exchange rate and markup.
6. Calculate customer charge.
7. Deduct balance atomically.
8. Record a credit transaction.
9. Prevent duplicate charging of the same usage record.

## Top-Up Checkout

### Authorized route

An authenticated, authorized user creates a checkout request.

The backend:

1. Resolves user and company context server-side.
2. Validates the requested amount.
3. Creates an internal top-up order.
4. Claims checkout creation.
5. Calls ToyyibPay to create the external bill.
6. Stores the gateway order ID and checkout URL.
7. Returns safe checkout details.

### Amount validation

The backend is authoritative.

Validation includes:

- Positive integer amount
- Correct internal unit
- Minimum allowed amount
- Required cent divisibility
- Upper-bound rules where configured

The frontend must not be trusted as the sole validator.

## Top-Up Order Lifecycle

Expected states include:

```text
pending
    ↓
claimed
    ↓
paid
    ↓
credited
```

Failure states may include:

```text
failed
expired
cancelled
```

Transitions must be controlled and idempotent.

## Callback Processing

The ToyyibPay callback flow:

1. Receive the public callback.
2. Verify callback authenticity.
3. Parse and validate fields.
4. Resolve the internal order.
5. Verify gateway and payment state.
6. Compare expected amount.
7. Mark the order paid when appropriate.
8. Grant credit through an atomic RPC.
9. Mark the order credited.
10. Return idempotent success for duplicate callbacks.

The frontend return URL must never directly grant credit.

## Idempotency

Idempotency is required for:

- Checkout creation claims
- Gateway retries
- Duplicate callbacks
- Paid-order processing
- Credit granting
- Reconciliation

A duplicate callback must never produce duplicate credit.

## Order Status

The order-status endpoint must:

- Require authentication
- Scope the order to the current company
- Validate the order reference
- Return only safe fields
- Avoid exposing gateway secrets or internal diagnostics

## Frontend Billing Flow

The profile page includes:

- Current subscription
- Usage summary
- AI-credit balance
- Top-up amount selection
- Custom amount input
- ToyyibPay redirect
- Return handling
- Order-status polling
- Transaction history
- Loading, success, empty, and error states

## Testing

Recorded focused coverage includes:

- ToyyibPay configuration and conversion
- Callback hash verification
- Callback parsing
- Checkout route
- Order status route
- Pending-to-credited processing
- Already-paid handling
- Already-credited handling
- Duplicate callback protection
- Order UUID validation
- Smoke and reconciliation helpers

The latest recorded full suite passed 136 tests.

## Production Verification Checklist

Before release:

- Confirm ToyyibPay credentials
- Confirm category code
- Confirm callback URL
- Confirm return URL
- Confirm HTTPS
- Perform a controlled payment
- Confirm callback authenticity
- Confirm amount
- Confirm order reaches `credited`
- Confirm balance increases once
- Replay callback and confirm no duplicate credit
- Confirm transaction history
- Confirm reconciliation process
- Confirm logs contain no secrets
