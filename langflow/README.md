# Langflow automation contracts

These files are **contract JSON**, not raw Langflow canvas exports. They define
the webhook payload, validation rules, monitoring fields, and side-effect
decision that a Langflow flow must produce. Build the visual flow in a private
Langflow instance with a Chat Input carrying JSON and Chat Output, then keep Flask as
the tenant, billing, and side-effect boundary.

Recommended flow shape:

`Webhook → JSON validation → decision/routing → JSON output`

Do not add database, filesystem, Python, messaging, or arbitrary HTTP tools to
these flows.

`app/services/langflow_decision.py` validates every flow response against the
`output_schema` in these contract files before it is allowed to influence
anything, and `app/services/automation_service.py` consults it advisorily:
Langflow can refuse a transition Flask allows, but can never permit one Flask
rejects, and any Langflow failure (disabled, unreachable, slow, or
non-conforming output) leaves the decision with Flask rather than blocking a
user-facing action. `app/services/langflow_adapter.py` is only the transport.

Endpoint format:

```text
POST https://LANGFLOW_SERVER/api/v1/run/FLOW_ID
x-api-key: LANGFLOW_API_KEY
Content-Type: application/json
```

Use `/api/v1/run/`, not `/api/v1/webhook/`. Both exist on the server, but
`webhook` is fire-and-forget - it answers "task started" and never returns the
flow output, so a decision cannot be read back from it. The `trigger.source`
field inside the contract JSON still says `webhook`; that is historical and the
adapter deliberately does not follow it.

Note that a flow whose input node is a **Webhook** component receives nothing
when invoked through `/api/v1/run/`, which is why the current stub flows echo
empty values.

Both automations are wired into Flask:

- `apply_crm_stage_automation` consults the CRM flow before applying a stage
  change. Langflow may refuse a transition Flask allows; it can never permit one
  Flask rejects, and any failure leaves the decision with Flask.
- `schedule_knowledge_document_follow_up` consults the knowledge flow for a
  reviewer summary. That flow's `decision` and `requires_approval` are `const`,
  so it has no blocking path at all - the review is queued either way and the
  summary is enrichment.

Every event records `automation.consulted`, `automation.correlation_id`, and
either `automation.summary` or `automation.skipped_because`, so it is always
visible whether Langflow contributed and why not.

The current backend endpoints are:

- `GET /api/automation/events` — owner/admin monitoring
- `GET /api/automation/health` — operator health (`degraded` when the event table is unavailable)
- `POST /api/automation/crm-stage` — owner/admin stage transition

Migration `data/049_automation_events.sql` is applied in the active Supabase
project. Durable event persistence still remains advisory at runtime, and the
health endpoint reports if the table becomes unavailable.

## Running without Langflow

The Flask application does not require a Langflow process to be open. Langflow
is an advisory second opinion: when it is disabled or unreachable, Flask keeps
its own tenant checks, CRM stage allowlist, and side effects running, while the
decision result records that the advisory call was skipped when an event can be
persisted. Start the pinned local server only when advisory decisions or
review summaries are wanted; closing it leaves user workflows fail-open.

## Imported local flows

Validated on the active local Langflow `1.11.5` server on 2026-08-29:

- Knowledge Document Follow-up: `3c0a6167-01f7-4ed1-9b8c-5842ef75b3d2`
- CRM Stage Automation: `f755be84-2dd6-4412-8161-aa2e07cebf68`

Server-generated exports are stored beside these contracts as
`*.langflow.json`. They contain only Webhook, Parser, and Text Output nodes;
Flask still performs tenant authorization and every CRM side effect.

## Built flows

Both flows were rebuilt on 2026-09-02 and now satisfy their contracts. They use
only stock components - no custom component, code interpreter, filesystem or
outbound network access, as the contracts' `security` block requires.

**CRM Stage Automation** (7 nodes)

```
ChatInput -> JSONtoData -> Parser(apply)  -.
          |                Parser(block)  -+-> ConditionalRouter -> ChatOutput (apply)
          '------------------------------'                      -> ChatOutput (block)
```

The `authorize` step is one `ConditionalRouter` in `regex` mode. Its match
pattern is an order-independent lookahead encoding of the same allowlist held in
`CRM_STAGE_TRANSITIONS`:

```
new -> contacted|qualified|lost ; contacted -> qualified|won|lost ; qualified -> won|lost
```

The two Parser nodes render the `apply_crm_stage` and `block_crm_stage` objects
from the incoming payload, so identifiers are echoed back and Flask can confirm
the verdict is about the transition it asked about.

**Knowledge Document Follow-up** (4 nodes)

```
ChatInput -> JSONtoData -> Parser(review) -> ChatOutput
```

Its `decision` and `requires_approval` are `const` in the contract, so it needs
no routing; the flow echoes the correlation id and renders a reviewer summary.

Two things worth knowing before editing these flows:

- Invoke with `input_type: "chat"`. `input_value` is routed to the input node
  matching that type, so a flow starting with `ChatInput` receives nothing when
  called with `input_type: "text"`.
- `ChatOutput.input_value` is not a list input. Two edges into one output
  silently drop one branch, which is why the CRM flow has an output per branch.

Server-generated exports are stored beside the contracts as `*.langflow.json`.

### Connection repair verified on 2026-09-08

The local saved CRM flow had lost four connections and the knowledge flow had
lost one, so the server returned HTTP 200 with empty outputs. The installed
editor removes connections to advanced input fields and handles whose metadata
does not match the target field. The repair makes the router's two connected
message fields non-advanced and regenerates all three Chat Output input handles
from their actual templates. Component code and flow IDs are unchanged.

The corrected exports and local saved flows retain all **8 CRM and 3 knowledge
connections**. `tests/test_langflow_exports.py` checks field visibility, handle
types, serialized handles and edge IDs so future edits cannot silently restore
the invalid metadata.

## Running the local server

Windows starts the local server at **Vincent's sign-in**, through the existing
Startup-folder `start-langflow-hidden.vbs` entry and the launcher below. This
does not provide service before sign-in, during sleep, or while the PC is off.
The Flask application must also be running for application-triggered automation.

The server runs on the canonical origin **`http://127.0.0.1:7860`**. That exact
host and port is hard-coded in three places that must agree: `LANGFLOW_SERVER_URL`
in `.env`, and both `langflow-*` MCP server registrations.

**Start it with `C:\Users\Vincent\bin\start-langflow.cmd`**. The launcher runs
[`scripts/start-langflow-supervisor.ps1`](../scripts/start-langflow-supervisor.ps1),
using the installed Hermes-environment Langflow executable with
`--host 127.0.0.1 --port 7860 --backend-only`. It retains the existing storage
and environment settings. A per-user, per-port mutex within the Windows sign-in
session rejects duplicate supervisors. An occupied port is observed without starting another server;
when that listener disappears, or a launched process exits, the supervisor
retries at 30-second intervals. Server startup time is additional.

The supervisor records only state and exit codes in
`%LOCALAPPDATA%\langflow\supervisor.log`, rotating at 1 MiB. It does not restart
a hung process that still holds the port or restart itself after being killed;
run the launcher again in those cases. The existing Windows Startup entry runs
it on the next sign-in. The pre-change launcher backup is
`C:\Users\Vincent\bin\start-langflow.cmd.backup-20260908-110447`.

The final session-local lock repair passed isolated testing. Restarting the
existing supervisor was blocked by automatic approval review, so that running
process retains the earlier Global lock until the next Windows sign-in.

Run the isolated recovery regression with
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-langflow-supervisor.ps1`.
It uses a temporary fake executable and an unused loopback port; it checks
occupied-port handling, duplicate supervision, failed-start retries and child
crash recovery without stopping the real server.

Local verification on 2026-09-08: **65 focused tests passed**, both live flows
returned valid decisions, four concurrent synthetic requests retained distinct
client/request identities, and a refused loopback connection preserved both
fail-open paths. A controlled real process stop was recovered by the supervisor
on port 7860, followed by ten successful runtime health checks. Cold server
startup took several minutes in that run. These checks establish local behavior;
a Windows reboot, unattended operation over days and hosted deployment were not
tested. The Flask application was not running on ports 8000/5000 at verification
time, so application routes were tested with mocks and live flow calls used
synthetic inputs directly.

Security follow-ups remain for CRM request-size limits, hard overall HTTP
deadlines and trust in the local HTTP service. The security scan covers the
version before the final health-cache and session-lock repairs; those two
repairs passed separate verification, not a fresh full scan.

Do **not** run a bare `langflow run`. Langflow auto-bumps to the next free port
when 7860 is briefly held — by a still-shutting-down previous instance, for
example — and comes up on **7861** instead. This is the worst kind of failure
because it looks like success: the console reports a healthy server and the web
UI loads, but nothing that depends on the canonical origin can reach it. `.env`
still points at 7860, so every automation silently degrades to
`skipped_because: unreachable` (fail-open, so no user-facing error appears), and
both `langflow-*` MCP servers fail to dial their `/api/v1/mcp/project/.../sse`
endpoints. The supervisor's mutex and occupied-port check prevent its duplicate
launches; avoid starting a separate bare CLI while it is supervising the port.

## Local configuration

`GET /api/automation/health` retains its HTTP 200 response and
`checks.automation_events` boolean, and also returns `checks.langflow.status`:
`disabled`, `not_configured`, `unavailable`, `checking`, or `ok`. Enabled but incomplete or
unreachable Langflow makes the overall status `degraded`. The runtime probe
uses `/health_check`, a two-second socket timeout and a 1 KiB response limit;
it sends no API key and runs no flows. `ok` confirms configuration presence and
server health, not API-key validity or successful flow execution. The complete
health snapshot is cached per Flask process for ten seconds, including failures.
Only one request can refresh it at a time; other requests with no fresh snapshot
return `degraded`/`checking` immediately, never a stale `ok` or a blocking wait.

The run adapter requires HTTP 200; an asynchronous HTTP 202 acknowledgement is
not a completed decision. CRM advice must match company, chatbot, lead, target
and correlation ID; knowledge advice must match the request's correlation ID.
Mismatches follow the existing fail-open policy and appear in event metadata.

All seven settings are also listed in the tracked `.env.txt` template.

```env
LANGFLOW_AUTOMATION_ENABLED=true
LANGFLOW_SERVER_URL=http://127.0.0.1:7860
LANGFLOW_ALLOW_INSECURE_LOCAL=true      # required: local server is plain HTTP
LANGFLOW_API_KEY=...                    # langflow api-key (AUTO_LOGIN must be on)
LANGFLOW_TIMEOUT_SECONDS=5
LANGFLOW_CRM_FLOW_ID=f755be84-2dd6-4412-8161-aa2e07cebf68
LANGFLOW_KNOWLEDGE_FLOW_ID=3c0a6167-01f7-4ed1-9b8c-5842ef75b3d2
```

A **User-scope Windows environment variable** named `LANGFLOW_API_KEY` takes
precedence over this file, because `load_dotenv()` does not override real
environment variables. If the server answers `403 Invalid or missing API key`
while `.env` looks correct, that stale variable is the cause.

That shadowing variable had drifted out of sync and **has now been realigned**:
`.env` and the User-scope `LANGFLOW_API_KEY` hold the same value, so the two no
longer disagree. Anyone rotating the key must change it in **both** places, or
the stale User-scope copy silently wins again.

## Verified live

End-to-end against the local server on `127.0.0.1:7860`, both flows consulted
successfully:

| Flow | Case | Result |
|------|------|--------|
| CRM Stage Automation | `new` → `contacted` | approved |
| CRM Stage Automation | `lost` → `contacted` | blocked |
| CRM Stage Automation | `qualified` → `won` | approved |
| Knowledge Document Follow-up | reviewer summary | returned |

`lost → contacted` blocking is the meaningful check: `lost` is a terminal stage
in `CRM_STAGE_TRANSITIONS`, and the flow's `ConditionalRouter` allowlist agrees
with Flask rather than contradicting it.

Note this exercises the **advisory** path only. Because the layer is fail-open by
design, a passing run proves Langflow is reachable and contract-conforming; it
does not prove the automation is load-bearing, and it would still report success
if durable persistence were missing (see the migration note above).

Langflow 1.11.5 requires `mcp<2.0.0` (pinned by its `lfx` dependency). With
`mcp` 2.x installed the server aborts at import with
`cannot import name 'McpError' from 'mcp.shared.exceptions'`.
