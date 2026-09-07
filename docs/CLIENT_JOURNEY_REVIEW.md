# First-client bot journey review

Date: 2026-09-07. Scope: Bots, knowledge upload, instructions, testing, publishing,
workspace navigation and selected-bot navigation. User choices: full journey,
guided steps, one main action per page and explicit choice among channels.

## Delivery checklist

- [x] Inspect current source and capture the existing client-facing flow.
- [x] Interview the user and list replacements before redesign.
- [x] Implement guided setup, distinct sidebars and explicit channel publishing.
- [x] Verify focused mocked behavior and browser interactions; record delivery gaps.
- [ ] Obtain a completed security report and verify public deployment after hosting is resolved.

## Review evidence and replacements

The server on localhost:8000 returned exactly this checkout's bots.html (HTTP 200).
Current screenshots are in `output/client-journey-review/`. Existing user bots were
read only; the first-create/upload/deploy path was tested with synthetic data.

| Step | Observed issue | Replacement and acceptance |
| --- | --- | --- |
| Bots | Account menu sits near top; rows expose Edit/Archive without an Open button; technical summary dominates. | Workspace navigation with bottom account, obvious Open bot, plain My bots and a clear creation action. |
| New bot | Successful creation sends a beginner to the full analytics overview. | Send a new bot directly to guided knowledge setup with its bot ID preserved. |
| Upload | First successful upload sets action=upload, but the next-step link only handles setActive. Empty page exposes maps, Q&A and filters before a document exists. | Show upload progress and a continuation after confirmed primary knowledge; retain advanced tools behind explicit access. |
| Instructions and test | Apply-profile updates runtime settings then automatically redirects; applying settings can be confused with publishing. | Preserve profile activation, match and apply checks; explain saved bot settings and offer Test replies, then Choose a channel. |
| Publishing | Opening the page creates an enabled website record; website is visually favored; enabled flag is labelled Working even for an expired temporary hostname. | New website records start disabled. Show equal channel choices. Preserve existing connections and keys. Separate enabled/configured state from verified availability. |

Current browser evidence: publishing, Bots, dashboard, knowledge and upload dialog.
Screenshots establish layout and visible state, not full accessibility or backend
success. Existing test suites provide mocked infrastructure for mutation checks.

## Implementation contract

Use existing Aveon tokens, fonts and shared UI/auth components. Workspace navigation
and selected-bot navigation are deliberate variants. The guided sequence is Add
knowledge → Review instructions → Test replies → Publish. A current-step marker is
navigation context; it never fabricates completion. Bot ID and guided setup context
must survive each continuation.

HTTP remains in routes, business logic in services, storage in repositories. Preserve
tenant ownership checks, entitlements, API response shapes and existing deployed bot
settings. Do not automatically connect a channel, rotate a public key, alter a live
database schema or change production hosting configuration.

## Public delivery findings

The current UI shows a trycloudflare.com hostname labelled Working; a current DNS
probe cannot resolve that hostname. Persisted widget keys have no expiry. A stable
address therefore requires a permanent public HTTPS hostname and a running origin.
Cloudflare's connected account exposed no zones; the reported subscription/domain
ownership is unresolved. Production configuration awaits the user's hostname/account.

Read-only checks also found zero Pages projects, an unrelated Worker, R2 error
10042 (enable R2 in the dashboard), and a subscription-read authentication error.
The Fly account check for the existing wa-chatbot-my app reports an ended trial
requiring a credit card; current machine status could not be verified. Neither
account billing nor public configuration was changed.

The checked-in fly.toml already sets min_machines_running = 1 and disables automatic
stop/start. There is no evidence that changing those settings would resolve the
reported billing block, so the runtime configuration was preserved.

Cloudflare describes [Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
as testing infrastructure. A paid Cloudflare subscription alone cannot keep a
stopped application origin running. Keep the existing persistent widget keys;
restore the origin and point one stable HTTPS hostname at it.

The deployment operator should set PUBLIC_BASE_URL to that hostname, verify
the chosen providers' callbacks, bypass edge caching for authenticated and widget
runtime routes, and verify disconnect/reconnect from an unauthenticated browser.
No-store headers now cover widget runtime responses. R2 is optional; moving files
there does not make in-process retries safe on multiple server instances. Retain
the existing instance model until queue ownership and claims are reviewed.

The existing edge plan's mutable-asset cache recommendation was corrected:
unchanged filenames must revalidate until versioned asset URLs exist. CDN purge
does not evict fresh immutable browser caches. See [Cloudflare origin cache control](https://developers.cloudflare.com/cache/concepts/cache-control/).

## Verification

The Agents Orchestrator reviewed the journey before implementation and independently
reviewed publishing afterwards. The final review found two additional status defects:
failed initial reads appeared as zero connections, and malformed HTTPS hostnames
appeared permanent. Both were corrected and regression checked.

| Check | Current evidence |
| --- | --- |
| Widget routes, service, dashboard health and tenant suspension | 97 tests and 138 subtests passed after hostname validation fix |
| Knowledge upload/recovery/source roles/display and persona fields | 81 tests passed |
| Bot limit and dashboard source contracts | 41 tests passed |
| Publishing and account-menu source contracts | 35 tests passed; three old publishing layout assertions updated to the approved channel-first design |
| Instructions and reply-testing browser suites | Initial combined 45 passed; final instructions-only suite 18 passed after plain-language and optional-template changes |
| New navigation browser cases | Six cases passed across the initial run and create-navigation timeout rerun; desktop/footer bounds and mobile/member states included |
| Bots, dashboard and publishing regression run | All 34 cases passed in the combined run; three focused publishing cases passed after the unknown-state correction |
| Full synthetic journey | Three cases passed; final-source complete-journey rerun passed in 59.4 seconds with refreshed screenshots |

The broader combined browser run returned 53 passed and 10 failed. All ten failures
were in the existing tenant-account-menu suite. Independent review traced stale
selectors to the separately modified Support page and baseline assertions to the
unchanged account component behavior. An isolated current-versus-HEAD browser probe
reproduced icon absence, expanded mobile navigation bounds and hidden closed-mobile
account behavior on both versions. These unrelated issues remain unchanged; see
`output/client-journey-review/baseline-account-test-findings.md` for classification.

Manual browser interaction on the isolated loopback fixture created a bot, uploaded
a synthetic business-hours PDF, applied instructions, asked a question and explicitly
chose website publishing. The fixture marks every page as synthetic and blocks live
API/provider access. Mobile navigation and bottom account access were also checked
manually at 390 px. It does not establish actual extraction, AI response quality,
database persistence, provider delivery or public deployment.

Scoped JavaScript/Python syntax and diff checks passed. The whole-tree diff check has
a pre-existing blank line at EOF in app/services/email_service.py:522. Widget CSP is
verified at response-header/origin-rule level; cross-origin browser enforcement has
not been exercised against the real server.

### Security result: incomplete

The scoped Codex Security run `f6e379ad-1418-4e24-a4e7-76cce98f46bb` exited 1.
Its runtime reported 17/17 files reviewed and entered findings validation, then the
service rejected the scan prompt as potentially violating its usage policy. The
saved `scans show` record is failed, with reportAvailable = false and zero canonical
closed coverage rows. This is not a completed or passed security scan.

The external scan directory contains only scoped-source-input.jsonl; no sealed
manifest, completed report or finalized coverage was produced. No policy/configuration
bypass was attempted. A successful security run remains a release requirement.
The independent source review and regression tests above do not replace that gate.
Sanitized readback: [security-scan-status.json](../output/client-journey-review/security-scan-status.json).

## Review locally

Run `node tests/browser/client-journey-server.js` and open
[the synthetic demo](http://127.0.0.1:4187/bots.html). It starts with no bots and no
enabled website connection; restarting clears only its in-memory synthetic state.
Use `output/client-journey-review/Acme-hours.pdf` for manual upload. The regular
Flask server on localhost:8000 is separate and retains its existing state.
That Flask process was not restarted; the edited Python backend must be loaded by
a controlled restart or deployment before its new behavior can be used there.

| Screen | Synthetic browser evidence |
| --- | --- |
| My bots | [Workspace and bottom account](../output/client-journey-review/06-bots-after.png) |
| Add knowledge | [Ready document and continuation](../output/client-journey-review/mock-02-document-ready.png) |
| Instructions | [Applied instructions and next action](../output/client-journey-review/mock-03-instructions-applied.png) |
| Test replies | [Document question and reply](../output/client-journey-review/mock-04-test-reply.png) |
| Publish | [Equal channel choices](../output/client-journey-review/mock-05-channel-choice.png) and [same key after reconnect](../output/client-journey-review/mock-07-website-reconnected.png) |

The evidence directory is ignored by Git. Reproduce the full synthetic journey with
`node node_modules/@playwright/test/cli.js test tests/browser/client-journey.spec.js --timeout=90000 --reporter=line --output=output/client-journey-review/test-results`.
The fixture uses only installed Playwright and Node, with cached pinned browser
assets; no application dependency or production authentication behavior is added.
