#!/usr/bin/env python3
"""Offline self-check for the CHIP Pay MCP server.

Run:  python mcp/chip-pay/selfcheck.py

Makes no network calls and needs no credentials. Deliberately not named
test_*.py: this repo sets no pytest testpaths, so a bare `pytest` run would
otherwise collect it alongside the application suite.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Neutralise any real .env so the check is deterministic.
os.environ.setdefault("CHIP_COLLECT_SECRET_KEY", "selfcheck-not-a-real-key")
os.environ["CHIP_ALLOW_MONEY_MOVEMENT"] = "false"
os.environ["CHIP_TOOLS"] = "curated"

import mcp.types as types  # noqa: E402

import server  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}{(' -- ' + detail) if detail else ''}")
        FAILURES.append(label)


def main() -> int:
    print("CHIP Pay MCP server self-check\n")

    # --- 1. specs parse and index -------------------------------------------
    print("specs")
    collect = server.Spec(server.SPEC_DIR / "chip-collect.yaml", "chip_", server.COLLECT_BASE_DEFAULT)
    send = server.Spec(server.SPEC_DIR / "chip-send.yaml", "chip_send_", server.SEND_BASE_DEFAULT)
    check("collect spec indexes 33 operations", len(collect.ops) == 33, f"got {len(collect.ops)}")
    check("send spec indexes 25 operations", len(send.ops) == 25, f"got {len(send.ops)}")
    check(
        "collect base url is the documented gateway",
        collect.base_url == "https://gate.chip-in.asia/api/v1",
        collect.base_url,
    )

    all_ops = {**collect.ops, **send.ops}
    check(
        "no operation name collides across the two APIs",
        len(all_ops) == len(collect.ops) + len(send.ops),
        "prefixes chip_ / chip_send_ must keep them distinct",
    )

    # --- 2. curated + money lists reference real operations -----------------
    print("\nconfiguration lists (catches typos)")
    unknown_curated = sorted(server.CURATED - set(all_ops))
    check("every CURATED entry is a real operation", not unknown_curated, str(unknown_curated))
    unknown_money = sorted(server.MONEY_MOVING - set(all_ops))
    check("every MONEY_MOVING entry is a real operation", not unknown_money, str(unknown_money))

    # --- 3. schemas build for every operation -------------------------------
    print("\nschema generation")
    nested = []
    schema_problems: list[str] = []
    for name, op in all_ops.items():
        spec = send if name.startswith("chip_send_") else collect
        schema = spec.input_schema(op)
        if schema["type"] != "object":
            schema_problems.append(f"{name}: not an object schema")
        for placeholder in op["path_params"]:
            if placeholder not in schema["properties"]:
                schema_problems.append(f"{name}: path param {placeholder} missing")
        if op.get("body_mode") == "nested":
            nested.append(name)
    check("all 58 operations indexed", len(all_ops) == 58, f"got {len(all_ops)}")
    check("every operation yields a usable schema", not schema_problems, str(schema_problems[:3]))
    print(f"  INFO  body nested under 'body' for: {nested or 'none (all merged top-level)'}")

    purchase = collect.input_schema(collect.ops["chip_purchases_create"])
    check(
        "purchases_create exposes brand_id/client/purchase at top level",
        {"brand_id", "client", "purchase"} <= set(purchase["properties"]),
        str(sorted(purchase["properties"])[:6]),
    )
    check(
        "purchases_create marks brand_id/client/purchase required",
        {"brand_id", "client", "purchase"} <= set(purchase["required"]),
        str(purchase["required"]),
    )

    # --- 4. OpenAPI 'nullable' is normalised to JSON Schema -----------------
    print("\nJSON Schema normalisation")
    normalised = server.normalise({"type": "string", "nullable": True})
    check("nullable:true becomes a union type", normalised == {"type": ["string", "null"]}, str(normalised))
    check("nullable key is dropped", "nullable" not in normalised)

    # --- 5. CHIP Send HMAC matches the vendor's published vector ------------
    print("\nCHIP Send request signing")
    import hashlib
    import hmac

    caller = server.Caller(timeout=5)
    caller.send_key = "e0645c9e-fcf2-4f29-a327-202f7ed3d969"
    caller.send_secret = "a118729e-4243-4145-83b3-0b8cb213fe8e"

    expected = (
        "45bee62dba8087ab1e7e767d92f8d6e26f8bd19ee5fd2fef6386bb9425976498"
        "a86ffdbddb7a49919998e993c20626196ea652320f438a9528d2b8c9d19ec266"
    )
    actual = hmac.new(
        caller.send_secret.encode(),
        f"1689826456{caller.send_key}".encode(),
        hashlib.sha512,
    ).hexdigest()
    check("checksum matches CHIP's documented example vector", actual == expected, actual)

    headers = caller.headers(send)
    check("send headers carry epoch and checksum", {"epoch", "checksum"} <= set(headers))
    check("send authorises with the API key, never the secret", caller.send_secret not in str(headers))

    # --- 6. Send stays hidden without credentials ---------------------------
    print("\ncredential gating")
    bare = server.Caller(timeout=5)
    bare.send_key = ""
    bare.send_secret = ""
    check("send disabled when credentials absent", not bare.send_enabled)
    tools_no_send = server.build_tools([collect, send], "curated", send_enabled=False)
    check(
        "no CHIP Send tools exposed without credentials",
        not any(t.startswith("chip_send_") for t in tools_no_send),
    )

    # --- 7. money-movement guard --------------------------------------------
    print("\nmoney-movement guard")
    # Regression guard for the handshake timeout: parsing the specs during
    # build_server() pushed startup past the client's 10s limit, so the server
    # must construct no Spec until the loader is actually called.
    parsed: list[str] = []
    real_spec = server.Spec

    class CountingSpec(real_spec):  # type: ignore[misc,valid-type]
        def __init__(self, path, prefix, base_url):
            parsed.append(path.name)
            super().__init__(path, prefix, base_url)

    server.Spec = CountingSpec  # type: ignore[misc]
    try:
        srv, load = server.build_server()
        check("build_server parses no specs (keeps initialize fast)", parsed == [], str(parsed))
        _, tools = load()
        check("loader parses both specs on first use", len(parsed) == 2, str(parsed))
        load()
        check("loader is memoised, does not re-parse", len(parsed) == 2, str(parsed))
    finally:
        server.Spec = real_spec  # type: ignore[misc]

    check("server builds and registers tools", len(tools) > 0, f"{len(tools)} tools")
    check(
        "meta tools always present",
        {"chip_list_operations", "chip_describe_operation", "chip_request"} <= set(tools),
    )

    entry = srv.get_request_handler("tools/call")
    check("tools/call handler is registered", entry is not None)

    async def call(name: str, arguments: dict) -> types.CallToolResult:
        params = types.CallToolRequestParams(name=name, arguments=arguments)
        return await entry.handler(None, params)  # type: ignore[union-attr,arg-type]

    def body_of(result: types.CallToolResult) -> str:
        return getattr(result.content[0], "text", "")

    refund = asyncio.run(call("chip_purchases_refund", {"id": "00000000-0000-0000-0000-000000000000"}))
    check("refund refused while CHIP_ALLOW_MONEY_MOVEMENT=false", refund.is_error is True)
    check("refusal names the flag to flip", "CHIP_ALLOW_MONEY_MOVEMENT" in body_of(refund), body_of(refund)[:120])

    via_request = asyncio.run(
        call("chip_request", {"operation": "chip_purchases_refund", "arguments": {"id": "x"}})
    )
    check("guard also applies through chip_request", via_request.is_error is True)

    # --- 8. discovery tools work offline ------------------------------------
    print("\ndiscovery tools")
    listing = asyncio.run(call("chip_list_operations", {"search": "refund"}))
    check("chip_list_operations finds the refund operation", "chip_purchases_refund" in body_of(listing))
    described = asyncio.run(call("chip_describe_operation", {"operation": "chip_balance"}))
    check("chip_describe_operation returns a schema", '"input_schema"' in body_of(described))
    unknown = asyncio.run(call("chip_describe_operation", {"operation": "chip_nope"}))
    check("unknown operation is an error, not a crash", unknown.is_error is True)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
