# Feature Status

## Status Definitions

- **Verified complete**: implemented and supported by current test evidence or recorded successful end-to-end verification
- **Implemented**: coherent implementation exists but verification is incomplete
- **Partially implemented**: required parts are missing or disconnected
- **On hold**: intentionally paused
- **Obsolete**: no longer part of the active system
- **Needs investigation**: evidence is conflicting or insufficient

## Superadmin Environment Boundary

The current Supabase project is intentionally used as the prototype/shared-testing
environment for Superadmin development and team verification. Supabase
labels its main branch as `PRODUCTION`, but this project is not the future real
production environment. Future staging and future real production have not been
verified or deployed for the current Superadmin milestone.

The current Superadmin prototype milestone is runtime-verified complete in that
prototype/shared-testing environment. Completed current Superadmin scope
includes the foundation/security work, Support Case Operations, Tenant
Communication, bounded Platform Admin Management, Tenant / Company
Administration, Platform Monitoring, and read-only Billing & Subscription
Oversight. Broader Phase 4 Platform Admin account-management expansion remains
deferred and is not required for the current prototype milestone.

Repository/database reconciliation confirmed that Superadmin migrations 029
through 038 are already represented in the current prototype/shared-testing
database. Do not reapply migrations 029-038. Migration 043
(`data/043_atomic_platform_support_case_creation.sql`) and Migration 044
(`data/044_platform_admin_user_recent_activity_batch.sql`) are applied and
runtime verified in prototype/shared-testing only. They are not staging
verified and are not production deployed.

Final Superadmin prototype runtime verification is now represented by the
consolidated hardening verification pass: focused evidence recorded 310 passed
tests and 779 subtests, and the broader focused platform-admin suite recorded
431 passed tests and 991 subtests. The pass covered atomic support-case
creation, bounded support history pagination, pagination regression repairs,
platform-admin recent-activity batching, human-readable assignee identities,
inactive historical assignee safety, and the monitoring-depth audit conclusion
that current Phase 6 is sufficient for prototype/shared-testing.

## Authentication and Account Management

| Feature | Status | Notes |
|---|---|---|
| Registration | Implemented | Backend and frontend flow exist; broader automated coverage is still needed |
| Public Landing Page | Implemented | Clean, glassmorphic landing page introducing project features, FAQ, and subscription pricing aligned with the authoritative billing plan catalogue; dynamic login checks; served as root `/` |
| Login | Implemented | JWT login flow exists |
| Logout | Implemented | Client-side token removal; no server-side revocation |
| Forgot password | Implemented | Requires renewed end-to-end verification |
| Reset password | Implemented | Requires renewed end-to-end verification |
| Password visibility controls | Implemented | Present in authentication flows |
| Email verification / OTP | Implemented | Security review required for OTP logging and production behavior |
| Google authentication | Implemented | Public client configuration loads at runtime; missing `GOOGLE_CLIENT_ID` fails closed, token audience must match exactly, Google email must be verified, and invitation email must match. `RATELIMIT_GOOGLE_AUTH=10/minute` covers Google login, registration, and invitation acceptance; live external Google verification is still required |
| Auth and public-invitation rate limiting | Verified complete | Flask-Limiter decorators registered before `create_app()` are enforced during normal startup. Existing login, OTP, password-reset, checkout, retry, receipt, and export limits are active when enabled; invitation validation is 30/minute and password invitation acceptance is 5/minute by default |
| User profile | Implemented | Profile viewing and update flow exists |
| Authenticated tenant Support page | Implemented | `support.html` is authenticated, reachable from the shared tenant account menu, submits only category, title, and redacted description to `POST /api/support/requests`, and now includes request history/detail with tenant-visible replies from safe tenant endpoints. Migration 030 is verified only in the main shared testing Supabase with fake/team data. Phase 3 tenant communication and Migration 033 are verified only in the main shared-testing Supabase with fake/team data. Email, attachments, billing actions, impersonation, exports, charts, staging readiness, and production use remain excluded |
| Password change | Implemented | Requires regression coverage |

## Company and Team

| Feature | Status | Notes |
|---|---|---|
| Company creation | Implemented | Created during account onboarding |
| Profile company/workspace summary | Verified complete | Uses only company lookup, exact active-user count, valid pending-invitation count, and the current subscription Team limit. It is independent of full billing, chatbot, channel, knowledge, storage, AI-usage, and payment metrics, so unrelated usage failures do not blank the cards |
| Team member list | Verified complete | Company-scoped read-only access for members uses refreshed database company and role context; admin/owner management actions remain permission-gated |
| Team invitations | Implemented | Onboarding is invitation-only and direct `POST /api/users` returns HTTP 410. Roles are limited to `admin`/`member`. Active members plus valid unexpired pending invitations count toward the limit. Stale rows are refreshed and resend rotates token/expiry. Resend submits invitation ID, blocks duplicate in-flight requests, disables the clicked button, and refreshes invitations and Team usage after success. Password/Google acceptance joins `invitation.company_id`; transactional acceptance remains deferred |
| Role management | Implemented | Writes are company-scoped; refreshed database roles are authoritative with no JWT fallback, and owner accounts are protected |
| Member deactivation | Implemented | Status updates are company-scoped, owner accounts are protected, and reactivation checks the Team limit |

## Chatbots and Configuration

| Feature | Status | Notes |
|---|---|---|
| Chatbot creation | Implemented | Backend and frontend exist |
| Chatbot listing | Implemented | Company-scoped |
| Chatbot archive, restore, and permanent deletion | Verified complete | Active and archived lists are company-scoped; authenticated archive listing plus admin/owner restore and permanent-delete routes are covered by focused route tests. Permanent deletion still depends on Migration 022 being deployed in the target Supabase environment |
| Chatbot editing | Implemented | Requires broader route tests |
| Chatbot deletion | Implemented | Requires deletion-flow verification |
| Prompt configuration | Implemented | Profile and deployment flow exists. `frontend/new_prompt.html` was rebuilt on 2026-08-17 as a vanilla-DOM four-step wizard (Profile → Knowledge → Validate → Deploy) on the control-room design system, replacing the React 18 UMD page loaded from unpkg without SRI. No endpoint or payload changed; the deploy precondition that `handleDeployToLiveBot` previously enforced only after the click (active profile + active primary knowledge + passing `/api/match/check`) is now shown up front via a disabled button and a named blocker, and any profile change or save clears the stored validation. Covered by `tests/browser/bot-config.spec.js` (mocked APIs — no live-backend verification). Dead `extraction*` state that the old render never referenced was removed |
| Profile editor (tone, optional websites) | Implemented | On 2026-08-18 three defects in `frontend/new_prompt.html` were fixed. (1) Tone was a three-option `<select>` (`Friendly`/`Professional`/`Formal`), but the column is free text and `persona_derivation_service` writes arbitrary phrasing such as `"Clear, professional"`. Opening Edit reset the control to blank, and because `bot_config_fields.merge_persona_write` treats a present-but-blank persona field as a deliberate delete, saving silently wiped the stored tone and its provenance. It is now a free-text input with a `<datalist>` of suggestions, so any stored value round-trips. (2) Supporting websites reported `Needs attention` when empty; they are genuinely optional (many clients have no site) and never gated deployment, so the row now reads `Optional` with a neutral pill. (3) `_row_to_profile` did not forward `updated_at`, which `save_profile` already stamps on every write, so the library's "Last updated" column was always blank; it is now returned (additive, no existing key changed). The page's `api()` helper also no longer reports a non-JSON error body (an unhandled Flask 500 returns HTML) as a network failure. Covered by `tests/browser/bot-config.spec.js`; both new cases were confirmed failing before the fix. Note: profile saves can still fail at the database layer while migrations `039`/`040` remain unapplied — see the persona rows above |
| Profile/knowledge match validation | Implemented | `POST /api/match/check` is an LLM topical-alignment check: it asks whether the active profile's persona describes the same business as the active primary knowledge, and returns `{match, reason}`. It is **not** a malware, safe-content or PII scan. On 2026-08-17 the frontend was corrected and automated. Both `frontend/index.html` and `frontend/new_prompt.html` previously compared `knowledge.validation_status` (a display label such as `"Profile validated"`) against machine values, so the Dashboard's Validate step could never leave "Needs attention", and Bot config held the result only in memory so a reload forgot it. Both now read the tri-state `knowledge.match_result`, which `dashboard_health_service` already returned from `chatbots.last_match_result`; that service additionally forwards `match_reason` so a failure states why. Both pages now run the check automatically when both inputs exist and the stored result is NULL — the state the backend already sets on upload, on active-knowledge change and in `set_active_profile` — at most once per page load, and on the Dashboard only for admin/owner because the endpoint is `@role_required`. A `false` or unavailable result is surfaced for the user to act on and is never retried automatically. Note this spends AI credits without an explicit click, since the check runs through `ai_router.generate_system_response` |
| Behaviour Studio (merged Tune AI + Message Style + Test Bot) | Implemented | On 2026-08-18 the three Behaviour pages were merged into `frontend/behaviour.html`, a three-tab studio (1 Model, 2 Message experience, 3 Test lab) on the control-room design system. They had remained on the legacy glass system (Outfit, `--bg:#050b18`, `--primary:#3b82f6`) while the dashboard, bot config and knowledge screens moved to control-room, so half the tenant surface looked like a different product. Merging is justified by the data: Model and Message experience both write `PUT /api/bots/{id}`, and `bot_service.edit_bot` is key-presence based so partial payloads already merged safely. **Temperature was replaced with Answer style** — three named outcomes (Precise 0.2, Balanced 0.7, Creative 0.9) that say what each is for rather than exposing a sampling parameter. The raw value survives inside a collapsed Advanced disclosure, and a stored value that is not one of the three shows as a selected `Custom (n)` card so existing settings are never silently moved; the cards follow the number, so the two cannot disagree the way the mockups' side-by-side mode-cards-plus-slider would. **Test lab gained an Active setup strip** that names the profile, knowledge, model and menu in use and warns when `deployed_profile_name` is blank — the case where `rag_service.get_deployed_settings` falls back to `DEFAULT_SETTINGS` and the bot answers convincingly as someone else. One save and one dirty state now cover both editable tabs, with a `beforeunload` guard. Plan gating moved verbatim into `assets/js/model-catalog.js` rather than being retyped, since it is billing-enforcement surface. Tabs are URL-addressable (`?tab=`); `model_settings.html`, `message_style.html` and `testbot.html` are now redirects preserving `bot_id`, and the sidebar keeps its three familiar labels. No endpoint or payload changed. Covered by `tests/browser/behaviour.spec.js` (27 cases, mocked APIs — no live-backend verification) |
| Test lab: business-matched scenarios | Implemented | On 2026-08-18 the Test lab's *Try a scenario* list stopped being a fixed clinic-flavoured set ("Hi, I need to move my appointment on Friday") and is now derived per bot from its own active document via `GET /api/testbot/scenarios` → `app/services/test_scenario_service.py`. The old list was unusable for the half of the tenant base that takes no bookings: a shop testing "reschedule my appointment" learns nothing about the bot it is about to deploy. Four slots are generated, in a fixed order, following the pre-deployment set a support assistant is normally checked against — the most common request, one fact that must be retrieved correctly, one request that is out of scope and must be declined rather than invented, and one message too vague to answer. The first two prove the bot is useful; the last two prove it is safe. Slot keys are assigned server-side **by position**, so a model that invents its own key cannot change which icon or slot a row gets. Asking for a human is never derived (`HANDOFF_SCENARIO` in `app/routes/testbot_routes.py`): it means the same for every business, so it is appended last and survives an empty document and an exhausted AI balance. Failure degrades rather than blocks — no document, no readable text, a billing limit or an unusable reply all fall back to a business-neutral set plus a `note` saying why and what to do about it. The LLM call happens only after a document and its chunks are found, so nothing is billed when there is nothing to read, and the result is cached in `sessionStorage` per bot with an explicit Refresh. Text from the document is stripped of control and bidi characters before display, since a poisoned document could otherwise reorder what the operator reads before pressing Send. Covered by `tests/test_test_scenario_service.py` (10 cases on the pure parse path) and `tests/browser/behaviour.spec.js` |
| Test lab: live reply buttons | Implemented | On 2026-08-18 the Test lab began rendering the reply buttons a channel would send, so the welcome menu configured on Message experience can be tapped and tested rather than only described. A reply may end with `[BUTTONS: A | B | C]` — appended by `chat_logic_service.handle_greeting` from the saved `welcome_menu_labels`, and asked for by `rag_service`'s prompt on broad questions. Every channel strips it via `message_style_utils.parse_buttons_tag` before sending; the Test lab did not, so it printed the raw tag in the transcript, the one place a customer never sees it. `behaviour.js` now ports that parser (tag at the end, `|`-separated, labels capped at 20 characters and 3 buttons) and renders the labels as buttons under the bubble. Tapping one sends the label as the next message, which is exactly what the backend receives from a channel: Telegram returns it as `callback_data`, WhatsApp as `button_reply.title`. Buttons follow **saved** state, not the draft, because the reply came from the server reading the saved row. With quick replies off no buttons are drawn and a note says how many were not sent — the toggle's real cost, otherwise invisible. Older keyboards stay tappable as they do in Telegram, but are disabled while a request is in flight so two taps cannot interleave. Covered by four cases in `tests/browser/behaviour.spec.js` |
| Message experience preview: numbered fallback removed | Fixed | The preview claimed that turning quick replies off made the bot say "Reply with 1 for available times, or 2 to speak with our team." No such reply exists: `parse_buttons_tag` strips the tag whether or not buttons are sent, and nothing in either channel renumbers the options. An operator could therefore switch buttons off believing customers still got a numbered menu, when in fact the choice survives only inside the sentence. The preview now says what actually happens — "No buttons. The customer types their answer instead." — matching what the Test lab shows for the same setting |
| Test lab: `chatbot_id` query parameter | Fixed | The merged Test lab called `/api/testbot/context` and `/api/testbot/chat` with `?bot_id=`, but `app/routes/testbot_routes.py` reads `chatbot_id` and answers `400 chatbot_id is required`. The chat path rendered that message as the bot's reply, which is the error operators reported; the context path swallowed it and reported "Nothing is deployed yet" for every bot, deployed or not. Both now send `chatbot_id`. A failed context lookup no longer claims the bot is undeployed — it says the setup could not be checked, because sending someone to redeploy a healthy bot is worse than admitting the lookup failed. The mock in `tests/browser/behaviour.spec.js` now returns the same 400 the route does, so a wrong parameter name cannot pass again |
| Behaviour Studio: access-denied state | Fixed | The merge dropped the Phase 1 staging fix that `model_settings.html` carried: a 403/404 on the bot load bounced the operator to `bots.html` with no explanation. `behaviour.js` now shows "Chatbot not found or you do not have access." in place, hides the tabs and footer (nothing behind them is readable), and sets `botLoadFailed` so no `PUT` can follow a failed load. `tests/test_staging_phase1_regressions.py::TestModelSettingsAccessDeniedState` was retargeted from the redirect stub to `behaviour.js`, and the behaviour spec exercises the 403 end to end |
| Model selection | Implemented | Model catalog and settings UI exist |
| Flow Builder runtime | Implemented | Flow Builder remains part of the active chatbot system. Backend flow save/fetch routes, V3 draft/published persistence, AI Router interception, Test Bot integration, flow execution, safe AI/RAG handoff, and legacy `flow_data` compatibility are covered by `tests/test_flow_builder_runtime.py`; broader UI and live-channel flow verification remain needed |
| Media Attachments | Implemented | Backend, UI, and webhook dispatch created |
| Persona field unification (migration 039) | Partially implemented | `bot_config_fields.py` makes the canonical/legacy column mapping single-source and writes NULL into the deprecated `business_objective`/`response_style`/`prompt_text` mirrors. Migration `data/039_unify_bot_config_persona_fields.sql` is unapplied everywhere and its mandatory SELECT-only preflight `scripts/bot_configs_persona_unification_preflight.sql` is unrun; section 10 must be exported to the restricted archive before applying because divergent legacy values become unrecoverable. Deploying the code before the migration fails every `bot_configs` write with `23502`. See `docs/KNOWLEDGE_INGESTION_AND_DERIVED_PERSONA.md` |
| Derived persona from ingested documents | Partially implemented | `persona_derivation_service.py` fills `company_name`, `business_description`, and `tone` from the client's uploaded PDF after `POST /upload-pdf`, through `ai_router` so billing and tier enforcement apply; a non-JSON reply writes nothing. 73+32+14 focused tests pass plus real-browser `tests/browser/testbot-persona.spec.js`. Blocked from delivering its stated benefit: `rag_service.get_deployed_settings` returns `DEFAULT_SETTINGS` when `chatbots.deployed_profile_name` is blank, so an undeployed bot still replies "Your Company" — exactly the never-opened-the-form population targeted. A test pins the gap; closing it is separate create-RPC/promotion work. Residual stored prompt-injection risk: up to 1000 characters of document-chosen prose reach the serving system prompt as asserted company fact (structural newline/control-character lever closed, semantic lever open). Whether `tone` should be excluded from placeholder-matching is an open design call |
| Persona provenance and client override | Implemented | `bot_configs.persona_provenance` jsonb tags each derivable field `client_entered` or `derived` in the same INSERT/UPDATE as the value, so the two cannot disagree. A client edit flips the marker to `client_entered` and re-ingestion never overwrites it. Partial profile saves preserve omitted persona fields by key presence; `custom_prompt`, `bot_name`, `additional_instructions`, and `out_of_scope_reply` are still full-replaced. Migration `data/040_bot_config_persona_provenance.sql` is unapplied everywhere and must be applied before the code or every settings/profile save fails with `PGRST204`. No backfill by design: pre-existing rows read as unknown and are adjudicated by value. Client procedure documented in `docs/KNOWLEDGE_INGESTION_AND_DERIVED_PERSONA.md` |
| Message style & welcome menu buttons | Implemented | Welcome-menu buttons always render regardless of the interactive-buttons toggle (per product decision). The `[BUTTONS: ...]` tag is now stripped from the reply before markdown formatting on both Telegram and WhatsApp so buttons reliably render. Welcome-menu AI generation is capped at 3 labels to match the UI. Regression tests added in `tests/test_message_style_buttons.py` |


## Knowledge and RAG

| Feature | Status | Notes |
|---|---|---|
| Knowledge file upload | Implemented | External storage and full error-path verification still needed |
| Knowledge file listing | Implemented | Chatbot-scoped |
| Active knowledge selection | Implemented | Current active file behavior exists |
| Supporting knowledge toggle | Implemented | Enabled/disabled knowledge behavior exists |
| Supporting PDF relevance validation | Verified complete | Additional PDFs use candidate preflight when a Primary PDF exists: local extraction, `semantic_hybrid_v2`, bounded temporary candidate embeddings against stored Primary embeddings, and the environment-configurable `PDF_SUPPORTING_RELEVANCE_THRESHOLD` default of `0.65`. Exact duplicates are blocked separately. PASS requires explicit confirmation before Supporting ingestion; FAIL creates no normal knowledge files, chunks, GraphRAG, persona, README, or Supporting source. Confirmed Supporting PDFs remain enabled and non-active, preserve the Primary, skip persona derivation, and use `source_pdf_candidate_id` for idempotency/recovery. `original_file_name`/`display_name` keep human-facing UI names readable. Migration 045 creates the candidate/data-linkage structure; Migration 046 hardens candidate `service_role` privileges. Shared-testing/prototype manual verification passed, including Supporting RAG/Test Bot retrieval. Future staging/real production are not claimed. Known limits remain: small threshold sample, no per-row historical embedding-model metadata, bounded per-chunk validation embedding requests with small provider cost, opportunistic candidate cleanup, and local Playwright blocked where Chromium is missing |
| Website scraping | Implemented | Single URL scraping requires single_website_scraping feature; batch scraping requires batch_website_scraping; Advanced can scrape single URLs only |
| Website source prerequisite | Verified complete | Website knowledge can only be added when the chatbot has an enabled active Primary PDF. Server-side enforcement covers `/api/knowledge/scrape`, `/api/knowledge/scrape-analyze`, `/api/knowledge/scrape-batch`, `/api/knowledge/scrape-extract`, `/api/knowledge/scrape-embed`, and `/api/knowledge/ingest`; missing Primary returns HTTP 409 with `code=primary_pdf_required`. Supporting, disabled, inactive, and website sources do not satisfy the rule. The frontend keeps website controls disabled until an active Primary PDF exists, and existing website sources are not deleted or changed by this rule |
| Knowledge processing feedback | Verified complete | Primary PDF upload, Supporting PDF validation, Supporting confirmation, and website processing show a compact indeterminate progress state with a visible elapsed timer updating once per second. No fake percentage or ETA is shown. Duplicate action protection remains active while processing, a standard browser `beforeunload` warning is installed only while a long-running knowledge operation is in flight, processing state clears on success/failure, and Supporting PASS still requires explicit confirmation |
| Knowledge refinement | Implemented | Requires end-to-end verification |
| Chunk storage and retrieval | Implemented | Database/vector configuration requires environment verification |
| RAG response flow | Implemented | Quality and adversarial testing remain |
| Knowledge graph visualization | Implemented | Graph rendering and node/edge CRUD in new_linkdocs.html |
| Knowledge graph editing | Implemented | Add, rename, delete nodes; add, delete edges; focused route tests exist |
| Single-call website ingestion (`POST /api/knowledge/ingest`) | Partially implemented | Composes analyze→scrape→extract→embed in one call with per-source per-stage progress, partial success, and no roll-back of ingested siblings; reuses the four staged services, which are unchanged. 41+19 focused route tests pass. **Review verdict BLOCK — do not enable behind a proxy.** (i) The synchronous run cannot finish in any realistic proxy window: 40s of timeout budget per page (Jina 25s then static 15s) x up to 10 sources x 5 default pages is ~35 minutes before LLM and embedding calls, and over two hours at the `max_pages` ceiling of 20; `requests`' timeout is a between-bytes read gap, not a wall clock, so per-page cost is genuinely unbounded. A proxy kill loses the report, and with no idempotency key a retry re-scrapes, re-charges storage, and re-runs the billed extraction. (ii) A source can report `succeeded` with zero chunks persisted — `save_refined_knowledge_chunks` writes the quota-consuming `knowledge_files` row first and then swallows every chunking/embedding failure. (iii) **Websites only; it does not accept uploaded documents.** See `docs/KNOWLEDGE_INGESTION_AND_DERIVED_PERSONA.md` |
| Website scraping storage-quota enforcement | Verified complete | Staged website storage paths now pass authenticated `company_id` through before storage work, including `/api/knowledge/scrape`, `/api/knowledge/scrape-embed`, and `/api/knowledge/scrape-batch`; the batch route calls `scrape_website_urls_batch(..., company_id=g.company_id)` so the service's storage-quota check is not bypassed. Focused route/frontend tests passed, the broader Knowledge Workspace regression reported 223 passed with 7 existing warnings, and `git diff --check` passed |
| Conversation graph memory and keyword recall | Partially implemented | `conversation_graph_nodes` persists facts learned mid-chat (name, contact, interest) and recalls them beside the vector path; the producer reuses the existing pure-regex extractor, so no LLM call and no billing change. 35 tests plus 16 subtests pass. Blocked: (i) migration `data/041_conversation_graph_nodes.sql` cannot be certified without running `scripts/conversation_graph_nodes_preflight.sql` — `chatbots` and `conversations` have no `CREATE TABLE` in this repository, and a pre-existing relation would make `CREATE TABLE IF NOT EXISTS` a silent no-op; (ii) the write path is not tenant-filtered — the upsert conflict target is `(conversation_id, label)` and `chatbot_id` is a payload column, so a mismatched pair re-tenants another chatbot's PII row. Unreachable today only because `conversation_id` is server-derived; (iii) recall is exact-match on a single normalised ASCII token, so "what's my phone number" does not find a fact stored under `contact`, and only `name`/`contact`/`interest` are extracted (no order numbers); (iv) raw customer name, email, and phone are persisted with no expiry, in a codebase that had deliberately avoided persisting these values |
| Compiled README generation | Implemented | Automatically updates bot_<id>_readme.md on PDF uploads, graph mutations, and Q&A submissions |
| README popup viewer | Verified complete | Modal dialog next to the active PDF file in new_linkdocs.html showing parsed markdown with search, results count, next/prev navigation buttons, and scroll focus |

## AI Providers

| Feature | Status | Notes |
|---|---|---|
| Model catalog | Implemented | Static/catalog-based model definitions |
| OpenRouter routing | Implemented | External API verification required |
| DeepSeek routing | Implemented | External API verification required |
| Gemini usage | Implemented | Used in AI and/or embedding flows; verify exact active paths |
| AI usage logging | Implemented | Integrated with AI-credit charging |
| Provider fallback behavior | Implemented | Cross-provider fallback is disabled; selected-provider failures return the safe generic chatbot failure response without trying another provider |

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
| Broadcast campaigns dashboard | Verified complete | Dedicated frontend workspace and CRUD routes verified |
| Broadcast CSV uploading | Verified complete | Client-side CSV parser and pending logs registration verified |
| Broadcast CRM contacts extraction | Verified complete | Extraction of unmasked contacts from active chats verified |
| Broadcast pacing delay sending | Verified complete | Context-propagated background worker sending with 3s delays verified |

## Conversations and CRM

| Feature | Status | Notes |
|---|---|---|
| Conversation list | Implemented | Backend and frontend exist |
| Message history | Implemented | Conversation-scoped |
| Message search | Implemented | Previously reviewed in the conversation interface |
| Inbox auto-polling | Implemented | 3-second interval for escalations, conversations, and messages |
| Agent reply and dispatch | Implemented | Reply via inbox dispatches to WhatsApp, Telegram, Wasender |
| Handoff email notification | Implemented | SMTP-based email to active staff when customer requests human agent |
| Conversation deep links | Implemented | URL synchronization and direct loading were previously reviewed |
| Copy conversation link | Implemented | Previously reviewed |
| Copy transcript | Implemented | Previously reviewed |
| Download transcript | Implemented | Previously reviewed |
| CRM lead list | Implemented | Company/chatbot scoped |
| Lead status | Implemented | Canonical stages are `new`, `contacted`, `qualified`, `won`, and `lost`; the legacy CRM page and company-wide conversations pipeline use the same vocabulary. API reads and writes accept `in_progress`/`closed` aliases during the compatibility window. Migration 047 widens the database check; live schema application and browser verification remain outstanding. |
| Lead priority | Implemented | Priority editing exists |
| Lead assignment | Verified complete | Non-empty assignment uses the authenticated database-backed company context and remains gated by crm_lead_assignment; assignment clearing remains available to all plans; focused route regression tests cover success and rejection paths |
| Lead follow-up | Implemented | Follow-up fields and UI exist |
| CRM filters | Implemented | Status, assignment, and related filtering exist across the legacy CRM page and the company-wide conversations pipeline |
| CRM-to-conversation navigation | Implemented | Conversation ID linking was previously reviewed |

## Analytics and Operations

| Feature | Status | Notes |
|---|---|---|
| Dashboard metrics | Implemented | Requires broader regression tests |
| Message charts | Implemented | Data aggregation and frontend display exist |
| Live workflow status | Implemented | Requires runtime verification |
| Dashboard health | Implemented | Requires environment verification |
| Agent insights | Implemented | Server-side owner/admin access uses the database-refreshed role and preserves chatbot ownership checks; new Agent Actions and automatic CRM leads derive company ownership from the authoritative chatbot record. Staging migrations 028 and 027 hardened stored data and service-role-only access. Expanded review/dismissal/linkage lifecycle fields and frontend actions remain deferred; production database migrations remain unapplied. |
| AI-generated reports | Implemented | External model and feature-gate verification required |
| Escalation handling | Implemented | Listing and exact-ID resolution require the current database-backed owner/admin role; resolution is compare-and-set idempotent and leaves unrelated signals unchanged. Same-action retries cannot repeat the AI-resumed notification; atomic deduplication across two different concurrently resolved final actions remains deferred to the lifecycle transaction/RPC phase. Focused regression tests are present; execution remains pending in a repaired test environment. |

## Subscription and AI Credit

| Feature | Status | Notes |
|---|---|---|
| Subscription plans | Implemented | Plan catalogue active for Free trial, Essential (RM39/month), Advanced (RM89/month), and Pro (RM169/month); included AI credits are RM1 Free trial, RM5 Essential, RM20 Advanced, and RM60 Pro. Free stores `model_access_tier=economy` for compatibility, but customer-facing trial access is DeepSeek Only and the active trial provider policy is direct DeepSeek only. Public landing pricing uses a tested duplicate catalogue; the Pro public description is application-only safe copy until `subscription_plans.description` is corrected through a reviewed data migration. |
| Current subscription | Implemented | Company-scoped |
| AI-access policy resolver | Implemented | Central resolve_ai_access() in ai_access_policy.py handles trial/paid/denied states |
| Trial initialization | Implemented | New companies get Free plan + status=trialing + 7-day trial_ends_at |
| Trial provider isolation | Implemented | Active trial uses direct DeepSeek only; no OpenRouter for trials |
| Paid provider isolation | Implemented | Paid plans (Essential/Advanced/Pro) use OpenRouter only; direct DeepSeek denied |
| Bot creation enforcement | Implemented | add_bot() and edit_bot() enforce AI access policy; trial locks provider/model |
| Runtime provider enforcement | Implemented | _route_for_enforcement and _get_system_provider_for_enforcement in ai_router.py |
| ToyyibPay top-up restriction | Implemented | Active trial, Free, expired trial and past_due cannot top up AI credits |
| Provider fallback disabled | Implemented | Cross-provider fallback (deepseek->google->openai) removed for Phase 2B-2A |
| Model-tier enforcement (Phase 2B-2B) | Implemented | Economy/Standard/Premium mapping in model_catalog.py; save-time and runtime enforcement; OpenAI/Gemini/Claude/Qwen/Mistral/xAI classified |
| GraphRAG/background AI cleanup (Phase 2B-2C) | Implemented | GraphRAG routes through ai_router; website knowledge no longer hardcodes Google; AI reports no longer use Gemini fallback; all AI entry points use central provider, subscription, model-tier and credit enforcement |
| Usage summary | Implemented | Usage data exposed in billing UI |
| Default subscription | Implemented | Created during company onboarding; new companies receive Free plan with 7-day trial (status=trialing); expired trials denied AI access |
| Subscription limit enforcement | Implemented | Guard layer with fail-closed fallback; missing subscriptions resolved to Free plan or denied |
| Feature flag enforcement | Implemented | Keys: single_website_scraping, batch_website_scraping, crm_lead_assignment, ai_generated_reports, ai_assisted_menu_generation |
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

Latest recorded full automated suite:

```text
1534 passed, 1 skipped, 143 subtests passed
```

- Focused workspace, Team, invitation, Google configuration, and tenant-scoping tests passed.
- Rate-limit tests verified normal-startup enforcement, same-IP blocking, independent IP and endpoint buckets, disabled mode, test-application isolation, and rejection before protected writes, invitation acceptance, excess password hashing, or external Google verification.
- Python compilation passed.
- Invitation-page and Team-page JavaScript syntax validation passed.
- Diff validation passed.
- Manual resend verification produced one POST request and one email.
- Manual cancellation verification returned HTTP 200, removed the invitation, changed pending invitations from 1 to 0, and restored available seats from 2 to 3.
- `/api/workspace` returned HTTP 200 after resend, cancellation, and Profile load.
- Live visual browser verification and external Google verification are still required.

## Cross-Cutting Items Requiring Investigation

- Live Supabase row-level security configuration
- Version-controlled definitions for all production RPC functions
- Exact current external integration readiness
- Production deployment configuration
- Full route-level tenant-isolation review
- Frontend automated test strategy
- Current removal readiness of legacy backup files
- Transactional company registration
- Transactional invitation acceptance
- Database-level protection against concurrent duplicate pending invitations
- Trusted reverse-proxy/client-IP handling for public rate-limit keys
- Redis or equivalent shared production limiter storage for multi-worker enforcement
- Live shape of `public.bot_configs`, `public.chatbots`, and `public.conversations` (no `CREATE TABLE` for any of them exists in this repository; migrations 039/040/041 all depend on catalog captures that have not been taken)
- Retention and data-subject-deletion policy for customer PII persisted in `conversation_graph_nodes`
- Wall-clock bounding and idempotency for synchronous multi-page scraping requests
- Whether a `derived` persona value should be fenced in the serving system prompt the way retrieved chunks are

## Document Maintenance

Update this file after:

- Completing a development phase
- Adding or removing a major feature
- Changing an integration
- Changing billing or database behavior
- Completing meaningful verification

Do not record temporary branch names, commit hashes, local paths, or working-tree status here.
## Phase 4E — Subscription Billing History and Customer Receipts

**Status:** Verified complete

- Order history listing with pagination and status filtering
- Order detail API with safe fields
- Printable HTML receipt with "Not a tax invoice" wording
- JSON receipt endpoint
- Billing history and AI-credit CSV exports
- Profile billing history UI with order reference, amount, dates, status badges
- Order detail modal with retry button
- Customer support guidance for manual-review states
- Data accuracy guarantees (amount from order, timestamps consistent, no reversal leakage)

## Phase 4F — Production Security, Tenant Scope and Plan Enforcement Audit

**Status:** Verified complete

- Data-scope matrix: company-scoped vs bot-scoped resources
- Billing/credit authorization: company_id resolved from JWT, client-supplied ignored
- Company-wide billing presentation with shared-credit explanation
- Plan-limit enforcement matrix with guards for all resource types
- Security hardening: authentication, webhook verification, UUID validation
- Reconciliation job safety checks
- Structured monitoring logs for billing lifecycle events
- Health check endpoint
- Phase 4F runbook

## Phase 4G — Admin and Support Operations

**Status:** Verified complete

- Authorization model documented (company owner/admin vs platform admin)
- Support search repositories and API
- Admin order listing with filters
- Admin reconciliation endpoint (idempotent, reuses canonical service)
- AI-credit support inspection
- Auditable credit adjustment RPC design
- Billing support runbook

## Phase 4H — Customer Receipts, Exports, and Usage Reporting

**Status:** Verified complete

- Printable HTML payment receipt
- JSON receipt endpoint
- Canonical receipt building helper
- Billing history CSV export with injection protection
- AI-credit activity CSV export
- AI-credit usage summary API
- Profile UI enhancements (receipt, export, summary cards)
- Email receipt: deferred (no approved email service)
- Migration 014: not required

## Phase 4I — Subscription Renewal, Grace Period, and Failed-Payment Recovery

**Status:** Implemented

## Phase 4J ? Billing Notifications and Customer Communication

**Status: Complete**

- In-app billing notifications with event-key deduplication
- Renewal reminders at 7/3/1-day thresholds and expiry day
- Grace-period started/ending notifications
- Payment confirmed and activation notifications
- AI-credit low/critical/depleted alerts
- Company-scoped notification API
- Notification generation job

## Phase 4K ? Advanced Billing and Usage Reporting

**Status: Complete**

- Monthly billing summaries and trends
- Plan-usage reporting against limits
- CSV exports of all reports
- Integer arithmetic, company isolation

## Phase 4M ? Production Launch Audit and Remediation

**Status: Complete**

- Rate limiting (Flask-Limiter)
- CORS hardening
- Hardcoded URL fix
- Development route isolation
- Auth/billing endpoint rate limits
- Full test suite: 1,084 pass

## Phase 4L - Platform-Admin Read-Only Backend and Frontend

**Status: Original scope staging verified; later extensions have mixed local
and prototype/shared-testing evidence; production blocked**

The original five platform-admin endpoints retain their historical staging
verification. Later extensions have mixed evidence: some remain
local/application-tested only, while Phase 5, Phase 6, Phase 7, and later
hardening paths have prototype/shared-testing runtime verification where
explicitly recorded. Unless explicitly stated otherwise, later extensions are
not staging verified and are not production deployed. At the current local
implementation, localhost manual verification recorded on 2026-08-03 passed for
the full current twelve-route read-only investigation stack: dashboard, operational alerts,
company directory/detail, subscription summary/history, AI-credit usage and
transactions, billing orders, users, chatbots, Support Workspace, Audit Logs,
billing-order audit filters, and local revocation with Access Denied and stale
platform-data clearing. This does not establish staging verification or
production readiness. The complete platform-admin surface additionally includes
separately approved bounded support-case, platform-admin user-management, and
company lifecycle mutation routes; those later mutation routes are not staging
verified.

- Separate active `platform_admin_users` mapping required on every request;
  tenant owner/admin/member roles never grant platform access
- Twelve GET-only investigation endpoints for platform identity, operations overview, company directory/detail,
  subscription summary, current-period AI-credit/usage summary, and lazy
  read-only subscription-history, AI-credit transaction history, billing-order history,
  company users, company chatbots, and audit-log
  inspection. The original five endpoints were verified in staging; later
  operations-overview, users/chatbots, subscription-history, AI-credit
  transaction-history, billing-order history, and audit-log viewer extensions
  have mixed local and prototype/shared-testing evidence where explicitly
  recorded, and are not automatically staging verified or production deployed.
- Cross-tenant reads isolated in dedicated platform repositories with explicit
  safe projections and mandatory audit-before-response behavior
- Automated authorization, repository, route, and audit tests added
- Manual staging verification passed for all five endpoints and expected audit
  events, including metadata redaction and immediate revocation
- Separate read-only frontend implemented for platform identity, exact company
  counts, server-paginated company search, company billing/AI-credit detail, and
  lazy read-only subscription-history, AI-credit transaction-history, and company users/chatbots sections. A bounded application-only
  Platform Operations overview now adds one GET-only locally tested dashboard
  endpoint for company counts, latest-subscription status counts, latest-plan
  distribution, and at most 10 past-due/expired attention companies using
  `created_at DESC, id DESC` latest-subscription semantics. Operational Alerts
  Phase 1 extends this same dashboard and `/overview` response with typed
  read-only subscription past-due/expired alerts derived from existing
  attention data. Phase 6 later adds deterministic aggregate alerts for
  support backlog, pending and reconciliation-required billing orders,
  depleted AI-credit balances, retry backlog, and integration channel
  attention without adding a mutation route. AI low-balance alerts remain
  deferred because no threshold is approved; generic background job monitoring
  remains deferred because no durable telemetry exists; provider-cost
  monitoring, inactive-company and no-current-chatbot alert variants, charts,
  exports, and overview remediation/write actions remain deferred. The older
  Phase 2 alert definitions and approval gates are recorded in
  `docs/PLATFORM_ADMIN_OPERATIONAL_ALERTS_CONTRACT.md`.
- A separate platform-admin Support Workspace is implemented as tenant
  investigation with controlled internal case operations. It is distinct from tenant `support.html`, reuses only
  existing `/overview` and `/companies` APIs after the fresh `/me` gate, and
  links operators into existing company investigation pages. Support Cases
  Phase 1 is implemented for internal platform-admin use and verified in the
  main shared testing Supabase with fake/team data; this is not staging or
  production verification. Platform-admin Support Case Operations Phase 2 is
  implemented and verified only in the main shared testing Supabase with
  fake/team data. It adds operation-specific assignment, status, priority, and
  internal-note controls, a server-provided case timeline, and Migration 032
  trusted RPCs for atomic mutation/event/audit writes. Verified fake/team
  evidence covers assignment, status/priority changes, internal notes,
  no-op/invalid-transition rejection without extra event/audit rows,
  close/reopen `closed_at` behavior, least-privilege grants, RLS/policies, and
  service-role-only RPC execution. This is not staging or production
  verification. Platform-admin Tenant Communication Phase 3 is verified only
  in the main shared-testing Supabase with fake/team data: it adds tenant-visible reply composer/history, tenant support
  request history/detail, `tenant_reply_created` activity, safe reply audit
  metadata, and pending in-app support notification outbox records through
  Migration 033. This is not staging verification and does not establish
  production readiness. Live chat, external email, attachments, impersonation, billing
  actions, exports, charts, SLA timers, escalation automation, and production
  use remain blocked. The workflow contract is documented in
  `docs/PLATFORM_ADMIN_SUPPORT_WORKFLOW_CONTRACT.md`.
  Current prototype hardening is complete: Migration 043
  (`data/043_atomic_platform_support_case_creation.sql`) creates
  `platform_support_cases`, the initial `platform_support_case_events` row,
  and the `platform_admin_audit_events` create audit atomically through
  `public.create_platform_support_case(...)`; the application service no
  longer performs duplicate application-side create/audit inserts. Support-case
  detail history is bounded with `event_limit`/`event_offset` (default 25,
  maximum 100), tenant-visible replies use `limit`/`offset` (default 25,
  maximum 100), and reply-notification reads are restricted to notification
  rows linked to reply IDs on the returned page. Frontend Load More appends
  timeline events by `id`, replies by `reply_id`, and notifications by
  `notification_id`; not-found support-case and reply-list reads return the
  intended 404 instead of an audit-validation 503. The assignee endpoint now
  returns only `id`, `user_id`, `is_active`, `user_full_name`, and
  `user_email`; assignment still submits `platform_admin_users.id` mapping IDs,
  active mappings are the only selectable assignees, and inactive historical
  current assignees remain visible with a safe fallback without becoming
  assignable.
  SQL execution requires project/ref/environment preflight evidence. Migration
  029 controlled application/rollback evidence is recorded in the access
  lifecycle for the Supabase project that was labeled main/PRODUCTION; under
  the current environment interpretation, that evidence belongs to the
  prototype/shared-testing boundary and does not establish deployment to the
  future real production environment. Future SQL/testing is limited to
  confirmed local/dev, the approved prototype/shared-testing environment with
  fake/team data, or approved staging targets. Future real production remains
  blocked.
  Tenant support submission is governed by
  `docs/TENANT_SUPPORT_SUBMISSION_CONTRACT.md`; its backend endpoint and
  bounded frontend form are implemented locally. Migration 030 is applied and
  verified only in the main shared testing Supabase with fake/team data, and
  local browser/API E2E verification passed with fake data. This is not staging
  verification or production readiness; the platform-admin support-case tables
  and mappings were not modified.
  The read-only tenant-support intake viewer is implemented locally under
  `docs/PLATFORM_ADMIN_TENANT_SUPPORT_INTAKE_VIEWER_CONTRACT.md` with two
  GET-only routes and a separate Support Workspace section. No SQL was required;
  Migration 030 remains verified only in the main shared testing Supabase with
  fake/team data. This is not staging verification or production readiness.
  Tenant Support Intake Review/Conversion is implemented locally and verified
  only in the main shared testing Supabase with fake/team data. Migration 031
  was applied there and browser/API E2E passed locally: request 1 was reviewed
  then converted, producing internal case 2 exactly once. This is not staging
  verification or production readiness; production remains blocked.
- A separate platform-admin Audit Logs viewer is implemented as a read-only,
  application-only local extension. It adds one audited GET-only endpoint,
  `GET /api/platform-admin/audit-events`, displays actor mapping IDs and safe
  metadata summaries only, and does not expose raw metadata, tenant records,
  exports, downloads, charts, audit editing, audit deletion, or platform-admin
  user management. The original investigation inventory remains twelve
  GET-only routes; Support Cases now adds operation-specific bounded
  GET/POST/PATCH paths. Phase 2 and Phase 3 are verified only in the main
  shared-testing Supabase with fake/team data.
- A bounded platform-admin Billing Order History section is implemented as a
  read-only, application-only local extension on company detail. It adds one
  audited GET-only endpoint,
  `GET /api/platform-admin/companies/<company_id>/billing-orders`, lists safe
  mutable `company_subscription_orders` records only, displays `amount_sen` as
  integer sen as stored, returns no currency and infers no MYR, and excludes
  payment/gateway/checkout/reference, idempotency, raw-error, reconciliation,
  retry, activation, manual-credit, export/download, chart, and write behavior.
  The current read-only investigation inventory is twelve GET-only routes. The
  complete platform-admin surface additionally includes operation-specific
  bounded support-case, user-management, and company lifecycle mutation paths.
  Phase 2, Phase 3, Phase 4, and Phase 5 shared-testing evidence remains
  environment-scoped and does not establish staging or production readiness.
  The billing-order audit-filter fix changed frontend filtering only; it added
  no route or backend behavior change.
- Frontend performs a fresh `/me` authorization check on every page entry,
  clears cross-tenant state on denial or unavailability, and never trusts tenant
  roles, cached users, JWT claims, local flags, or hidden navigation
- Tenant pages now use a shared top-right account menu for Profile, Support,
  and Logout. Support points to an authenticated tenant help page with a
  bounded local support-submission form. The optional Platform
  Administration menu item is discovered lazily through a live
  `/api/platform-admin/me` check and is not stored or placed in the tenant
  sidebar.
- Focused frontend source-contract tests cover endpoint restrictions, request
  cancellation, state clearing, safe rendering, accessibility, and responsive
  behavior
- `scripts/platform_admin_smoke_check.py` provides a read-only local/staging-
  ready HTTP smoke check for the current twelve-route investigation stack. It accepts the
  bearer token only from the environment, never prints response bodies or
  credentials, and does not establish staging verification or production
  readiness.
- Access request, revocation, replacement, and periodic-review procedure is
  documented in `docs/PLATFORM_ADMIN_ACCESS_LIFECYCLE.md`; it adds no access,
  mapping management, write controls, or production authorization.
- Platform-admin User Management Phase 4 is implemented locally with bounded
  directory/detail, add-existing-user, activate, and deactivate workflows.
  Migration 034 is applied and structurally verified only in the approved main
  shared-testing Supabase with fake/team data. Company 29 is explicitly
  registered as the protected internal company for main shared-testing only;
  it is not a staging or production designation and is not hardcoded into the
  application. Shared testing currently has only one active user in company 29,
  user 32, and that user already has the sole platform-admin mapping, so the
  successful create-mapping shared-testing E2E remains pending until a second
  approved active fake/team user exists. Migration 035 is applied and verified
  only in the approved main shared-testing Supabase with fake/team data; it
  corrected only the Phase 4 RPC audit endpoint metadata, preserved RPC
  ownership/security/EXECUTE posture, did not create mappings, did not create
  Phase 4 mutation audit events merely by application, and did not alter
  existing audit rows. Staging verification and production readiness remain
  blocked. Migration 044
  (`data/044_platform_admin_user_recent_activity_batch.sql`) is applied and
  runtime verified in prototype/shared-testing only. It eliminates the
  platform-admin directory recent-activity N+1 pattern: before, the directory
  used one mapping query, one users query, and N audit queries; now it uses one
  mapping query, one users identity batch query, and one
  `get_latest_platform_admin_activity` RPC. The
  `recent_platform_admin_activity_at` field means the latest
  `platform_admin_audit_events.created_at` for that platform-admin mapping, or
  explicit null when no audit activity exists. It is not last login, user
  activity, mapping `updated_at`, or account modification time.
- Platform-admin Tenant and Company Administration Phase 5 is implemented and
  verified for the current milestone in the approved main shared-testing
  Supabase with fake/team data. It includes the global company directory,
  Company Detail investigation, company users and chatbot/configuration
  inspection, current subscription context, subscription history, AI-credit
  usage and transaction history, billing-order history, controlled
  suspend/restore, protected internal-company safeguard, centralized inactive-
  company operational enforcement, Company Detail support-history integration,
  company-filtered Support Workspace navigation, and company-related Platform
  Admin audit navigation. Migration 036 is applied and verified only in the
  approved main shared-testing Supabase with fake/team data. It constrains
  `companies.status` to non-null `active`/`inactive`, keeps `companies` RLS
  disabled and not forced, tightens direct companies privileges to no browser-
  role access and service_role `SELECT`, `INSERT`, and `UPDATE` only, and
  exposes service-role-only `SECURITY INVOKER` suspend/restore RPCs with
  `search_path=pg_catalog`.
  Shared-testing lifecycle evidence includes the earlier company 23
  suspend/restore cleanup with audit events 355 and 356, plus controlled
  runtime verification on approved fake/team company 34, `Autobot Company`,
  chatbot 52. Company 34 was suspended and restored twice and left active:
  audit events 527/538 covered the representative runtime matrix, and audit
  events 541/542 covered the final targeted `/api/chat/test` repair check.
  Representative live checks verified chatbot mutation, knowledge mutation,
  `POST /upload-pdf`, Telegram config mutation, and `/api/chat/test` reject
  suspended companies with `403 company_suspended` while preserving intended
  Platform Admin reads, tenant support/history reads, and safe knowledge
  graph/README reads. PDF upload rejection occurs before file processing,
  quota checks, `save_uploaded_pdf`, embeddings, chunks, graph generation,
  README/history generation, chatbot runtime changes, and persona derivation.
  The final test-chat check confirmed AI usage rows stayed `0`, AI-credit
  transaction count stayed `3`, included balance stayed `20000000` micro-MYR,
  top-up balance stayed `0`, no provider execution occurred, and chatbot
  runtime/configuration was unchanged. Protected company 29 rejected suspend
  with `protected_company` and remained active. CRM mutation was not exercised
  live because company 34 had no suitable CRM lead and no risky data was
  manufactured; local automated CRM enforcement coverage exists. Phase 5 does
  not provide tenant impersonation, arbitrary tenant data access, raw tenant
  messages, AI prompts/responses, provider payloads, API credentials, payment
  secrets, unrestricted configuration inspection, financial mutations, true
  tenant application audit history, Phase 4 account-management expansion,
  duplicate Phase 6 monitoring, or Phase 7 financial mutation controls.
  Staging verification and production readiness remain blocked.
- Platform-admin Platform Monitoring Phase 6 is implemented locally as a
  read-only extension of `GET /api/platform-admin/overview`; no new
  platform-admin mutation routes were added.
  It adds platform summary, support operations, messaging and integration
  health, billing attention, AI usage and credits, and platform-admin activity
  aggregates, plus deterministic aggregate alerts for support backlog, pending
  and reconciliation-required billing orders, depleted AI-credit balances,
  retry backlog, and integration channel attention. Existing subscription
  alerts remain. Read-only inspection in the approved main shared-testing
  Supabase with fake/team data confirmed all required monitoring tables and
  fields exist and current index coverage is sufficient for the first
  implementation. The original PostgREST aggregate implementation failed in
  shared testing because REST aggregate select syntax such as
  `status,count:id.count()` returned HTTP 400, so Migration 037 was introduced
  and verified only in the approved main shared-testing Supabase with fake/team
  data. Migration 037 adds one bounded read-only
  `public.get_platform_admin_monitoring_overview()` RPC, executable only by
  service_role, with `SECURITY INVOKER`, `search_path=pg_catalog`, no writes,
  no dynamic SQL, no RLS/table-privilege weakening, and platform-admin activity
  filtered to current approved audit actions and resource types. Existing
  company/subscription overview reads remain separate from the monitoring RPC.
  Runtime verification against the approved main shared-testing Supabase plus
  localhost frontend/API returned 200 for `/api/platform-admin/me`, the
  monitoring RPC, and `/api/platform-admin/overview`; the Platform Operations
  dashboard rendered and the Temporarily Unavailable state disappeared.
  The current milestone also verifies the local repository/source tests and a
  full Platform Admin browser suite for the visual dashboard and Superadmin UI
  polish. The dashboard is intentionally a concise operations summary rather
  than a full analytics explorer: detailed investigation remains on Companies,
  Company Detail, Support, Billing, and Audit Logs. It preserves read-only
  aggregate visibility into company counts, active users, support workload,
  support status, operational alerts, messaging delivery/channel health, retry
  backlog, AI request/token activity, depleted AI-credit balance signals,
  billing/order attention, companies requiring attention, and aggregate
  platform-admin activity. It deliberately excludes unsupported SLA/overdue
  metrics, generic failed-job monitoring, fabricated trends, real-time online
  users, detailed provider incident telemetry, financial mutation controls, raw
  message content, AI prompt/response content, raw audit metadata, and raw
  financial/provider payloads. The Superadmin workspace now has a more
  consistent operational UI across Dashboard, Companies, Company Detail,
  Support, Billing, Audit Logs, and Platform Admin Management, including shared
  page hierarchy, improved panels/tables/cards, clearer filters, mobile card
  alternatives, responsive behavior, and reduced dashboard information density.
  This is not staging verification and does not establish production readiness.
  Unsupported aggregate values fail closed.
- Platform-admin Billing & Subscription Oversight Phase 7 is implemented for
  the current read-only milestone as a Platform Billing & Subscriptions page with
  `GET /api/platform-admin/billing/overview` and
  `GET /api/platform-admin/billing/companies`. Migration 038 is applied and
  verified only in the approved main shared-testing Supabase with fake/team
  data. No additional Phase 7 billing migration beyond Migration 038 was
  required; Migration 043 belongs to the later atomic support-case creation
  hardening. Migration 038 adds
  `public.get_platform_admin_billing_overview()`,
  `public.get_platform_admin_billing_companies(integer, integer, text, text,
  boolean)`, and updates `public.get_platform_admin_monitoring_overview()` so
  `platform_admin.billing.overview.read`, `platform_admin.billing.company_list`,
  `platform_billing_overview`, and `platform_billing_companies` are included in
  Platform-admin Activity. Local runtime verification returned 200 for
  `/api/platform-admin/me`, `/api/platform-admin/overview`,
  `/api/platform-admin/billing/overview`, and
  `/api/platform-admin/billing/companies?limit=25&offset=0`; the frontend
  rendered Subscription status, Plan distribution, Active plan catalogue,
  Subscription order attention, AI-credit top-up attention, AI Credit Overview
  with MYR-formatted balances, Billing Notifications, Subscription lifecycle,
  and Tenant Billing Directory. Companies without subscriptions are included
  with `subscription_status = null`, `current_plan = null`, null period dates,
  and false pending/cancellation flags. Filtering, counting, stable
  `company_id ASC` ordering, and pagination happen inside PostgreSQL.
  Responsive/accessibility hardening was verified locally through source and
  Playwright browser tests: desktop tables remain available, mobile Billing
  overview and Tenant Billing Directory cards remain visible below 767px, the
  directory filters have explicit labels for Subscription status, Plan code,
  and Attention, hostile Billing values render as text, and mobile View Company
  navigation opens `platform-admin-company.html?company_id=<id>`. Latest focused
  evidence is 54 frontend source tests with 14 subtests, a 5-test Billing
  browser group, and a 70-test full Platform Admin browser suite. A broader
  Phase 7 regression scope previously passed with 153 tests and 271 subtests.
  Phase 7 remains read-only: manual AI-credit adjustment, payment
  reconciliation mutation, refund, subscription correction/override, manual
  plan change, direct balance editing, payment retry mutation, manual credit
  reversal, and billing impersonation/remediation controls remain deferred.
  Direct balance editing is not appropriate for this milestone. Subscription
  history is persisted `company_subscriptions` records, not a true
  event-sourced plan/status transition history. This is not staging
  verification and does not establish production readiness.
- The lifecycle document now includes a redacted access, revocation, smoke,
  audit-log, and localhost/staging/production evidence checklist; it does not
  change the current local-only verification boundary.
- Local smoke evidence recorded on 2026-08-03 against localhost
  (`http://127.0.0.1:8000`): all twelve checks passed with an approved company
  ID; the four required checks passed and child checks were correctly skipped
  without a company ID; and removing `PLATFORM_ADMIN_TOKEN` failed safely with
  the required configuration error. This remains localhost evidence only and
  requires an approved environment and token for any local/staging use.

### Local read-only investigation coverage checklist

This checklist describes the current localhost-only investigation surface. It
does not establish staging verification or production readiness; production
remains blocked.

| Route | Purpose and safe read-only coverage | Intentionally excluded |
|---|---|---|
| `/me` | Confirm current platform-admin identity and active mapping shape | Tenant-role authority, token details, mapping management |
| `/overview` | Show company/subscription summaries and typed operational alerts | Writes, charts, exports, global activity, remediation |
| `/audit-events` | List safe audit-event summaries, filters, actor mapping IDs, and approved metadata fields | Raw payloads, secrets, exports, editing, deletion, retention controls |
| `/companies` | Search, filter, sort, and page safe company directory fields | Customer content, mutations, bulk actions, deletion, export |
| `/companies/<company_id>` | Inspect safe company profile and status fields | Full tenant records, impersonation, edits, customer content |
| `/companies/<company_id>/subscription` | Read current subscription summary and safe plan fields | Activation, plan changes, cancellation, payment actions |
| `/companies/<company_id>/subscription-history` | Read persisted subscription history rows and safe plan/status fields | Guaranteed event-sourced timeline, reconciliation, lifecycle changes |
| `/companies/<company_id>/ai-credit-usage` | Read current-period balance, usage summary, and safe period fields | Credit adjustment, charging, provider economics, raw usage payloads |
| `/companies/<company_id>/ai-credit-transactions` | Read safe ledger deltas, balances, transaction types, and periods | Manual credit, reversal, payment references, provider payloads |
| `/companies/<company_id>/billing-orders` | Read safe order status, amount-in-sen, plan, activation, and lifecycle timestamps | Payment/gateway details, checkout, retry, reconciliation, manual credit |
| `/companies/<company_id>/users` | Read safe company-user identity, role, status, and timestamps | User management, role changes, credentials, invitations |
| `/companies/<company_id>/chatbots` | Read safe chatbot identity, state, configuration summary, and timestamps | Bot edits, messaging, credentials, deployment, customer content |
- Staging browser verification passed for the dashboard, company directory,
  company detail, read-only controls, tenant-app return path, and logout
- Post-verification revocation was confirmed: refresh showed Access Denied and
  no stale platform data remained visible
- Bootstrap mapping remains present and inactive after the browser verification
  revocation; no production deployment occurred and existing production gates
  remain open
- Phase 4 production-readiness package prepared with preflight/approval gates,
  deployment and rollback procedures, audit metadata/retention policy,
  monitoring, completed final staging rehearsal evidence, and emergency
  revocation runbook
- Migration 026 append-only trigger applied and verified in staging: postgres
  owner, SECURITY INVOKER, fixed pg_catalog search path, minimized function
  EXECUTE, enabled row-level UPDATE/DELETE rejection, and unchanged RLS/grants
- Rollback-only staging verification proved INSERT/SELECT success, stable
  UPDATE/DELETE rejection through service_role, temporary-row removal, and
  rollback of temporary mutation grants; the mapping remained inactive
- Final Phase 4 staging rehearsal completed successfully: inactive-state denial,
  time-bounded reactivation, dashboard/directory/detail and exact-count checks,
  approved audit INSERTs and metadata, and post-revocation state clearing passed
- The rehearsal ended with the mapping present and inactive; refresh showed
  Access Denied with no stale company, subscription, or AI-credit data, and no
  production SQL or deployment occurred
- Production remains blocked pending protected-company/bootstrap/executor
  approvals, exact archive configuration, formal audit-policy approval, backup
  restore evidence, monitoring activation, migration 026 production approval,
  and final go/no-go

Additional current blockers are the absence of a confirmed staging/online
environment in repository configuration, lack of staging verification for the
latest extensions, pending production ownership/executor approval, and pending
monitoring, rollback, and backup evidence.

## Guided Knowledge Ingestion, Derived Persona, and Conversation Memory

**Status: Implemented locally; unmerged; three of four workstreams blocked;
migrations unapplied everywhere**

All of this work exists in the working tree only. No migration in the
`039` → `040` → `041` sequence has been applied to any environment, and two of
the three have a mandatory SELECT-only preflight that has not been run. Full
detail, including the client-facing override procedure and the operator
migration runbook, is in `docs/KNOWLEDGE_INGESTION_AND_DERIVED_PERSONA.md`.

- `POST /api/knowledge/ingest` runs the four website-scraping stages in one
  call with per-source per-stage progress and partial success. Gated on
  `batch_website_scraping` and the knowledge-file quota, checked before the
  billed extraction. Review verdict is BLOCK on three grounds: no wall-clock
  bound and no idempotency key on a synchronous run that can exceed any proxy
  window; a source that reports `succeeded` with zero chunks persisted while
  storage is charged; and websites only, with no uploaded-document support.
  The earlier staged batch-route storage-quota skip has been fixed by passing
  authenticated `company_id` into `scrape_website_urls_batch`, but the
  synchronous/idempotency and zero-chunk-success limitations remain.
- Persona derivation fills `company_name`, `business_description`, and `tone`
  from the client's own uploaded document, tagging each `client_entered` or
  `derived` in `bot_configs.persona_provenance`. A client edit flips the marker
  and re-ingestion then leaves the value alone permanently. The override
  procedure is the one clean, shippable part of this work.
- The derived persona does not reach generated replies for a bot whose
  `chatbots.deployed_profile_name` is blank, which is the population the feature
  targets. A residual stored prompt-injection risk remains: the structural lever
  is closed, the semantic one is not.
- Conversation graph memory persists mid-chat facts and recalls them by exact
  keyword beside the vector path, adding no LLM call and no billing change.
  Blocked on an uncertified migration, a write path that is not tenant-filtered,
  single-ASCII-token exact-match recall, and unexpiring raw customer PII.
- Recorded focused test evidence at the current working tree: 73 + 32 + 14
  persona, 35 (plus 16 subtests) conversation memory, 41 + 19 ingestion routes.
  Real-browser Playwright coverage for the derived persona exists as
  `tests/browser/testbot-persona.spec.js`. This is local evidence against a
  working tree; it is not staging verification and not production readiness.

## Platform Limitations

| Limitation | Status |
|---|---|
| Single-call website ingestion | Blocked. Synchronous run is unbounded and non-idempotent; `succeeded` can mean zero chunks persisted; websites only, no uploaded documents |
| Derived persona reaching replies | Blocked for bots with a blank `chatbots.deployed_profile_name`; requires separate create-RPC/promotion work |
| Conversation memory recall quality | Exact match on a single ASCII token; only `name`, `contact`, and `interest` are extracted |
| Conversation memory PII retention | No expiry; cleanup only by conversation or chatbot cascade |
| Migrations 039/040/041 | Unapplied everywhere; two mandatory preflights unrun |
| Platform-admin controls | Original five-endpoint backend/frontend verified in staging. Later extensions have mixed evidence: some remain local/application-tested only, while Phase 5, Phase 6, Phase 7, and Migration 043/044 hardening paths have prototype/shared-testing runtime verification where explicitly recorded. Later extensions are not automatically staging verified, and real production remains blocked |
| Platform-admin Support Workspace | Implemented as tenant investigation with controlled internal case operations; Support Cases Phase 2/Migration 032 and Tenant Communication Phase 3/Migration 033 are verified only in main shared testing Supabase with fake/team data. No live chat, generic messaging, impersonation, billing actions, exports, charts, SLA automation, staging readiness, or production use |
| Platform-admin Tenant and Company Administration | Implemented and verified for the current milestone in main shared-testing Supabase with fake/team data. Includes company directory/detail investigation, users/chatbots, subscription and AI-credit context/history, billing orders, support-history integration, company-filtered audit navigation, controlled suspend/restore, protected-company safeguard, and centralized inactive-company enforcement. Company 34 (`Autobot Company`, chatbot 52) was suspended/restored and left active; representative chatbot, knowledge, PDF upload, Telegram config, and `/api/chat/test` inactive checks returned `403 company_suspended` without side effects. Company 29 protected suspend returned `protected_company` and remained active. CRM mutation was not live-tested because no suitable CRM lead existed; local coverage exists. It does not provide tenant impersonation, true tenant application audit history, financial mutations, staging readiness, or production use |
| Platform-admin Tenant Communication | Verified only in main shared-testing Supabase with fake/team data; Migration 033 adds tenant-visible replies, `tenant_reply_created` case events, safe reply audit metadata, and a pending in-app support notification outbox. This is not staging verification and does not establish production readiness; email and attachments remain deferred |
| Automatic recurring billing | Deferred (ToyyibPay limitation) |
| Email/SMS delivery | Deferred (no provider) |
| Direct tenant support contact/tickets | Implemented locally as bounded submission plus tenant-visible reply history for the signed-in requester; no live chat, email, attachments, staging readiness, or production use |
| Platform-admin tenant support intake viewer | Implemented locally as separate read-only GET list/detail routes and Support Workspace section; no mutation, conversion, reply, export, staging verification, or production use |
| Platform-admin tenant support intake review/conversion | Runtime code and Migration 031 verified only in main shared testing Supabase with fake/team data; case 2 conversion, safe audit metadata, service-role-only RLS/EXECUTE, and mapping baseline verified; not staging or production-ready |
| PDF receipts | Open (HTML only) |
| Cross-company dashboard | Bounded read-only cross-tenant operational monitoring aggregates are implemented locally through `GET /api/platform-admin/overview` in Phase 6. Generic/unrestricted cross-company analytics, arbitrary global drilldowns, charts, exports, unrestricted tenant browsing, and remediation/write controls remain deferred |
