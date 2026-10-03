#!/usr/bin/env python3
"""CHIP Pay MCP server.

Exposes the CHIP Collect API (accept payments) and, optionally, the CHIP Send
API (payouts) as MCP tools.

Tool definitions are generated from the vendored OpenAPI specs in ./spec, so
they cannot drift from the published contract. Credentials are read from the
environment or a sibling .env file -- never hardcoded.

Docs: https://docs.chip-in.asia/
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import anyio
import mcp.types as types
import yaml
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server

# httpx is NOT imported here on purpose. It costs ~0.8s to import, and the MCP
# client gives a stdio server only 10s to complete its handshake. Importing
# mcp.types alone already costs ~3s, so everything not needed to answer
# `initialize` is deferred until a tool is actually called. See load() below.

HERE = Path(__file__).resolve().parent
SPEC_DIR = HERE / "spec"

COLLECT_BASE_DEFAULT = "https://gate.chip-in.asia/api/v1"
SEND_BASE_DEFAULT = "https://api.chip-in.asia/api"
SEND_BASE_STAGING = "https://staging-api.chip-in.asia/api"

# Operations that move money or change what may be moved. Gated behind
# CHIP_ALLOW_MONEY_MOVEMENT so an agent cannot refund or pay out by accident.
MONEY_MOVING = {
    "chip_purchases_refund",
    "chip_purchases_capture",
    "chip_purchases_charge",
    "chip_purchases_release",
    "chip_purchases_mark_as_paid",
    "chip_send_send_instructions_create",
    "chip_send_send_limits_create",
}

# Default tool set: the operations a payments integration actually reaches for.
# Everything else stays reachable via chip_request. Override with CHIP_TOOLS=all.
CURATED = {
    "chip_purchases_create",
    "chip_purchases_read",
    "chip_purchases_cancel",
    "chip_purchases_refund",
    "chip_purchases_charge",
    "chip_purchases_delete_recurring_token",
    "chip_purchases_resend_invoice",
    "chip_payment_methods",
    "chip_clients_create",
    "chip_clients_list",
    "chip_clients_read",
    "chip_clients_partial_update",
    "chip_client_recurring_tokens_list",
    "chip_webhooks_create",
    "chip_webhooks_list",
    "chip_webhooks_delete",
    "chip_balance",
    "chip_turnover",
    "chip_public_key",
    "chip_send_accounts_index",
    "chip_send_bank_accounts_index",
    "chip_send_bank_accounts_create",
    "chip_send_send_instructions_create",
    "chip_send_send_instructions_index",
    "chip_send_send_instructions_get",
    "chip_send_send_limits_index",
}

MAX_DESCRIPTION_CHARS = 700


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without shadowing real env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- #
# OpenAPI -> JSON Schema
# --------------------------------------------------------------------------- #
def normalise(node: Any) -> Any:
    """Convert OpenAPI-isms that are not valid JSON Schema draft 2020-12.

    Three fixes, all of which the CHIP specs need:
      * `nullable: true` (OpenAPI 3.0 style) becomes a `["x", "null"]` union.
      * `allOf` composition is flattened, so base-model fields mixed in via
        `allOf: [{$ref: BaseModelBody}]` land alongside the schema's own.
      * an object that lists `properties` but omits `type` gets `type: object`,
        which is what lets the caller merge its fields into the tool schema.
    """
    if isinstance(node, list):
        return [normalise(v) for v in node]
    if not isinstance(node, dict):
        return node

    out = {k: normalise(v) for k, v in node.items() if k != "nullable"}

    # Flatten allOf, but only when every branch is a plain object fragment --
    # a branch carrying oneOf/anyOf/not cannot be merged without changing meaning.
    branches = out.get("allOf")
    if isinstance(branches, list) and branches:
        mergeable = all(
            isinstance(b, dict) and not ({"oneOf", "anyOf", "not"} & set(b)) for b in branches
        )
        if mergeable:
            base_props: dict[str, Any] = {}
            base_required: list[str] = []
            for branch in branches:
                base_props.update(branch.get("properties") or {})
                base_required.extend(branch.get("required") or [])
                for key, value in branch.items():
                    if key not in {"properties", "required", "allOf"}:
                        out.setdefault(key, value)
            out.pop("allOf", None)
            # The schema's own declarations win over the mixed-in base.
            combined = {**base_props, **(out.get("properties") or {})}
            if combined:
                out["properties"] = combined
            required = sorted({*base_required, *(out.get("required") or [])})
            if required:
                out["required"] = required

    if "type" not in out and isinstance(out.get("properties"), dict):
        out["type"] = "object"

    if node.get("nullable") is True:
        declared = out.get("type")
        if isinstance(declared, str):
            out["type"] = [declared, "null"]
        elif isinstance(declared, list) and "null" not in declared:
            out["type"] = [*declared, "null"]
    return out


class Spec:
    """One OpenAPI document, indexed by operationId."""

    def __init__(self, path: Path, prefix: str, base_url: str) -> None:
        self.doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.prefix = prefix
        self.base_url = base_url.rstrip("/")
        self.components = self.doc.get("components", {})
        self.ops: dict[str, dict[str, Any]] = {}
        self._index()

    # -- $ref handling ----------------------------------------------------- #
    def deref(self, node: Any) -> Any:
        """Follow a single local $ref one level."""
        if isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if ref.startswith("#/components/"):
                rest = ref.split("#/components/", 1)[1]
                section, _, name = rest.partition("/")
                return self.components.get(section, {}).get(name, {})
        return node

    def inline(self, node: Any, stack: tuple[str, ...] = ()) -> Any:
        """Recursively inline local $refs, breaking cycles."""
        if isinstance(node, list):
            return [self.inline(v, stack) for v in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[-1]
            if name in stack:
                return {"type": "object", "description": f"Recursive reference to {name}."}
            target = self.components.get("schemas", {}).get(name, {})
            return self.inline(target, (*stack, name))
        return {k: self.inline(v, stack) for k, v in node.items()}

    # -- indexing ---------------------------------------------------------- #
    def _index(self) -> None:
        for path, item in (self.doc.get("paths") or {}).items():
            shared = item.get("parameters", [])
            for method, op in item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                op_id = op.get("operationId")
                if not op_id:
                    continue
                tool = f"{self.prefix}{op_id}"
                params = [self.deref(p) for p in [*shared, *op.get("parameters", [])]]
                body = None
                request_body = op.get("requestBody")
                if request_body:
                    content = self.deref(request_body).get("content", {})
                    media = content.get("application/json") or next(iter(content.values()), {})
                    body = media.get("schema")
                self.ops[tool] = {
                    "tool": tool,
                    "operation_id": op_id,
                    "method": method.upper(),
                    "path": path,
                    "summary": op.get("summary") or op_id,
                    "description": op.get("description") or "",
                    "params": params,
                    "body": body,
                    "path_params": re.findall(r"\{([^}]+)\}", path),
                }

    # -- schema building --------------------------------------------------- #
    def input_schema(self, op: dict[str, Any]) -> dict[str, Any]:
        props: dict[str, Any] = {}
        required: list[str] = []

        by_norm = {
            str(p.get("name", "")).strip().lower().replace(" ", "_"): p
            for p in op["params"]
            if p.get("in") == "path"
        }
        for placeholder in op["path_params"]:
            spec_param = by_norm.get(placeholder.lower(), {})
            schema = normalise(self.inline(spec_param.get("schema") or {"type": "string"}))
            schema["description"] = spec_param.get("description") or f"Path parameter `{placeholder}`."
            props[placeholder] = schema
            required.append(placeholder)

        for param in op["params"]:
            if param.get("in") != "query":
                continue
            name = param.get("name")
            if not name or name in props:
                continue
            schema = normalise(self.inline(param.get("schema") or {"type": "string"}))
            if param.get("description"):
                schema["description"] = param["description"]
            props[name] = schema
            if param.get("required"):
                required.append(name)

        body_mode = "none"
        body_props: dict[str, Any] | None = None
        if op["body"]:
            body = normalise(self.inline(op["body"]))
            body_props = body.get("properties") if body.get("type") == "object" else None
            if body_props and not (set(body_props) & set(props)):
                body_mode = "merged"
                props.update(body_props)
                required.extend(body.get("required", []))
            else:
                body_mode = "nested"
                body["description"] = (body.get("description") or "").strip() + " Request body."
                props["body"] = body
                required.append("body")

        op["body_mode"] = body_mode
        # Record the RESOLVED body field names. op["body"] is often a bare
        # {"$ref": ...} with no "properties", so anything inspecting it directly
        # (such as the brand_id fallback) silently sees an empty body.
        op["body_prop_names"] = set(body_props or ())
        return {"type": "object", "properties": props, "required": sorted(set(required))}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class ChipError(RuntimeError):
    pass


class Caller:
    """Executes one operation against the right CHIP API with the right auth."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.collect_key = os.environ.get("CHIP_COLLECT_SECRET_KEY", "").strip()
        self.brand_id = os.environ.get("CHIP_BRAND_ID", "").strip()
        self.send_key = os.environ.get("CHIP_SEND_API_KEY", "").strip()
        self.send_secret = os.environ.get("CHIP_SEND_API_SECRET", "").strip()

    @property
    def send_enabled(self) -> bool:
        return bool(self.send_key and self.send_secret)

    def headers(self, spec: Spec) -> dict[str, str]:
        if spec.prefix == "chip_send_":
            if not self.send_enabled:
                raise ChipError(
                    "CHIP Send is not configured. Set CHIP_SEND_API_KEY and "
                    "CHIP_SEND_API_SECRET (separate credentials from the Collect key)."
                )
            epoch = str(int(time.time()))
            checksum = hmac.new(
                self.send_secret.encode(),
                f"{epoch}{self.send_key}".encode(),
                hashlib.sha512,
            ).hexdigest()
            return {
                "Authorization": f"Bearer {self.send_key}",
                "epoch": epoch,
                "checksum": checksum,
                "Content-Type": "application/json",
            }
        if not self.collect_key:
            raise ChipError("CHIP_COLLECT_SECRET_KEY is not set. See .env.example.")
        return {
            "Authorization": f"Bearer {self.collect_key}",
            "Content-Type": "application/json",
        }

    async def call(self, spec: Spec, op: dict[str, Any], args: dict[str, Any]) -> tuple[int, Any]:
        args = dict(args or {})
        path = op["path"]
        for placeholder in op["path_params"]:
            if placeholder not in args:
                raise ChipError(f"Missing required path parameter '{placeholder}'.")
            value = quote(str(args.pop(placeholder)), safe="")
            path = path.replace("{" + placeholder + "}", value)

        query_names = {p.get("name") for p in op["params"] if p.get("in") == "query"}
        query: dict[str, Any] = {}
        for name in list(args):
            if name in query_names:
                query[name] = args.pop(name)

        body: Any = None
        if op.get("body_mode") == "nested":
            body = args.pop("body", None)
        elif op.get("body_mode") == "merged":
            body = args or None

        # Convenience: fall back to the configured brand for calls that need one.
        if self.brand_id:
            if "brand_id" in query_names and "brand_id" not in query:
                query["brand_id"] = self.brand_id
            if (
                isinstance(body, dict)
                and "brand_id" in op.get("body_prop_names", ())
                and "brand_id" not in body
            ):
                body["brand_id"] = self.brand_id

        import httpx  # deferred: see the note beside the imports

        url = f"{spec.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                op["method"],
                url,
                headers=self.headers(spec),
                params=query or None,
                json=body if body else None,
            )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = response.text
        return response.status_code, payload


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #
def build_tools(specs: list[Spec], mode: str, send_enabled: bool) -> dict[str, types.Tool]:
    tools: dict[str, types.Tool] = {}
    for spec in specs:
        if spec.prefix == "chip_send_" and not send_enabled:
            continue
        for tool_name, op in spec.ops.items():
            if mode != "all" and tool_name not in CURATED:
                continue
            schema = spec.input_schema(op)
            description = op["summary"]
            if op["description"]:
                description = f"{description}. {' '.join(op['description'].split())}"
            if len(description) > MAX_DESCRIPTION_CHARS:
                description = description[:MAX_DESCRIPTION_CHARS].rstrip() + "..."
            api = "CHIP Send" if spec.prefix == "chip_send_" else "CHIP Collect"
            description = f"[{api}] {description}"
            if tool_name in MONEY_MOVING:
                description += " MOVES MONEY - requires CHIP_ALLOW_MONEY_MOVEMENT=true."
            tools[tool_name] = types.Tool(
                name=tool_name,
                title=op["summary"],
                description=description,
                input_schema=schema,
                annotations=types.ToolAnnotations(
                    read_only_hint=op["method"] == "GET",
                    destructive_hint=op["method"] == "DELETE" or tool_name in MONEY_MOVING,
                    idempotent_hint=op["method"] in {"GET", "PUT", "DELETE"},
                    open_world_hint=True,
                ),
            )
    return tools


META_TOOLS = [
    types.Tool(
        name="chip_list_operations",
        title="List CHIP API operations",
        description=(
            "[CHIP] Catalogue every CHIP Collect and CHIP Send operation, including ones not "
            "exposed as their own tool. Use this to discover what is available, then "
            "chip_describe_operation for the schema and chip_request to execute it."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Case-insensitive filter on operation name, path or summary.",
                },
                "api": {
                    "type": "string",
                    "enum": ["collect", "send", "all"],
                    "description": "Which API to list. Defaults to all.",
                },
            },
            "required": [],
        },
        annotations=types.ToolAnnotations(
            read_only_hint=True, idempotent_hint=True, open_world_hint=False
        ),
    ),
    types.Tool(
        name="chip_describe_operation",
        title="Describe a CHIP operation",
        description=(
            "[CHIP] Return the full JSON Schema, HTTP method, URL and documentation for one "
            "CHIP operation, named as it appears in chip_list_operations."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "Operation name, e.g. chip_purchases_create.",
                }
            },
            "required": ["operation"],
        },
        annotations=types.ToolAnnotations(
            read_only_hint=True, idempotent_hint=True, open_world_hint=False
        ),
    ),
    types.Tool(
        name="chip_request",
        title="Call any CHIP operation",
        description=(
            "[CHIP] Execute any CHIP Collect or CHIP Send operation by name, including those "
            "without a dedicated tool. Call chip_describe_operation first to get the argument "
            "schema. Money-moving operations still require CHIP_ALLOW_MONEY_MOVEMENT=true."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "Operation name, e.g. chip_company_statements_list.",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments matching that operation's input schema.",
                },
            },
            "required": ["operation"],
        },
        annotations=types.ToolAnnotations(open_world_hint=True),
    ),
]


def text_result(payload: Any, is_error: bool = False, limit: int = 20000) -> types.CallToolResult:
    body = payload if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False)
    if len(body) > limit:
        body = body[:limit] + f"\n... [truncated, {len(body)} chars total]"
    return types.CallToolResult(content=[types.TextContent(type="text", text=body)], is_error=is_error)


Loader = Callable[[], tuple[dict[str, tuple["Spec", dict[str, Any]]], dict[str, types.Tool]]]


def build_server() -> tuple[Server, Loader]:
    """Wire credentials and handlers into a Server.

    Returns the server and a memoised loader. Calling the loader parses the
    specs and returns `(by_tool, tools)`; until then no spec work has happened,
    which is what keeps `initialize` inside the client's handshake budget.
    """
    load_dotenv(HERE / ".env")

    timeout = float(os.environ.get("CHIP_TIMEOUT_SECONDS", "30"))
    limit = int(os.environ.get("CHIP_MAX_RESPONSE_CHARS", "20000"))
    mode = os.environ.get("CHIP_TOOLS", "curated").strip().lower()
    allow_money = env_flag("CHIP_ALLOW_MONEY_MOVEMENT", False)

    send_base = os.environ.get("CHIP_SEND_BASE_URL", "").strip() or (
        SEND_BASE_STAGING if env_flag("CHIP_SEND_STAGING") else SEND_BASE_DEFAULT
    )
    collect_base = os.environ.get("CHIP_COLLECT_BASE_URL", "").strip() or COLLECT_BASE_DEFAULT
    caller = Caller(timeout)

    # Parsing 273KB of YAML and building 58 schemas costs ~0.7s. That is not
    # much on its own, but it sits on the 10s handshake budget alongside a ~3s
    # `import mcp`, and at session start dozens of MCP servers contend for the
    # CPU. So `initialize` does none of it -- the first tools/list or tools/call
    # pays for it instead, on a request with no such deadline.
    state: dict[str, Any] = {}

    def load() -> tuple[dict[str, tuple[Spec, dict[str, Any]]], dict[str, types.Tool]]:
        if not state:
            specs = [
                Spec(SPEC_DIR / "chip-collect.yaml", "chip_", collect_base),
                Spec(SPEC_DIR / "chip-send.yaml", "chip_send_", send_base),
            ]
            tools = build_tools(specs, mode, caller.send_enabled)
            for meta in META_TOOLS:
                tools[meta.name] = meta
            state["by_tool"] = {
                name: (spec, op) for spec in specs for name, op in spec.ops.items()
            }
            state["tools"] = tools
        return state["by_tool"], state["tools"]

    async def on_list_tools(_ctx: Any, _params: Any) -> types.ListToolsResult:
        _, tools = load()
        return types.ListToolsResult(tools=list(tools.values()))

    async def on_call_tool(
        _ctx: Any, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        name = params.name
        args = dict(params.arguments or {})
        try:
            by_tool, tools = load()
            if name == "chip_list_operations":
                search = (args.get("search") or "").lower()
                which = (args.get("api") or "all").lower()
                rows = []
                for tool_name, (spec, op) in sorted(by_tool.items()):
                    is_send = spec.prefix == "chip_send_"
                    if (which == "collect" and is_send) or (which == "send" and not is_send):
                        continue
                    haystack = f"{tool_name} {op['path']} {op['summary']}".lower()
                    if search and search not in haystack:
                        continue
                    rows.append(
                        {
                            "operation": tool_name,
                            "method": op["method"],
                            "path": op["path"],
                            "summary": op["summary"],
                            "exposed_as_tool": tool_name in tools,
                            "moves_money": tool_name in MONEY_MOVING,
                        }
                    )
                return text_result({"count": len(rows), "operations": rows}, limit=limit)

            if name == "chip_describe_operation":
                target = args.get("operation", "")
                if target not in by_tool:
                    return text_result(
                        f"Unknown operation '{target}'. Use chip_list_operations.", True, limit
                    )
                spec, op = by_tool[target]
                return text_result(
                    {
                        "operation": target,
                        "method": op["method"],
                        "url": f"{spec.base_url}{op['path']}",
                        "summary": op["summary"],
                        "description": op["description"],
                        "moves_money": target in MONEY_MOVING,
                        "input_schema": spec.input_schema(op),
                    },
                    limit=limit,
                )

            if name == "chip_request":
                target = args.get("operation", "")
                if target not in by_tool:
                    return text_result(
                        f"Unknown operation '{target}'. Use chip_list_operations.", True, limit
                    )
                name = target
                args = dict(args.get("arguments") or {})

            if name not in by_tool:
                return text_result(f"Unknown tool '{name}'.", True, limit)

            if name in MONEY_MOVING and not allow_money:
                return text_result(
                    f"Refused: '{name}' moves money and CHIP_ALLOW_MONEY_MOVEMENT is not "
                    "enabled. Set CHIP_ALLOW_MONEY_MOVEMENT=true in mcp/chip-pay/.env and "
                    "restart the server to permit it.",
                    True,
                    limit,
                )

            spec, op = by_tool[name]
            if "body_mode" not in op:
                spec.input_schema(op)
            status, payload = await caller.call(spec, op, args)
            return text_result(
                {"operation": name, "status": status, "response": payload},
                is_error=status >= 400,
                limit=limit,
            )

        except ChipError as exc:
            return text_result(f"CHIP configuration error: {exc}", True, limit)
        except Exception as exc:  # surface it, never swallow it
            # httpx is imported lazily, so it is matched by module rather than
            # by class -- naming it here would drag the import back to startup.
            if type(exc).__module__.split(".")[0] == "httpx":
                return text_result(f"HTTP error calling CHIP: {exc!r}", True, limit)
            return text_result(f"Unexpected error in {name}: {exc!r}", True, limit)

    server = Server(
        "chip-pay",
        version="1.0.0",
        title="CHIP Pay",
        instructions=(
            "Tools for the CHIP payment gateway (chip-in.asia): CHIP Collect for accepting "
            "payments and CHIP Send for payouts. Start with chip_list_operations to see the "
            "full surface. Amounts are in the currency's minor unit (MYR 10.00 = 1000)."
        ),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    return server, load


def main() -> None:
    server, _ = build_server()

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(run)


if __name__ == "__main__":
    main()
