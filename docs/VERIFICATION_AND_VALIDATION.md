# Verification, Validation and Confirmation

What must be installed, run and proven before the next build cycle starts.

Compiled 7 August 2026. Structural figures come from a `codebase-memory-mcp` index of this
repository; tooling figures come from import probes against `.venv` and a file-existence
sweep. Both are reproducible with the commands in section 8.

---

## 1. Why this document exists

`~/.claude/rules/common/testing.md` requires 80% coverage and three test types. The
security rules require a secret scan and a dependency audit before every commit. The code
review rules require CI to be green before review.

**None of that is currently measurable.** Coverage is not installed, no linter or type
checker exists, no security scanner is present, and there is no CI at all. The standards
are stated; the instruments that would prove them are absent.

This document lists the instruments, what each one answers, and what must be true before
work is called done.

---

## 2. What is being verified

From the knowledge graph index of this repository:

- 5,640 nodes and 27,953 edges across 237 Python files, 41 SQL files, 33 HTML files and
  5 JavaScript files.
- **305 HTTP routes**, 303 classes, 1,256 functions and 2,124 methods.
- 1,613 TESTS edges, meaning the suite reaches a large part of the call graph.
- Three cron entry points under `app/jobs/`, none of which a web request can reach.

Three functions carry the load-bearing invariants, by fan-in:

- `app/utils/access_control.py :: verify_chatbot_access` — 73 call sites. This is the
  tenant isolation gate. There are 305 routes and 73 call sites, so any V&V plan must
  answer which routes are chatbot-scoped and whether every one of them passes through it.
- `app/services/ai_access_policy.py :: resolve_ai_access` — 64 call sites. Provider and
  model entitlement.
- `app/services/billing_guard.py :: can_use_plan_feature` — 33 call sites. Plan gating,
  and it fails open when a key is absent.

Those three are where a regression costs money or leaks data, so they set the priority
order for tooling.

---

## 3. Current tooling state, verified

| Tool | Purpose | State |
|---|---|---|
| pytest | Test runner | Installed in `.venv` |
| @playwright/test 1.62.0 | Browser end-to-end | Installed, pinned in `package.json` |
| pytest-cov | Coverage measurement | **Missing** |
| coverage | Coverage measurement | **Missing** |
| ruff | Lint | **Missing** |
| black | Format | **Missing** |
| isort | Import order | **Missing** |
| mypy | Type check | **Missing** |
| bandit | Python security scan | **Missing** |
| pip-audit | Dependency CVE scan | **Missing** |

Configuration and automation, all absent: `pyproject.toml`, `setup.cfg`, `pytest.ini`,
`tox.ini`, `.ruff.toml`, `mypy.ini`, `requirements-dev.txt`, `Makefile`,
`.pre-commit-config.yaml`, `.github/workflows`.

**`requirements.txt` declares runtime dependencies only.** pytest is not in it. A new
developer who follows the documented install cannot run a single test. The suite runs today
only because pytest was installed by hand into `.venv` during a working session.

---

## 4. The six V&V layers and the tool each one needs

### Layer 1. Static verification

Answers: does the code parse, conform, and type-check before anyone runs it.

- **ruff** for lint. Fastest to adopt, no config required to start, and it subsumes
  flake8 and isort.
- **black** for format, so diffs stop carrying whitespace noise.
- **mypy** for types. Adopt it in non-strict mode over `app/services/` and
  `app/database/` first, because the newest modules already carry full annotations while
  the older services carry none.

This layer is currently zero. Every style and typing judgement this week was made by
reading, not by tool.

### Layer 2. Unit and integration test

Answers: does behaviour hold, and how much of it is actually exercised.

- **pytest** is present and works. Declare it.
- **pytest-cov** is the missing half. Without it the 80% requirement is unenforceable and
  unfalsifiable.

Baseline to record before anything changes: the suite currently reports 23 failures and
37 errors that pre-date this work. **A gate of "tests pass" is meaningless while 60 node
IDs are permanently red.** The gate must be "the failure set is byte-identical to the
recorded baseline", which is how every change this week was actually verified. Either
adopt that comparison formally or fix the 60 and gate on green.

### Layer 3. Security

Answers: are we shipping a known vulnerability or a leaked credential.

- **bandit** for static Python security. It would have flagged the SSRF in
  `fetch_and_parse_url`, where URL validation checks the scheme only.
- **pip-audit** for dependency CVEs. Nothing checks this today.
- **A secret scanner** in pre-commit. There is a live outstanding case: the account
  password from the former `tests/test_api.py` still requires rotation. Removing a file
  does not unpublish a credential that was pushed.

### Layer 4. Database validation

Answers: will this migration apply, and can it be reversed.

This is the weakest layer and the one with the highest blast radius.

- **The DDL for the core tables is not in this repository.** `chatbots`, `bot_configs`,
  `knowledge_files`, `knowledge_chunks` and `conversations` have no `CREATE TABLE`
  anywhere in `data/`. Column types, nullability and constraints are inferred from the
  repository layer.
- `\d+` is a psql meta-command and this team applies migrations through the Supabase SQL
  Editor, so the obvious verification step is not executable here. The workaround is a
  SELECT-only catalog inspection script.
- Two such preflights exist: `scripts/bot_configs_persona_unification_preflight.sql` and
  `scripts/conversation_graph_nodes_preflight.sql`. **Migrations 032 and 034 have none.**
- There is no migration runner and no applied-migrations ledger. Ordering is enforced by
  documentation only. The one mechanical guard that exists,
  `HIGHEST_MIGRATION_NUMBER` in two test files, still reads 29 while the highest migration
  is 34, so it has been failing silently since migration 030 landed.

Required before the next cycle: a preflight per migration that alters an existing table,
and a decision on whether to reconstruct the missing DDL in the style of
`data/030_bot_media_attachments.sql`, which already sets that precedent.

### Layer 5. Browser end to end

Answers: does the user-facing path work in a real browser.

`@playwright/test` is installed and pinned, `playwright.config.js` exists, and four specs
live under `tests/browser/`. This layer works.

Two harness styles now coexist: the older specs serve `frontend/` statically and mock
`/api/**`, while `testbot_persona_server.py` runs the real Flask app with only Supabase
and the model provider doubled. The second style is the one that can catch a real
regression; mocking the API under test produces a green that proves nothing. Standardise
on the live-app harness for anything that asserts behaviour.

### Layer 6. Runtime confirmation

Answers: did the thing we deployed actually come up and serve.

Nothing automated exists. `docs/DEPLOYMENT_CHECKLIST.md` covers the steps but there is no
post-deploy smoke check. At minimum: one request per critical route family after deploy,
asserting status and a known response key.

---

## 5. MCP servers in the V&V loop

These are registered at user scope and are the default instrument for their job.

| Server | V&V use |
|---|---|
| `codebase-memory-mcp` | Impact analysis before a change. `search_graph` to find every definition, `trace_path` for call chains, `get_architecture` for seams. Use it before grepping file by file, per the code discovery protocol. It produced every structural figure in section 2. |
| `headroom` | Compress large diffs, logs and test output before reasoning over them, so a long run does not consume the context that the reasoning needs. |
| `prompt-optimizer` | Sharpen a vague verification brief into an executable one before dispatching work. |
| `markitdown` | Convert a PDF or DOCX specification into Markdown so it can be diffed and cited rather than described from memory. |
| `agent-reach` | Check which channels are reachable before attempting web research, so a blocked channel does not read as a missing answer. |

Practical note from this cycle: the repository was not indexed until today. Index it at the
start of a work session, not in the middle, or early exploration silently falls back to
grep and misses relationships the graph would have surfaced.

---

## 6. Confirmation gates

What must be true before each transition. Nothing here is aspirational; each item is
something that went wrong or nearly went wrong during the last cycle.

### Before a change is called done

- Failure set byte-identical to the recorded baseline, compared by sorted node ID, not by
  count. Counts drifted twice this week and hid nothing only by luck.
- Tests written before implementation, and observed failing for the stated reason. A test
  that passes on first run proves nothing until it has been shown to fail.
- Mutation check on any test asserting a security or billing invariant. Two agents this
  week ran mutations that initially passed because the mutation was a no-op, which would
  otherwise have been reported as strong coverage.
- No test reaching a billed provider. Every provider seam stubbed, and the stub asserted
  not-called where the path should not reach it.

### Before a migration is applied

- The matching preflight has been run against the live database and every result set
  attached to the change record.
- Any destructive or irreversible export taken first. Divergent legacy values are
  unrecoverable once overwritten.
- Migration applied strictly before the code that depends on it. Code first fails every
  write with `PGRST204` or `23502`.
- The rollback has been read, and what it cannot restore is written down.

### Before deploy

- Secret scan clean, dependency audit clean.
- The outstanding credential rotation closed.
- One smoke request per critical route family after the deploy completes.

---

## 7. What blocks confirmation today

- Coverage cannot be measured, so the 80% standard cannot be met or refuted.
- 23 test failures and 37 errors pre-date this work and have no owner. Until they are
  fixed or formally accepted as a baseline, "green" has no meaning here.
- No CI. Every check this week was run by hand, which is why the failure-set comparison
  had to be done manually each time.
- Migrations 032 and 034 have no preflight.
- The core table DDL is absent, so no migration touching those tables can be certified
  from the repository alone.
- The `HIGHEST_MIGRATION_NUMBER` guard is stale at 29 and has been failing since 030.
- The credential from the former `tests/test_api.py` is unrotated.

---

## 8. Install plan

Nothing below changes runtime behaviour. Each line is one command and one file.

1. Create `requirements-dev.txt` declaring pytest, pytest-cov, ruff, black, mypy, bandit
   and pip-audit, so the toolchain is reproducible rather than resident in one developer's
   `.venv`.
2. Add `pyproject.toml` with the pytest, ruff, black and mypy sections. One file, four
   tools, no scattered config.
3. Record the current failure set to a checked-in baseline file so the comparison gate is
   mechanical rather than remembered.
4. Add `.pre-commit-config.yaml` running ruff, black and a secret scan on changed files
   only, so the hook stays fast enough to survive.
5. Add a CI workflow running the suite, the linters and pip-audit. Start it advisory, not
   blocking, until the 60 pre-existing failures are resolved.
6. Write the missing preflights for migrations 032 and 034 following the two that exist.
7. Fix `HIGHEST_MIGRATION_NUMBER` in
   `tests/test_crm_agent_actions_hardening_migration.py` and
   `tests/test_crm_agent_actions_orphan_cleanup_migration.py`.

Reproduce the audit in this document with:

- Tooling: import-probe each package against `.venv` and test for the config files listed
  in section 3.
- Structure: `index_repository` then `get_architecture` via `codebase-memory-mcp`.

---

## 9. Order of adoption

Adopt in the order that closes the largest blind spot first, not in the order that is
easiest.

1. Declare the test dependencies. Without this nobody else can verify anything.
2. Coverage, so the existing standard becomes measurable.
3. The failure-set baseline, so a gate can exist at all.
4. Security scanning, because the three highest-fan-in functions guard tenancy, model
   entitlement and billing.
5. Lint and format, which are cheap and reduce review noise.
6. CI, once there is something stable to run.
7. Type checking last, scoped to the newest modules, because it is the most invasive to
   retrofit.
