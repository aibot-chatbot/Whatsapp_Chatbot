---
description: Inspect or operate this repository's Render deployment; defaults to read-only status.
argument-hint: "[status|preflight|apply|logs|env|webhooks|verify] (default: status)"
---

Read and follow [wa-render-ops](../../.agents/skills/wa-render-ops/SKILL.md).
Requested mode: $ARGUMENTS. Empty means status. The shared skill is the source of
truth; this command does not authorize deployment, secret changes or live messaging.
