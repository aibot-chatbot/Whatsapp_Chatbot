# n8n automation worker

n8n drains the `automation_events` outbox. It is the opposite half of the
Langflow layer, and the two never overlap:

| | Langflow | n8n |
|---|---|---|
| When | Synchronously, inside a request | Asynchronously, after the response |
| Job | Judgement — *should* this happen? | Action — do the outward-facing work |
| Owns side effects | Never | Yes, but only work Flask already queued |
| If it is down | Flask fails open and proceeds | Queued events wait, users unaffected |

Flask makes exactly one outbound call to n8n, a health probe. The work flows the
other way: n8n polls, claims, acts, and reports back. That is why n8n holds a
worker token and this app holds no n8n credentials.

Unlike `langflow/*.json`, nothing here is a runtime input. These files are not
in the `.dockerignore` allowlist and are not shipped in the container.

## Setup

1. **Flip the flag.** In `.env`, set `N8N_WORKER_ENABLED=true`. Until you do,
   both worker routes answer `503` even with a valid token.

2. **Create the n8n credential.** In n8n: *Credentials → New → Header Auth*.
   - Name: `Flask Automation Worker Token`
   - Header name: `Authorization`
   - Header value: `Bearer <the N8N_WORKER_TOKEN from .env>`

3. **Set the base URL.** Give n8n an environment variable
   `FLASK_BASE_URL=http://host.docker.internal:5000` (or your Fly URL in
   production). The workflow reads it as `{{ $env.FLASK_BASE_URL }}` so the same
   export works in both places.

4. **Import the workflow.** *Workflows → Import from File* →
   `automation-outbox-worker.n8n.json`. Reselect the credential on the three
   HTTP Request nodes — the exported credential id is a placeholder.

5. **Replace the two `noOp` nodes.** `Do The CRM Work` and
   `Do The Knowledge Work` are placeholders. The real side effect goes there.

6. **Verify.** `GET /api/automation/health` should report
   `checks.n8n.status = "ok"`. That proves the instance answers; it does not
   prove the workflow is active, so check the n8n executions list too.

## The contract

**Claim** — `POST /api/automation/worker/events`, body `{"limit": 10}`:

```json
{
  "status": "success",
  "data": {
    "events": [
      {
        "id": 1,
        "company_id": 42,
        "chatbot_id": 7,
        "event_type": "crm_stage_transition",
        "status": "running",
        "idempotency_key": "crm:5:qualified",
        "payload": {},
        "created_at": "2026-09-19T14:00:00+00:00",
        "updated_at": "2026-09-19T14:00:30+00:00"
      }
    ],
    "lease_seconds": 300
  }
}
```

**Report** — `POST /api/automation/worker/events/<id>/status`:

```json
{ "status": "completed", "result": { "worker": "n8n" } }
{ "status": "failed", "error_message": "SMTP timeout" }
```

Only `completed` and `failed` are accepted. `queued`, `running` and `blocked`
stay Flask's to set.

## Things that will bite you

- **The lease is the retry mechanism.** A claimed event sits at `running` for
  `N8N_WORKER_LEASE_SECONDS` (default 300). If n8n never reports, the event is
  re-offered on the next poll. So a workflow that dies silently produces an
  *infinite retry loop*, not a lost event — always keep the `Report Failed`
  branch wired.

- **Make the poll interval shorter than the lease.** At the defaults, a
  one-minute poll against a five-minute lease gives four chances to report
  before the event is handed to another run.

- **Repeat callbacks are safe.** Reporting an already-finished event returns
  `200` with `changed: false` and writes nothing. Do not add conditional logic
  to avoid the second call.

- **`limit` must be a JSON integer**, not a string. `{"limit": "10"}` is a
  `400`.

- **The worker token is a platform credential, not a tenant one.** It drains
  every company's outbox, so treat it like a service-role key: rotate it in
  `.env` and in the n8n credential together, never paste it into a workflow
  node, and never expose these routes to the public internet without the same
  care as the Supabase service role.
