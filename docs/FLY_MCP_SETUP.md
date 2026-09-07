# Fly.io MCP connection for Codex

Configured and tested: 2026-09-07.

## Installed connection

The global Codex configuration at `C:\Users\Vincent\.codex\config.toml`
now contains the official, already-installed Fly CLI MCP server:

```toml
[mcp_servers.fly]
command = 'C:\Users\Vincent\.fly\bin\fly.exe'
args = ['mcp', 'server']
```

It uses local standard input/output. No HTTP listener, custom server, new Fly
application or token copied into Codex configuration is required. The installed
Fly CLI is version 0.4.95; Fly labels its MCP server experimental.
[Official Fly MCP server](https://fly.io/docs/flyctl/mcp-server/).

Restart Codex to load the server into a fresh session, then request a read-only
check such as: **Use Fly MCP to list my apps and check wa-chatbot-my.**
Codex supports executable-based MCP registration through `codex mcp add`.
[Official Codex MCP documentation](https://developers.openai.com/codex/mcp).

## Verification and current hosting state

| Check | Result |
| --- | --- |
| Fresh `codex mcp get fly` | Enabled; stdio; expected executable and arguments |
| Fresh server process using the saved configuration | MCP initialization succeeded; 60 tools listed |
| Read-only `fly-apps-list` through MCP | Existing Fly authentication worked; `wa-chatbot-my` returned as suspended |
| Read-only `fly-status` through MCP | Fly rejected Machine lookup: trial ended; credit card required |
| Configuration preservation | Backup created; parsed configuration comparison confirmed only the `fly` entry was added |

The MCP connection is working; this does not mean the public app is running.
This setup performed no deployment, Machine start, DNS change, secret update or
billing action. Management tools are exposed by the official server; future
production mutations still need authorization for the specific task.

The active conversation's tools were not hot-reloaded. Protocol testing used a
fresh local MCP process with read-only calls, not a claim that this conversation
already exposes the new `fly` tools.

## Maintenance

Inspect configuration with `codex mcp get fly`. Remove only this connection with
`codex mcp remove fly` if desired. The pre-change backup is
`C:\Users\Vincent\.codex\config.toml.before-fly-mcp-20260907-173551.bak`;
do not restore the entire backup over later unrelated configuration changes.

If authentication expires, use the official `fly auth login` flow locally;
never paste an access token into chat or this file. Resolving Fly billing is a
separate account action, not an MCP installation repair.

For the application release, see [Public Deployment Plan](PUBLIC_DEPLOYMENT_PLAN.md).

## Security verification handoff

The required Codex Security scan was started against the exact new MCP stanza
in an isolated configuration snapshot, not the full credential-bearing global
configuration or the upstream Fly executable. Preflight passed. At handoff it
remains running, with no completed report; this is **not a passed scan**.

Scan ID: `6b396a98-91ff-40b8-8273-d815ec258096`.
Inspect with:

```powershell
codex-security scans show 6b396a98-91ff-40b8-8273-d815ec258096 --format json
```

Artifacts are directed to
`C:\Users\Vincent\AppData\Local\Temp\codex-fly-mcp-scan-20260907`.
The scan was left running; verify its terminal outcome, finalized report and
coverage before closing the security check.
