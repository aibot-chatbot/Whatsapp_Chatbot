# Running the Langflow automation without a Langflow server

Status: design note, no code changed. Written against HEAD `d539431` plus the
untracked `app/services/langflow_*.py` working tree.

## Short answer

**You do not need a Langflow server, and you do not need to replace it with one
either.** The two flows are already fully described by code that Flask runs
anyway. With a perfectly healthy server the entire Langflow layer contributes
exactly one thing that Flask does not already have: a single formatted sentence
on the knowledge-review event.

Everything below is the evidence for that, then the four options costed, then a
recommendation.

---

## 1. What actually runs today

The automation is wired, opt-in, and **inert in production**.

| Where | `LANGFLOW_AUTOMATION_ENABLED` | `LANGFLOW_SERVER_URL` | Result |
|---|---|---|---|
| Dev laptop (`.env`) | `true` | `http://127.0.0.1:7860` (with `LANGFLOW_ALLOW_INSECURE_LOCAL=true`, 46-char API key) | Flows run — against a process on the developer's own machine |
| `.env.txt` template | `false` | empty | Disabled |
| Fly.io `wa-chatbot-my` | **not set** — `fly.toml` contains zero `LANGFLOW` references | not set | `_enabled()` is False → `RuntimeError("Langflow automation is disabled")` |

`run_langflow_automation` raises when disabled; both callers in
`app/services/langflow_decision.py` catch every exception and return `_skip(...)`
with `consulted: False, blocked: False`. So in production the automation always
takes the fail-open path and **never contributes anything**.

Note the second failure mode: even if the dev `.env` were copied wholesale into
Fly secrets, `http://127.0.0.1:7860` inside the Fly container reaches nothing —
connection refused, same fail-open branch. There is no configuration of the
current design that makes these flows run on Fly without also standing up a
server somewhere.

## 2. What the flows actually compute

This is the part that decides the whole question.

**Node inventory** (verified against the exported JSON):

| Flow | Nodes / edges | Components |
|---|---|---|
| `crm-stage-automation` | 7 / 8 | `ChatInput`, `JSONtoData`, 2× `ParserComponent`, `ConditionalRouter`, 2× `ChatOutput` |
| `knowledge-document-follow-up` | 4 / 3 | `ChatInput`, `JSONtoData`, `ParserComponent`, `ChatOutput` |

All stock. No LLM node, no HTTP node, no code executor. The contracts
themselves forbid ever adding one — both set `allow_custom_components: false`,
`allow_code_interpreter: false`, `allow_arbitrary_network: false`. These flows
are deterministic string routing by construction and are not permitted to grow
into anything else.

### 2a. The CRM flow is a re-implementation of a rule Flask already applied

The entire decision is one `ConditionalRouter` in `regex` mode. Its pattern:

```
(?s)^(?:(?=.*"current_status"\s*:\s*"new")(?=.*"target_status"\s*:\s*"(?:contacted|qualified|lost)")
    |(?=.*"current_status"\s*:\s*"contacted")(?=.*"target_status"\s*:\s*"(?:qualified|won|lost)")
    |(?=.*"current_status"\s*:\s*"qualified")(?=.*"target_status"\s*:\s*"(?:won|lost)")).*$
```

Executed against all 25 stage pairs and compared with `CRM_STAGE_TRANSITIONS`
(`app/services/automation_service.py:18-24`): **25 pairs, 0 mismatches.** The
regex is that dict.

The consequence is stronger than "duplicated logic". In
`apply_crm_stage_automation`, Flask checks the allowlist *first*:

```python
if target not in CRM_STAGE_TRANSITIONS.get(current, set()):
    raise ValueError(f"Invalid CRM stage transition: {current} -> {target}")
# ... only now is Langflow consulted
decision = crm_stage_decision(...)
```

By the time the flow is asked, the transition is already known-allowed — and the
flow evaluates the identical predicate. So it always answers `apply_crm_stage`.
**`decision["blocked"]` is unreachable for any input that can reach it**, even
with a perfectly healthy server. The advisory second opinion is the first
opinion, recomputed over HTTP, and it always agrees.

The `blocked` branch in `automation_service.py` (the one that writes a
`status="blocked"` event and raises `PermissionError`) is therefore dead in
production *and* dead against a healthy dev server. It is reachable only from
the test suite, which injects a refusal directly.

### 2b. The knowledge flow renders one sentence

Its contract pins the two decision fields as constants — `decision` is
`{"const": "review_document"}` and `requires_approval` is `{"const": true}` — so
it structurally cannot change whether a review is queued. Its only variable
output is `summary`, and the `ParserComponent` template shows exactly what that
is:

```
{display_name} finished training with {chunk_count} chunk(s) as the {target_role} source and needs a human review.
```

A Python f-string over three values Flask already passed into the call.

**Net contribution of the whole Langflow layer, assuming a healthy server: one
formatted sentence.**

---

## 3. The four options

### (a) Embed `lfx` and run the flow JSON in-process

**It genuinely works — this was tested, not assumed.** `lfx` 1.11.5 is installed
in the hermes venv and `lfx.load.run_flow_from_json` loaded and executed the
exported CRM flow with no server running, returning exactly the contract output
the HTTP adapter expects:

```
{"decision":"apply_crm_stage","company_id":1,"chatbot_id":2,"lead_id":3,
 "target_status":"contacted","correlation_id":"test-corr-1"}
```

Routing was correct on the negative cases too (`won->lost` and `qualified->new`
both returned `block_crm_stage`).

So (a) is real. It is also, measured, the most expensive option on the board:

| Cost | Measured |
|---|---|
| Dependencies | **49 new core requirements** for `lfx` alone — pulls `langchain`, `langchain-core`, `langchain-classic`, `fastapi`, `uvicorn[standard]`, `pandas`, `pillow`, `networkx`, `markitdown`, `pypdf`, `openpyxl`, `cryptography`, `mcp`. Today's app has ~15 direct requirements. |
| Memory | **+302 MB RSS on import** (17 MB → 319 MB; 340 MB after one run) |
| Import time | **89 s warm**, 113 s cold |
| Disk | `lfx` 16 MB + `langflow` 79 MB, before the 49-package transitive tree |
| Per-run latency | 0.26 – 5.0 s |

Caveats, stated honestly: those numbers come from a Windows dev laptop with a
595-package venv and a slow filesystem. A clean Linux container with only
`lfx`'s tree would be meaningfully faster — but the *shape* survives any
plausible correction. The Fly machine is `shared-cpu-1x` with **1 GB**, and
`fly.toml` already records that 512 MB OOMs because PyMuPDF and the Google GenAI
client load at import. Adding a ~300 MB import-time baseline to that machine is
a real OOM risk, and a multi-second import on a `--workers 1` gunicorn process
delays every boot and every deploy.

Pin conflicts: `lfx` requires `mcp<2.0.0,>=1.17.0` and `pydantic<2.14`. Neither
collides with anything in `requirements.txt` today (the app uses neither
directly), but both are transitive constraints the app would inherit forever, and
`supabase`/`openai` both move on `httpx` and `pydantic`.

- **Effort:** medium (swap the adapter for a loader; re-pin the image)
- **Runtime cost:** ~300 MB RAM + 0.3-5 s/call, on a 1 GB machine
- **Risk:** high — OOM on the current VM size, large new dependency surface
- **Gain:** the one sentence

### (b) Port the two flows to plain Python behind the same interface

Keep `langflow_decision.py`'s public surface (`crm_stage_decision`,
`knowledge_document_decision`, their return dicts, the fail-open contract) and
the contract JSONs and their validator. Replace only the HTTP transport with the
local producer.

How much logic is this, precisely:

- **CRM:** none. The predicate is `CRM_STAGE_TRANSITIONS`, which the caller
  already evaluated on the line above. The honest port is a function that
  returns `consulted: True, blocked: False` plus a correlation id — about
  **8 lines**, and it is a tautology.
- **Knowledge:** **one f-string**, the template quoted in §2b, wrapped in the
  existing return shape — about **8 lines**.

That is ~20 lines replacing 358 (272 in `langflow_decision.py` + 86 in
`langflow_adapter.py`). **Net deletion of roughly 340 lines**, plus 8 env vars
and an outbound authenticated HTTP call.

What is lost: nothing that runs in production today, because nothing runs in
production today. Against the *dev* server you lose the ability to edit routing
in the Langflow GUI without a deploy — real, but the contracts already forbid
these flows from becoming anything a GUI edit could usefully change.

- **Effort:** low (half a day including test rework)
- **Runtime cost:** microseconds, zero new dependencies, zero image growth
- **Risk:** low
- **Gain:** the one sentence, *and* a 340-line deletion, *and* removal of a live
  outbound call that currently ships a 46-char API key over plaintext HTTP from
  the dev laptop on every CRM transition

### (c) Run Langflow as a separate always-on service

A second Fly app with `LANGFLOW_SERVER_URL` pointed at it over HTTPS.

- **Cost:** Langflow wants ~2 GB. On Fly that is `shared-cpu-1x` at 2 GB,
  roughly **$12-19/month** always-on (it cannot scale to zero — a cold start
  would blow the adapter's 10 s timeout and fail open anyway, i.e. you would pay
  for an idle machine to avoid a path that already degrades gracefully).
- **Failure surface:** a new network hop on the CRM transition path, a new
  deployable, a new API key to rotate, a new thing to monitor, a new upgrade
  treadmill (Langflow moves fast and its flow JSON format moves with it).
- **Auth:** the adapter already does this correctly (HTTPS enforced, key
  server-side, no redirects, bounded body/timeout), so this part is cheap.
- **Gain:** the one sentence.
- **Effort:** medium-high. **Runtime cost:** ~$15/mo + latency. **Risk:** medium.

Paying ~$180/year and adding a network dependency to a user-facing write path,
to obtain a sentence you can format locally, is not a defensible trade.

### (d) Do nothing

Leave it fail-open. Production behaviour is unchanged and, importantly, **already
correct** — Flask owns the decision, the event records `skipped_because`, and no
user-facing action is blocked by an absent server.

- **Effort:** zero. **Runtime cost:** zero. **Risk:** zero functionally.
- **Cost:** 358 lines of app code, 36 tests, and 186 KB of flow JSON that imply a
  capability which never executes. The next person to read this repo will
  reasonably believe the automation runs. That is the entire cost, and it is a
  real one.

---

## 4. Recommendation

**Take (b), in its minimal form.** Port the one f-string, delete the transport,
keep the contract and its validator.

Reasoning:

1. **The server buys nothing.** Options (a) and (c) are both engineering
   programmes whose entire payoff is a sentence Flask can format in one line.
   That is settled by measurement, not opinion: the CRM regex is provably
   `CRM_STAGE_TRANSITIONS` (25/25), and the knowledge contract pins both decision
   fields to constants.
2. **(a) is technically viable but lands wrong.** `lfx` really does run these
   flows serverlessly — that is worth knowing, and it would be the right answer
   if the flows contained judgement worth preserving. They don't. Paying 49
   dependencies and ~300 MB on a 1 GB machine that already OOMs at 512 MB, to
   execute a regex, is the expensive way to compute `target in
   CRM_STAGE_TRANSITIONS[current]`.
3. **(b) is mostly deletion**, which is the cheapest kind of change, and it
   closes a small live security seam: today a CRM transition on the dev laptop
   makes a real outbound HTTP call carrying an API key to a plaintext localhost
   endpoint.
4. **(d) is a legitimate deferral.** Nothing is broken. If there is no appetite
   to touch this now, the minimum honest action is a comment at both call sites
   saying the layer is inert in production — do not leave the next reader to
   discover it.

What would change this recommendation: a flow that contains an actual LLM call,
or routing a human is expected to edit without a deploy. Neither is true here,
and the contracts' `allow_*: false` flags mean neither can become true without a
contract change first.

---

## 5. Migration plan for (b)

### Stays identical (do not touch)

- The advisory **fail-open contract**: every failure path returns
  `blocked: False` and the caller proceeds on Flask's own validation.
- **Schema validation** against the contract's `output_schema` —
  `validate_against_schema`, `ContractViolation`, `_contract`, and the two
  contract JSONs. Validating locally-produced output against the published
  contract is the runnable self-check that keeps the port honest.
- The **`automation` event fields**: `consulted`, `correlation_id`,
  `skipped_because`, `summary`. Event payloads and the
  `automation_events` schema are unchanged, so migration 049 and
  `automation_event_repository.py` are untouched.
- `automation_service.py`'s call sites, function names, and return shapes.

### Changes

| File | Change |
|---|---|
| `app/services/langflow_adapter.py` | **Delete** (86 lines) |
| `app/services/langflow_decision.py` | Delete `extract_flow_output`, `_search_for_decision`, `_flow_id`, both envelope builders and the `run_langflow_automation` import (~150 lines). Replace the two `try/except` transport blocks with local producers that build the contract object, validate it, and return the same dict. |
| `.env.txt` | Drop the 8 `LANGFLOW_*` entries |
| `requirements.txt` | No change (nothing added, nothing removed) |

Consider also renaming the module away from `langflow_*` once the dependency is
gone — but that is cosmetic and can wait.

### Test impact — all 36 accounted for

| File | Tests | Effect |
|---|---|---|
| `test_automation_service.py` | 5 | **Unchanged.** Patches `app.services.automation_service.crm_stage_decision`, which still exists with the same signature and return shape. |
| `test_automation_routes.py` | 2 | **Unchanged.** |
| `test_knowledge_follow_up_hook.py` | 1 | **Unchanged.** |
| `test_langflow_decision.py` | 25 | 12 **unchanged** (contract/schema: `test_conforming_output_validates`, the 7 `test_non_conforming_output_is_rejected` params, `test_bare_contract_object_is_accepted`, `test_decision_is_extracted_from_a_run_envelope`, `test_prose_output_is_a_contract_violation`, `test_knowledge_contract_pins_decision_and_approval`). 9 **reworked** — same assertions, new injection point, since they patch `langflow_decision.run_langflow_automation` which no longer exists. 4 **deleted** — `test_transport_failure_does_not_block`, `test_flow_id_with_unsafe_characters_is_refused`, and the two `missing_flow_id_skips` tests, all of which assert properties of a transport that is gone. |
| `test_langflow_adapter.py` | 3 | **Deleted** with the adapter. |

Totals: **20 unchanged, 9 reworked, 7 deleted.** Note that
`test_decision_is_extracted_from_a_run_envelope` survives only if
`extract_flow_output` is kept; if it is deleted with the rest of the transport,
move that count to "deleted" (19 unchanged, 8 deleted).

The two behavioural guarantees to keep asserting after the port:

1. A knowledge document still queues a review with `requires_approval` true.
2. A CRM transition that Flask rejects is never permitted by the decision layer
   — the direction the advisory contract actually cares about.

---

## 6. What was verified, and what was not

**Verified by execution:**

- `lfx.load.run_flow_from_json` loads and runs both exported flows with no
  server (CRM flow run three times, correct routing on all three).
- The router regex matches `CRM_STAGE_TRANSITIONS` on all 25 stage pairs.
- `lfx` import cost: +302 MB RSS, 89 s warm / 113 s cold, 49 core requirements.
- 36 automation tests collect across the five files.
- Dev `.env` enables the automation against `http://127.0.0.1:7860`;
  `fly.toml` has zero `LANGFLOW` references.

**Not verified:**

- The actual Fly secret set on `wa-chatbot-my` was not read, so "unset in
  production" is inferred from `fly.toml` plus the fail-open code path. Both
  possible states (unset, or set to the localhost URL) end in the same skip
  branch, so the conclusion holds either way — but the secret list is worth a
  glance before acting.
- `lfx` cost on Linux/Fly. All performance numbers are Windows dev-laptop
  numbers in a 595-package venv and will be optimistic-to-correct by an unknown
  factor. The comparison against a 1 GB VM is directional, not a benchmark.
- Fly pricing is from published shared-cpu-1x/2 GB rates, not from this
  account's bill.
