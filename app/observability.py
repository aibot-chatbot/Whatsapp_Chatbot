"""Opt-in server error reporting with an allowlist for outgoing event data."""

import logging
import os
from pathlib import Path
from threading import Lock
from time import monotonic

from flask import has_request_context, request
import sentry_sdk
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.threading import ThreadingIntegration

_ROOT = Path(__file__).resolve().parent.parent
_WEBHOOK_REPORT_LOCK = Lock()
_NEXT_WEBHOOK_REPORT_AT = 0.0
_PAYMENT_TAG_VALUES = {
    "payment.gateway": {"chip"},
    "payment.operation": {"checkout", "webhook", "reconciliation", "fulfillment", "status", "unknown"},
    "payment.reason": {
        "configuration", "provider_unavailable", "provider_rejected", "invalid_response",
        "invalid_signature", "mismatch", "brand_mismatch", "persistence", "fulfillment",
        "status_review", "unexpected",
    },
    "payment.mode": {"test", "live", "unknown"},
}


def capture_payment_failure(operation, *, reason="unexpected", mode="unknown", exc=None):
    """Report a handled CHIP failure with static labels and no payment/customer data."""
    global _NEXT_WEBHOOK_REPORT_AT
    tags = {
        "payment.gateway": "chip",
        "payment.operation": operation,
        "payment.reason": reason,
        "payment.mode": mode,
    }
    try:
        if operation == "webhook":
            # ponytail: one report/minute per worker; share the budget if workers grow.
            # Anonymous callback traffic must not exhaust the monitoring quota.
            with _WEBHOOK_REPORT_LOCK:
                now = monotonic()
                if now < _NEXT_WEBHOOK_REPORT_AT:
                    return None
                _NEXT_WEBHOOK_REPORT_AT = now + 60
        with sentry_sdk.new_scope() as scope:
            for key, value in tags.items():
                fallback = "unexpected" if key == "payment.reason" else "unknown"
                scope.set_tag(key, value if isinstance(value, str) and value in _PAYMENT_TAG_VALUES[key] else fallback)
            if exc is not None:
                return sentry_sdk.capture_exception(exc)
            return sentry_sdk.capture_message("CHIP payment failure", level="error")
    except Exception:
        # Monitoring must never interrupt fulfillment or change a callback response.
        return None


def _safe_stack(stack):
    frames = []
    for frame in stack.get("frames", []):
        safe = {key: frame[key] for key in ("function", "module", "lineno", "in_app") if key in frame}
        filename = frame.get("filename", "")
        # Never send machine/user directories, source text, or frame variables.
        try:
            filename = Path(frame.get("abs_path") or filename).resolve().relative_to(_ROOT).as_posix()
        except (ValueError, OSError):
            filename = Path(filename).name
        safe["filename"] = filename
        frames.append(safe)
    return {"frames": frames}


def scrub_event(event, hint):
    """Keep code locations and error types; never transmit customer payloads."""
    record = hint.get("log_record")
    if record and getattr(record, "sentry_skip", False):
        return None
    safe = {key: event[key] for key in (
        "event_id", "timestamp", "platform", "level", "release", "environment",
    ) if key in event}
    tags = event.get("tags", {})
    payment_tags = {
        key: value for key, value in tags.items()
        if key in _PAYMENT_TAG_VALUES and isinstance(value, str) and value in _PAYMENT_TAG_VALUES[key]
    }
    if payment_tags.get("payment.gateway") == "chip":
        safe["tags"] = payment_tags
    values = []
    for exc in event.get("exception", {}).get("values", []):
        item = {"type": exc.get("type", "Error"), "value": "[redacted]"}
        if "stacktrace" in exc:
            item["stacktrace"] = _safe_stack(exc["stacktrace"])
        mechanism = exc.get("mechanism", {})
        item["mechanism"] = {key: mechanism[key] for key in ("type", "handled") if key in mechanism}
        values.append(item)
    if values:
        safe["exception"] = {"values": values}
    else:
        safe["message"] = "Server error (message redacted)"
    if "threads" in event:
        safe["threads"] = {"values": [
            {"stacktrace": _safe_stack(thread["stacktrace"]), "crashed": thread.get("crashed", False)}
            for thread in event["threads"].get("values", []) if "stacktrace" in thread
        ]}
    if "stacktrace" in event:
        safe["stacktrace"] = _safe_stack(event["stacktrace"])
    if has_request_context() and request.url_rule:
        safe["transaction"] = request.url_rule.rule
    return safe


def init_sentry():
    """Initialize once per application startup, only when a DSN is configured."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
        release=os.getenv("SENTRY_RELEASE") or os.getenv("RENDER_GIT_COMMIT") or None,
        default_integrations=False,
        auto_enabling_integrations=False,
        integrations=[
            FlaskIntegration(),
            LoggingIntegration(level=None, event_level=logging.ERROR),
            ThreadingIntegration(),
            DedupeIntegration(),
        ],
        send_default_pii=False,
        include_local_variables=False,
        include_source_context=False,
        max_request_body_size="never",
        max_breadcrumbs=0,
        attach_stacktrace=True,
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        auto_session_tracking=False,
        send_client_reports=False,
        enable_logs=False,
        before_send=scrub_event,
    )
