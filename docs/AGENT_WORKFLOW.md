# Repository development workflow

Read this for code changes; use only the sections relevant to the task.

## Scope and implementation

For reported bugs/errors, use the installed Sentry plugin when the relevant
project is accessible: inspect the issue and deployed release, reproduce safely,
fix and test, then check events after an authorized deployment. Follow
[the Sentry workflow](SENTRY.md); unavailable access is a verification gap.

Inspect `git status --short` and the affected routes, services, repositories,
frontend callers and tests. Trace bugs to the shared source of truth before editing.
Use the current checkout and source as evidence; historical reports are context.
For multi-step work, state the outcome, constraints, short plan and completion check.
Small, clear edits can proceed directly.

Make focused changes; avoid speculative abstractions or dependencies. Add a regression
check for changed logic; for refactoring, establish coverage for behavior that must
remain stable before changing it. Use existing test infrastructure.

Delegate independent slices with a bounded question or file set, acceptance evidence
and instructions to preserve others' changes. Keep dependent edits sequential. The
parent integrates and verifies; a worker's completion message alone is not proof.
Use native collaboration when available; OMX-specific operations require a verified
compatible runtime. Never edit `.omx` pointers manually.

## Verification

Use a working project Python interpreter. Inspect tests before execution: external
clients, HTTP, email, AI providers, payments and messaging must be mocked. Avoid
root-level diagnostic scripts that may connect to live services.

| Change | Smallest relevant check |
|---|---|
| Python behavior | `python -m pytest tests/<relevant_test>.py -q` and `python -m py_compile <changed_file.py>` |
| Shared Python behavior | Focused suite first; `python -m pytest tests -q` when broader risk warrants it |
| Frontend interaction | Relevant source tests and matching Playwright script in `package.json`; verify which checkout the server serves |
| Astro page (`web/`) | `npm --prefix web run build`, `run check` and `test`. Flask and the Playwright server serve `web/dist` before `frontend/`, so rebuild after every `web/` change and after switching branches (`web/dist` is gitignored and survives a checkout) |
| Instructions/skills | Validate frontmatter, paths, loading and realistic decisions; distinguish simulation from execution |
| Any diff | `git diff --check`, plus final scope review including new files |

Substitute real paths for template arguments in angle brackets.
Confirm installed tools and repository config before choosing lint/typecheck commands.
For security-sensitive code, infrastructure, dependency, auth, data, network or CI/CD
changes, run the applicable Codex Security scan. A blocked scan is incomplete.
Keep scan artifacts outside tracked source and protect secrets in collected output.

Once required checks pass, repeat or broaden them only for new changes, failures or
unresolved risks. Record actual counts and exit codes. Distinguish baseline failures,
environment failures and regressions; do not stash or overwrite unrelated work.
See [Testing Guide](TESTING_GUIDE.md) for coverage areas; historical totals do not
establish current results.

## Completion and continuation

Update [Feature Status](FEATURE_STATUS.md) for meaningful feature status changes and
[Development Roadmap](DEVELOPMENT_ROADMAP.md) for completed or changed phases.
Instruction maintenance alone does not change product feature status.

Use existing status vocabulary: **Verified complete** requires current verification
and a stated scope; **Implemented** means verification is incomplete; **Partially
implemented** means missing/disconnected parts; **On hold** is intentional;
**Obsolete** is superseded; **Needs investigation** means insufficient evidence.
Local mocked tests do not establish live database, browser or deployment success.

Finish with the outcome, changed files, exact validation and material gaps. Add manual
steps, a commit suggestion or next phase only when relevant. For interrupted work,
retain the objective, completed checks and next unresolved step in the task's existing
plan; do not restart discovery or create parallel progress logs by default.
