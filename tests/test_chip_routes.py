"""CHIP callback HTTP tests with real RSA authentication and mocked provider/DB."""

import base64
import json
from unittest.mock import Mock

import pytest
import httpx
import requests
from flask import Flask
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import app.routes.chip_routes as routes
import app.services.chip_topup_payment_service as topup
import app.services.chip_payment_service as subscription_service
from app.services.chip_service import ChipAPIError, ChipConfig

BRAND = "00000000-0000-4000-8000-000000000001"
PURCHASE = "00000000-0000-4000-8000-000000000002"
REFERENCE = "00000000-0000-4000-8000-000000000003"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected network call in mocked payment tests")
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(httpx.Client, "request", blocked)


def purchase():
    return {
        "type": "purchase", "id": PURCHASE, "brand_id": BRAND, "reference": REFERENCE,
        "status": "paid", "is_test": False, "marked_as_paid": False,
        "event_type": "purchase.paid", "purchase": {"total": 200, "currency": "MYR"},
        "payment": {"amount": 200, "currency": "MYR", "is_outgoing": False,
                    "payment_type": "purchase", "paid_on": 1789000000},
    }


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def callback(monkeypatch, signing_key):
    public_key = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    config = ChipConfig(
        enabled=True, environment="live", live_enabled=True, api_key="synthetic-api-key",
        brand_id=BRAND, callback_public_key=public_key, webhook_public_key=public_key,
    )
    monkeypatch.setattr(routes.ChipConfig, "from_env", lambda: config)
    fetch = Mock(return_value=purchase())
    monkeypatch.setattr(routes, "get_purchase", fetch)
    lookup = Mock(return_value=None)
    monkeypatch.setattr(routes, "get_subscription_order_by_gateway_id", lookup)
    monkeypatch.setattr(topup, "get_topup_order_by_gateway_order_id", lambda *args: {
        "company_id": 42, "order_reference": REFERENCE, "gateway_order_id": PURCHASE,
        "payment_gateway": "chip", "gateway_environment": "live", "gateway_brand_id": BRAND,
        "amount_micro_myr": 2_000_000, "currency": "MYR", "status": "pending",
    })
    fulfill = Mock(return_value={"status": "credited", "idempotent": False})
    monkeypatch.setattr(topup, "process_topup_payment_callback", fulfill)
    monkeypatch.setattr(topup, "mark_chip_topup_order_for_review", Mock())
    report = Mock()
    monkeypatch.setattr(routes, "capture_payment_failure", report)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(routes.chip_bp)

    def post(payload=None, *, path="callback", raw=None, signature=None):
        body = raw if raw is not None else json.dumps(payload if payload is not None else purchase()).encode()
        if signature is None:
            signature = base64.b64encode(signing_key.sign(body, padding.PKCS1v15(), hashes.SHA256())).decode()
        return app.test_client().post(
            "/api/billing/chip/" + path, data=body,
            headers={"X-Signature": signature, "Content-Type": "application/json"},
        )

    return post, fetch, lookup, fulfill, report


@pytest.mark.parametrize("path", ["callback", "webhook"])
def test_real_signature_reaches_authoritative_topup_processing(callback, path):
    post, fetch, _, fulfill, _ = callback
    response = post(path=path)
    assert response.status_code == 200
    assert response.json == {"status": "success", "result": "credited"}
    assert fetch.call_args.args[1] == PURCHASE
    assert fulfill.call_args.args[0]["amount_sen"] == 200


@pytest.mark.parametrize("signature", ["", "not-base64", "AAAA"])
def test_bad_signature_never_fetches_or_fulfils(callback, signature):
    post, fetch, lookup, fulfill, report = callback
    assert post(signature=signature).status_code == 401
    fetch.assert_not_called()
    lookup.assert_not_called()
    fulfill.assert_not_called()
    if signature:
        assert report.call_args.kwargs["reason"] == "invalid_signature"
    else:
        report.assert_not_called()


def test_missing_signature_does_not_load_config_or_fetch_public_key(callback, monkeypatch):
    post, _, _, _, _ = callback
    monkeypatch.setattr(routes.ChipConfig, "from_env", Mock(side_effect=AssertionError("must not load")))
    key = Mock()
    monkeypatch.setattr(routes, "get_public_key", key)
    assert post(signature="").status_code == 401
    key.assert_not_called()


@pytest.mark.parametrize("event", sorted(routes._REVIEW_EVENTS))
@pytest.mark.parametrize("order_type", ["subscription", "topup"])
def test_reversal_events_validate_original_order_and_alert_without_granting(callback, monkeypatch, event, order_type):
    post, fetch, lookup, fulfill, report = callback
    payload = {**purchase(), "event_type": event}
    if event.startswith("payment."):
        payload.update(type="payment", id=REFERENCE, related_to={"type": "purchase", "id": PURCHASE})
    update = Mock()
    subscription_fulfill = Mock()
    monkeypatch.setattr(subscription_service, "update_subscription_order_activation_state", update)
    monkeypatch.setattr(subscription_service, "capture_payment_failure", Mock())
    monkeypatch.setattr(subscription_service, "process_subscription_payment_callback", subscription_fulfill)
    if order_type == "subscription":
        lookup.return_value = {
            "payment_gateway": "chip", "gateway_environment": "live", "gateway_brand_id": BRAND,
            "order_reference": REFERENCE, "gateway_order_id": PURCHASE, "amount_sen": 200,
            "currency": "MYR", "status": "credited", "payment_reference": PURCHASE,
        }
        monkeypatch.setattr(subscription_service, "get_subscription_order_by_gateway_id", lookup)
    # Even if current state is paid after a reversal, an event must not grant again.
    assert post(payload, path="webhook").status_code == 500
    assert fetch.call_args.args[1] == PURCHASE
    fulfill.assert_not_called()
    subscription_fulfill.assert_not_called()
    assert report.call_args.kwargs["reason"] == "status_review"
    if order_type == "subscription":
        assert update.call_args.kwargs["reconciliation_required"] is True
    else:
        topup.mark_chip_topup_order_for_review.assert_called_once_with(REFERENCE, PURCHASE)


@pytest.mark.parametrize("related", [None, [], {"type": "payout", "id": PURCHASE}])
def test_reversal_event_requires_purchase_relation(callback, related):
    post, fetch, _, fulfill, _ = callback
    payload = {**purchase(), "type": "payment", "event_type": "payment.refunded", "related_to": related}
    assert post(payload, path="webhook").status_code == 400
    fetch.assert_not_called()
    fulfill.assert_not_called()


def test_reversal_event_cannot_skip_stored_order_amount_validation(callback):
    post, fetch, _, fulfill, report = callback
    fetch.return_value = {**purchase(), "purchase": {"total": 201, "currency": "MYR"},
                          "payment": {**purchase()["payment"], "amount": 201}}
    assert post({**purchase(), "event_type": "purchase.pending_refund"}, path="webhook").status_code == 400
    fulfill.assert_not_called()
    assert report.call_args.kwargs["reason"] == "mismatch"


@pytest.mark.parametrize("field,value", [("brand_id", "other-brand"), ("is_test", True), ("is_test", 0)])
def test_signed_wrong_brand_or_mode_is_rejected_before_lookup(callback, field, value):
    post, fetch, _, fulfill, report = callback
    assert post({**purchase(), field: value}).status_code == 400
    fetch.assert_not_called()
    fulfill.assert_not_called()
    # Sentry redacts the message, so this tag is the only way to tell a stale-mode
    # callback from malformed data that happens to share the same 400 response.
    assert report.call_args.kwargs["reason"] == "brand_mismatch"


def test_brand_mismatch_is_tagged_apart_from_other_rejected_payloads(callback):
    post, _, _, _, report = callback
    assert post(raw=b"{broken").status_code == 400
    assert report.call_args.kwargs["reason"] == "mismatch"
    assert post({**purchase(), "brand_id": "other-brand"}).status_code == 400
    assert report.call_args.kwargs["reason"] == "brand_mismatch"
    # Both answer identically, so the split adds no oracle for an unsigned caller.
    assert post(raw=b"{broken").json == post({**purchase(), "brand_id": "other-brand"}).json


@pytest.mark.parametrize("field,value", [
    ("id", "00000000-0000-4000-8000-000000000099"),
    ("brand_id", "00000000-0000-4000-8000-000000000099"),
    ("reference", "00000000-0000-4000-8000-000000000099"), ("is_test", True),
])
def test_authoritative_mismatch_never_fulfils(callback, field, value):
    post, fetch, _, fulfill, _ = callback
    fetch.return_value = {**purchase(), field: value}
    assert post().status_code == 400
    fulfill.assert_not_called()


def test_authoritative_amount_mismatch_never_fulfils(callback):
    post, fetch, _, fulfill, _ = callback
    fetch.return_value = {**purchase(), "purchase": {"total": 201, "currency": "MYR"},
                          "payment": {**purchase()["payment"], "amount": 201}}
    assert post().status_code == 400
    fulfill.assert_not_called()


def test_oversized_body_rejected_before_configuration(callback, monkeypatch):
    post, fetch, _, fulfill, _ = callback
    monkeypatch.setattr(routes.ChipConfig, "from_env", Mock(side_effect=AssertionError("must not load")))
    assert post(raw=b"x" * (1024 * 1024 + 1), signature="AAAA").status_code == 413
    fetch.assert_not_called()
    fulfill.assert_not_called()


@pytest.mark.parametrize("raw", [b"{broken", b"[]", b"null", b"\xff"])
def test_authenticated_malformed_json_cannot_reach_provider(callback, raw):
    post, fetch, _, fulfill, _ = callback
    assert post(raw=raw).status_code == 400
    fetch.assert_not_called()
    fulfill.assert_not_called()


def test_unknown_webhook_event_is_ignored_without_provider_call(callback):
    post, fetch, _, fulfill, _ = callback
    assert post({**purchase(), "event_type": "client.created"}, path="webhook").json == {"status": "ignored"}
    fetch.assert_not_called()
    fulfill.assert_not_called()


@pytest.mark.parametrize("error", [ChipAPIError("private-provider-secret"), RuntimeError("private-db-secret")])
def test_provider_or_persistence_failure_is_retryable_and_redacted(callback, error):
    post, fetch, _, fulfill, report = callback
    fetch.side_effect = error
    response = post()
    assert response.status_code == 500
    assert "private-" not in response.get_data(as_text=True)
    assert report.called
    fulfill.assert_not_called()


@pytest.mark.parametrize("status", [
    "credit_failed", "activation_failed", "activation_credit_pending",
    "malformed_atomic_order", "unsupported_order_schema_version",
    "activation_already_claimed", "manual_review_required", None, "unknown",
])
def test_incomplete_fulfilment_requests_callback_retry(callback, status):
    post, _, _, fulfill, report = callback
    fulfill.return_value = {"status": status}
    assert post().status_code == 500
    assert report.call_args.kwargs["reason"] == "fulfillment"
