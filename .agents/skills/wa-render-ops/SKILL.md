---
name: wa-render-ops
description: Inspect, troubleshoot or operate the Whatsapp_Chatbot Render deployment and its channel webhooks. Use for Render status, preflight, logs, environment review or an explicitly requested rollout; not general app development or other hosting providers.
---

# Render operations for Whatsapp_Chatbot

Use the requested mode below; default to `status`. Follow the repository AGENTS.md.
An inspection request authorizes inspection only. Check existing authorization
before any deployment, production environment change, secret rotation, webhook
re-registration, disconnect/reconnect, paid resource creation or live message.
Prepare the exact target/change first; ask only for missing authorization.

Read `render.yaml` and the current checkout before using a host, workspace, branch or
service ID. A blueprint is desired configuration, not proof of a live deployment.
Discover available provider tools; confirm workspace and service using read-only
results. Null/error/inaccessible results mean unknown, not confirmed absence.
If several services match, resolve the target before acting. Respect another
provider explicitly selected by the user; do not migrate it to Render.

| Mode | Action and completion evidence |
|---|---|
| `status` | Report verified service, deployment state and commit/time when available. Stop after reporting; never advance to apply automatically. |
| `preflight` | Read [deployment constraints](references/operations.md). Inspect declared config and run relevant mocked tests. Do not import the real app with inherited credentials. Report checks and gaps. |
| `logs` | Retrieve only the relevant service/time window; redact secrets, personal message content and tokens before reporting. An unavailable tool is a stated gap. |
| `env` | Compare required key names and presence only. Read deployment constraints; do not dump values or bulk-copy `.env`. Updates require authorized keys/target and merge semantics. |
| `apply` | Read deployment constraints; reuse the existing blueprint. Verify current provider capabilities. Perform the authorized rollout through an available supported tool/UI; otherwise report the exact missing access/action. Confirm the resulting deployment state. |
| `webhooks` | Read channel procedures in [operations](references/operations.md). Confirm host, tenant/channel scope and authorization before changing callbacks or secrets. |
| `verify` | Read verification in [operations](references/operations.md). Start with read-only evidence. Report live messaging, uploads and redeploy tests separately; execute only when authorized. |

Finish with observed state, checks and remaining gaps. Do not convert historical
CLI/auth failures into permanent tool limitations. Do not regenerate deployment
configuration or write cross-project memory as a side effect of this skill.
