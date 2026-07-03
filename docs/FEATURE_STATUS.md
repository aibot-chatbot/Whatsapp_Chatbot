# Feature Status

## Status Definitions

- **Verified complete**: implemented and supported by current test evidence or recorded successful end-to-end verification
- **Implemented**: coherent implementation exists but verification is incomplete
- **Partially implemented**: required parts are missing or disconnected
- **On hold**: intentionally paused
- **Obsolete**: no longer part of the active system
- **Needs investigation**: evidence is conflicting or insufficient

## Authentication and Account Management

| Feature | Status | Notes |
|---|---|---|
| Registration | Implemented | Backend and frontend flow exist; broader automated coverage is still needed |
| Login | Implemented | JWT login flow exists |
| Logout | Implemented | Client-side token removal; no server-side revocation |
| Forgot password | Implemented | Requires renewed end-to-end verification |
| Reset password | Implemented | Requires renewed end-to-end verification |
| Password visibility controls | Implemented | Present in authentication flows |
| Email verification / OTP | Implemented | Security review required for OTP logging and production behavior |
| Google authentication | Implemented | External verification required |
| User profile | Implemented | Profile viewing and update flow exists |
| Password change | Implemented | Requires regression coverage |

## Company and Team

| Feature | Status | Notes |
|---|---|---|
| Company creation | Implemented | Created during account onboarding |
| Team member list | Implemented | Company-scoped |
| Team invitations | Implemented | Invite creation, validation, and acceptance flows exist |
| Role management | Implemented | Owner/admin controls exist |
| Member deactivation | Implemented | Requires permission regression tests |

## Chatbots and Configuration

| Feature | Status | Notes |
|---|---|---|
| Chatbot creation | Implemented | Backend and frontend exist |
| Chatbot listing | Implemented | Company-scoped |
| Chatbot editing | Implemented | Requires broader route tests |
| Chatbot deletion | Implemented | Requires deletion-flow verification |
| Prompt configuration | Implemented | Profile and deployment flow exists |
| Model selection | Implemented | Model catalog and settings UI exist |
| Automated menu or flow generation | Implemented | Requires current verification |

## Knowledge and RAG

| Feature | Status | Notes |
|---|---|---|
| Knowledge file upload | Implemented | External storage and full error-path verification still needed |
| Knowledge file listing | Implemented | Chatbot-scoped |
| Active knowledge selection | Implemented | Current active file behavior exists |
| Supporting knowledge toggle | Implemented | Enabled/disabled knowledge behavior exists |
| Website scraping | Implemented | Requires safe URL and production verification |
| Knowledge refinement | Implemented | Requires end-to-end verification |
| Chunk storage and retrieval | Implemented | Database/vector configuration requires environment verification |
| RAG response flow | Implemented | Quality and adversarial testing remain |

## AI Providers

| Feature | Status | Notes |
|---|---|---|
| Model catalog | Implemented | Static/catalog-based model definitions |
| OpenRouter routing | Implemented | External API verification required |
| DeepSeek routing | Implemented | External API verification required |
| Gemini usage | Implemented | Used in AI and/or embedding flows; verify exact active paths |
| AI usage logging | Implemented | Integrated with AI-credit charging |
| Provider fallback behavior | Needs investigation | Confirm current failure and fallback rules |

## Messaging Integrations

| Feature | Status | Notes |
|---|---|---|
| Telegram connection | Implemented | Requires controlled live verification |
| Telegram webhook | Implemented | Requires production webhook verification |
| Telegram disconnect/reconnect | Implemented | Requires live regression |
| Wasender connection | Implemented | Requires controlled live verification |
| Wasender webhook | Implemented | Requires live verification |
| Wasender retry worker | Implemented | Operational verification required |
| Meta WhatsApp Embedded Signup | Implemented | Live status depends on Meta app/business approval |
| Meta WhatsApp webhook | Implemented | Production signature and message-flow verification required |
| Message deduplication | Implemented | Repository support exists for supported channels |

## Conversations and CRM

| Feature | Status | Notes |
|---|---|---|
| Conversation list | Implemented | Backend and frontend exist |
| Message history | Implemented | Conversation-scoped |
| Message search | Implemented | Previously reviewed in the conversation interface |
| Conversation deep links | Implemented | URL synchronization and direct loading were previously reviewed |
| Copy conversation link | Implemented | Previously reviewed |
| Copy transcript | Implemented | Previously reviewed |
| Download transcript | Implemented | Previously reviewed |
| CRM lead list | Implemented | Company/chatbot scoped |
| Lead status | Implemented | Status editing exists |
| Lead priority | Implemented | Priority editing exists |
| Lead assignment | Implemented | Requires permission verification |
| Lead follow-up | Implemented | Follow-up fields and UI exist |
| CRM filters | Implemented | Status, assignment, and related filtering exist |
| CRM-to-conversation navigation | Implemented | Conversation ID linking was previously reviewed |

## Analytics and Operations

| Feature | Status | Notes |
|---|---|---|
| Dashboard metrics | Implemented | Requires broader regression tests |
| Message charts | Implemented | Data aggregation and frontend display exist |
| Live workflow status | Implemented | Requires runtime verification |
| Dashboard health | Implemented | Requires environment verification |
| Agent insights | Implemented | Requires data-path tests |
| AI-generated reports | Implemented | External model and feature-gate verification required |
| Escalation handling | Implemented | Requires workflow tests |

## Subscription and AI Credit

| Feature | Status | Notes |
|---|---|---|
| Subscription plans | Implemented | Plan retrieval and display exist |
| Current subscription | Implemented | Company-scoped |
| Usage summary | Implemented | Usage data exposed in billing UI |
| Default free subscription | Implemented | Created during company onboarding |
| Subscription limit enforcement | Implemented | Guard layer exists |
| Feature flag enforcement | Implemented | Backed by plan feature data |
| AI-credit summary | Verified complete | Included in the latest billing test work |
| AI-credit transactions | Verified complete | Included in the latest billing implementation |
| AI-credit usage charging | Implemented | Atomic repository/RPC flow exists; broader integration verification needed |
| ToyyibPay checkout | Verified complete | Latest billing work and focused tests completed |
| ToyyibPay callback | Verified complete | Callback parsing and processing covered by focused tests |
| Order status endpoint | Verified complete | Focused route tests exist |
| Duplicate callback protection | Verified complete | Idempotent callback behavior covered |
| Atomic top-up credit grant | Verified complete | RPC-based design and focused tests exist |
| Billing and top-up frontend | Verified complete | Latest frontend billing work completed and committed |
| Live production payment | Needs investigation | Requires controlled end-to-end production verification |

## Known Verification Evidence

The latest recorded full automated suite after the ToyyibPay migration passed:

```text
136 tests passed
```

A later read-only Codex audit could not rerun the suite because its virtual environment referenced an unavailable Python installation. That environment limitation does not replace the previously recorded successful result.

## Cross-Cutting Items Requiring Investigation

- Live Supabase row-level security configuration
- Version-controlled definitions for all production RPC functions
- Exact current external integration readiness
- Production deployment configuration
- Full route-level tenant-isolation review
- Frontend automated test strategy
- Current removal readiness of legacy backup files

## Document Maintenance

Update this file after:

- Completing a development phase
- Adding or removing a major feature
- Changing an integration
- Changing billing or database behavior
- Completing meaningful verification

Do not record temporary branch names, commit hashes, local paths, or working-tree status here.
