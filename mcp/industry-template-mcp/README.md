# industry-template-mcp

Remote MCP server (Cloudflare Worker) for adding a chatbot industry. It opens a pull
request; it never merges or deploys.

## Connect (developers)

```
claude mcp add --transport http industry-mcp https://industry-template-mcp.aibot-1a3.workers.dev/mcp
```

Then `/mcp` → `industry-mcp` → Authenticate: approve the consent page, then authorize on
GitHub. Every tool requires write access to `aibot-chatbot/Whatsapp_Chatbot`.

## Tools

| Tool | What it does |
|---|---|
| `list_industries` | Built-in and added industry ids on the base branch. `acceptsNewIndustries: false` means the base branch has no extension loader yet. |
| `validate_industry` | Checks a spec with the same rules as `validate_extension` in `app/services/industry_template_catalog.py` and previews the file. Changes nothing. |
| `propose_industry` | One commit on `industry/<id>`: `app/services/industry_templates/<id>.py` plus its `.dockerignore` line, and a pull request to the base branch. |

After a proposal: the `industry-templates` workflow runs the industry tests, a human
reviews the checklist in the PR, the owner merges, then Flask and the analysis worker
are deployed on the same image.

## Operate

- Deploy: `npm ci && npx wrangler deploy`. The base branch is `BASE_BRANCH` in `wrangler.jsonc`.
- Secrets (never in files): `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `COOKIE_ENCRYPTION_KEY`,
  set with `npx wrangler secret put <NAME>`. GitHub OAuth App callback: `<worker URL>/callback`.
- Check: `npm test` and `npx tsc --noEmit`.
