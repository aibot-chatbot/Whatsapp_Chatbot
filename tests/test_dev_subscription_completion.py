"""Fake payment completion must never grant paid entitlements."""
from unittest.mock import patch
from flask import Flask
from app.routes.dev_billing_routes import retired_payment_simulation


def test_fake_completion_is_retired():
    app = Flask(__name__)
    with app.test_request_context(), patch("app.services.subscription_payment_callback_service.process_subscription_payment_callback") as grant:
        response, status = retired_payment_simulation.__wrapped__("test-reference")
        assert status == 410
        assert "CHIP test checkout" in response.get_json()["message"]
        grant.assert_not_called()
