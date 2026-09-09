# Sentry error reporting and repair workflow

## Connect the application

1. Select the Python/Flask project
   [whastapp_chatbot_project](https://kaguyahouraisan.sentry.io/projects/).
   The requested name `Whastapp_Chatbot_Project` is normalized to
   `whastapp_chatbot_project`; the organization slug is `kaguyahouraisan`.
2. Install `requirements.txt` and set `SENTRY_DSN` in the application's private
   environment. An empty value leaves reporting disabled. Set
   `SENTRY_ENVIRONMENT` to `development`, `staging`, or `production` as appropriate.
3. Set `SENTRY_RELEASE` to the deployed commit SHA. On Render,
   `RENDER_GIT_COMMIT` is used when no explicit release is supplied. Restart the
   authorized target process after changing its environment.
4. Verify a synthetic exception in a development environment, confirm its event
   in Sentry, and check the release and environment. Do not add a public crash
   endpoint or provoke an error using live customer/payment data.

The app needs the DSN, **not** a Sentry API auth token. Keep `SENTRY_AUTH_TOKEN`
only in the developer's private environment for the Codex Sentry plugin, with
read-only `org:read`, `project:read`, and `event:read` access. Never put it in
frontend code, `.env.txt`, logs, screenshots, or chat.

## What is reported

After the Flask app initializes, the SDK captures unhandled request exceptions,
caught exceptions passed to the shared `server_error` helper, error-level Python
logs (including scheduled worker failures), and uncaught thread failures.
The helper's accompanying log is excluded to prevent duplicate reports.

Outgoing events retain error types, code filenames/functions/line numbers,
static route patterns, release, environment, and event metadata. An allowlist
removes exception/log messages, request details, customer IDs, user details,
extra contexts/tags, breadcrumbs, source snippets, and local variables. This
intentionally reduces diagnostic detail. Do not loosen the filter to investigate
an issue; reproduce it with synthetic data instead.

Tracing, profiling, session tracking, Sentry Logs, and automatic AI/database/HTTP
integrations are disabled. Browser JavaScript errors, warning-only or silently
swallowed errors, imports before initialization, and standalone job commands
that do not initialize the application are outside this integration's coverage.
The existing application logs are separate from Sentry's outgoing filter.

## Inspect, analyze, fix, verify

1. Use the installed **Sentry plugin** to read unresolved issues for the actual
   project, deployment environment, and relevant time window. If access fails or
   no project is visible, report that gap; do not interpret it as no errors.
2. Read the issue and representative event. Record its ID, release, first/last
   seen time, error type, and code location. Match the event to that release's
   source before diagnosing; current source may differ.
3. Reproduce with mocked providers and synthetic data. Trace shared callers,
   make the smallest fix, and retain a regression test. Run applicable project
   checks and the Codex Security workflow.
4. After an authorized deployment, re-run the affected behavior and compare new
   events for the fixed release/environment. State the observation window;
   absence of events alone is not proof of a fix. The plugin is read-only, so it
   does not mark issues resolved or deploy changes automatically.

This is an on-demand investigation workflow. It does not start recurring Codex
tasks or promise to detect/fix every bug automatically.

## Verification

`tests/test_observability.py` exercises the real SDK with an in-memory transport:
handled/unhandled Flask failures, background error logs, duplicate suppression,
missing DSN, and private-data removal across the serialized outgoing envelope.
The shared test configuration clears any inherited live DSN before app imports.

On 2026-09-09, the private local `.env` was configured and synthetic event
`352b65b646e142e8bf7e59f97b65443d` was confirmed through the Sentry event API:
`SentrySetupProbe: [redacted]`, environment `development`, release
`85fd720-sentry-integration-check`. This proves SDK delivery from the local
integration, not a deployed application restart or production coverage. No
customer data or production operation was used to trigger it.

References: [Sentry Flask integration](https://docs.sentry.io/platforms/python/integrations/flask/)
and [SDK options](https://docs.sentry.io/platforms/python/configuration/options/).
