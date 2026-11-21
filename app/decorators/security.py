from functools import wraps
from flask import current_app, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
import logging
import os
import hashlib
import hmac

_MAX_WEBHOOK_BYTES = 1024 * 1024


def validate_signature(payload, signature):
    """
    Validate the incoming payload's signature against our expected signature
    """
    app_secret = current_app.config.get("APP_SECRET") or ""
    if not app_secret:
        # Fail closed. An unset secret used to raise TypeError here and surface
        # as a 500; an empty one is worse, because HMAC-SHA256 keyed on b"" is
        # computable by anyone, so every "verified" Meta callback would be
        # forgeable for any tenant whose phone_number_id could be guessed.
        logging.error(
            "APP_SECRET is not configured; rejecting Meta webhook delivery"
        )
        return False

    # Use the App Secret to hash the payload
    expected_signature = hmac.new(
        bytes(app_secret, "latin-1"),
        msg=payload.encode("utf-8") if isinstance(payload, str) else payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Check if the signature matches
    return hmac.compare_digest(expected_signature, signature)


def read_webhook_body():
    limit = min(request.max_content_length or _MAX_WEBHOOK_BYTES, _MAX_WEBHOOK_BYTES)
    # Read one extra byte to detect oversized streams instead of accepting a truncated body.
    request.max_content_length = limit + 1
    payload = request.get_data(cache=True)
    if len(payload) > limit:
        raise RequestEntityTooLarge()
    return payload


def signature_required(f):
    """
    Decorator to ensure that the incoming requests to our webhook are valid and signed with the correct signature.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            payload = read_webhook_body()
        except RequestEntityTooLarge:
            return jsonify({"status": "error", "message": "Webhook body is too large."}), 413
        signature = request.headers.get("X-Hub-Signature-256", "")[
            7:
        ]  # Removing 'sha256='
        if not validate_signature(payload, signature):
            logging.info("Signature verification failed!")
            return jsonify({"status": "error", "message": "Invalid signature"}), 403
        return f(*args, **kwargs)

    return decorated_function


_MIN_WORKER_TOKEN_LENGTH = 32


def worker_token_required(f):
    """Authenticate the out-of-process automation worker by shared token.

    Fails closed on an unset, short, or mismatched token. The guard is
    platform-scoped on purpose: the automation outbox spans tenants, so this
    is a platform credential and never a tenant one. A short token is treated
    as unconfigured rather than compared, for the same reason an empty
    APP_SECRET is rejected above - a guessable secret verifies everything.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        expected = os.getenv("N8N_WORKER_TOKEN", "").strip()
        if len(expected) < _MIN_WORKER_TOKEN_LENGTH:
            logging.error(
                "N8N_WORKER_TOKEN is unset or shorter than %d characters; "
                "rejecting automation worker request",
                _MIN_WORKER_TOKEN_LENGTH,
            )
            return jsonify({
                "status": "error",
                "message": "Worker authentication is not configured",
            }), 503

        header = request.headers.get("Authorization", "")
        presented = header[7:] if header.startswith("Bearer ") else ""
        if not presented or not hmac.compare_digest(presented, expected):
            logging.info("Automation worker token verification failed")
            return jsonify({"status": "error", "message": "Invalid worker token"}), 403
        return f(*args, **kwargs)

    return decorated_function
