# AGENTS.md

Multi-tenant Flask/Supabase; vanilla HTML/CSS/JS.

## Boundaries
- Scope tenant data to the authenticated company; verify chatbot ownership and permissions.
- HTTP in app/routes; business logic in app/services; Supabase in app/database.
- Keep secrets out of frontend, logs and commits; mock external services and use no live credentials in tests.
- Use integer micro-MYR internally; preserve payment/callback/retry idempotency and API contracts.
- Require explicit authorization for destructive DB work, production data/config changes, RPC/RLS changes, live payments/messages, authentication architecture changes, breaking APIs, history rewrites or bulk deletion. Existing authorization counts; prepare reviewable local work first.
- Preserve unrelated edits. Check references and team ownership before removing legacy files.

## Execution
Follow the user's scope through implementation and verification. Resolve routine gaps from evidence; ask only when an answer materially changes the outcome or authority is missing. User instructions take precedence over skill guidance, within system/developer constraints.

Trace callers and tests before editing; reuse existing patterns. Load only task-relevant skills/docs. Use available tools; verify capability before relying on a named MCP server. Delegate independent bounded work when it saves time; assign file ownership and keep integration with the parent.

For code changes, read [the workflow](docs/AGENT_WORKFLOW.md). Run focused mocked tests, applicable syntax checks and git diff --check; expand checks when risk or failures justify it. Documentation-only work needs link/structure and behavior review, not the application suite. Report outcome, changed paths, exact checks and gaps; never present unrun checks as passed.

For Render operations, use the repository wa-render-ops skill. Keep runtime model, effort and permission settings in the host configuration.
