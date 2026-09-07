# Deployment constraints and channel procedures

Use only the requested section. Verify current source when changing deployment
behavior; these are repository constraints, not a snapshot of provider state.

## Preflight and environment

Keep the existing `render.yaml` and Docker deployment. Inspect the branch/commit
actually configured by the provider; a local fix does not prove it is deployed.
For private-repository access failures, verify the GitHub connection and repository
grant. Missing credentials are an access gap, not permission to replace the provider.

| Check | Repository reason |
|---|---|
| Production CORS | `app/config.py` rejects missing/empty CORS or a bare wildcard with `FLASK_DEBUG=false`. Match approved HTTPS origins. |
| Dev billing | Omit `ENABLE_DEV_BILLING_ROUTES` entirely in production; any non-empty value, including `false`, is rejected. |
| Meta version | `app/utils/whatsapp_utils.py` uses `VERSION` directly for outbound sends. Other Graph paths have fallbacks; verify the actual send path. |
| Meta secrets | `APP_SECRET` authenticates inbound HMAC; `WHATSAPP_META_APP_SECRET` supports signup OAuth. Confirm both belong to the intended Meta app; the code does not compare them. |
| Proxy trust | Preserve current `TRUSTED_PROXY_HOPS` unless trusted ingress topology is verified; increasing it can trust forged forwarding headers. |
| Disk/workers | Preserve the `/app/data` mount and single-instance topology until storage and Wasender retry coordination are redesigned. |
| Public URLs | Confirm `PUBLIC_BASE_URL`, `FRONTEND_URL`, CORS and gateway callback/return URLs against the selected host and current routes. |
| Secret handling | Use the provider's secret mechanism for approved keys; do not export `.env`, print values or overwrite unrelated keys. Do not rotate existing JWT/Flask secrets implicitly. |

Focused checks available in this repository (inspect mocks first):

```powershell
python -m pytest tests/test_cors_config.py tests/test_cors_allowlist.py tests/test_dev_billing_routes.py tests/test_reregister_telegram_webhooks.py -q
git diff --check
```

These are local tests, not production boot proof. A separate boot probe must block
external effects, disable workers and dotenv loading, and use isolated dummy config;
do not execute an ad hoc production import as part of read-only status.

## Webhooks

Confirm the target public HTTPS host and tenant/channel scope before live reads or mutations.

| Channel | Procedure |
|---|---|
| Telegram | Inspect `scripts/reregister_telegram_webhooks.py` and its CLI arguments. Default dry-run reads Supabase channels and calls Telegram `getMe`; it does not verify current webhook configuration. Treat it as live access, not an offline test. `--apply` changes Telegram and Supabase state and needs explicit scope/authorization. Route: `/telegram/webhook/<secret>`. Exit 0 is clean, 2 failed, 3 unverified; never print secret URLs. |
| Meta WhatsApp | Check the Meta App callback `/webhook`, verify token and messages subscription through an authorized supported surface. Do not infer provider subscription from local route existence. |
| Wasender | Inspect current channel reconnect support. Disconnect/reconnect can rotate secrets and interrupt delivery; obtain authorization and coordinate provider callback updates. A stored connected flag is not delivery proof. |
| Widget | Check generated embed origin and deployed customer snippets. Old snippets may still point at the old host; do not silently modify customer sites. |

## Verification

Read-only checks: deployment state and commit, HTTP availability, approved CORS
behavior and relevant worker startup logs. HTTP 200 alone is not full application
health. Report each observation with its target and scope.

Live delivery tests, rate-limit probes, uploads and redeploy persistence tests need
explicit authorization for the relevant action. Use a designated test tenant/channel
and state any delivery/storage checks not executed. Do not report a complete rollout
when required checks remain missing; local tests and provider deployment are separate.
