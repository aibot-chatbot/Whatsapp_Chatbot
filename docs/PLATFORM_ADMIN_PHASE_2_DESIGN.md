# Platform Admin Phase 2: Read-Only Backend Design

## Status and scope

**Implemented with automated verification; staging API verification is blocked
pending bootstrap approval.** Migrations 023, 024, and 025 remain verified in
staging only. Production deployment and first-admin bootstrap remain blocked.
The implementation introduces no frontend, bootstrap data, production database
change, tenant-role change, or platform claim in application JWTs.

Phase 2 is limited to a read-only backend surface for internal SaaS operators.
Audit-event inserts are the only planned database writes and do not mutate
tenant business data. Flow Builder and Broadcast remain out of scope.

## Current authentication and authorization findings

### JWT creation

`app/routes/auth_routes.py` issues application JWTs for password and Google login
using HS256 and the configured `JWT_SECRET`. Tokens expire after 24 hours and
contain:

- `user_id`
- `company_id`
- `email`
- tenant `role`
- `exp`

No platform-admin claim exists, and none should be added. Existing-user login
reads role and company from the current user row before issuing the token. New
accounts are created as tenant `admin`; this has no platform significance.

### `token_required`

`app/decorators/auth_decorator.py` currently:

1. Requires an exact `Authorization: Bearer <token>` header.
2. Decodes HS256 and validates expiry/signature through PyJWT.
3. Copies `user_id`, `company_id`, and `role` from JWT claims into `flask.g`.
4. Loads `users` by the JWT `user_id` on every protected request.
5. Denies the request with 403 unless that user exists and has
   `status = 'active'`.

The per-request user lookup is the correct base for immediate deactivation. Two
limitations matter for Phase 2:

- the refreshed user row is not stored in `g` for subsequent guards;
- database exceptions during the user lookup are not converted into a stable,
  sanitized authentication response, although an exception currently prevents
  the route from executing.

Phase 2 should minimally enhance this decorator to store the authoritative row
as `g.authenticated_user` and to deny safely on lookup failure. Existing tenant
behavior should otherwise remain unchanged.

### `role_required`

`app/utils/access_control.py` compares the case-normalized JWT-derived `g.role`
against an allowlist. This is suitable only for existing tenant authorization.
It must not be called by the platform-admin blueprint and must never recognize a
`platform_admin` tenant role.

Changing a mapped platform administrator's tenant role among `owner`, `admin`,
and `member` must have no effect on platform access.

### User status and verification

Password login checks active status and email verification. Existing Google
login checks active status. Every `token_required` request refreshes active
status from `users`, which satisfies the platform requirement for a valid active
application user. Phase 2 does not broaden this task into a redesign of login,
verification, JWT issuer/audience claims, or token revocation.

### Company scoping

Tenant routes normally trust the signed JWT `company_id` to populate
`g.company_id`, then repositories scope records using that value. Chatbot access
adds an explicit chatbot/company ownership predicate.

Platform reads must intentionally cross tenant boundaries, so they cannot use
`g.company_id`, `get_current_company_id()`, `verify_chatbot_access()`, or tenant
role guards. The target company must instead be a validated path parameter
passed only to explicitly platform-scoped repository functions.

### Existing “admin” routes

`/api/admin/billing` is a tenant owner/admin surface and remains company-scoped.
It must not be extended or reused as the platform API. The new namespace is
`/api/platform-admin` to make the security boundary unambiguous.

## Proposed authorization layer

### Decorator contract

Add a separate `platform_admin_required` decorator. It should compose
`token_required` internally so call sites cannot accidentally reverse or omit
the authentication layer.

Conceptual flow:

```text
validate JWT
  -> load users row by signed user_id
  -> require users.status = active
  -> store g.authenticated_user
  -> query platform_admin_users by authoritative users.id
  -> require is_active = true
  -> store g.platform_admin_user
  -> execute endpoint
```

The platform blueprint should apply this decorator once through
`Blueprint.before_request`. Every current and future route in that blueprint is
then protected by default. A structural test should fail if the blueprint-level
guard is removed.

### Required behavior

- Use `g.authenticated_user['id']`, not email, company, or role, for the mapping
  lookup.
- Query `platform_admin_users` on every protected request with both
  `user_id = <id>` and `is_active = TRUE`.
- Do not cache authorization in-process, in the session, or in the JWT.
- Ignore any JWT claim named `platform_admin`, `is_platform_admin`, or similar.
- Never read `users.role` when deciding platform access.
- Never compare the platform administrator's tenant company with the requested
  target company.
- Store the mapping row as `g.platform_admin_user`; use its `id` as the audit
  actor FK.
- Catch lookup errors, log a safe server-side error without identifiers beyond
  a request correlation ID, and deny without invoking the endpoint.

### Failure responses

| Condition | HTTP | Code | Notes |
|---|---:|---|---|
| Missing, expired, or invalid JWT | 401 | Existing token error | Preserve current convention |
| Application user missing/inactive | 403 | `account_inactive` | Do not query platform mapping |
| Missing or inactive platform mapping | 403 | `platform_admin_access_denied` | Same response for both states |
| User database unavailable | 503 | `authentication_backend_unavailable` | Existing auth layer fails closed; sanitized message |
| Platform-mapping database unavailable | 503 | `platform_admin_authorization_unavailable` | Platform guard fails closed; sanitized message |
| Guard installed without authenticated user context | 500 | `platform_admin_guard_misconfigured` | Fail closed and alert |

Do not reveal whether a mapping exists or is inactive. The endpoint function
must never run after any authorization failure.

### `g` state

- `g.current_user`: decoded JWT, retained for compatibility
- `g.user_id`, `g.company_id`, `g.role`: current legacy claim values
- `g.authenticated_user`: freshly loaded authoritative application user
- `g.platform_admin_user`: freshly loaded active allowlist mapping

Platform routes may use only the last two for identity. They must not authorize
from the legacy claim values other than the signed `user_id` used to locate the
fresh user row.

## Repository and service design

Use dedicated platform repositories rather than adding cross-tenant modes to
tenant repositories. The explicit naming makes privileged reads reviewable and
reduces accidental exposure through tenant routes. Repository exceptions must
propagate; only the decorator/service/route boundary should translate them into
safe HTTP errors.

### `platform_admin_repository.py`

```python
get_active_platform_admin_by_user_id(user_id: int) -> dict | None

insert_platform_admin_audit_event(
    platform_admin_user_id: int,
    action: str,
    resource_type: str,
    resource_id: str | None,
    metadata: dict,
) -> dict
```

The lookup selects only `id,user_id,is_active,created_at,updated_at` and applies
both user ID and active predicates in SQL. It must not swallow database errors.

The audit insert validates its input before writing and returns the created
event. It never accepts arbitrary request dictionaries as metadata.

### `platform_company_repository.py`

```python
list_companies_for_platform_admin(
    *,
    limit: int,
    offset: int,
    search: str | None,
    status: str | None,
    sort_by: str,
    sort_order: str,
) -> tuple[list[dict], int]

get_company_for_platform_admin(company_id: int) -> dict | None
```

List fields:

- `id`, `company_name`, `business_type`, `status`, `contact_email`
- `created_at`, `updated_at`

Detail may additionally return `contact_phone`. Never select user password
hashes, tokens, channel credentials, integration secrets, provider payloads, or
payment credentials.

The list query must use explicit columns, exact count, server-side range, stable
ordering, and an escaped search expression. The detail query must include
`id = target_company_id` even though the service already validated the ID.

### `platform_billing_repository.py`

```python
get_subscription_summary_for_platform_admin(company_id: int) -> dict | None

get_ai_credit_balance_for_platform_admin(company_id: int) -> dict | None

get_ai_usage_summary_for_platform_admin(
    company_id: int,
    period_start: datetime,
    period_end: datetime,
) -> dict

get_ai_credit_charge_summary_for_platform_admin(
    company_id: int,
    period_start: datetime,
    period_end: datetime,
) -> dict
```

Subscription fields are limited to plan identity, status, period/trial dates,
cancellation/downgrade state, and timestamps. Exclude external customer IDs,
gateway subscription IDs, raw payment references, checkout URLs, and provider
details.

Credit balance fields use integer micro-MYR and include initialized state,
included balance, top-up balance, total balance computed by the service, and
credit period. A missing balance returns `initialized: false`; this read-only
path must never call an ensure/initialization RPC.

Usage is limited to the current credit period, falling back to the current
subscription period. Aggregate completed AI usage tokens and provider cost plus
ledger customer charges. The existing repositories sum usage rows in Python;
that convention is acceptable initially for a bounded current period but is a
scalability risk. A future database aggregate/RPC requires separate schema
approval and is not part of Phase 2.

### `platform_admin_service.py`

The service coordinates repositories, checks company existence before billing
reads, resolves the usage period, computes totals, formats safe output, and
writes audit events. Routes should not assemble Supabase rows directly.

For cross-tenant financial/detail reads, the sequence is:

```text
authorize -> validate -> read and format -> insert audit event -> return data
```

If the audit insert fails, return 503 and do not disclose the fetched response.
This trades availability for an auditable cross-tenant access boundary.

## Initial read-only API

All routes use GET and live under `/api/platform-admin`.

| Endpoint | Purpose | Audit action |
|---|---|---|
| `GET /api/platform-admin/me` | Current authoritative app user and platform mapping identity | `platform_admin.identity.read` |
| `GET /api/platform-admin/companies` | Paginated company directory | `platform_admin.company.list` |
| `GET /api/platform-admin/companies/<company_id>` | Safe company detail | `platform_admin.company.read` |
| `GET /api/platform-admin/companies/<company_id>/subscription` | Latest subscription and safe plan summary | `platform_admin.company.subscription.read` |
| `GET /api/platform-admin/companies/<company_id>/ai-credit-usage` | Current credit balance, charges, and usage-period totals | `platform_admin.company.ai_credit_usage.read` |

No create, update, delete, reconcile, credit adjustment, subscription change,
export, impersonation, login-as, or messaging endpoint is included.

## Tenant-isolation bypass rules

Platform reads intentionally bypass the caller's tenant boundary, not resource
ownership validation generally. Required safeguards:

1. Only the dedicated platform blueprint may call platform repositories.
2. Blueprint-wide `platform_admin_required` runs before parsing target data.
3. The target company comes from a positive integer path parameter, never
   `g.company_id` and never an unvalidated JSON/query company value.
4. Every single-company repository query includes an explicit target
   `company_id` predicate.
5. Company existence is checked before subscription/credit/usage queries.
6. Platform repositories select explicit safe fields and never use `select('*')`.
7. Tenant repositories receive no `bypass_tenant`, `platform`, or optional
   unscoped flag.
8. Existing tenant routes and `role_required` behavior remain unchanged.
9. Cross-tenant results are audited before they are returned.
10. Tests use at least two tenant companies and prove the target path ID, not the
    caller's JWT company, controls the authorized platform read.

## Validation, pagination, filtering, and sorting

### Company identifiers

- Flask integer path converter plus explicit `company_id > 0` validation.
- Invalid/non-positive ID: 400 with code `invalid_company_id`.
- Valid but absent company: 404 with code `company_not_found`.

### Company list

- `limit`: default 25, integer 1–100; reject rather than silently clamp.
- `offset`: default 0, integer 0 or greater.
- `search`: optional trimmed UTF-8 string, 1–100 characters after trimming;
  search only company name and contact email. Escape PostgREST wildcard/control
  characters before constructing the expression.
- `status`: optional allowlist `active` or `inactive`; reject other values.
- `sort_by`: allowlist `created_at`, `company_name`, `status`, `id`; default
  `created_at`.
- `sort_order`: `asc` or `desc`; default `desc`.
- Always append `id` as a deterministic tiebreaker in the same direction.
- Use exact count so the client can calculate pages.

### Response shape

Preserve the project's `status`/`data` convention.

Single resource:

```json
{
  "status": "success",
  "data": {}
}
```

Company list:

```json
{
  "status": "success",
  "data": {
    "companies": [],
    "pagination": {
      "limit": 25,
      "offset": 0,
      "returned": 0,
      "total": 0,
      "has_more": false
    },
    "sort": {
      "by": "created_at",
      "order": "desc"
    },
    "filters": {
      "search": null,
      "status": null
    }
  }
}
```

Error:

```json
{
  "status": "error",
  "code": "company_not_found",
  "message": "Company not found."
}
```

Do not return raw exceptions, Supabase payloads, SQL details, stack traces, or
different denial messages for missing versus inactive platform mappings.

## Audit-event rules

### Required events

Create one event for every successfully returned platform endpoint, including
identity and list reads. For an authorized actor whose target is not found,
record the normalized action with `outcome = 'not_found'`. Authorization denials
without an active mapping cannot satisfy the audit FK and belong in sanitized
application security logs instead.

Future mutations, exports, impersonation, support actions, or credential access
must always be audited, but none is authorized in this phase.

### Canonical fields

- `platform_admin_user_id`: `g.platform_admin_user['id']`
- `action`: one of the fixed action constants above
- `resource_type`: `platform_admin`, `company`, `company_subscription`, or
  `company_ai_credit_usage`
- `resource_id`: text form of the relevant numeric ID; null only for list reads
- `metadata`: validated JSON object

### Metadata allowlist

Only these keys are permitted initially:

- `outcome`: `success` or `not_found`
- `endpoint`: fixed route template, never the raw URL
- `http_method`: always `GET` in Phase 2
- `limit`, `offset`, `sort_by`, `sort_order`
- `search_applied`: boolean; never store the search text
- `status_filter`: normalized allowlisted value or null
- `returned_count`
- `period_start`, `period_end`

Serialize metadata canonically and reject it if its UTF-8 JSON representation
exceeds 8,192 bytes. Reject unknown keys rather than silently persisting them.

### Redaction and prohibited data

Never store:

- authorization headers, JWTs, cookies, session values, API/service keys;
- passwords, password hashes, OTPs, reset or invitation tokens;
- webhook signatures, provider credentials, full external payloads;
- customer messages, prompts, retrieved knowledge, generated responses;
- email search text, phone numbers, or raw user-entered filters;
- stack traces, raw exception text, or database responses.

Apply a case-insensitive deny-key check for `authorization`, `cookie`, `token`,
`secret`, `password`, `credential`, `api_key`, `service_role`, `signature`,
`payload`, `prompt`, and `message` before serialization.

## Test plan

### Authorization decorator tests

1. Valid JWT plus active user plus active mapping allows the wrapped endpoint.
2. Tenant `admin` without a mapping receives 403.
3. Tenant `owner` without a mapping receives 403.
4. Tenant `member` with an active mapping is allowed.
5. Missing mapping receives the same 403 as an inactive mapping.
6. Inactive mapping receives 403.
7. Inactive application user receives 403 before the mapping lookup.
8. User-repository failure denies with sanitized 503 and does not call the route.
9. Platform-mapping repository failure denies with sanitized 503 and does not
   call the route.
10. Changing a mapped user's tenant role through owner/admin/member does not
    change the platform decision.
11. A forged or stale JWT platform-admin claim is ignored.
12. Revoking `is_active` between two requests denies the second request, proving
    the database lookup happens every time.
13. Two consecutive allowed requests produce two mapping lookups; no cache is
    used.
14. Missing `g.authenticated_user` fails closed as guard misconfiguration.

### Repository tests

- Lookup filters by both `user_id` and `is_active = true` and selects only safe
  fields.
- Mapping and platform data repository errors propagate.
- Company list applies exact count, range, filter escaping, whitelisted sorting,
  and stable ID tiebreaker.
- Detail and billing queries include the supplied target company predicate.
- No platform query selects password, token, credential, or raw provider fields.
- Missing balance produces an uninitialized read-only result and never calls a
  credit initialization RPC.
- Usage aggregation includes only completed rows inside the resolved period.
- All micro-MYR/micro-USD values remain integers.
- Audit validation rejects unknown metadata keys, prohibited keys, non-object
  metadata, oversized JSON, blank actions/resource types, and invalid actor IDs.

### Route and service tests

- Every endpoint rejects unauthenticated requests with 401.
- Tenant admin denied, tenant owner denied, inactive mapping denied, missing
  mapping denied, database failure denied, and active mapping allowed.
- Cross-tenant platform read uses the path company ID despite a different JWT
  company claim.
- Tenant role changes do not affect any endpoint outcome.
- Invalid pagination, status, sort, search, and company IDs return stable 400s.
- Valid missing company returns 404 without leaking other resource details.
- List pagination metadata and stable sorting are correct.
- Safe response projections exclude secrets and external payment identifiers.
- An audit event is written before each successful response.
- Audit failure returns 503 without returning the fetched tenant data.
- Blueprint registration exposes only the five GET routes.
- A structural test proves the blueprint-wide guard covers every platform route.

Use mocks for Supabase and JWT decoding; never use live credentials or staging
data in automated tests.

## Security risks and mitigations

| Risk | Mitigation |
|---|---|
| `service_role` bypasses RLS | Mandatory per-request application guard; fail closed |
| Decorator omitted on a future route | Blueprint-wide guard plus structural route test |
| Stale/forged platform JWT claim | No claim used; fresh database lookup every request |
| Tenant role accidentally grants platform access | Separate decorator/repository; explicit role-independence tests |
| Stale JWT company/role | Platform guard and repositories ignore both claims |
| Cross-tenant repository reused by tenant route | Dedicated modules and imports limited to platform service |
| Unlogged sensitive read | Audit before response; audit failure withholds data |
| Broad `select('*')` leaks secrets | Explicit field projections and response projection tests |
| Expensive usage aggregation | Current-period bound; future reviewed aggregate RPC |
| Search-expression injection | Length limits, escaping, fixed searchable columns |
| Mapping revoked during long request | Fresh check at request start; keep endpoints short/read-only |
| Protected internal company deleted | Existing FK RESTRICT plus operational company protection gate |
| Audit metadata leaks PII/secrets | Strict allowlist, deny-key check, 8 KiB cap |

## Exact files likely to change during implementation

### New files

- `app/decorators/platform_admin_decorator.py`
- `app/database/platform_admin_repository.py`
- `app/database/platform_company_repository.py`
- `app/database/platform_billing_repository.py`
- `app/services/platform_admin_service.py`
- `app/routes/platform_admin_routes.py`
- `tests/test_platform_admin_authorization.py`
- `tests/test_platform_admin_repositories.py`
- `tests/test_platform_admin_routes.py`
- `tests/test_platform_admin_audit.py`

### Existing files

- `app/decorators/auth_decorator.py` — expose the refreshed user row and sanitize
  user-lookup database failure without changing tenant authorization semantics.
- `app/__init__.py` — import and register the platform-admin blueprint.
- `docs/FEATURE_STATUS.md` — record Phase 2 implementation/verification status.
- `docs/DEVELOPMENT_ROADMAP.md` — record Phase 2 completion when implemented.
- `docs/PLATFORM_ADMIN_PHASE_2_DESIGN.md` — reconcile design with final behavior.

`app/utils/access_control.py`, tenant billing routes, existing tenant
repositories, frontend files, Flow Builder, Broadcast, migrations, and
authentication token claims are not expected to change.

## Implementation sequence

1. Add repository tests and platform-admin mapping/audit repository.
2. Enhance `token_required` with authoritative user context and safe DB failure.
3. Add and exhaustively test `platform_admin_required`.
4. Add platform company/billing repositories and service formatting tests.
5. Add the blueprint with its global guard and five GET routes.
6. Register the blueprint and run authorization/route/tenant-isolation tests.
7. Run the full safe test suite and update feature/roadmap status.
8. Perform staging API verification only after bootstrap and deployment gates
   receive separate approval.

## Final implementation reconciliation

Phase 2 was implemented in the files listed above. The final implementation
matches the design with these concrete choices:

- `token_required` retains JWT-derived `g.company_id` and `g.role` for tenant
  compatibility, stores the freshly loaded active row in
  `g.authenticated_user`, and sanitizes user-repository failures as
  `authentication_backend_unavailable`.
- `platform_admin_required` composes `token_required` and performs a fresh
  `user_id` plus `is_active = true` mapping query for every request. The guard
  does not inspect tenant role, tenant company, or platform-like JWT claims.
- The blueprint guard is registered with `before_request`, so all five routes
  inherit the same fail-closed authorization boundary.
- Company search is escaped before it is placed in the fixed PostgREST OR
  expression. Listing uses exact count, range pagination, allowlisted fields,
  and an ID tiebreaker.
- Subscription plans are loaded through a second explicit safe projection;
  payment identifiers and provider fields are not selected.
- The AI usage period uses a complete valid credit-balance period first and a
  complete valid subscription period second. It never combines boundaries from
  two different periods and never initializes a missing balance.
- Audit actions and resource types are fixed allowlists. Metadata must be an
  object with allowlisted keys, passes a recursive prohibited-key check, and is
  limited to 8,192 bytes of canonical UTF-8 JSON.
- Audit insertion remains the only platform write. A failed audit insert is
  returned as `platform_admin_audit_unavailable` and fetched tenant data is not
  placed in the response.

Automated coverage is in the four focused platform-admin test modules. Staging
API verification is not claimed because no platform-admin mapping has been
bootstrapped. Production remains blocked by the Phase 1.5 gates, including the
protected internal company, bootstrap approval, metadata/retention decisions,
append-only enforcement decision, and production executor/ownership approval.
