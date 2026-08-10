# Knowledge Ingestion, Derived Persona, and Conversation Memory

## Reading Warning

None of the three features described here is merged, deployed, or approved for
production. All of the code lives in the working tree only, and three of the
four workstreams carry unresolved blockers.

Do not follow this document as a "how to use it" guide. Follow it as a
"what exists, what it does, and what stops it from being used" record.

| Workstream | Status | Safe to use today? |
|---|---|---|
| Single-call ingestion endpoint (`POST /api/knowledge/ingest`) | Implemented | **No.** Review verdict is BLOCK; see [Blockers](#blockers-single-call-ingestion) |
| Derived persona and provenance | Implemented | Partly. Storage and override behavior work; the derived value does not reach replies for an undeployed bot |
| Conversation graph memory | Implemented | **No.** Migration cannot be certified, write path is not tenant-filtered, PII has no expiry |
| Migrations `031` → `032` → `033` | Not applied anywhere | **No.** Two mandatory preflights are unrun |

Related documents:

- `docs/FEATURE_STATUS.md` — per-feature status table
- `docs/DATABASE_AND_RPC.md` — schema-change rules and table inventory
- `docs/BILLING_AND_AI_CREDIT.md` — plan gates and AI-credit charging
- `docs/PHASE_4F_OPERATIONS_RUNBOOK.md` — migration application conventions
- `docs/SECURITY_AND_TENANCY.md` — tenant-scoping rules

---

## 1. Single-Call Knowledge Ingestion

### Overview

`POST /api/knowledge/ingest` composes the four website-scraping stages that are
otherwise four separate HTTP calls, and returns one report with per-source,
per-stage progress.

| Stage | Service function | Equivalent single-stage endpoint |
|---|---|---|
| `analyze` | `discover_website_links` | `POST /api/knowledge/scrape-analyze` |
| `scrape` | `scrape_pages` | `POST /api/knowledge/scrape-batch` |
| `extract` | `extract_business_knowledge` | `POST /api/knowledge/scrape-extract` |
| `embed` | `save_refined_knowledge_chunks` | `POST /api/knowledge/scrape-embed` |

The four staged endpoints are unchanged and still work. The new endpoint reuses
the same service functions; it does not replace them.

**Scope: websites only.** The endpoint does not accept uploaded documents. PDF
upload remains `POST /upload-pdf` (`app/views.py`), which uses a different
request encoding and has no per-stage seams. Any plan or brief that describes
this endpoint as a general "documents and websites" ingest is describing
something that does not exist.

### Request

```text
POST /api/knowledge/ingest?chatbot_id=<int>
Authorization: Bearer <application JWT>
Content-Type: application/json
```

Role: `admin` or `owner`. Chatbot ownership is verified through
`verify_chatbot_access`.

Body:

```json
{
  "sources": [
    "https://example.com",
    {
      "url": "https://example.com",
      "urls": ["https://example.com/a", "https://example.com/b"],
      "discover_links": true,
      "max_pages": 5,
      "file_name": "Example site"
    }
  ]
}
```

| Field | Meaning | Default | Bound |
|---|---|---|---|
| `sources` | URL strings and/or source objects | required | at most 10 per request |
| `url` | The source URL. `http://` or `https://` only | required | — |
| `urls` | Explicit page list. Skips the `analyze` stage | absent | at most 20; rejected, not truncated, when exceeded |
| `discover_links` | Run link discovery on `url` | `false` | — |
| `max_pages` | Cap on discovered pages | 5 | ceiling 20 |
| `file_name` | Knowledge-file label | derived from the primary URL | — |

Validation happens before any work is done; a malformed body does no scraping
and spends no AI credit.

### Plan gates

The endpoint applies the same gates the staged chain applies, in the same order:

1. `can_use_plan_feature(company_id, "batch_website_scraping")`
2. `can_upload_knowledge_file(company_id)` — checked **before** the billed LLM
   extraction

A blocked plan returns HTTP 403 with the `BillingLimitError` code and details.

### Response

HTTP 200 when at least one source was ingested, including the partial case.
HTTP 400 only when every source failed, or when the body is malformed.
Already-ingested sources are never rolled back because a sibling source failed.

```json
{
  "status": "success",
  "message": "Ingested 2 of 3 sources; 1 failed.",
  "data": {
    "chatbot_id": 12,
    "status": "partial",
    "totals": {"requested": 3, "succeeded": 2, "partial": 0, "failed": 1},
    "sources": [
      {
        "url": "https://example.com",
        "status": "succeeded",
        "phase": "done",
        "file_name": "https://example.com (+4 pages)",
        "error_code": null,
        "error_message": null,
        "error_details": null,
        "stages": [
          {"name": "analyze", "status": "succeeded", "detail": {"discovered_pages": 11, "selected_pages": 5}},
          {"name": "scrape",  "status": "succeeded", "detail": {"scraped_pages": 5, "failed_pages": []}},
          {"name": "extract", "status": "succeeded", "detail": {"characters": 4820}},
          {"name": "embed",   "status": "succeeded", "detail": {"file_name": "..."}}
        ]
      }
    ]
  }
}
```

Vocabulary, per source and per stage: `pending`, `skipped`, `succeeded`,
`partial`, `failed`. Every returned report is terminal — the endpoint runs
synchronously, so there is no `queued` or `running` state. Stages the run never
reached are reported as `skipped`, so the report always shows how far a source
got.

Error codes on a source record: `scrape_failed`, `extract_failed`,
`embed_failed`, or the `BillingLimitError` code when the storage quota rejected
the write.

### Blockers (single-call ingestion)

**Review verdict: BLOCK. Do not enable this endpoint in any environment that
sits behind a proxy, and do not advertise it to clients.**

**B1 — The synchronous run cannot finish inside a realistic proxy window, and
per-page cost is unbounded.**

`fetch_and_parse_url` tries Jina Reader with a 25 s timeout and then falls back
to a static fetch with a 15 s timeout (`app/services/knowledge_service.py`), so
one page can consume 40 s of timeout budget. Link discovery adds another 15 s
per source. At the default `max_pages` of 5 with the maximum 10 sources, the
timeout budget alone is roughly 35 minutes, before the per-source LLM extraction
call and the per-chunk embedding calls. At the `max_pages` ceiling of 20 the
same arithmetic gives over two hours.

Worse, `requests`' `timeout` is a **between-bytes read gap**, not a wall clock.
A server that trickles one byte every 20 s keeps a single page alive
indefinitely, and no cap in this code bounds that.

Consequences when a proxy kills the request:

- The report is lost. There is no persisted job record to read it back from.
- A retry re-ingests from scratch. There is **no idempotency key**, so the
  retry re-scrapes, re-runs the billed LLM extraction, and writes a second
  `knowledge_files` row that counts against the storage quota again.

Required before use: move the run behind a persisted job with a resumable
report and an idempotency key, or hard-bound total wall-clock time per request.

**B2 — A source can report `succeeded` with zero chunks persisted, and storage
is still charged.**

`save_refined_knowledge_chunks` writes the `knowledge_files` row (carrying the
byte size that counts against the storage quota) first, then wraps chunking,
embedding, and chunk persistence in a `try`/`except` that only logs. It also
skips any chunk whose embedding is falsy (`if embedding:`). It returns the same
success payload either way.

The ingestion service treats a returned payload as `embed: succeeded`. So an
embedding-provider outage produces a source marked `succeeded`, a knowledge file
the client can see, quota consumed, and nothing retrievable at reply time.

Required before use: `save_refined_knowledge_chunks` must report chunk counts
and surface embedding failure, and the `embed` stage must map zero persisted
chunks to `partial` or `failed`.

**B3 — A third quota-skip bug is still unfixed.**

`app/routes/knowledge_routes.py:334` calls `scrape_website_urls_batch(data["urls"], chatbot_id)`
with no `company_id`. Inside that function the storage-quota check is guarded by
`if company_id:` (`app/services/knowledge_service.py:599`), so
`POST /api/knowledge/scrape-batch` writes knowledge files **without any storage
quota check at all**.

Two sibling instances of the same bug were fixed in this same working tree —
`app/routes/knowledge_routes.py:246` (`scrape-website`) and
`app/routes/knowledge_routes.py:467` (`scrape-embed`). This third one was not.
It is not part of the new endpoint, but it is on the same route module and the
same billing surface, and it must be fixed in the same change.

---

## 2. Derived Persona and Provenance

### Overview

A client who never opens the prompt/profile form gets the system placeholders,
and the bot introduces itself as an assistant for "Your Company". Derived
persona fills three values from the client's own uploaded document instead:

- `company_name`
- `business_description`
- `tone` (constrained to `Friendly`, `Professional`, `Formal`)

Each value is tagged with a **provenance marker** so a later ingest can refresh
a value the system derived without ever overwriting one the client typed.

### How it runs

1. The client uploads a PDF through `POST /upload-pdf`.
2. After the upload succeeds, `derive_persona_for_upload(chatbot_id)` runs
   (`app/views.py`). It never raises — a failure to describe a document must not
   turn a successful upload into a 500.
3. `persona_derivation_service.load_source_text` reads the chatbot's active
   knowledge file's chunks (already extracted, already scoped by `chatbot_id`)
   and sends the first 12 000 characters to the LLM.
4. The LLM is asked for a strict JSON object. Anything that does not parse into
   one — raw text very much included — is a failure that writes nothing.
5. Each value is sanitised: control characters and Unicode format characters are
   stripped, whitespace runs collapse to a single space, `company_name` is capped
   at 120 characters and `business_description` at 1 000, and `tone` must match
   the closed vocabulary exactly. A value that fails is dropped, never truncated.
6. `settings_service.update_settings(values, chatbot_id, source="derived")`
   writes the active `bot_configs` row, applying the provenance rules below.

The upload response reports the outcome without changing the upload's own status:

```json
{
  "message": "...",
  "persona_derivation": {"status": "succeeded", "error_code": null}
}
```

Statuses: `succeeded` (all three derived and at least one applied), `partial`
(fewer than three derived), `skipped` (no source text, or every field is already
a client override), `failed` (nothing written). Error codes: `no_source_text`,
`persona_llm_failed`, `persona_unparseable`, `persona_derivation_crashed`,
`persona_client_override`, or a `BillingLimitError` code.

Routing, provider, and model selection are unchanged: the call goes through
`ai_router.generate_system_response` with `operation_type=OPERATION_KNOWLEDGE_EXTRACTION`,
so subscription, provider, model-tier, and AI-credit enforcement all apply.

### Provenance model

Storage is one `jsonb` column, `bot_configs.persona_provenance`, holding
`{field: marker}`. It is written in the **same** INSERT/UPDATE as the value it
describes, so a value and its provenance can never disagree.

| Marker | Meaning | May a derivation overwrite it? |
|---|---|---|
| `client_entered` | The client typed it | Never |
| `derived` | Read out of an ingested document | Yes — a later ingest refreshes it |
| *(key absent)* | Unknown. Every row written before migration `032` | Only if the stored value is blank or byte-identical to the system placeholder |

There is **deliberately no backfill**. Marking every pre-existing row
`client_entered` would freeze the whole existing tenant base on "Your Company",
which is the bug this work exists to fix. Marking every row `derived` would
license the first ingest to destroy values clients really typed. "Unknown" is
the honest state, and it is adjudicated by value.

Known and accepted cost: a client who deliberately chose the exact placeholder
(most plausibly `tone = "Friendly"`, the form's pre-selected default) loses it to
the first derivation. The loss is bounded and self-healing — the field then
carries `derived`, and the moment the client retypes it, it becomes
`client_entered` and is permanent.

### Legacy column unification (migration `031`)

Three persona values were historically stored under two column names each, and
both writer services kept the pair in sync by hand:

| Canonical column | Legacy column (deprecated) |
|---|---|
| `business_description` | `business_objective` |
| `tone` | `response_style` |
| `custom_prompt` | `prompt_text` |

`app/services/bot_config_fields.py` is now the single definition of that mapping.
Reads prefer the canonical column and fall back to the legacy one for rows the
`031` backfill has not reached. Writes populate the canonical column and write
SQL `NULL` into the legacy one, so a row touched by this code can never leave a
stale mirror for the fallback to resurrect.

### Blockers (derived persona)

**P1 — The derived persona does not reach the generated reply for a bot whose
`chatbots.deployed_profile_name` is blank.**

Derivation writes the **active** `bot_configs` row.
`rag_service.get_deployed_settings` (`app/services/rag_service.py:26-43`)
resolves the row named by `chatbots.deployed_profile_name`, and returns
`DEFAULT_SETTINGS` when that field is blank. A bot that has never been deployed
therefore still says "Your Company" no matter what was derived.

That is exactly the never-opened-the-form population this feature targets, so
the observable customer benefit is capped until separate create-RPC/promotion
work lands. `tests/test_persona_derivation.py::test_an_undeployed_bot_still_falls_back_to_the_placeholders`
pins the gap deliberately, and
`tests/test_persona_reaches_replies.py::test_the_same_derived_row_undeployed_cannot_name_the_store`
is the negative control proving the precondition is load-bearing.

Operator workaround, and the only one available today: after the upload, the
client (or an operator on their behalf) must deploy the profile —
`PUT /api/settings/apply-profile` — so `deployed_profile_name` names the row
derivation wrote. See the client procedure in section 4.

**P2 — Residual stored prompt-injection risk.**

Up to 1 000 characters of document-chosen prose reach the serving **system**
prompt as asserted company fact. `rag_service.build_prompt` interpolates
`company_name` and `business_description` as company configuration, not as the
untrusted knowledge that safety rule 12 tells the model to distrust.

The **structural** lever is closed: newlines and control characters are stripped
before storage, so a document cannot add a *line* to the system prompt. The
**semantic** lever is not: a poisoned document can still state a refund policy or
a support phone number where the serving model reads it as fact.

Closing it requires `build_prompt` to fence a `derived` persona value the way it
fences retrieved chunks. That is a change to the serving prompt and is not made.
**Do not add a fourth derived free-text field before it is.**

**P3 — Open design call: should `tone` be excluded from placeholder matching?**

`tone` is the field most likely to be deliberately set to its placeholder value
(`Friendly` is the form default). Excluding it from the "unknown provenance +
value equals placeholder ⇒ derivable" rule would remove the accepted loss
described above, at the cost of never deriving a tone for a pre-`032` row.
Unresolved.

### Verification evidence

Local, at the current working tree:

```text
tests/test_persona_derivation.py        73 passed
tests/test_bot_config_persona_fields.py 32 passed
tests/test_persona_reaches_replies.py   14 passed
```

Plus a real-browser Playwright end-to-end spec,
`tests/browser/testbot-persona.spec.js`, run with `pnpm test:testbot-persona-browser`.
It drives `frontend/testbot.html` against the real Flask app with only the
Supabase and LLM-provider boundaries doubled, so no billed provider call is
possible.

This is local evidence against a working tree. It is not staging verification
and not production readiness.

---

## 3. Conversation Graph Memory and Keyword Retrieval

### Overview

Facts the bot learns mid-conversation persist as conversation-scoped graph nodes
that a later turn in the **same** conversation can recall by keyword.

Producer: `conversation_memory_service.remember_conversation_facts`, called from
`chat_pipeline_service.prepare_chat_prompt`. It stores fields that
`agent_decision_service._extract_fields` has already extracted for the turn. That
extractor is pure regex and runs on every turn regardless, so this adds **no LLM
call and no billing change**.

Consumer: `conversation_memory_service.recall_conversation_facts`, called from
`rag_service.retrieve_relevant_chunks` when a `conversation_id` is supplied.
Recall runs **beside** the vector path, never instead of it. Omitting
`conversation_id` reproduces the previous behavior exactly.

Storage is a new relation, `public.conversation_graph_nodes` (migration `033`).
It deliberately does not extend `knowledge_graph_nodes`: that table is uniquely
keyed on `(chatbot_id, name)`, so two concurrent conversations that both learned
a customer name would collide on one row and overwrite each other — a
cross-conversation leak of personal data.

Lifetime is the conversation's lifetime. Both foreign keys are
`ON DELETE CASCADE`, so deleting a conversation or a chatbot removes its facts.
`delete_conversation_facts` exists for an explicit "forget this conversation"
action.

### Blockers (conversation memory)

**C1 — Migration `033` cannot be certified without a live catalog capture.**

`public.chatbots` and `public.conversations` have no `CREATE TABLE` anywhere in
this repository, so the `bigint` column types and the `ON DELETE` behavior `033`
assumes are unverified. Run `scripts/conversation_graph_nodes_preflight.sql`
(SELECT-only) in the Supabase SQL Editor and attach every result set to the
change record **before** applying `033`. Without it, three failure modes are
open: incompatible FK types (`42804`), no unique constraint on the parent key
(`42830`), and — the silent one — a pre-existing relation of a different shape
turning `CREATE TABLE IF NOT EXISTS` into a no-op that reports success while
every CHECK, the UNIQUE key, and both foreign keys are absent.

**C2 — The write path is not tenant-filtered.**

`upsert_conversation_fact` resolves on the conflict target
`(conversation_id, label)`. `chatbot_id` is a payload column, not a predicate,
and the schema does not enforce that it agrees with the parent conversation. An
upsert carrying a `conversation_id` owned by another tenant does not select zero
rows — it takes the `DO UPDATE` branch and **rewrites that row's `chatbot_id`
and value**, re-tenanting another chatbot's PII row.

Reads and deletes filter on both `chatbot_id` and `conversation_id`, so this is
a write-path-only gap. It is not reachable today because the only producer
derives `conversation_id` from `get_or_create_conversation(chatbot_id=...)`. It
becomes live the moment any caller accepts a conversation id from a request.

Required before that: the composite foreign key documented in the "TENANCY IS
NOT ENFORCED BY THIS SCHEMA" section of `data/033_conversation_graph_nodes.sql`,
which needs `UNIQUE (id, chatbot_id)` on `public.conversations`.

**C3 — Recall is exact-match on a single normalised ASCII token.**

Write and read do not share one normalisation. Write applies `normalize_label`
(lowercase, collapse whitespace, keep spaces/hyphens/non-ASCII). Read first
reduces the query through `rag_service.clean_query_words` — lowercase
`[a-z0-9]+` tokens longer than one character, stopwords removed — and only then
normalises.

A label is therefore recallable only if it is a single ASCII alphanumeric
non-stopword token. Practical consequences:

- "what's my phone number" does **not** find a fact stored under the label
  `contact`. The stored label is `contact`; no token in that question equals it.
- A fact written under `order number`, `order-id`, or `prenom` stores fine and
  is then permanently unfindable.
- Only three labels are extracted at all — `name`, `contact`, `interest`. There
  is no order-number extraction.

`tests/test_conversation_graph_memory.py` pins that the three emitted labels
round-trip, so a later change to `STOPWORDS` or the tokenizer fails loudly.

**C4 — Raw customer PII is persisted with no expiry.**

Customer name, email address, and phone number are now written to
`conversation_graph_nodes` in plaintext. This codebase had deliberately avoided
persisting exactly these values. There is no independent expiry — a fact is as
durable as the conversation that produced it, and conversations are not aged out.

Required before production: a retention decision (and, if data-subject deletion
is in scope, a path that reaches these rows). `delete_conversation_facts` covers
a single conversation only.

### Verification evidence

```text
tests/test_conversation_graph_memory.py  35 passed, 16 subtests passed
```

Local only. No database has this table.

---

## 4. Client Procedure: Overriding a Derived Value

**Audience: non-technical. This is the one clean, shippable part of this work.**

Your chatbot can fill in its own company details by reading the document you
uploaded. If it got something wrong, or you would simply rather write it
yourself, you can replace it. Once you do, the chatbot will never change that
value again on its own — not even if you upload a new document later.

### What you can override

- **Company Name** — the name the bot uses when it talks about your business
- **Business Description** — one short paragraph about what you sell or do
- **Tone** — Friendly, Professional, or Formal

### Steps

1. Open the **Bot Configuration** page (`new_prompt.html`) for your chatbot.
2. Select the profile you want to change, or create a new one and give it a
   **Profile Name**.
3. Edit **Company Name**, **Business Description**, or **Tone**. You can change
   one, two, or all three.
4. Click **Save Profile** (or **Update Profile** when editing an existing one).
   The value you typed is now marked as yours.
5. Click **Deploy to Live Bot** to make the saved profile the live one. Until
   you do this, the chatbot keeps replying with whatever it was last deployed
   with.

### What happens afterwards

- The value you typed is stored and marked `client_entered`.
- The next time you upload a document, the chatbot reads it for anything you
  left blank — but it leaves your value completely alone.
- If you later clear a field and save it empty, that is treated as deliberate:
  the field is emptied and becomes eligible to be filled from a document again.

### Two things to know

**Deploying is a separate step.** Saving a profile changes what is stored.
Deploying is what makes the live chatbot use it. A chatbot that has never been
deployed keeps replying with the built-in placeholders ("Your Company") even
after a document has been read — see blocker P1 above. If the bot still says
"Your Company" after an upload, the profile has not been deployed.

**Saving part of a profile.** If you (or an integration) save a profile without
including one of the three persona fields, that field keeps its current value and
its current ownership mark. This is deliberate: a partial save must not silently
wipe an override.

**The Custom Prompt Template does not work that way.** `custom_prompt` is still
fully replaced on every save. A save that omits it clears it. The same applies to
`bot_name`, `additional_instructions`, and `out_of_scope_reply`. Only the three
persona fields are protected by key-presence.

Note for integrators: the standard UI form always submits all four fields, so
key-presence preservation only changes behavior for a partial API body sent to
`POST /api/profiles` or `PUT /api/settings`.

---

## 5. Operator Procedure: Migrations `031` → `032` → `033`

### Ordering is strict

```text
031_unify_bot_config_persona_fields.sql
        ↓
032_bot_config_persona_provenance.sql
        ↓
033_conversation_graph_nodes.sql
```

Each is deploy-order-sensitive in the same direction: **apply the migration
before the application code.** Deploying code first fails loudly, not silently —
which is deliberate — but it fails every write on the affected table.

| Migration | If code is deployed first | Failure |
|---|---|---|
| `031` | The new code writes SQL `NULL` into the legacy columns rather than omitting them. If those columns are still `NOT NULL`, every `bot_configs` INSERT and UPDATE is rejected | `23502` not-null violation |
| `032` | The new code writes `persona_provenance` on every `bot_configs` INSERT and UPDATE. If the column does not exist, PostgREST rejects the write | `PGRST204` |
| `033` | Every memory write targets a table that does not exist | PostgREST schema error; replies still succeed because the producer swallows and logs |

Old code keeps working against the migrated schema in every case. The unsafe
direction is only ever code-before-migration.

### Mandatory preflights

Two of the three migrations have a **SELECT-only** preflight script that must be
run first and whose results must be attached to the change record. Migrations
here are applied through the Supabase SQL Editor, which cannot run psql
meta-commands, so these scripts are the `\d+` substitute.

| Migration | Preflight | Why it is mandatory |
|---|---|---|
| `031` | `scripts/bot_configs_persona_unification_preflight.sql` | There is no `CREATE TABLE` for `public.bot_configs` in this repository. The preflight is the only record of which `NOT NULL` constraints step 2 relaxes — without it the rollback is best-effort, not exact. Section 10 must be **exported before** `031` is applied, because divergent legacy values become unrecoverable afterwards |
| `032` | `scripts/bot_configs_persona_unification_preflight.sql` (section 1) | Recommended, not required — `032` is purely additive. Keep the column inventory as the record that step 1 had nothing to abort on |
| `033` | `scripts/conversation_graph_nodes_preflight.sql` | `public.chatbots` and `public.conversations` have no `CREATE TABLE` in this repository, so `033`'s FK column types and `ON DELETE` behavior are assumed, not observed |

**Customer-content warning:** section 10 of the `031` preflight returns tenant
business text, not just identifiers. Route its output to the restricted archive
used for migration 028 manifests — not into a ticket or a chat transcript.

### What each migration changes

| Migration | Change | Reversible |
|---|---|---|
| `031` | Backfills canonical persona columns from legacy ones; relaxes `NOT NULL` on `business_objective`, `response_style`, `prompt_text`. Only relaxes, never tightens. Adds, drops, and renames nothing | `data/031_unify_bot_config_persona_fields_rollback.sql`; exact only with preflight section 2 output |
| `032` | Adds `bot_configs.persona_provenance jsonb DEFAULT '{}'`. Catalog-only on PostgreSQL 11+; no table rewrite. **No backfill by design** | `data/032_bot_config_persona_provenance_rollback.sql` |
| `033` | Creates `public.conversation_graph_nodes` with two `ON DELETE CASCADE` foreign keys and `UNIQUE (conversation_id, label)` | `data/033_conversation_graph_nodes_rollback.sql` |

Both `031` and `033` set `SET LOCAL lock_timeout = '5s'`. `033`'s inline foreign
keys take `SHARE ROW EXCLUSIVE` on `public.conversations` and `public.chatbots`,
which blocks writes on the product's two hottest tables while the statement
waits. The hold itself is instantaneous (nothing is scanned), so the only real
risk is queueing behind a long transaction. If the timeout trips, re-run in a
quieter window — every statement is idempotent.

### Pre-application checklist

- [ ] `scripts/bot_configs_persona_unification_preflight.sql` run; every result
      set attached to the change record; section 10 exported to the restricted
      archive
- [ ] Preflight items A–I confirmed (see the script header)
- [ ] `scripts/conversation_graph_nodes_preflight.sql` run; items A–E confirmed
- [ ] Human approval recorded, per `docs/DATABASE_AND_RPC.md` schema-change rules
- [ ] Applied to a non-production environment first
- [ ] Migration applied **before** the application deploy, in `031` → `032` →
      `033` order
- [ ] Blockers B1, B2, B3, C2, and C4 resolved or explicitly accepted in writing

---

## 6. New and Changed Schema

| Object | Kind | Migration | Notes |
|---|---|---|---|
| `bot_configs.business_description` | existing column, now canonical | `031` | Legacy mirror `business_objective` deprecated and NULLed on write |
| `bot_configs.tone` | existing column, now canonical | `031` | Legacy mirror `response_style` deprecated |
| `bot_configs.custom_prompt` | existing column, now canonical | `031` | Legacy mirror `prompt_text` deprecated |
| `bot_configs.persona_provenance` | new `jsonb` column | `032` | `{field: "client_entered" \| "derived"}`; absent key means unknown |
| `conversation_graph_nodes` | new table | `033` | Conversation-scoped facts; `UNIQUE (conversation_id, label)`; both FKs `ON DELETE CASCADE` |

## 7. New and Changed Modules

| Path | Kind | Purpose |
|---|---|---|
| `app/services/knowledge_ingestion_service.py` | new | Composes the four website stages; validation, bounds, per-stage report |
| `app/routes/knowledge_routes.py` | changed | Adds `POST /api/knowledge/ingest`; passes `company_id` on two of three quota paths |
| `app/services/knowledge_service.py` | changed | Adds `scrape_pages`, the shared fetch-and-collect loop |
| `app/services/persona_derivation_service.py` | new | Derives the three persona values from an ingested document |
| `app/services/bot_config_fields.py` | new | Single definition of canonical/legacy mapping and all provenance rules |
| `app/services/settings_service.py` | changed | `update_settings(..., source=)`; persona merge and provenance write |
| `app/services/profile_service.py` | changed | Key-presence persona preservation on partial saves |
| `app/services/rag_service.py` | changed | Optional `conversation_id` on `retrieve_relevant_chunks` |
| `app/services/conversation_memory_service.py` | new | Remember/recall conversation facts |
| `app/database/conversation_graph_repository.py` | new | Data access for `conversation_graph_nodes` |
| `app/services/chat_pipeline_service.py` | changed | Calls the memory producer; passes `conversation_id` to retrieval |
| `app/views.py` | changed | Runs persona derivation after a successful PDF upload |

---

## Document Maintenance

Update this file when any blocker listed above is resolved, when a migration is
applied to any environment, or when the ingestion endpoint's scope changes.
Move the corresponding rows in `docs/FEATURE_STATUS.md` at the same time.

Do not record branch names, commit hashes, local paths, or working-tree status
here.
