# CHIP Pay MCP server

MCP server for the [CHIP](https://www.chip-in.asia/) payment gateway (Malaysia).
Wraps **CHIP Collect** (accept payments: FPX, cards, e-wallets, DuitNow QR) and,
optionally, **CHIP Send** (payouts to bank accounts).

Tool definitions are **generated from the vendored OpenAPI specs** in `spec/`, so
they cannot drift from the published contract. Adding an operation is a spec
refresh, not a code change.

## Quick start

```bash
pip install -r mcp/chip-pay/requirements.txt
cp mcp/chip-pay/.env.example mcp/chip-pay/.env   # then paste your secret key
python mcp/chip-pay/selfcheck.py                 # offline checks, no network
```

Register it with Claude Code (already done for this project at `local` scope):

```bash
claude mcp add chip-pay --scope local -- python "<abs path>/mcp/chip-pay/server.py"
```

Use `--scope user` instead to make it available in every project — at the cost of
loading its tools into every session.

## Tools

22 tools by default: 19 CHIP Collect operations plus 3 discovery tools. CHIP Send
tools appear only once Send credentials are set.

| Area | Tools |
|---|---|
| Purchases | `chip_purchases_create`, `_read`, `_cancel`, `_refund`, `_charge`, `_resend_invoice`, `_delete_recurring_token` |
| Clients | `chip_clients_create`, `_list`, `_read`, `_partial_update`, `chip_client_recurring_tokens_list` |
| Webhooks | `chip_webhooks_create`, `_list`, `_delete` |
| Account | `chip_balance`, `chip_turnover`, `chip_public_key`, `chip_payment_methods` |
| Discovery | `chip_list_operations`, `chip_describe_operation`, `chip_request` |

### Reaching the other operations

The two specs define **58 operations**; exposing all of them would bloat every
session's tool list. The rest stay reachable without it:

```
chip_list_operations { "search": "statement" }        -> find it
chip_describe_operation { "operation": "..." }        -> get its JSON Schema
chip_request { "operation": "...", "arguments": {} }  -> call it
```

Set `CHIP_TOOLS=all` in `.env` to expose all 58 as first-class tools instead.

## Safety

Money-moving operations — `refund`, `capture`, `charge`, `release`,
`mark_as_paid`, and both CHIP Send payout operations — are **refused by default**
and return an error naming the flag to flip. Set `CHIP_ALLOW_MONEY_MOVEMENT=true`
in `.env` and restart the server when you actually intend to move money. The guard
applies to `chip_request` too, so it cannot be routed around.

Read operations and non-financial writes (creating a purchase link, a client, a
webhook) are always allowed.

## Configuration

All settings live in `.env` (gitignored via `.gitignore:58`). See `.env.example`
for the annotated list. The essentials:

| Variable | Purpose |
|---|---|
| `CHIP_COLLECT_SECRET_KEY` | **Required.** Portal → Developers → API Keys. |
| `CHIP_BRAND_ID` | Optional. Auto-filled on calls needing a `brand_id`. |
| `CHIP_SEND_API_KEY` / `CHIP_SEND_API_SECRET` | Optional. Enables CHIP Send. |
| `CHIP_ALLOW_MONEY_MOVEMENT` | Default `false`. |
| `CHIP_TOOLS` | `curated` (default) or `all`. |

### The two APIs are not interchangeable

CHIP Collect and CHIP Send use **different base URLs and different credentials**.
Collect authenticates with `Authorization: Bearer <secret key>`. Send additionally
requires per-request `epoch` and `checksum` headers, where the checksum is
`HEX(HMAC_SHA512(key=API Secret, message=epoch + API Key))` and the API Secret is
never transmitted. A Collect key will not work for Send. `selfcheck.py` verifies
the signing implementation against CHIP's own published test vector.

Send requires the server clock to be within **30 seconds** of CHIP's, or requests
are rejected as `Unauthorized`.

## Notes

- Amounts are in the currency's **minor unit**: MYR 10.00 is `1000`.
- Errors are returned as `{"operation", "status", "response"}` with `is_error`
  set, so CHIP's own field-level validation messages reach you intact rather than
  being flattened into a generic failure.
- `selfcheck.py` is deliberately **not** named `test_*.py`: this repo sets no
  pytest `testpaths`, so a bare `pytest` run would otherwise collect it into the
  application suite.

## Refreshing the specs

```bash
curl -o mcp/chip-pay/spec/chip-collect.yaml https://docs.chip-in.asia/openapi/chip-collect.yaml
curl -o mcp/chip-pay/spec/chip-send.yaml    https://docs.chip-in.asia/openapi/chip-send.yaml
python mcp/chip-pay/selfcheck.py
```

The self-check asserts the operation counts (33 Collect, 25 Send) and that every
name in `CURATED` and `MONEY_MOVING` still resolves, so a spec change that drops
or renames an operation fails loudly instead of silently dropping a tool.
