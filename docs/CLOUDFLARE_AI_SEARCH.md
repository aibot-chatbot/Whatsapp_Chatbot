# Cloudflare AI Search over the tenant document bucket

Operator runbook for indexing `aibot-client-documents` (Cloudflare R2) with an
AI Search instance and filtering retrieval down to one chatbot.

The instance is live. `omnexa-knowledge`, namespace `default`, indexing the
`aibot-client-documents` bucket -- provisioned and verified on 2026-09-21.

What is **not** live is application retrieval. `app/services/ai_search_service.py`
has never run against this instance; everything proven below was proven with
direct REST calls. Read the **tenant isolation** section before you change that,
and section 9 for what is actually verified versus what is still assumed.

> Replace every `<PLACEHOLDER>` with a real value at the shell. **Never commit an
> API token or a service token id** into this file or any other. The account id,
> the instance name and the service token's *label* are recorded in section 9 on
> purpose: they are identifiers, not credentials, and every command below is
> useless without a token that is nowhere in this repository.

> **Do not take wire format from the bundled Cloudflare plugin skill.** Its
> cached `references/ai-search/` files (`api.md`, `gotchas.md`) still document
> the superseded AutoRAG surface: the `/autorag/rags/{NAME}/ai-search` path,
> `ranking_options.score_threshold`, and a `data[]` response whose entries carry
> `metadata.filename`. Following it faithfully produces a parser that reads
> `undefined` for every source key -- **that has already happened once on this
> project.** Every endpoint, payload and response shape in this document was read
> off the live instance instead. For anything not covered here, query the live
> API or search the current Cloudflare API spec; do not trust the cached skill
> reference.

---

## 1. Why a metadata filter and not a folder filter

Cloudflare's documented multi-tenant pattern filters retrieval on the `folder`
attribute, where `folder` is the object's key prefix -- `customer-a/contracts/`.

**That pattern cannot work for this bucket.** Every tenant document lives under
the same prefix:

```
knowledge/bot_<chatbot_id>_<uuid4>_<secure_filename>
knowledge/_pdf_candidates/<company_id>/<chatbot_id>/<uuid4>.pdf
media/bot_<chatbot_id>_<uuid4>_<secure_filename>
```

Every knowledge object's folder is literally `knowledge/`, so a folder filter
returns every tenant's documents to every tenant. Cloudflare metadata filters
additionally match only the **first 64 UTF-8 bytes** of an indexed string, and
`knowledge/bot_<id>_<36-char uuid>_` already consumes roughly 50 of them.

Re-keying the bucket was rejected: R2 is the authoritative store with no local
read fallback, and a prior review of this repository proved that re-migrating it
can resurrect documents a tenant deleted.

The chosen mechanism is **custom object metadata**. AI Search reads S3-compatible
`x-amz-meta-*` headers off each R2 object and exposes them as filterable
attributes. `app/services/document_storage_service.py` writes
`x-amz-meta-chatbot_id` (and `x-amz-meta-company_id` where the caller has it) at
`put_object` time. No key changes, no row changes, no read-path changes.

---

## 2. Before you index: what is actually marked today

Three things decide whether an object is retrievable at all. **2a is settled and
needs no action**; 2b is one-time historical cleanup; 2c is the one that still
bites when a new file type is added to the bucket.

### 2a. New uploads -- already wired, nothing to do

`persist_file()` and `write_file()` attach the marker **only when their caller
passes `chatbot_id=`**. An earlier revision of this document listed those callers
as unwired and told you to fix them before enabling retrieval. **That work is
done.** As of 2026-09-21 all six call sites pass the tenant id, verified by a
test that captures the real `put_object` call and asserts the marker lands:

| Caller | Site | Passes |
|---|---|---|
| `app/services/knowledge_service.py` | `save_uploaded_pdf` -> `persist_file` | `chatbot_id` |
| `app/services/knowledge_service.py` | readme -> `write_file` | `chatbot_id` |
| `app/services/knowledge_service.py` | active alias -> `write_file` | `chatbot_id` |
| `app/services/knowledge_service.py` | `log_knowledge_modification` -> `write_file` | `chatbot_id` |
| `app/services/pdf_relevance_validation_service.py` | candidate persist | `chatbot_id` **and** `company_id` |
| `app/routes/media_attachment_routes.py` | media upload, after `verify_chatbot_access` | `chatbot_id` |

`app/services/document_storage_migration.py` (bulk cutover) is the one genuine
exception and correctly passes nothing -- it walks paths only and has no tenant
context to pass.

**A document uploaded today is therefore marked automatically.** The only objects
that can lack a marker are ones written before this change, which is the entire
purpose of 2b.

The standing obligation is narrower than it was: **any *new* writer added to this
codebase must pass `chatbot_id`.** Nothing downstream will tell you if one does
not -- the object uploads fine, indexes fine, and is silently invisible to every
tenant forever.

### 2b. Objects written before 2a was wired -- one-time backfill

> **This is historical cleanup, not a recurring step.** It exists only for
> objects uploaded before the callers in 2a began passing `chatbot_id`. It does
> not need scheduling, it is not part of any deploy, and it does not need
> re-running after a normal upload. If you are reaching for it because a *recent*
> upload is unmarked, stop -- that is a regression in 2a, and backfilling over it
> hides the bug.

R2 cannot mutate metadata in place; the operation is a `copy_object` onto the
same key with `MetadataDirective="REPLACE"`.

```bash
export R2_ACCOUNT_ID=<ACCOUNT_ID> \
       R2_ACCESS_KEY_ID=<ACCESS_KEY_ID> \
       R2_SECRET_ACCESS_KEY=<SECRET_ACCESS_KEY> \
       R2_BUCKET_UPLOADS=aibot-client-documents

# Dry run. Writes nothing, prints every object it would change, exits 0.
python scripts/backfill_r2_tenant_metadata.py

# Rewrite metadata. Re-running is a no-op.
python scripts/backfill_r2_tenant_metadata.py --apply
```

It is scoped to the `knowledge/` prefix, skips every key it cannot resolve a
chatbot id for (including `knowledge/_pdf_candidates/**`), preserves each
object's `ContentType` and `CacheControl` across the copy, and finishes with an
`updated / skipped / failed` count. **Read the skipped list.** A skipped object
is an object no tenant will ever retrieve.

`scripts/` is not shipped in the container. Run this from an operator machine
that holds the R2 credentials; it needs no database access.

> **The backfill alone does not reach the index.** `copy_object` with
> `MetadataDirective="REPLACE"` leaves the object body byte-identical, and AI
> Search fingerprints **content**. The sync sees an unchanged checksum, skips
> re-extraction, and the new `chatbot_id` never lands in the index. Every signal
> reads healthy while every filtered query returns zero, permanently.
> **Section 7 is not optional after running this script.**

### 2c. Content-Type -- the extension wins, not the header

**AI Search decides a file's type from the filename extension, not from
`Content-Type`.** This is the opposite of what the header-driven mental model
predicts, and an earlier revision of this document got it backwards.

`put_object` sets `mimetypes.guess_type(path)[0] or "application/octet-stream"`,
and Python's `mimetypes` returns nothing for `.md` -- so every generated summary
is uploaded as `application/octet-stream`. **They index anyway.** 19 `.md`
objects are in the index right now (verified 2026-09-21).

| Object | Content-Type sent | Indexes? |
|---|---|---|
| `bot_<id>_<uuid>_<name>.pdf` (uploaded source) | `application/pdf` | **yes** |
| `bot_<id>_<file_id>_readme.md` (generated summary) | `application/octet-stream` | **yes** -- the `.md` extension decides |
| `bot_<id>_<file_id>_history.json` (audit log) | `application/json` | excluded deliberately by `**/*.json` -- see section 3 |

> **Do not "fix" `document_storage_service` to send `text/markdown`, and do not
> re-upload the summaries.** A previous revision of this file instructed exactly
> that, on the theory that the summaries were being silently skipped. They were
> not. Re-uploading them buys nothing and rewrites every object's
> `LastModified` for no gain.

What *is* true, and still worth checking before adding a new artefact type to
the bucket: a file whose **extension** AI Search does not support is skipped
with no error and no warning. Confirm the supported extension list in the
current Cloudflare docs rather than inferring it from a Content-Type.

---

## 3. Create the instance

An R2-backed AI Search instance needs a **service** API token, and its
`token_id` is supplied at create time.

Path filtering and the R2 prefix live under **`source_params`**. Send them in
the create call -- this payload is the live configuration of `omnexa-knowledge`:

```bash
curl -X POST "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances" \
  -H "Authorization: Bearer <API_TOKEN>" -H "Content-Type: application/json" \
  --data '{
    "id": "omnexa-knowledge",
    "type": "r2",
    "source": "aibot-client-documents",
    "token_id": "<SERVICE_TOKEN_ID>",
    "source_params": {
      "prefix": "knowledge/",
      "exclude_items": [
        "knowledge/_pdf_candidates/**",
        "_pdf_candidates/**",
        "media/**",
        "**/*.json"
      ]
    }
  }'
```

### The fields are `include_items` / `exclude_items` / `prefix`, inside `source_params`

> **The API accepts unknown keys, answers `201`, and silently drops them.**

There is no validation error for a filter field that does not exist. Invented
names such as `path_include` / `path_exclude`, or the right names placed at the
top level instead of inside `source_params`, all produce a successful create
with **no filtering at all**. That is exactly how the first sync on this account
indexed the entire bucket -- `media/` binaries and `.json` audit logs included.

**A 2xx tells you nothing. Read `source_params` back and look at it:**

```bash
curl -s "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances/omnexa-knowledge" \
  -H "Authorization: Bearer <API_TOKEN>" | python -m json.tool
```

If `source_params` is missing, empty, or missing the keys you just sent, the
filter did not take. Fix it and read it back again. Do this after **every**
write, not only the first one.

Patterns are **micromatch globs** matched against the object key.
`_pdf_candidates` holds abandoned supporting-document upload candidates -- they
are not tenant knowledge, they expire, and indexing them would surface documents
a tenant never confirmed. `media/**` is attachment binaries, not text.
`**/*.json` drops the per-file audit logs.

Both `knowledge/_pdf_candidates/**` and the bare `_pdf_candidates/**` are listed
because it was never established whether a pattern is matched against the full
object key or against the key with `prefix` already stripped. Listing both costs
nothing and removes the question.

---

## 4. Update the instance -- the verb is PUT, not PATCH

```bash
curl -X PUT "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances/omnexa-knowledge" \
  -H "Authorization: Bearer <API_TOKEN>" -H "Content-Type: application/json" \
  --data '{ ...full instance body, including source_params... }'
```

> **`PATCH` on this path does not mean "partially update the instance".** On the
> namespaced instance path it means *move the instance into another namespace*,
> and it requires `new_namespace`. Sending a config body to it fails with:
>
> ```
> 7001: Invalid input: expected string, received undefined
> ```
>
> which names neither the missing field nor the operation, and reads exactly
> like a malformed config body. It is not. Change the verb to `PUT`.

After any `PUT`, re-read the instance as shown in section 3. A success response
is not evidence that the fields were kept.

---

## 5. Watch indexing finish, and list what actually landed

```bash
# Trigger a sync
curl -X POST "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances/omnexa-knowledge/jobs" \
  -H "Authorization: Bearer <API_TOKEN>" -H "Content-Type: application/json" \
  --data '{"type":"sync"}'

# Counts
curl "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances/omnexa-knowledge/stats" \
  -H "Authorization: Bearer <API_TOKEN>"

# The individual indexed items -- keys, timestamps, attributes
curl "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances/omnexa-knowledge/items" \
  -H "Authorization: Bearer <API_TOKEN>"
```

A gap between the bucket object count and the indexed count is **expected** here:
`prefix` and `exclude_items` deliberately keep `media/`, `_pdf_candidates/` and
`.json` out. An *unexpected* gap means either an extension AI Search does not
support (section 2c) or an `exclude_items` pattern broader than intended.

`/items` is the important one. `/stats` and the job status only tell you the
pipeline ran; only `/items` tells you **what is in the index and which
attributes each item carries**. Section 7 is why that distinction matters.

---

## 6. Query with a tenant filter

Current AI Search REST filter syntax is Vectorize-style: `$`-prefixed operators,
nested under `ai_search_options.retrieval.filters`.

```bash
curl "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances/omnexa-knowledge/search" \
  -H "Authorization: Bearer <API_TOKEN>" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"..."}],
       "ai_search_options":{"retrieval":{"filters":{"chatbot_id":"<ID>"}}}}'
```

The value is a **string**, matching what is stored in the object metadata. An
integer will not match a string attribute.

### Response shape -- the source identifier is `item.key`, not `filename`

Confirmed against the live instance on 2026-09-21:

```jsonc
{
  "query_kind": "...",
  "search_query": "...",
  "chunks": [
    {
      "id": "...",
      "type": "...",
      "score": 0.0,
      "text": "...",
      "item": { "key": "knowledge/bot_29_...", "timestamp": 0, "metadata": {} },
      "scoring_details": { "vector_score": 0.0 }
    }
  ]
}
```

There is no top-level `data` array and no `filename` field. Anything mapping a
chunk back to a stored document must read **`item.key`**. Code written against
the older AutoRAG-shaped response (`data[].metadata.filename`) reads `undefined`
and silently loses the ownership link.

That is not hypothetical, and it is not a careless mistake when it happens: the
old shape is what the bundled Cloudflare plugin skill still documents. See the
warning at the top of this file.

### Retrieval options

All nested under `ai_search_options.retrieval`:

| Option | Range | Default | Notes |
|---|---|---|---|
| `max_num_results` | 1--50 | 10 | Chunks returned |
| `match_threshold` | 0--1 | **0.4** | Minimum vector similarity |
| `retrieval_type` | `vector` / `keyword` / `hybrid` | -- | This instance is vector-only |
| `filters` | -- | -- | The tenant filter -- section 8 |

`match_threshold` defaults to 0.4, high enough to return nothing for a loosely
worded query against a small tenant corpus. An empty result is not evidence that
the filter is wrong -- lower the threshold before concluding anything.

### Response caching defaults to ON, and here that is a disclosure risk

`cache` defaults to **`true`**, with `cache_threshold: "close_enough"` and a
**48-hour TTL**. A *semantically similar* query is served a previous answer.

On a single-tenant docs index that is a cost optimisation. On this index it is a
cross-tenant read waiting to happen: if the cache key does not include the
`chatbot_id` filter, tenant B's similar question is answered out of tenant A's
cached result. Whether the key includes it was never established.

**`cache` is `false` on `omnexa-knowledge` and must stay that way** until
someone proves the cache key is filter-aware. Do not turn it on for latency.

---

## 7. The expensive trap: a metadata-only change is invisible to sync

> This is the failure that cost the most time on this instance. Read it before
> running the backfill in section 2b, not after.

**AI Search fingerprints object *content*.** The R2 backfill rewrites custom
metadata with `copy_object` / `MetadataDirective="REPLACE"`, which leaves the
object body byte-identical. The checksum does not change, so the sync skips
re-extraction, and **the new attribute never reaches the index.**

What makes it expensive is that nothing looks broken:

- the sync job completes successfully;
- `last_seen_at` updates on **every** item, so they all look freshly processed;
- an unfiltered query returns results normally;
- every filtered query returns **zero** -- and keeps returning zero forever, no
  matter how many syncs are run.

There is no error anywhere. The natural reaction is to assume the filter syntax
is wrong and spend hours rewriting queries that were correct all along.

### The fix: invalidate the fingerprint

Force a content-level change by altering a chunking setting, then sync.

```bash
# 1. PUT the instance with a different chunk_size (1024 -> 1000).
#    The change is what matters, not the value. PUT, not PATCH -- see section 4.
curl -X PUT "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances/omnexa-knowledge" \
  -H "Authorization: Bearer <API_TOKEN>" -H "Content-Type: application/json" \
  --data '{ ...full instance body with "chunk_size": 1000... }'

# 2. Sync.
curl -X POST "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances/omnexa-knowledge/jobs" \
  -H "Authorization: Bearer <API_TOKEN>" -H "Content-Type: application/json" \
  --data '{"type":"sync"}'
```

### Verify by counting items that carry the field -- never by re-running the query

```bash
curl -s "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances/omnexa-knowledge/items" \
  -H "Authorization: Bearer <API_TOKEN>"
```

Count how many returned items carry a `chatbot_id` attribute and compare that
against the `updated` count the backfill reported.

**Do not verify from the query side.** "Filter applied, index not yet rebuilt"
and "filter applied, index rebuilt, this tenant genuinely has no match" are
indistinguishable from a query response -- both return zero. Only the item list
separates them.

### Related, and still true

Metadata filtering applies only to data indexed **on or after 2025-04-21**.
Content indexed before that date carries no filterable attributes at all. The
remedy is the same one above. An instance created fresh today does not need it
for that reason -- but it still needs it after any metadata-only backfill.

---

## 8. Tenant isolation -- read this before enabling anything

> **The `chatbot_id` filter is the ONLY thing standing between tenants.**

Once retrieval is switched on there is no second check. Every knowledge document
of every company sits in one bucket, in one index, behind one instance. A
dropped filter, a typo in the attribute name, an object indexed before the
marker existed, a client that forgets to pass the filter -- any one of those
returns one tenant's documents to another.

**Verify live with two different chatbot ids before the feature is enabled for
anyone:**

1. Pick two chatbots belonging to **different companies**, each with at least
   one indexed document whose content is distinctive.
2. Query with `chatbot_id` = A. Confirm every returned chunk belongs to A.
3. Query with `chatbot_id` = B. Confirm every returned chunk belongs to B, and
   that none of A's distinctive content appears.
4. Query with the filter **omitted**. If that returns documents from both, the
   filter is the only control -- which is exactly the point: no caller may ever
   issue an unfiltered query.
5. Query with a `chatbot_id` that does not exist. Confirm it returns nothing.

Fail any of these and the feature does not ship.

**Run live on 2026-09-21 against `omnexa-knowledge`: all five passed.** Chatbots
1, 29, 53 and 55 each returned only their own `item.key` values;
`chatbot_id=999999` returned zero; the unfiltered query was strictly wider than
any filtered one. That proves the *vendor-side* filter works. It proves nothing
about the application, which has never issued one of these calls.

### Two known gaps in the indexed corpus -- both deliberate, both worth recording

- **Six indexed tenants (1, 2, 25, 29, 46, 50) have R2 objects but no
  `knowledge_files` rows.** The application-side ownership check therefore
  discards every chunk they return. That is the fail-closed direction and is
  correct behaviour, but it means the index carries content no tenant can ever
  retrieve. Treat those keys as candidates for R2 cleanup -- never as a reason
  to relax the ownership check.
- **`knowledge/airbnb-faq.pdf` carries no `chatbot_id`.** Its key has no
  `bot_<id>_` prefix, so the backfill could not resolve an owner and correctly
  skipped it. It is invisible to every tenant. Deliberate and correct: an object
  with no owner belongs to nobody.

### Standing rules

- The application must construct the filter from the **authenticated** chatbot
  id it already resolves via `verify_chatbot_access`, never from a request
  parameter the caller supplies.
- An unfiltered search call is a cross-tenant read. Treat any code path that can
  reach the search endpoint without a filter as a defect, not a convenience.
- An object with no `chatbot_id` marker matches nobody. That is the safe
  direction and is deliberate -- storage omits an unusable id rather than
  failing the upload or guessing one.
- Nothing in the write path derives the tenant from the object key. A key is an
  identifier, not an authorization fact. Only the one-time historical backfill
  reads keys, and only because that is the sole record those objects carry.
- The application does not rely on the vendor filter alone.
  `app/services/ai_search_service.py` resolves the owned file names from
  `knowledge_files` for the authenticated chatbot and discards any chunk it
  cannot attribute. **Keep that second check.** A filter in a vendor query
  string and a check in our own code are not the same class of control, and the
  six orphan tenants above are the evidence that the second one actually fires.

---

## 9. Live configuration, and what is actually verified -- 2026-09-21

### The instance

| Field | Value |
|---|---|
| Account id | `1a382cd701e57fc2a4cf409a844dc4b6` |
| Instance | `omnexa-knowledge` |
| Namespace | `default` |
| R2 bucket | `aibot-client-documents` |
| Service token | `AI Search Token - 2026-09-21` |

> **Never delete that service token.** Revoking it raises no error anywhere in
> this pipeline -- indexing simply stops, silently. If items stop appearing and
> nothing else changed, check the token before you check anything else.

### Configuration

| Setting | Value |
|---|---|
| `prefix` | `knowledge/` |
| `exclude_items` | `knowledge/_pdf_candidates/**`, `_pdf_candidates/**`, `media/**`, `**/*.json` |
| `cache` | `false` -- deliberate, see section 6 |
| `custom_metadata` | `[{"field_name": "chatbot_id", "data_type": "text"}]` |
| Index | vector only |
| Embedding model | `@cf/qwen/qwen3-embedding-0.6b` |
| Dimensions | 1024 |
| `chunk_size` | 1000 -- was 1024, changed to invalidate the fingerprint (section 7) |
| `sync_interval` | 21600 seconds (6 hours) |

### Custom metadata constraints

- Maximum **5** custom fields per instance.
- Field names are stored **lowercase**.
- `timestamp`, `folder` and `filename` are **reserved** built-in attributes and
  cannot be reused as custom field names.
- Filters match only the **first 64 UTF-8 bytes** of an indexed string -- the
  same limit that rules out a key-prefix scheme in section 1.
- **Changing the custom metadata schema forces a full re-index.** Adding a
  second field later is not cheap. Decide the schema once.

### Verified live on 2026-09-21

Proven by direct REST calls against the live instance:

- `source_params` with `prefix` / `exclude_items` reads back correctly after a write.
- `PUT` updates the instance; `PATCH` fails with `7001` because it means "move namespace".
- `.md` objects index normally -- 19 of them are in the index.
- A metadata-only R2 rewrite does **not** re-index; a `chunk_size` change plus a sync does.
- Search response shape: top-level `query_kind` / `search_query` / `chunks`, source key at `item.key`.
- Tenant isolation: chatbots 1 / 29 / 53 / 55 each returned only their own keys, `chatbot_id=999999` returned zero, and the unfiltered query was strictly wider.
- Six tenants (1, 2, 25, 29, 46, 50) have indexed objects but no `knowledge_files` rows.
- `knowledge/airbnb-faq.pdf` carries no `chatbot_id` and is unreachable by every tenant.

### NOT verified -- do not assume any of this works

- **`app/services/ai_search_service.py` has never run against the live
  instance.** Every result above came from `curl`. The service's request
  construction, response parsing, ownership filtering and error handling are all
  unexercised against real data. Nothing in this document is evidence that our
  own code path works.
- Whether the response cache key includes the `chatbot_id` filter. `cache` is
  off here precisely because that is unknown.
- Whether `exclude_items` patterns match the full object key or the key with
  `prefix` already stripped. Both forms are listed, so the question never had to
  be answered.
- `retrieval_type` values other than `vector`. Hybrid and keyword retrieval have
  not been exercised on this instance.

`OPEN:` the per-instance file-count and per-file size limits were not read back
from the live account and are deliberately not quoted here. Check the current
Cloudflare docs before assuming headroom.

The first thing the next operator should close is the top item: run
`ai_search_service` against the live instance behind a feature flag, with one
test tenant, and re-run the five isolation checks in section 8 **through the
application** rather than through `curl`.

---

## Related

- `app/services/document_storage_service.py` -- the only writer; attaches the marker
- `app/services/ai_search_service.py` -- the application-side reader; builds the tenant filter and re-checks ownership against `knowledge_files`
- `scripts/backfill_r2_tenant_metadata.py` -- one-time marker backfill
- `docs/SECURITY_AND_TENANCY.md` -- tenancy boundaries across the application
