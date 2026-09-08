"""Meta authentication must bound reads and preserve exact signed bytes."""
import hashlib
import hmac
import io

import pytest
from flask import Flask, request
from app.decorators import security


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("oversized", [False, True])
def test_signed_body_limit(monkeypatch, streaming, oversized):
    monkeypatch.setattr(security, "_MAX_WEBHOOK_BYTES", 64)
    app = Flask(__name__)
    app.config.update(TESTING=True, APP_SECRET="")

    @app.post("/webhook")
    @security.signature_required
    def hook():
        return {"bytes": len(request.get_data()), "value": request.get_json()["value"]}

    body = b'{"value":"hello"}' if not oversized else b"x" * 65
    signature = hmac.new(b"synthetic-secret", body, hashlib.sha256).hexdigest()
    environ = {"wsgi.input": io.BytesIO(body), "CONTENT_LENGTH": str(len(body))}
    if streaming:
        environ.update(CONTENT_LENGTH="", **{"wsgi.input_terminated": True})
    response = app.test_client().post("/webhook", content_type="application/json",
        headers={"X-Hub-Signature-256": "sha256=" + signature}, environ_overrides=environ)
    assert response.status_code == (413 if oversized else 200)
    if not oversized:
        assert response.json == {"bytes": len(body), "value": "hello"}


def test_unsigned_invalid_utf8_is_rejected_without_decode_error():
    app = Flask(__name__)
    app.config.update(TESTING=True, APP_SECRET="")
    app.add_url_rule("/webhook", view_func=security.signature_required(lambda: "unexpected"), methods=["POST"])
    assert app.test_client().post("/webhook", data=b"\xff", content_type="application/json").status_code == 403
