# Knowledge graph Cloudflare repair — 2026-09-24

## Diagnosis
Sentry issues WHASTAPP_CHATBOT_PROJECT-W (7752290841) and -X (7752306697)
pointed to graph chunk processing and GET auto-extraction. Production Qwen
usage repeatedly reached the 4,096-token output cap. Unconstrained JSON parsing
and overlapping upload/GET extraction allowed failed chunks and repeated paid
work. Saved partial graphs were hidden by the GET error path.

## Repair
- Explicit graph JSON schema for the three native Cloudflare models; Qwen uses
  its documented /no_think switch for this structured extraction only.
- Validate complete graph JSON before writes; stop at the first invalid response.
  Truncated provider output is settled once before rejection, without retry.
- Share a single-process extraction guard across upload and GET recovery. GET
  recovery rechecks existing nodes after acquiring the guard. Ingest progress,
  recorded failures and interrupted durable jobs prevent duplicate generation.
- Keep existing graph nodes visible with safe progress/error responses. Polling
  is bounded to two minutes and cancelled when leaving the graph.
- Pro remains on the existing OpenRouter models; plan and tenant-wallet checks
  remain on the central router and settlement path.

## Verification
- Combined focused backend suite: 341 passed, 123 subtests passed.
- Four mocked Playwright graph checks passed; Python compilation and diff check passed.
- Live synthetic nine-course extraction using the actual adapter, prompt, schema
  and strict parser: Qwen 48 nodes/46 relationships; GPT-OSS 39/54; Llama 40/46.
  All finish_reason=stop. No customer data or tenant-wallet charges in probes.
- Codex Security attempted; preflight stopped because stored ChatGPT credentials
  could not refresh. This is an incomplete scan, not a pass.

## Deployment evidence
Fly app aibot-chatbot-my, release v40, one Singapore machine 185de27f125998.
Image: sha256:a87229fbe696405cc78174f6d10f309f9f593a9f579c9a978439807e25865de5.
Built from isolated production baseline b9c1d6c with only five runtime files changed.
All 316 live runtime files matched canonical build manifest SHA-256:
5c3ff31177fa5e7930cc2919d47ed459635ad4574f53a3b3a0ecb9487803ead0.
Machine health passing and public HTTP200 at 09:37:31 UTC.

Read-only production view check for bot57/company40 returned HTTP200 with zero
AI calls. That bot had no remaining knowledge_files rows at verification, so
its originally reported document cannot be rechecked. This was an internal
view check with real ownership lookup, not an authenticated browser upload.
At 09:38:53 UTC Sentry issue counts remained32 and1, lastSeen09:13:22 and09:04:21
respectively (before deployment). This short observation is not proof of a
new customer upload. Issues remain unresolved pending real-use confirmation.

Unrelated Analysis edits were excluded from deployment and preserved in the
main workspace. Scoped source/test files were synchronized back to that workspace.
