# Filter 2 block-mode handoff

Checkout: C:/Users/Vincent/Desktop/wa-release/content-filters. Branch: feat/content-filters. Starting HEAD: 766b555 (verified). Local, uncommitted changes only.

## Behavior and design

- The existing mode default is unchanged. No production configuration was read or changed; the owner keeps CONTENT_REVIEW_MODE=log until review and a separate authorized change.
- content_review_service.BLOCK_WAIT_SECONDS is 4. chat_pipeline_service submits the review to four shared threads and waits on its Future using a monotonic wall-clock budget. A completion timestamp also prevents a verdict completed after the deadline from blocking. Submission failure, an unavailable verdict, an exception, or all four workers being occupied lets the message through. A semaphore prevents an unbounded queue across tenants.
- A timeout retains the original Future. Its completion callback starts background bookkeeping and records an unsafe verdict with mode log. It never starts another Cloudflare call. IC/card masking still happens before review_text. Existing log-mode review remains off the reply path.
- An unsafe verdict in budget returns the existing ContentFlag to ai_router. The existing refusal path records it, hands the chat to staff and uses the safe acknowledgement; self-harm uses the existing Befrienders/999 reply. Filter 1 payloads and behavior remain unchanged. New Filter 2 stops explicitly record mode block.

## Exact stored-message identity

All five persisted inbound paths save the customer message before generate_response. Each now retains that exact returned row and passes its id through the additive message_id keyword. This avoids matching text or looking up the latest row, which would race concurrent messages. record_content_flag stores the ID in payload.content_flag.message_id on the existing agent_actions row (intent unknown). No messages columns or message contents/types are changed.

Stored paths: Telegram (telegram_utils), Meta WhatsApp (whatsapp_utils), WaSender, WhatChimp, and the web widget. The /chat test route and Test Bot route do not persist their input and need no stored-message ID.

## Shared lookup and readers

agent_action_repository.get_blocked_content_message_ids(conversation_id) makes one query scoped to the already authorized conversation. It selects only the message ID from content_flag, filters payload->content_flag not null in the database, requires filter 2, and excludes mode log. Missing mode also matches older blocking flags. It has no recent-window or explicit list limit. It returns string IDs for consistent comparisons. Lookup errors log only the exception type and conversation ID, return an empty set, and drop nothing.

1. chat_history_repository excludes IDs before formatting history for prepare_chat_prompt. The same history feeds analyze_agent_intent, prompt construction and conversation-memory extraction. There is no independent stored-message reader in the memory extractor.
2. analytics_repository.get_transcript_logs excludes IDs before flattening text. report_service receives those already filtered transcripts, so report_service itself needed no change.
3. analysis_repository.load_report_sources excludes IDs from both messages and customer_questions, sharing a lookup per conversation between the two sources.
4. business_observation_service skips a persisted blocked ID before constructing or calling its classifier.

The existing Filter 1 history/transcript checks remain in place. No Cloudflare re-review was added to any reader.

## Changed files

Backend (13):

- app/database/agent_action_repository.py
- app/database/analysis_repository.py
- app/database/analytics_repository.py
- app/database/chat_history_repository.py
- app/routes/widget_routes.py
- app/services/ai_router.py
- app/services/business_observation_service.py
- app/services/chat_pipeline_service.py
- app/services/content_review_service.py
- app/services/wasender_service.py
- app/services/whatchimp_service.py
- app/utils/telegram_utils.py
- app/utils/whatsapp_utils.py

Tests (5): tests/conftest.py; tests/test_content_filter_pipeline.py; new tests/test_filter2_message_identity.py; new tests/test_filter2_readers.py; new tests/test_filter2_verdict_repository.py.

Docs (3): this handoff, FEATURE_STATUS.md, DEVELOPMENT_ROADMAP.md.

No new app module was added, so the .dockerignore allowlist needs no change. No admin view or frontend file was edited.

## Verification ledger

Interpreter for every Python invocation: C:/Users/Vincent/Desktop/Whatsapp_Chatbot/.venv/Scripts/python.exe. Commands run from this worktree or its temporary HEAD archive; the other checkout is read-only. PYTHONDONTWRITEBYTECODE=1 prevents imported dependencies from writing bytecode there. Full/final focused runs use a worktree-local socket guard; subsequent invocations also reject DNS lookups. Fixture temp files and explicit compile outputs stay inside the worktree.

| Check | Actual result |
|---|---|
| Initial review/pipeline tests | 82 passed in 2.58 s; exit 0 |
| Reader slice (agent-run) | 129 passed in 2.69 s; exit 0 |
| Existing channel slice (agent-run) | 130 passed, 30 subtests passed in 2.04 s; exit 0 |
| New identity tests (agent-run) | 9 passed in 0.75 s; exit 0 |
| Integrated review/reader/channel tests | 193 passed in 6.77 s; exit 0 |
| Final consolidated focus: 14 test files | 361 passed, 30 subtests passed in 9.86 s; exit 0 |
| First required full suite | 6,930 passed, 28 failed, 70 skipped, 4 warnings, 1 collection error, 2,382 subtests passed in 483.45 s; exit 1 |
| Baseline comparison | Read-only git archive of unchanged HEAD 766b555 inside ignored output; all 29 failure/error identifiers reproduced: 28 failed, 1 collection error, 5 warnings in 8.09 s; exit 1. Exact identifier comparison: 29 current, 29 baseline, no missing or extra identifiers |
| Final required full suite | 6,935 passed, 28 failed, 70 skipped, 5 warnings, 1 collection error, 2,382 subtests passed in 373.72 s; exit 1. Includes all five new lookup tests. All 29 failure/error identifiers match the unchanged HEAD comparison; no new failure identified |
| Python syntax | All 18 changed/new Python files compiled to explicit worktree-local output paths; exit 0 |
| Codex Security CLI | scan --help exit 0. scan . --working-tree --dry-run exit 1: Diff targets require a Git repository. No actual scan passed; a network-backed scan was not run |
| Whitespace / HEAD | git diff --check exit 0; HEAD remains 766b555 |

Required full command: python -m pytest tests -q -p no:cacheprovider --continue-on-collection-errors. A short worktree-local basetemp is supplied through PYTEST_ADDOPTS. Failed Windows shell/Python-redirection startups ran no tests; successful invocations above supply the reported counts. The final invocation captures its log inside Python's verification-only sitecustomize because PowerShell native redirection could not open its private pipe.

The focus covers a real four-second wait with a mocked 4.3-second review, later log-mode persistence from that same single call, stored ID plus handoff, self-harm, safe/unavailable/error paths, masking, pool/submission failures, and all readers under block/log/lookup-error conditions. Existing log-mode cases are included.

The 28 broad failures comprise the supplied 11 known billing/GEO/profile/subscription failures plus 17 Langflow tests whose Windows asyncio socketpair setup is denied by the strict no-connection guard. The collection error is tests/test_geo_analysis_service.py. All reproduce on unchanged HEAD under the same restrictions. A full baseline suite was not run; comparison targeted every observed failure/error.

## Limits for Opus and owner review

- These changes enforce persisted blocking verdicts. They do not fence readers that start before a verdict is stored. In particular, data/065 queues observation jobs atomically with message insertion, before inline review, so another process can start classification before the flag exists. This timing limitation is separate from later replay of an already blocked message. No distributed pending-review barrier is implemented.
- The owner explicitly chose fail-open lookups: database lookup failure retains all input. Flag writes and late background logging are best effort; a process restart can lose an unfinished log-only review.
- A single-query lookup can be subject to a provider's configured row cap. No live provider cap was queried. Reports add one flag lookup per conversation. Four occupied review workers cause immediate fail-open behavior rather than queued work.
- No migration, commit, push, branch change, checkout, reset, stash, deployment, production access, live service test, or successful Codex Security scan. Live configuration/schema behavior remains unverified. A live mode flip is not part of this work.

Next action: Opus reviews this diff and the pre-verdict reader timing limit; keep production in log mode during review.
