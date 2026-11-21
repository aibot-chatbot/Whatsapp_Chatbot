# Client document protection

Updated: 2026-09-14. Scope: all uploaded files and chatbot knowledge documents.

**Deployed and verified on Fly v18 with private Cloudflare R2 storage.** The user approved R2 recurring usage billing, Cloudflare terms, and a bucket-scoped Object Read & Write token. R2 is activated and four Fly secrets are deployed. All 43 inventoried files were copied and verified. Synthetic storage, application, anonymous-access, and cleanup checks passed.

## Delivery checklist

- [x] Audit upload entry points, provider delivery, Cloudflare account, and Supabase metadata.
- [x] Implement upload validation, private cache headers, safe errors, and deleted-cache access guards.
- [x] Activate R2 with explicit approval; create the private bucket and deploy scoped credentials.
- [x] Implement authoritative R2 storage and a one-time migration before Flask and workers start.
- [x] Pass final local tests, runtime compilation, and diff checks; build the deployment image.
- [x] Verify live migration, completion marker, application health, and synthetic storage/media readback.
- [x] Verify anonymous access is denied, remove synthetic files, and complete release review.

## Verified provisioning and release state

| Boundary | Evidence | Meaning |
| --- | --- | --- |
| Application | `https://aibot-chatbot-my.fly.dev`, deployed Fly v18 in good state with 1/1 health checks passing. | Flask remains on Fly; R2 handles document storage. |
| Cloudflare account | The connected account returned zero zones. Authenticated dashboard evidence confirmed Workers Paid; the user separately approved and activated R2. | R2 storage does not add zone WAF, proxied DNS, or edge rules to the existing `fly.dev` hostname. |
| R2 bucket | `aibot-client-documents`, APAC, Standard. Bucket and public-access readback confirmed `r2.dev` disabled and no custom domains. | The bucket has no public delivery endpoint. |
| Credentials | Bucket-only Object Read & Write token approved and created. `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_BUCKET_UPLOADS` show Deployed in Fly. | Secret values are not recorded here. Synthetic application checks exercised R2. |
| Deployment target | Same single Machine `185de27f125998`, volume `vol_vwnl05wn2jxww88v` mounted at `/app/data`. Existing Wasender retry flag remains true. | No additional worker or volume topology is introduced. |
| Running image | `sha256:6f17a178a32b58b244398c11aec5e8fa4f813c0d1f28ce933f0341b467c4e0e5` | Live image matches the release; all 275 runtime file hashes match with no extra files. |

Private R2 is accessed from Fly through its S3-compatible API; no custom domain or Worker is required for that storage connection. [R2 setup](https://developers.cloudflare.com/r2/get-started/), [Python SDK configuration](https://developers.cloudflare.com/r2/examples/aws/boto3/). The historical [Cloudflare plan](CLOUDFLARE_EDGE_PLAN.md) contains superseded hosting targets; use this report and the [public deployment plan](PUBLIC_DEPLOYMENT_PLAN.md) for current scope.

## Storage and access boundaries

1. **R2 is authoritative when enabled.** `DOCUMENT_STORAGE_BACKEND=local` preserves the default filesystem behavior. In `r2` mode, originals, supporting candidates, generated README/history, and media use private object storage. Reads fetch R2 even when a local copy exists; a remote miss or outage never falls back to stale cache. Local materializations remain for PDF processing and delivery.
2. **Existing paths and provider URLs remain valid.** Keys use `knowledge/<DATA_FOLDER-relative path>` and `media/<MEDIA_FOLDER-relative path>`. Original writes complete before metadata creation or upload success. Generated artifacts upload their exact bytes and replace the local cache atomically. Downloads and writes are bounded to 32 MiB, and storage errors are sanitized.
3. **Media URLs remain anonymously shareable.** `/media/` intentionally serves files through Fly without login so messaging providers can retrieve them. Private R2 does not make these URLs owner-only, and they are unsuitable for confidential originals. Existing URLs are not replaced with links that expire at upload time.
4. **Removing an attachment record does not erase its bytes.** Media URLs can be reused by other records, queued deliveries, and Meta template samples (`frontend/assets/js/meta-templates.js`). No automatic media deletion or revocation was added.
5. **Tenant authorization stays in Flask.** Authenticated company and chatbot ownership checks remain necessary. Generated knowledge reads require a current bot-scoped file record, preventing old IDs from exposing caches after source deletion. Filenames, prefixes, and private buckets do not provide tenant authorization.

The storage implementation is in [document_storage_service.py](../app/services/document_storage_service.py), with lifecycle integration in [knowledge_service.py](../app/services/knowledge_service.py), [pdf_relevance_validation_service.py](../app/services/pdf_relevance_validation_service.py), [match_service.py](../app/services/match_service.py), and the knowledge/media routes.

### Deletion and consistency limits

Knowledge deletion removes the original and exact derived artifacts before deleting metadata. An R2 or local removal failure stops the operation and retains metadata for retry, but a multi-object deletion can already be partially complete. Existing graph deletion remains best effort; graph data, backups, and already delivered copies are not covered by a complete-erasure guarantee.

A failed or uncertain upload is compensated against its exact new object key and its new local copy is removed. If metadata saving and compensating R2 deletion both fail, a private orphan object can remain. The request fails; no erasure claim is made. Candidate cleanup can be retried after cancellation or successful ingestion; an ingestion read outage uses the existing failed state and requires revalidation or cancellation.

Database changes and R2 writes are not one transaction. A derived-file failure can return an error after a database mutation succeeded, so graph edits should not be blindly retried. History updates retain their existing last-write-wins behavior. Aggregate company media quotas and malware scanning remain separate work.

### Chat answers and AI processing

Enabled knowledge is deliberately retrieved into chatbot answer prompts and can appear in replies, including replies through an enabled public widget. See [chat_pipeline_service.py](../app/services/chat_pipeline_service.py) and [widget_routes.py](../app/routes/widget_routes.py). Confidential owner-only material should not be enabled as customer-answer knowledge; private storage does not change retrieval behavior.

Indexing sends extracted chunks to the configured embedding provider, and supporting-candidate scoring may embed text before confirmation. Answer prompts go to the configured AI provider. See [rag_service.py](../app/services/rag_service.py), [ai_router.py](../app/services/ai_router.py), and the candidate service. Provider retention, training terms, and contractual settings were not verified; this work makes no zero-retention or no-training claim.

## One-time migration and live verification

The pre-cutover volume inventory contains **43 files totaling 8,622,343 bytes**: 10 PDFs, 16 README files, 14 history files, and 3 mounted media files. The largest file is 5,718,851 bytes; no symlinks were found. Local originals remain on the mounted volume.

[document_storage_migration.py](../app/services/document_storage_migration.py) runs from [wsgi.py](../wsgi.py) with explicit migration configuration, before `create_app()` and background workers. The previous single Machine must stop before replacement uses the same volume. Migration admits document artifacts and media, preserves mounted-media precedence over legacy copies, excludes temporary files, and checks expected inventory. It uploads and reads back each object with SHA-256 verification, preserves local originals, and writes an atomic completion marker bound to the account and bucket. A valid completed marker prevents later boots from reuploading stale caches; migration errors stop startup with a sanitized message.

The deployed completion marker records **43 files / 8,622,343 bytes** with manifest SHA-256 `23ca162f604e3be2aac4ba2f8923427d4f5ae502661b902547765bd3b244a9f3`. The root deployment owner confirmed the expected image, Machine, volume, deployed secrets, and application health. The local Fly configuration now selects R2, requires at least 43 migration files, and uses a 60-second health grace period. The initial deployment submitted 180 seconds; Fly warned it caps the effective grace period at one minute.

Synthetic knowledge/media PUT, HEAD, authoritative GET, delete, and stale-cache denial checks passed. Fly media retrieval returned HTTP 200 with complete bytes, HTTP 206 for a range request, no-store headers, and HTTP 404 after deletion. Probe objects were removed; the bucket returned to 43 objects.

**Final live verification passed, exit 0.** Anonymous GETs for existing synthetic objects returned HTTP 400 with XML `InvalidArgument` / `Authorization`, without file content; the disabled public `r2.dev` endpoint returned HTTP 403. Both knowledge and media probes passed every check and removed their objects. All 275 runtime files match the release, with canonical runtime-manifest SHA-256 `221f57b29488ccb644d805647588204666fbf77f027518a813aae6adca9569f9`.

Captured Windows Fly SSH output initially caused a local invalid-handle exit after executing the command. The final verification used direct terminal output and completed with exit 0. Fly automatically updated its CLI from 0.4.95 to 0.4.102 during that check. Real customer uploads, authenticated tenant-isolation tests, and live provider deliveries were not exercised. Restart idempotency is covered by local marker tests; no separate live restart rehearsal is claimed.

## Supabase metadata findings

The audit matched application project `parjsxypengvubziwwjp` directly, with status `ACTIVE_HEALTHY`. Only project details, PostgreSQL catalogs, grants/policies, and bucket settings were inspected during that audit; no customer rows or document contents were queried through Supabase.

| Object | Observed audit state | Assessment |
| --- | --- | --- |
| `knowledge_files` | RLS disabled; client table read/write and column SELECT grants absent. | Missing defense in depth, without established direct client read exposure. |
| Knowledge chunks and graph nodes/edges | RLS enabled; client privileges present, no policies. | Default-deny RLS blocks client row access. Preserve that boundary. |
| PDF candidates | RLS enabled; client privileges denied. | Server-only metadata boundary is present. |
| `match_knowledge_chunks` overloads | Invoker functions, client-executable, mutable `search_path`. | Review unused execution grants and pin paths while preserving vector operator resolution. |
| Supabase Storage | Public `landing` bucket, restricted image/video types and a 10 MiB limit. | Marketing storage remains separate from client documents. |

No Supabase schema, RPC, RLS, or bucket-policy migration was applied. The backend service-role client bypasses RLS, so application ownership checks remain critical. Candidate queries bind candidate, chatbot, and company IDs; ordinary document queries bind chatbot ID. Composite tenant integrity constraints and server-only privilege hardening remain separate reviewed work. Existing SQL migrations 045/046 provide a local precedent. [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security).

## Separate Cloudflare edge work

The user currently has only the Fly hostname, and the connected Cloudflare account has zero zones. R2 is object storage; zone-based WAF, cache rules, TLS settings, and upload rate limits have not been applied to the application.

A later edge rollout needs a user-controlled domain, verified Fly origin TLS, and proxied DNS in the correct Cloudflare zone. Then review Full (strict), HTTPS redirection, cache bypass for `/api/`, `/media/`, and `/upload-pdf`, included WAF controls, measured upload rate limits, and a supported origin restriction. Preserve unrelated rules and provider callbacks. [Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/), [origin cache control](https://developers.cloudflare.com/cache/concepts/cache-control/).

Do not apply browser challenges or blanket upload rules to Telegram, Channel Server, Meta, or payment callbacks. Malware scanning is not enabled and no scanning entitlement is claimed; Cloudflare malicious-upload detection requires separate entitlement and mitigation rules. [Malicious uploads detection](https://developers.cloudflare.com/waf/detections/malicious-uploads/). Confidential provider delivery still needs an explicit, reviewed sharing/revocation design compatible with provider retries.

## Verification and implementation evidence

- **Final local suite:** 359 tests and 108 subtests passed in 26.54 seconds, exit 0. Twelve runtime Python files compiled; `git diff --check` passed.
- **Coverage:** request limits, PDF signatures, cache headers, tenant denials, deleted-cache guards, stable R2 keys, bounded atomic reads, failed writes/deletes, original/candidate/derived lifecycles, media delivery, and first-start migration behavior.
- **Regression files:** `test_document_r2_storage.py`, `test_knowledge_r2_storage.py`, `test_candidate_r2_storage.py`, `test_document_storage_migration.py`, and existing upload, deletion, media, graph, and container-release checks.
- **Codex Security:** explicitly waived by the user on 2026-09-14. The earlier preflight attempt scanned 0/12 files and was not a passed scan. No further scan or scanner login is required for this task.
- **Release boundary:** v18 deployment, the 43-file migration marker, runtime hashes, synthetic application/storage checks, and anonymous bucket-access denial are verified. Final remote verification exited 0. No live customer upload or provider message is claimed as a test.

Runtime changes include the R2 helper and migration, knowledge/candidate/match services, upload and media routes, `app/config.py`, `wsgi.py`, the boto3 dependency, environment template, and explicit container allowlist. Existing upload-validation and privacy fixes are retained. Unrelated work and customer files are preserved.

The deployed image includes the reviewed working-tree changes on source HEAD `657f41784c224533537ab08a90a3c745f9054736`; no commit or push was performed. The isolated release and verification records are in `C:/Users/Vincent/AppData/Local/Temp/codex-r2-release-20260914-2_tfhnoo`. Its `rollback-fly.toml` and previous image digest `sha256:5abe1b40efdab0d102787bd31d5378ec3c0a7d0bf38b38cfe1404dbad0a4abb3` record the pre-cutover configuration. Once new writes occur in R2, a rollback needs write quiescence and reconciliation of those objects before reverting to local storage; preserved originals alone are no longer a current backup.

Reproduce the local release suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_document_storage_migration.py tests/test_document_r2_storage.py tests/test_knowledge_r2_storage.py tests/test_candidate_r2_storage.py tests/test_upload_document_protection.py tests/test_deleted_knowledge_privacy.py tests/test_media_upload_privacy.py tests/test_media_serving_security.py tests/test_media_keyword_security.py tests/test_media_attachment.py tests/test_storage_paths.py tests/test_knowledge_supporting_documents.py tests/test_pdf_candidate_backend.py tests/test_upload_pdf_error_logging.py tests/test_document_ocr_service.py tests/test_security_hardening.py tests/test_knowledge_follow_up_hook.py tests/test_knowledge_graph_routes.py tests/test_platform_admin_company_suspension_runtime.py tests/test_container_release.py -q --tb=short
git diff --check
fly config validate --config fly.toml
```

## Team capability record

| Agent lane | Skills applied | Plugin and callable MCP use |
| --- | --- | --- |
| Orchestrator: storage helper, review, coordination | Prompt Master silent mode; ECC coding standards; relevant Matt Pocock review/diagnostic guidance; Cloudflare platform and R2 references. | Cloudflare `search`, read-only audit `execute`, and `docs`; current S3/Python API documentation retrieved. |
| Knowledge lifecycle and metadata audit | Prompt Master; ECC coding standards; Matt Pocock diagnostics; Cloudflare/R2; Supabase and PostgreSQL/RLS references. | Cloudflare docs MCP; Supabase project lookup, docs, and metadata-only SQL audit. |
| Media privacy and candidate lifecycle | Prompt Master; ECC coding standards; Flask security guidance; Matt Pocock diagnostics; Cloudflare/R2. | Cloudflare docs MCP and mocked local regressions. |
| Root integration and deployment | Prompt Master; relevant ECC/Matt Pocock and Cloudflare guidance. | Cloudflare MCP checks plus authenticated dashboard provisioning and Fly deployment operations under explicit authorization. |

The team used the requested native agents, skills, plugins, and real callable MCP tools. Earlier API authentication limitations were resolved through supported authenticated dashboard actions where needed; tool installation alone was not treated as proof of access.
