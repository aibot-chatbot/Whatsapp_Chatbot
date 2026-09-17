"""Advisory Langflow decision layer for automation side effects.

Langflow is consulted for a judgement but never owns the side effect and never
becomes a hard dependency of a user-facing action. When it is disabled,
unreachable, slow, or returns output that fails its own published contract, the
caller proceeds with Flask's own validation and the reason is recorded on the
automation event.

The contract JSON under ``langflow/`` is the single source of truth for the
response shape. This module validates against the file's own ``output_schema``
rather than keeping a second copy of the rules that could silently drift.
"""

import json
import logging
import os
import re
import uuid
from pathlib import Path

from app.services.langflow_adapter import run_langflow_automation


logger = logging.getLogger(__name__)

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "langflow"

CRM_CONTRACT = "crm-stage-automation"
KNOWLEDGE_CONTRACT = "knowledge-document-follow-up"

_CONTRACT_CACHE = {}


def _contract(name):
    """Load and cache one contract file."""
    if name not in _CONTRACT_CACHE:
        path = CONTRACT_DIR / f"{name}.json"
        with open(path, "r", encoding="utf-8") as handle:
            _CONTRACT_CACHE[name] = json.load(handle)
    return _CONTRACT_CACHE[name]


class ContractViolation(ValueError):
    """The flow answered, but not in the shape its contract promises."""


def validate_against_schema(value, schema, path="output"):
    """Validate the subset of JSON Schema these contracts actually use.

    Deliberately not a general implementation and deliberately not a new
    dependency: the two contracts use only type, required, properties,
    additionalProperties:false, enum, const, maxLength and minimum.
    """
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise ContractViolation(f"{path} must be an object")
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ContractViolation(f"{path}.{key} is required")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    raise ContractViolation(f"{path}.{key} is not permitted")
        for key, sub in properties.items():
            if key in value:
                validate_against_schema(value[key], sub, f"{path}.{key}")
        return value

    if expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ContractViolation(f"{path} must be an integer")
    elif expected == "string":
        if not isinstance(value, str):
            raise ContractViolation(f"{path} must be a string")
    elif expected == "boolean":
        if not isinstance(value, bool):
            raise ContractViolation(f"{path} must be a boolean")

    if "const" in schema and value != schema["const"]:
        raise ContractViolation(f"{path} must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractViolation(f"{path} must be one of {schema['enum']}")
    if "maxLength" in schema and isinstance(value, str) and len(value) > schema["maxLength"]:
        raise ContractViolation(f"{path} exceeds maxLength {schema['maxLength']}")
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        raise ContractViolation(f"{path} is below minimum {schema['minimum']}")
    return value


def extract_flow_output(response):
    """Pull the contract object out of whatever Langflow wrapped it in.

    A flow ending in a Text Output returns its JSON as a string buried in a run
    envelope, but a webhook-style flow can answer with the object directly.
    Both are accepted; anything else is a contract violation, not a guess.
    """
    if not isinstance(response, dict):
        raise ContractViolation("Langflow response was not an object")
    if "decision" in response:
        return response

    found = _search_for_decision(response, depth=0)
    if found is None:
        raise ContractViolation("Langflow response contained no decision object")
    return found


def _search_for_decision(node, depth):
    if depth > 8:
        return None
    if isinstance(node, dict):
        if isinstance(node.get("decision"), str):
            return node
        for value in node.values():
            found = _search_for_decision(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _search_for_decision(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, str):
        text = node.strip()
        if text.startswith("{") and '"decision"' in text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, dict) and "decision" in parsed:
                return parsed
    return None


def _flow_id(env_name):
    raw = os.getenv(env_name, "").strip()
    if raw and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", raw):
        return raw
    return ""


def _skip(reason, correlation_id):
    return {
        "consulted": False,
        "blocked": False,
        "reason": "",
        "detail": reason,
        "correlation_id": correlation_id,
    }


def crm_stage_decision(
    *, company_id, chatbot_id, lead_id, current_status, target_status,
    reason="", correlation_id=None
):
    """Ask the CRM flow whether a stage transition should proceed.

    Returns a dict with ``consulted``, ``blocked``, ``reason``, ``detail`` and
    ``correlation_id``. ``blocked`` is only ever True when Langflow answered
    with a valid, contract-conforming refusal for this exact transition; every
    failure mode leaves ``blocked`` False so the caller carries on.
    """
    correlation_id = str(correlation_id or uuid.uuid4())

    flow_id = _flow_id("LANGFLOW_CRM_FLOW_ID")
    if not flow_id:
        return _skip("LANGFLOW_CRM_FLOW_ID is not configured", correlation_id)

    payload = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "lead_id": lead_id,
        "current_status": current_status,
        "target_status": target_status,
        "correlation_id": correlation_id,
    }
    if reason:
        payload["reason"] = str(reason)[:500]

    # Langflow's /api/v1/run takes the flow input as `input_value`, routed by
    # `input_type` to the matching input node. The flow starts with a ChatInput,
    # so the payload travels as a compact JSON string under the chat type;
    # posting the bare payload reaches the flow but binds nothing to it.
    envelope = {
        "input_value": json.dumps(payload, separators=(",", ":")),
        "input_type": "chat",
        "output_type": "chat",
    }

    try:
        response = run_langflow_automation(flow_id, envelope)
        output = extract_flow_output(response)
        validate_against_schema(output, _contract(CRM_CONTRACT)["output_schema"])
    except Exception as exc:
        # Fail open. The transition is still governed by Flask's own allowlist;
        # Langflow only ever adds a second opinion.
        logger.warning(
            "Langflow CRM decision unavailable (correlation_id=%s): %s",
            correlation_id, type(exc).__name__,
        )
        return _skip(f"{type(exc).__name__}: {exc}"[:300], correlation_id)

    # Only advice for this tenant and this exact request may influence it.
    if any(output.get(key) != payload[key] for key in (
        "company_id", "chatbot_id", "lead_id", "target_status", "correlation_id"
    )):
        return _skip("Langflow answered about a different transition", correlation_id)

    blocked = output.get("decision") == "block_crm_stage"
    return {
        "consulted": True,
        "blocked": blocked,
        "reason": str(output.get("reason") or "")[:500],
        "detail": "",
        "correlation_id": output.get("correlation_id") or correlation_id,
    }


def _local_knowledge_summary(display_name, chunk_count, target_role):
    """Build the reviewer-facing summary without a decision service.

    This is deliberately deterministic rather than a model call. The knowledge
    payload carries only a filename, a chunk count and a role - it does not
    carry a single word of the document text - so a model asked to "summarise"
    from it could only invent content it has never seen. A reviewer is better
    served by the three facts we actually know, stated plainly.
    """
    name = str(display_name or "").strip()[:200] or "The knowledge document"
    role = "primary" if target_role == "primary" else "supporting"
    count = chunk_count if isinstance(chunk_count, int) and not isinstance(chunk_count, bool) else 0
    chunks = "1 chunk" if count == 1 else f"{count} chunks"
    return (
        f"{name} finished indexing as the {role} source with {chunks}. "
        "Check the extracted text before the bot answers from it."
    )[:500]


def knowledge_document_decision(
    *, company_id, chatbot_id, file_id, display_name, chunk_count,
    target_role, correlation_id=None
):
    """Ask the knowledge flow to summarise a completed document for review.

    The contract fixes ``decision`` to ``review_document`` and
    ``requires_approval`` to ``true``, so this call cannot change *whether* a
    review happens - it only enriches the queued event with a reviewer-facing
    summary. It therefore has no blocking path at all, and any failure simply
    leaves the event without a summary.
    """
    correlation_id = str(correlation_id or uuid.uuid4())

    flow_id = _flow_id("LANGFLOW_KNOWLEDGE_FLOW_ID")
    if not flow_id:
        # No decision service configured, and none is needed. The contract fixes
        # decision to "review_document" and requires_approval to true, so the
        # only thing an external call ever added here was the summary string -
        # and that is derivable from the payload we already hold. Produce it
        # locally instead of recording the review with no summary at all.
        return {
            "consulted": True,
            "blocked": False,
            "reason": "",
            "detail": "",
            "summary": _local_knowledge_summary(display_name, chunk_count, target_role),
            "requires_approval": True,
            "correlation_id": correlation_id,
            "source": "local",
        }

    payload = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "file_id": file_id,
        "display_name": str(display_name or "")[:200],
        "chunk_count": chunk_count,
        "target_role": target_role,
        "correlation_id": correlation_id,
    }
    envelope = {
        "input_value": json.dumps(payload, separators=(",", ":")),
        "input_type": "chat",
        "output_type": "chat",
    }

    try:
        response = run_langflow_automation(flow_id, envelope)
        output = extract_flow_output(response)
        validate_against_schema(output, _contract(KNOWLEDGE_CONTRACT)["output_schema"])
    except Exception as exc:
        logger.warning(
            "Langflow knowledge summary unavailable (correlation_id=%s): %s",
            correlation_id, type(exc).__name__,
        )
        return _skip(f"{type(exc).__name__}: {exc}"[:300], correlation_id)

    if output.get("correlation_id") != correlation_id:
        return _skip("Langflow answered about a different document request", correlation_id)

    return {
        "consulted": True,
        "blocked": False,
        "reason": "",
        "detail": "",
        "summary": str(output.get("summary") or "")[:500],
        "requires_approval": output.get("requires_approval") is True,
        "correlation_id": output.get("correlation_id") or correlation_id,
        "source": "langflow",
    }
