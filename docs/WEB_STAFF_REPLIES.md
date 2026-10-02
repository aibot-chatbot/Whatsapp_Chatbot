# Website staff replies — 2026-09-22

## Customer-service workflow

1. Open **Dashboard → Waiting for human**, then select the website conversation.
2. Type in the Conversations reply box and send. The message is labelled
   **Support team**; **Saved** confirms database persistence, not visitor receipt.
3. The visitor keeps the same share-link or embedded chat open. Staff replies
   appear automatically. Customer follow-ups appear in the staff inbox without
   running AI while the handoff is pending.
4. Use **Resolve** when the staff session is finished. The existing legacy
   workflow resumes AI with the next customer message once all pending handoff
   actions are resolved. Sending a staff reply does not resolve the handoff.

Pages loaded before this release need a refresh. Those old pages did not retain
their session ID, so the visitor must send a new message and request staff again;
reply to that new conversation. Sessions started with this release survive reload
in the same tab using sessionStorage. Closing the tab, clearing browser storage,
or storage restrictions can lose that session; there is no cross-device recovery.
The UI retains up to 80 recent message bubbles locally.

## Implementation and boundaries

- The existing authenticated `POST /api/conversations/<id>/agent-reply` now accepts
  website replies for a valid visitor session, active chatbot, enabled widget,
  verified tenant and existing pending handoff. It records `sender_type=human`,
  `ai_generated=false`, and the authenticated `actor_user_id`. Existing tenant
  staff permissions remain unchanged; Phase B assignee enforcement is not enabled.
- `POST /api/widget/<public_key>/messages` accepts the original opaque `web_...`
  session capability in the JSON body and a nonnegative `after_id`. It resolves
  only the widget's chatbot and web conversation, never a caller-provided company
  or conversation ID, and returns only saved human text with safe public fields.
  Internal notes, provider metadata and other sessions are excluded.
- Polling uses 50-message pages, a monotonic cursor and ID deduplication. The
  visible page polls every 3 seconds, hidden pages every 15 seconds; requests do
  not overlap, pagehide cancels polling, and focus triggers a fresh read. Failure
  preserves the cursor and history and shows a reconnecting status. The endpoint
  is rate limited to 120 requests/minute/IP and sends `Cache-Control: no-store`.
- Customer input during a pending handoff is saved without an AI quota check or
  model call. Final AI persistence rechecks the pause under the same conversation
  lock as staff writes and visitor reads, including the existing persisted
  handoff-acknowledgement exception. This lock relies on the current single
  Gunicorn process; it is not a distributed lock for future scaling.
- The existing session ID is a bearer capability. It has server-generated
  randomness and is kept out of polling URLs/logs. The design does not add an
  account login, signed session token, delivery/read receipt or retry idempotency.
  After an uncertain send, staff should refresh the transcript before retrying.
- Migration 060 supplies the author FK. Migration 061 adds a unique open website
  session index on `(chatbot_id, platform_user_id)` to prevent concurrent first
  messages from splitting one visitor into two conversations. The existing
  repository reloads the winning conversation after an insert conflict. The
  production preflight found 50 conversations and no duplicate eligible keys;
  application and readback confirmed a valid unique index, with 3-second lock
  and 30-second statement timeouts. No data was deleted or backfilled.
  `HANDOFF_CONTROL_ENABLED` remains false; Test Lab sessions without a real
  `web_...` visitor remain non-deliverable.

## Verification and release

Full working-tree tests passed **4828 tests, 6 skipped and 2303 subtests**,
exit 0 in 197.06 seconds. The suite disabled dotenv and external network access;
a temporary Git index admitted the new runtime module for the container manifest
test. Pre-existing unrelated fixture edits remain outside this commit, so this
is not a claim of the same full-suite count on a pristine checkout. The first
full run identified one obsolete assertion that web replies must always be
disabled; updating it to require a valid visitor session made the final run green.
Python syntax checks and `git diff --check` also passed.

Focused staff tests passed 41 cases,
including an in-memory PostgREST round-trip through the real Flask routes,
services and repositories: request handoff, staff save, capability-scoped poll,
customer follow-up without AI, Resolve and next-message AI resumption. Public
delivery/widget regression checks passed 65 cases and 30 subtests, including
pagination, failures and a real thread waiting on the delivery lock.

Browser verification passed 19 cases: 10 visitor/inbox cases, 8 existing
handoff/provider regressions, and a two-context staff/visitor round-trip. Browser
API calls were mocked. Real isolated PostgreSQL 18.3 concurrency verification
passed 1 case; the production database is PostgreSQL 17.6. Migration 061 was
applied as `20260922043754 / web_widget_session_uniqueness_061` and its index
readback is valid/unique. No real customer message is sent for release validation.

Codex Security was attempted on eight changed runtime/frontend files. It exited
2 during preflight at 0/8 because the stored ChatGPT sign-in could not refresh.
There is no completed security scan; migration 061 has independent SQL review
and database tests, but no Codex Security coverage. Sentry read-only inspection
found the earlier widget issue `WHASTAPP_CHATBOT_PROJECT-Q`, last seen September
18 on `chip-live-20260915-234ee13`; it is not evidence of this release's behavior.

The main agent integrates bounded Backend Architect, Frontend Developer and API
Tester lanes from `C:/Users/Vincent/agency-agents`, using Prompt Master, relevant
ECC/Matt Pocock skills, Supabase MCP, Fly MCP, Sentry plugin and Codex Security.

## Production evidence and recovery

Fly **v35** deployed successfully to the existing Singapore Machine
`185de27f125998`, with unchanged environment configuration, VM specification and
volume mounts. The image is
`registry.fly.io/aibot-chatbot-my@sha256:b28a5514dea60c86c1675254d8be8659b0aabf076bbe45a55072c4d63b0098fe`.
The build snapshot contains 293 explicit inputs; all 290 runtime files match
the deployed container hashes, with no missing or unexpected runtime files.
Unrelated local files and secrets were excluded from the build and commit.

The real Bot 38 share-link page returned 200 and polled the new endpoint with
200, an empty isolated session, `private, no-store`, enabled input, persisted
session and no browser script errors. Invalid session input returned 400;
unauthenticated staff reply returned 401. No customer message, lead, model call,
handoff email, payment or provider send was triggered. This verifies deployed
read behavior; the full send/receive chain was tested with mocked data above.
Immediate post-deploy Sentry inspection found zero issues last seen in the
three-minute window beginning `2026-09-22T04:44:55Z`; this short observation
is not a promise of future error-free operation or a substitute for tests.

`HANDOFF_CONTROL_ENABLED` and `N8N_WORKER_ENABLED` remain unset/false. Existing
Wasender retry, billing, ingest/Cloudflare queues, AI Search, credit enforcement
and CHIP switches remain true; R2 remains authoritative with initial migration 0.

If application rollback is necessary, restore the previous v34 image
`registry.fly.io/aibot-chatbot-my@sha256:df8b3719606211aa7240315877e1276b6641e9b695ec0331acda9a16a0bf9613`
while retaining the new index and stored human messages. A rollback stops
visitor polling and removes the website reply UI. Do not delete conversation
history or drop the integrity index to roll back application code.
