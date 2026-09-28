# Industry Template MCP — design + plan

> Owner approved the design in chat on 2026-09-28 and asked Claude to continue without further review gates. The owner only steps in to sign in, register the GitHub OAuth App and approve deploys. This file therefore carries the approved design (in place of a separate spec) plus the task list. Progress ledger: `.superpowers/sdd/2026-09-28-industry-template-mcp/progress.md` (git-ignored).

**Goal:** developers add a new chatbot industry by calling our own MCP server on Cloudflare. The server validates the industry and opens a GitHub PR; tests run in CI; a human merges and deploys. Nothing goes live without a merge.

## Design (approved)

- **Repo side.** Each added industry is one data-only file, `app/services/industry_templates/<id>.py`, containing:
  - `TEMPLATE` (the catalog fields);
  - `RULES` (the chatbot rules text);
  - `SAMPLES` (3 sentences in EN/MS/ZH, used by the detection check).

  `industry_template_catalog.py` loads these files after the 9 built-in templates, which stay unchanged. Tests cover every file automatically: schema, ID format and uniqueness, text bounds, and an AST check that the file contains data only.

  `.dockerignore` lists every `app/` Python file by name (test-pinned), so each new file also needs its allowlist line. A GitHub Actions workflow runs the industry and container tests on PRs; the repo had no CI.
- **Cloudflare side.** `mcp/industry-template-mcp/`, a TypeScript Worker based on Cloudflare's `remote-mcp-github-oauth` template (workers-oauth-provider + agents McpAgent + Octokit).
  - Developers sign in with GitHub. Access requires write permission on `aibot-chatbot/Whatsapp_Chatbot`.
  - The server acts with the developer's own token; no shared bot token exists.
  - Tools:
    - `list_industries`
    - `validate_industry(spec)`: checks plus a file preview.
    - `propose_industry(spec)`: branch `industry/<id>`, commits the file and the `.dockerignore` line, opens a PR with a checklist.
  - It never merges and never deploys.
- **Base branch.** `BASE_BRANCH` is a Worker variable, currently `release/2026-09-26` (live). `main` is 60 commits behind and conflicts, so merging it is a separate task.

## Validation rules (Python tests are the authority; the Worker mirrors them)

| Field | Rule |
|---|---|
| `id` | `^[a-z][a-z_]{1,39}$`, not a built-in, equal to the file name |
| `version` | `"1.0.0"` |
| `name` | 3–60 chars |
| `description` | 10–200 chars |
| `questions` | 2–5 items, 5–150 chars each |
| `required_information` | 2–6 items, 5–150 chars each |
| `unavailable_actions` | 2–8 items, 5–150 chars each |
| `classification_hint` | 20–400 chars |
| `lead_rule` | 10–300 chars |
| `RULES` | 100–1500 chars |
| `SAMPLES` | exactly 3, 10–240 chars each |

No other keys are allowed.

## Tasks

1. **Loader + extension tests** (`app/services/industry_templates/__init__.py`, catalog loader, `tests/test_industry_template_extensions.py`). TDD with a temporary fixture package. Allowlist the `__init__.py`.
2. **Guard update.** `test_industry_list_single_source` skips the data-only `industry_templates/` package.
3. **CI workflow** `.github/workflows/industry-templates.yml`: pull_request → Python 3.11 → install requirements → the industry + container tests.
4. **Worker** `mcp/industry-template-mcp/`: scaffold from the template, then the tools, the validation mirror, `.dockerignore` insertion, the PR body, and vitest unit tests for the validation, file rendering and insertion.
5. **Owner sign-ins, then deploy.**
   - `wrangler login`, KV namespace, GitHub OAuth App (callback `https://<worker>/callback`), secrets (piped from `%USERPROFILE%\.omnexa-secrets\industry-mcp.env`, never printed).
   - `wrangler deploy`, register it in Claude Code, and run an end-to-end dry-run PR (closed without merging).
6. **Close-out:** memory, Knowledge.md.
