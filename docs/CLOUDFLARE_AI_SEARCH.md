# Cloudflare AI Search over the tenant document bucket

Operator runbook for indexing `aibot-client-documents` (Cloudflare R2) with an
AI Search instance and filtering retrieval down to one chatbot.

Nothing in this document is live yet. Retrieval is unchanged until an operator
follows it deliberately. Read the **tenant isolation** section before you do.

> Replace every `<PLACEHOLDER>` with a real value at the shell. Never commit a
> token, an account id or a service token id into this file or any other.

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

Check all three of these. Each one silently produces an empty or partial index.

### 2a. New uploads

`persist_file()` and `write_file()` attach the marker **only when their caller
passes `chatbot_id=`**. At the time of writing, the callers below still call
them without it, so a freshly uploaded document carries no marker:

| Caller | Tenant id available there? |
|---|---|
| `app/services/knowledge_service.py` (`save_uploaded_pdf`, readme, history) | yes -- `chatbot_id` |
| `app/services/pdf_relevance_validation_service.py` (candidate persist) | yes -- `chatbot_id` and `company_id` |
| `app/routes/media_attachment_routes.py` (media upload) | yes -- `chatbot_id` |
| `app/services/document_storage_migration.py` (bulk cutover) | **no** -- walks paths only |

Wire those callers before enabling retrieval, or every document uploaded after
the backfill will be invisible to search.

### 2b. Existing objects -- run the backfill

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

### 2c. Content-Type -- this one currently bites

R2 objects with a missing, malformed, unsupported or `application/octet-stream`
`Content-Type` are **skipped silently at indexing**. No error, no warning; the
object simply never appears in results.

`put_object` sets `mimetypes.guess_type(path)[0] or "application/octet-stream"`.
Measured against this project's Python:

| Object | Content-Type sent | Indexes? |
|---|---|---|
| `bot_<id>_<uuid>_<name>.pdf` (uploaded source) | `application/pdf` | **yes** |
| `bot_<id>_<file_id>_readme.md` (generated summary) | `application/octet-stream` -- `mimetypes` returns nothing for `.md` | **no, skipped** |
| `bot_<id>_<file_id>_history.json` (audit log) | `application/json` | unlikely; not a supported document type |

**Plainly: of the current uploads, only the PDFs would index.** The generated
markdown summaries -- the densest, cleanest text in the corpus -- are uploaded as
`application/octet-stream` and are dropped on the floor. If those summaries are
meant to be retrievable, `document_storage_service` must send `text/markdown`
for `.md` and the affected objects must be re-uploaded or copied. That change is
deliberately **not** part of the metadata work; make it a separate, tested
change.

---

## 3. Create the instance

An R2-backed AI Search instance needs a **service** API token, and its
`token_id` is supplied at create time.

```bash
curl -X POST "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances" \
  -H "Authorization: Bearer <API_TOKEN>" -H "Content-Type: application/json" \
  --data '{"id":"omnexa-knowledge","type":"r2","source":"aibot-client-documents","token_id":"<SERVICE_TOKEN_ID>"}'
```

### Path filtering at index time

Index-time path filters use **micromatch globs**:

- include `knowledge/**`
- exclude `knowledge/_pdf_candidates/**`

`_pdf_candidates` holds abandoned supporting-document upload candidates. They
are not tenant knowledge, they expire, and indexing them would surface documents
a tenant never confirmed.

Consider whether `media/**` belongs in the index at all -- it is attachment
binaries, not text.

---

## 4. Watch indexing finish

```bash
curl "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai-search/namespaces/default/instances/omnexa-knowledge/stats" \
  -H "Authorization: Bearer <API_TOKEN>"
```

Compare the indexed count against the object count in the bucket. A large gap is
almost always section 2c -- objects skipped on `Content-Type`.

---

## 5. Query with a tenant filter

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

---

## 6. Metadata filtering only applies to newly indexed data

Metadata filtering applies only to data indexed **on or after 2025-04-21**.
Content indexed before that date carries no filterable attributes, and adding
metadata to the objects does not retroactively change the index.

To enable it on existing content:

1. Change **any** chunking setting on the instance (chunk size or overlap -- the
   change is what matters, not the value).
2. Run **Sync index**.
3. Re-check `/stats` and confirm the filtered query in section 5 returns rows.

An instance created fresh today does not need this. An instance that already
existed does.

---

## 7. Tenant isolation -- read this before enabling anything

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
- Before enabling retrieval, decide whether the application also checks
  ownership of each returned document against `knowledge_files` before showing
  it. A filter in a vendor query string and a check in our own code are not the
  same class of control.

---

## Related

- `app/services/document_storage_service.py` -- the only writer; attaches the marker
- `scripts/backfill_r2_tenant_metadata.py` -- one-time marker backfill
- `docs/SECURITY_AND_TENANCY.md` -- tenancy boundaries across the application
