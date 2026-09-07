# Skill review: repository Render command (2026-09-07 submission)
**Verdict:** NEEDS-WORK — 4/10 — Four major findings affect portability, scope, state freshness, and context cost.
**Safety scan:** hidden instructions: none found · unguarded destructive ops: live operations lack local mode gates; root AGENTS.md still requires approval
**Token cost:** description ~19 · body ~2404 · support files ~0 · flagged waste ~40 (tokens ≈ bytes ÷ 4)

## Findings
| ID | Severity | Rule | Location | Issue → concrete fix |
|---|---|---|---|---|
| F1 | `[major]` | D1 loading | [render.md](../.claude/commands/render.md) | Claude-only command, Bash heredoc and named MCP tools do not establish Codex/PowerShell compatibility → expose the shared procedure as a repository SKILL.md, retain a thin Claude entrypoint, discover current tools |
| F2 | `[major]` | D3 scope | [render.md](../.claude/commands/render.md) | `status` directs the agent to move to `apply`; webhook and verification modes include live changes → finish status as read-only and require existing authorization for the exact live operation |
| F3 | `[major]` | D4 behavior | [render.md](../.claude/commands/render.md) | A null tool result proves neither service absence nor API incapability; historical CLI/auth limitations are permanent instructions → distinguish unavailable evidence from confirmed absence, check current capabilities when needed |
| F4 | `[major]` | D7 efficiency | [render.md](../.claude/commands/render.md) | Repeated narrative and deployment history load for every subcommand; final paragraph mandates unrelated vault writes → remove the 161-byte final paragraph and route to only the requested mode, preserving operational constraints |

## Dimension coverage
| # | Dimension | Status |
|---|---|---|
| 1 | Loading & portability | F1 |
| 2 | Discoverability | clean |
| 3 | Scope & boundaries | F2 |
| 4 | Agent-behavior simulation & safety | F3 |
| 5 | Form matches failure | clean |
| 6 | Discipline enforcement | n/a — no demonstrated pressure failure |
| 7 | Token efficiency | F4 |
| 8 | Examples & structure | clean |
| 9 | Testing evidence | not reviewed — no retained behavioral run supplied |
| 10 | Plugin-level review | n/a — repository command, no plugin manifest |

## Enhancements
Add positive and negative trigger scenarios plus a read-only status scenario; retain the baseline separately from post-edit evidence.

## Done well
The command records useful CORS, proxy, disk, callback, and secret-handling concerns, and distinguishes preparation from successful deployment.

## Not reviewed
Live Render access, service identity, credentials, production webhooks, and runtime deployment health. Links above identify logical artifacts; the original command is backed up outside the repository before editing.

## Decision
**Call:** hold — fix the majors, then re-review
**Fix status:** fixes not applied; future fixes require independent re-review
**Open questions:** none
