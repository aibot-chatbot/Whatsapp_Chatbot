# Document-derived industry templates

Deployment update (2026-09-23): migration 062 was applied in two transactions and
validated; the reviewed implementation is deployed in Fly v36 (`f3f7f77`). The
local evidence below does not establish real-model classification accuracy. No
existing Bot was automatically reclassified. See [release evidence](ANALYSIS_IMPLEMENTATION.md).

## Merchant workflow

1. Upload a readable primary PDF in **Add knowledge**. Industry identification
   shares the existing paid persona derivation call and its entitlement checks.
2. Open **Review instructions**. Review the suggested industry, source excerpts
   and document checklist; correct the industry when the suggestion is uncertain.
3. Choose **Confirm and apply industry**. This applies only the fixed industry
   reply rules to this bot. It does not save the other profile fields or connect
   a publishing channel.

To correct a confirmed choice, choose **Change industry**, select another template
and confirm again. Opening this review keeps the current template effective and
does not spend another AI call or require uploading the document again.

Uploading another document creates a new suggestion. The previously confirmed
industry remains effective until an owner or admin confirms the new suggestion.
Supporting documents and websites do not switch the primary industry. Empty or
failed extraction and denied AI entitlement do not generate a successful suggestion.
Existing documents require another primary upload to generate the first suggestion;
this change does not silently classify every existing bot or spend a backfill's AI
credits.

## First catalog

| Template | Answering scope | Boundary |
| --- | --- | --- |
| Restaurant | Documented menu, location, opening hours, prices, policies | Menus do not establish table availability or confirm reservations. |
| Clinic | Published services, doctors, opening hours, contact and administrative procedures | No diagnosis, prescriptions, dosage advice or clinical triage. |
| Tuition center | Subjects, grades, language, lesson formats, published schedules, trial and application rules | A timetable does not establish vacancies, a booking or approved enrollment. |
| General | Grounded business questions and human help | Fallback for other businesses; no additional action permissions. |

The catalog is versioned. Keep published versions immutable when adding another
version. A template supplies reviewed instructions, clarification topics and a
merchant checklist. The checklist is **not** a claim that a document was checked
for every missing fact. No tool, booking, queue, payment or enrollment integration
is enabled by confirming an industry.

## Storage and request boundary

Migration `data/062_chatbot_industry_templates.sql` adds separate JSON objects to
`chatbots`: `industry_template_draft` and `industry_template_published`. The
existing persona provenance field and manual profile values are not repurposed.
Apply the additive migration before releasing the new management endpoints.

- `GET /api/settings/industry-template?chatbot_id=...` returns the draft, published
  selection, catalog and confirmation availability.
- `POST /api/settings/industry-template/confirm?chatbot_id=...` accepts only the
  proposal identity and selected template identity. The server supplies the
  version and confirmation identity/time.
- `POST /api/settings/industry-template/review?chatbot_id=...` creates a fresh
  proposal for explicitly correcting the current confirmed choice.

All endpoints require authenticated owner/admin access to the company-owned
bot. Confirmation checks the current source and proposal before mutation. A
stale confirmation is a conflict, not an instruction to overwrite newer state.
The general Bot editing endpoint rejects both internal industry columns; it
cannot bypass this confirmation flow or forge the confirmation identity.

The model returns a bounded allowlisted suggestion with source-grounded excerpts.
Excerpts remain display-only data. Serving prompts use only fixed catalog text
selected by the **published** identity and version, in both default and custom
prompt paths. Industry rules remain downstream of the existing human-handoff
guard; they do not resume AI or grant tool authority.

## Verification and release status

**Verified complete locally; not deployed.** No production migration, deployment,
commit or industry backfill has been performed for this feature.

- Full current working tree: **4935 passed, 7 skipped, 2303 subtests passed**
  (exit 0, 193.22 seconds). The run used synthetic credentials and disabled
  external network access; pre-existing unrelated test edits were preserved.
- Browser: **28 passed**, with mocked API responses and external requests blocked;
  desktop and 375px layouts, long text, escaped evidence, retry/conflict states,
  confirmation and explicit correction were exercised.
- PostgreSQL 18: real socket-free disposable database verified migration 062,
  repeat application, JSON-object constraints, draft/publication separation and
  conditional update semantics. This is not production Supabase validation.
- Python compilation, JavaScript syntax, inline-script parsing, new-file
  whitespace checks and `git diff --check` passed. The container manifest test
  used a temporary Git index for new runtime files, leaving the real index alone.

The first full run had one load-sensitive, pre-existing concurrency timing test
fail at 0.40 seconds against a 0.30-second threshold; its immediate isolated
rerun passed. The test now uses a thread barrier to prove concurrent execution
directly instead of treating machine speed as correctness. The final full run
above includes this fix; no performance improvement is claimed.

The team used the role definitions under the local `agency-agents` checkout:
Agents Orchestrator for integration; Backend Architect for ingestion/persistence;
AI Engineer for the catalog; Frontend Developer/API Tester for the confirmation
interface; and Application Security Engineer for independent source review.
All agents applied Prompt Master and the relevant Coding Standards, API Design,
Frontend Patterns, Codebase Design or Verification Loop skills. Supabase's docs
MCP and Codex App's read-only attachment MCP were actually called; no new plugin
or dependency was installed.

The independent review found a generic Bot edit bypass of the new internal
columns. Two mocked HTTP regressions reproduced it before the rejection guard
and passed after the fix. Re-review then found no remaining blocking issue in
the bounded source review. This is not a whole-application security certification.

Codex Security was attempted for nine affected files, but stopped in preflight
because its stored ChatGPT sign-in could not be refreshed (0/9 files scanned,
exit 1). It is **incomplete**, not a security pass. Artifacts are outside the
repository at `C:/Users/Vincent/AppData/Local/Temp/industry-security-20260922`.

This feature isolates industry draft/publication. The legacy persona/profile
pipeline still has its existing mutable-profile semantics; this is not a full
snapshot redesign of the existing profile and knowledge publishing system.
Document activation and persona updates are still separate operations; the
industry proposal/path compare-and-set is not an atomic transaction over that
entire legacy ingestion flow. Classification tests use mocked model responses:
they establish validation and propagation, not real-model classification accuracy.
