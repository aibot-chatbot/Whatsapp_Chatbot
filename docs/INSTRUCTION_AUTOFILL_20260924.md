# Document instruction autofill — 2026-09-24

## Behaviour

After a primary document finishes processing, Create instructions refreshes the
Bot's stored document-derived company name, description and tone. It suggests
an instruction name, uses the Bot's name, and supplies editable reply guidance.
Users can save directly or edit the fields. Existing saved instructions retain
their values. The advanced custom prompt remains optional because the serving
prompt is already composed from the ordinary fields and document knowledge.

Free, Essential, Advanced and Pro use this flow. Removing the legacy paid-only
persona gate leaves the central router's company, model, plan and credit checks
in place. The upload's existing persona call receives a structured JSON schema;
opening Create makes no additional billed generation request. Industry output
remains a suggestion requiring merchant confirmation.

Missing source facts are not invented. Failed/older uploads are not automatically
retried by opening the form; a successful newly processed primary document is
the supported path. Manually entered profile fields remain protected during
document derivation.

## Verification

- Focused persona, plan feature and industry backend suite: 189 passed,
  95 subtests passed. After schema adjustments, 126 persona/industry tests passed;
  two focused schema/null checks passed again after the final wording change.
- Browser suite: 29 passed initially; one focus-restoration regression was fixed
  and its rerun passed, covering all 30 checks.
- Python compilation and scoped diff checks passed.
- Live native Cloudflare probes found unsupported `uniqueItems`, then missing
  fields with an all-optional schema. Removed the unsupported keyword and
  required the three persona keys, allowing null for unsupported facts.
- Final exact-source synthetic probes passed for Qwen3 30B, GPT-OSS 20B and
  Llama3.3 70B: all three business fields validated, all finish_reason=stop.
  GPT-OSS suggested restaurant; Qwen/Llama returned the supported unknown-industry
  fallback. No customer data, database writes or tenant-wallet charges were used.
  Pro's existing OpenRouter transport was unchanged and was not live-probed here.
- Codex Security stopped during preflight because its saved ChatGPT login could
  not refresh. No completed security scan is claimed.

The browser uses mocked APIs and synthetic documents. These checks do not prove
a fresh authenticated customer upload in production.

## Deployment

Prepared in the isolated production checkout used for Fly v40. The verified
runtime delta is limited to `app/services/persona_derivation_service.py` and
`frontend/new_prompt.html`. No migration or new execution flags are required.
Image: sha256:f9e7bfcf20cd2c22682c04b28b6757cc59e7b3907aa7be69c5757ce833476173.
Canonical build manifest (316 runtime files):
85506f902d041e9aad333efe8827a97f75a3bbdb723d070d69597f10342d34ce.
Fly release v41 is running on the existing Singapore machine 185de27f125998
with its `/app/data` volume preserved. Health check passing; public `/` and
`/new_prompt.html` returned HTTP 200 at 2026-09-24 10:27:12 UTC. The public
instruction page matched the built file byte for byte. All 316 live runtime
files matched the canonical build manifest above. Unrelated workspace changes
and disabled automation execution settings were preserved.
