"""Replacement keeps the serving channel until the new provider is verified."""

import inspect
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from cryptography.fernet import Fernet
from flask import Flask

from app.database import whatsapp_channel_repository as meta_repository
from app.routes import whatsapp_routes as meta
from app.services import provider_connection_verification as verification


def test_meta_upsert_cannot_reassign_another_tenants_provider(monkeypatch):
    monkeypatch.setattr(meta_repository, "get_whatsapp_channel_by_phone_number_id", Mock(return_value={
        "id": 1, "company_id": 9, "chatbot_id": 9,
    }))
    update = Mock()
    monkeypatch.setattr(meta_repository, "update_whatsapp_channel", update)
    with pytest.raises(PermissionError):
        meta_repository.upsert_whatsapp_channel_by_phone_number_id("123", {"company_id": 2, "chatbot_id": 4})
    update.assert_not_called()


def invoke(module, name, body=None, channel_id=None):
    app = Flask(__name__)
    with app.test_request_context("/?chatbot_id=4", method="POST", json=body or {}):
        function = inspect.unwrap(getattr(module, name))
        response, status = function(channel_id) if channel_id is not None else function()
        return response.get_json(), status


@pytest.fixture(params=["whatsapp"])
def setup(request, monkeypatch):
    provider = request.param
    module = meta
    create_name = "create_whatsapp_channel"
    update_name = "update_whatsapp_channel"
    old = {"id": 1, "company_id": 2, "chatbot_id": 4, "is_active": True, "connection_status": "connected"}
    rows = {1: old}
    def create(**kwargs):
        rows[2] = {**kwargs, "id": 2, "is_active": True, "connection_status": "pending",
                   "connection_attempted_at": "2026-09-14T00:00:00+00:00"}
        return dict(rows[2])
    def update(channel_id, changes, expected_attempt_at=None, expected_status=None):
        if expected_attempt_at and rows[channel_id].get("connection_attempted_at") != expected_attempt_at:
            return None
        if expected_status and rows[channel_id].get("connection_status") != expected_status:
            return None
        rows[channel_id].update(changes)
        return dict(rows[channel_id])
    def activate(provider, channel_id, chatbot_id, company_id, expected_attempt_at=None):
        assert rows[channel_id].get("verified_at")
        assert old["is_active"] is True
        old.update(is_active=False, connection_status="disconnected")
        rows[channel_id].update(is_active=True, connection_status="connected")
        return dict(rows[channel_id])
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setattr(module, "publish_test_block", Mock(return_value=None))
    monkeypatch.setattr(module, "verify_chatbot_access", Mock(return_value={"company_id": 2}))
    monkeypatch.setattr(module, "get_bot_by_id", Mock(return_value={"id": 4, "company_id": 2}))
    monkeypatch.setattr(module, create_name, Mock(side_effect=create))
    monkeypatch.setattr(module, update_name, Mock(side_effect=update))
    monkeypatch.setattr(module, f"get_{provider}_channel_by_id", Mock(side_effect=lambda channel_id: dict(rows[channel_id])))
    monkeypatch.setattr(module, "ensure_channel_slot", Mock())
    activate_mock = Mock(side_effect=activate)
    monkeypatch.setattr(module, "activate_channel", activate_mock)
    metadata = {"id": "123", "display_phone_number": "+601112223333", "verified_name": "Synthetic"}
    check = Mock(return_value=metadata)
    monkeypatch.setattr(module, "verify_meta_connection", check)
    body = {"access_token": "synthetic-key", "phone_number_id": "123", "waba_id": "456", "phone_number": "+601112223333"}
    handler = "complete_embedded_signup"
    return SimpleNamespace(provider=provider, module=module, rows=rows, check=check, activate=activate_mock,
                           body=body, handler=handler)


def test_verified_replacement_switches_only_after_provider_check(setup):
    def check(*args):
        assert setup.rows[1]["is_active"]
        assert setup.rows[2]["connection_status"] == "pending"
        return setup.check.return_value
    setup.check.side_effect = check
    result, status = invoke(setup.module, setup.handler, setup.body)
    assert status == 200
    assert result["data"]["id"] == 2
    assert setup.rows[1]["is_active"] is False
    assert setup.rows[2]["connection_status"] == "connected"
    assert "synthetic-key" not in str(result)
    setup.activate.assert_called_once()
    assert setup.activate.call_args.kwargs["expected_attempt_at"] == setup.rows[2]["connection_attempted_at"]


@pytest.mark.parametrize("failure", [ValueError("The selected phone does not match."), requests.Timeout("private-token")])
def test_failed_replacement_remains_visible_and_preserves_old(setup, failure):
    setup.check.side_effect = failure
    result, status = invoke(setup.module, setup.handler, setup.body)
    assert status in (400, 502)
    assert result["data"]["id"] == 2
    assert result["data"]["connection_status"] == "failed"
    assert setup.rows[1]["is_active"] is True
    assert setup.rows[2]["is_active"] is False
    assert "private-token" not in str(result)
    setup.activate.assert_not_called()


def test_activation_failure_preserves_old_and_reports_safe_error(setup):
    setup.activate.side_effect = meta.ChannelActivationError("activation_unavailable", "Please retry.")
    result, status = invoke(setup.module, setup.handler, setup.body)
    assert status == 409
    assert result["code"] == "activation_unavailable"
    assert setup.rows[1]["is_active"] is True
    assert setup.rows[2]["connection_status"] == "failed"


def test_lost_activation_response_never_disables_committed_new_connection(setup):
    commit = setup.activate.side_effect
    def commit_then_timeout(*args, **kwargs):
        commit(*args, **kwargs)
        raise meta.ChannelActivationError("activation_unavailable", "Please retry.")
    setup.activate.side_effect = commit_then_timeout
    result, status = invoke(setup.module, setup.handler, setup.body)
    assert status == 503
    assert result["code"] == "activation_state_unknown"
    assert setup.rows[1]["is_active"] is False
    assert setup.rows[2]["is_active"] is True
    assert setup.rows[2]["connection_status"] == "connected"
    assert result["data"]["id"] == 2




def test_meta_code_failure_records_failed_new_attempt(setup, monkeypatch):
    if setup.provider != "whatsapp":
        pytest.skip("Meta-only authorization code flow")
    monkeypatch.setattr(meta, "exchange_embedded_signup_code", Mock(return_value=(None, "Authorization code expired.")))
    result, status = invoke(meta, "complete_embedded_signup", {**setup.body, "code": "synthetic-code"})
    assert status == 400
    assert result["data"]["connection_status"] == "failed"
    assert setup.rows[1]["is_active"] is True
    setup.check.assert_not_called()


def provider_response(data, status=200):
    return Mock(status_code=status, json=Mock(return_value=data))


@pytest.fixture
def embedded_meta(setup, monkeypatch):
    key = Fernet.generate_key()
    token = "EAAG" + "x" * 40
    monkeypatch.setenv("AI_KEY_ENCRYPTION_KEY", key.decode())
    monkeypatch.setenv("WHATSAPP_META_APP_ID", "999")
    monkeypatch.setenv("WHATSAPP_META_APP_SECRET", "synthetic-secret")
    monkeypatch.setenv("WHATSAPP_GRAPH_API_VERSION", "v26.0")
    monkeypatch.setattr(meta_repository, "get_registration_pin", Mock(return_value=None))
    phone = setup.check.return_value
    responses = {
        "oauth/access_token": {"access_token": token},
        "456/phone_numbers": {"data": [phone]},
        "456/subscribed_apps": {"data": [{"id": "999"}]},
        "999/subscriptions": {"data": [{"object": "whatsapp_business_account", "active": True,
                                        "callback_url": "https://example.test/webhook", "fields": ["messages"]}]},
    }
    calls = []
    def get(url, **kwargs):
        path = url.removeprefix("https://graph.facebook.com/v26.0/")
        calls.append(("GET", path))
        return provider_response(responses[path])
    def post(url, **kwargs):
        path = url.removeprefix("https://graph.facebook.com/v26.0/")
        assert kwargs["headers"]["Authorization"] == f"Bearer {token}"
        assert path in {"456/subscribed_apps", "123/register"}
        calls.append(("POST", path))
        return provider_response({"success": True})
    monkeypatch.setattr(meta.requests, "get", Mock(side_effect=get))
    posts = Mock(side_effect=post)
    monkeypatch.setattr(meta.requests, "post", posts)
    monkeypatch.setattr(meta, "verify_meta_connection", verification.verify_meta_connection)
    body = {k: v for k, v in setup.body.items() if k != "access_token"}
    body.update(code="fake-authorization-code", onboarding_type="standard")
    return SimpleNamespace(key=key, token=token, setup=setup, body=body, calls=calls,
                           responses=responses, posts=posts)


def test_meta_standard_subscribes_registers_and_stores_encrypted_pin(embedded_meta, caplog):
    case = embedded_meta
    response, status = invoke(meta, case.setup.handler, case.body)
    assert status == 200
    assert [path for method, path in case.calls if method == "POST"] == ["456/subscribed_apps", "123/register"]
    assert case.calls.index(("POST", "123/register")) < case.calls.index(("GET", "456/subscribed_apps"))
    payload = case.posts.call_args.kwargs["json"]
    assert payload["messaging_product"] == "whatsapp"
    pin = payload["pin"]
    assert re.fullmatch(r"[0-9]{6}", pin)
    row = case.setup.rows[2]
    assert row["onboarding_type"] == "standard"
    ciphertext = row["register_pin_encrypted"]
    assert Fernet(case.key).decrypt(ciphertext.encode()).decode() == pin
    for confidential in (case.token, pin, ciphertext):
        assert confidential not in str(response) + caplog.text


def test_meta_coexistence_subscribes_without_generating_or_registering_a_pin(embedded_meta, monkeypatch):
    case = embedded_meta
    monkeypatch.delenv("AI_KEY_ENCRYPTION_KEY")
    response, status = invoke(meta, case.setup.handler, {**case.body, "onboarding_type": "coexistence"})
    assert status == 200
    assert [path for method, path in case.calls if method == "POST"] == ["456/subscribed_apps"]
    assert case.setup.rows[2]["onboarding_type"] == "coexistence"
    assert case.setup.rows[2].get("register_pin_encrypted") is None
    assert case.token not in str(response)


@pytest.mark.parametrize("kind", ["other", None, []])
def test_meta_rejects_invalid_onboarding_type_before_graph_or_database(embedded_meta, kind):
    case = embedded_meta
    response, status = invoke(meta, case.setup.handler, {**case.body, "onboarding_type": kind})
    assert status == 400
    assert "onboarding" in response["message"].lower()
    assert not case.calls
    assert list(case.setup.rows) == [1]


def test_meta_registration_limit_returns_safe_72_hour_message(embedded_meta, caplog):
    case = embedded_meta
    case.posts.side_effect = [provider_response({"success": True}), provider_response({
        "error": {"code": 133016, "message": "private-provider-detail"}
    }, status=400)]
    response, status = invoke(meta, case.setup.handler, case.body)
    assert status == 429
    assert response["message"] == "Too many registration attempts. Try again in 72 hours."
    assert response["code"] == "registration_rate_limited"
    for confidential in ("private-provider-detail", case.token, case.posts.call_args.kwargs["json"]["pin"]):
        assert confidential not in str(response) + caplog.text
    assert case.setup.rows[1]["is_active"] and not case.setup.rows[2]["is_active"]
    case.setup.activate.assert_not_called()


def test_meta_wrong_authorized_phone_cannot_be_registered(embedded_meta):
    case = embedded_meta
    case.responses["456/phone_numbers"] = {"data": []}
    _, status = invoke(meta, case.setup.handler, case.body)
    assert status == 400
    case.posts.assert_not_called()


@pytest.mark.parametrize("exchange_reply", [
    {"error": {"message": "private-exchange-detail"}}, ["private-exchange-detail"],
    {"access_token": {"error": "private-exchange-detail"}},
])
def test_meta_failed_code_exchange_stops_before_graph_writes(embedded_meta, caplog, exchange_reply):
    case = embedded_meta
    case.responses["oauth/access_token"] = exchange_reply
    result, status = invoke(meta, case.setup.handler, case.body)
    assert status == 400
    assert "private-exchange-detail" not in str(result) + caplog.text
    case.posts.assert_not_called()
    case.setup.activate.assert_not_called()


def test_meta_standard_retry_reuses_pin_after_graph_response_is_lost(embedded_meta):
    case = embedded_meta
    post = case.posts.side_effect
    case.posts.side_effect = [provider_response({"success": True}), requests.Timeout()]
    _, status = invoke(meta, case.setup.handler, case.body)
    assert status == 502
    original_pin = case.posts.call_args.kwargs["json"]["pin"]
    original_cipher = case.setup.rows[2]["register_pin_encrypted"]
    case.posts.side_effect = post
    meta_repository.get_registration_pin.return_value = original_cipher
    result, status = invoke(meta, case.setup.handler, {**case.body, "code": "new-fake-code"})
    assert status == 200
    assert case.posts.call_args.kwargs["json"]["pin"] == original_pin
    assert original_pin not in str(result)


def test_meta_competing_pin_reservation_stops_before_graph_writes(embedded_meta):
    case = embedded_meta
    update = meta.update_whatsapp_channel.side_effect
    def reserve(channel_id, changes, **kwargs):
        if "register_pin_encrypted" in changes:
            raise RuntimeError({"code": "23505"})
        return update(channel_id, changes, **kwargs)
    meta.update_whatsapp_channel.side_effect = reserve
    response, status = invoke(meta, case.setup.handler, case.body)
    assert status == 409 and response["code"] == "provider_identity_in_use"
    case.posts.assert_not_called()
    assert case.setup.rows[1]["is_active"] and not case.setup.rows[2]["is_active"]


def test_meta_unexpected_error_after_pin_reservation_releases_the_number(embedded_meta, monkeypatch):
    case = embedded_meta
    monkeypatch.setattr(meta.meta_onboarding, "subscribe_waba", Mock(side_effect=RuntimeError("database unavailable")))
    response, status = invoke(meta, case.setup.handler, case.body)
    assert status == 500
    attempt = case.setup.rows[2]
    assert attempt["register_pin_encrypted"]
    assert attempt["connection_status"] == "failed" and attempt["is_active"] is False
    assert case.setup.rows[1]["is_active"]


def test_meta_lost_verification_write_does_not_leave_the_number_reserved(embedded_meta):
    case = embedded_meta
    update = meta.update_whatsapp_channel.side_effect
    def lose_verified_write(channel_id, changes, **kwargs):
        if changes.get("verified_at"):
            return None
        return update(channel_id, changes, **kwargs)
    meta.update_whatsapp_channel.side_effect = lose_verified_write
    response, status = invoke(meta, case.setup.handler, case.body)
    assert status == 409
    attempt = case.setup.rows[2]
    assert attempt["connection_status"] == "failed" and attempt["is_active"] is False


def _orphaned_reservation(case, monkeypatch, minutes_old):
    """Another tenant's attempt that died after saving its PIN, plus the 090 partial unique index."""
    from datetime import datetime, timedelta, timezone
    attempted = (datetime.now(timezone.utc) - timedelta(minutes=minutes_old)).isoformat()
    rows = case.setup.rows
    rows[3] = {"id": 3, "company_id": 77, "chatbot_id": 78, "phone_number_id": "123", "is_active": True,
               "connection_status": "pending", "register_pin_encrypted": "old-ciphertext",
               "connection_attempted_at": attempted}
    def reserved(row):
        return row.get("is_active") and (row.get("connection_status") == "connected" or (
            row.get("connection_status") == "pending" and row.get("register_pin_encrypted")))
    update = meta.update_whatsapp_channel.side_effect
    def indexed_update(channel_id, changes, **kwargs):
        if changes.get("register_pin_encrypted") and any(
                other_id != channel_id and other.get("phone_number_id") == "123" and reserved(other)
                for other_id, other in rows.items()):
            raise RuntimeError({"code": "23505"})
        return update(channel_id, changes, **kwargs)
    meta.update_whatsapp_channel.side_effect = indexed_update
    monkeypatch.setattr(meta.whatsapp_channel_repository, "get_pin_reservation", Mock(side_effect=lambda phone: next(
        (dict(row) for row in rows.values() if row.get("phone_number_id") == phone and reserved(row)
         and row.get("connection_status") == "pending"), None)), raising=False)
    return rows[3]


def test_meta_reservation_left_by_a_dead_attempt_is_released_after_ten_minutes(embedded_meta, monkeypatch):
    case = embedded_meta
    orphan = _orphaned_reservation(case, monkeypatch, minutes_old=60)
    response, status = invoke(meta, case.setup.handler, case.body)
    assert status == 200
    assert orphan["connection_status"] == "failed" and orphan["is_active"] is False
    assert case.setup.rows[2]["connection_status"] == "connected"


def test_meta_fresh_reservation_by_another_attempt_still_blocks(embedded_meta, monkeypatch):
    case = embedded_meta
    orphan = _orphaned_reservation(case, monkeypatch, minutes_old=1)
    response, status = invoke(meta, case.setup.handler, case.body)
    assert status == 409 and response["code"] == "provider_identity_in_use"
    assert orphan["connection_status"] == "pending" and orphan["is_active"] is True
    case.posts.assert_not_called()


@pytest.mark.parametrize("failure", [None, "phone", "waba", "subscription", "unverified"])
def test_meta_verifies_waba_phone_and_app_before_accepting(monkeypatch, failure):
    monkeypatch.setenv("WHATSAPP_META_APP_ID", "999")
    monkeypatch.setenv("WHATSAPP_META_APP_SECRET", "synthetic-app-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    phone = {"id": "123", "display_phone_number": "+60 111-2223333", "code_verification_status": "VERIFIED"}
    if failure == "unverified":
        phone["code_verification_status"] = "NOT_VERIFIED"
    get = Mock(side_effect=[provider_response({"data": [] if failure == "waba" else [phone]}),
                            provider_response({"data": [] if failure == "subscription" else [{"whatsapp_business_api_data": {"id": "999"}}]}),
                            provider_response({"data": [{"object": "whatsapp_business_account", "active": True,
                                "callback_url": "https://example.test/webhook", "fields": [{"name": "messages", "version": "v22.0"}]}]})])
    monkeypatch.setattr(verification.requests, "get", get)
    expected = "+60999999999" if failure == "phone" else "+601112223333"
    if failure:
        with pytest.raises(ValueError):
            verification.verify_meta_connection("123", "456", "synthetic-token", expected)
    else:
        assert verification.verify_meta_connection("123", "456", "synthetic-token", expected) == phone
    assert get.call_args_list[0].args[0].endswith("/456/phone_numbers")
    assert get.call_args_list[0].kwargs["headers"]["Authorization"] == "Bearer synthetic-token"
    assert "access_token" not in get.call_args_list[0].kwargs["params"]


@pytest.fixture
def meta_readback(monkeypatch):
    monkeypatch.setenv("WHATSAPP_META_APP_ID", "999")
    monkeypatch.setenv("WHATSAPP_META_APP_SECRET", "synthetic-app-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", " https://example.test/ ")
    phone = {"id": "123", "display_phone_number": "+601112223333", "code_verification_status": "VERIFIED"}
    waba_app = {"whatsapp_business_api_data": {"id": "999"}}
    app_subscription = {"object": "whatsapp_business_account", "active": True,
                        "callback_url": "https://example.test/webhook", "fields": [{"name": "messages", "version": "v22.0"}]}
    waba = {"data": [waba_app]}
    app = {"data": [app_subscription]}
    get = Mock(side_effect=[provider_response({"data": [phone]}), provider_response(waba), provider_response(app)])
    monkeypatch.setattr(verification.requests, "get", get)
    return SimpleNamespace(phone=phone, waba_app=waba_app, subscription=app_subscription, waba=waba, app=app, get=get)


@pytest.mark.parametrize("scenario", ["default", "override", "string_fields"])
def test_meta_accepts_only_matching_effective_callback(meta_readback, scenario):
    if scenario == "override":
        meta_readback.subscription["callback_url"] = "https://other.example.test/webhook"
        meta_readback.waba_app["override_callback_uri"] = "https://example.test/webhook"
    if scenario == "string_fields":
        meta_readback.subscription["fields"] = ["messages"]
    result = verification.verify_meta_connection("123", "456", "synthetic-user-token")
    assert result == meta_readback.phone
    assert meta_readback.get.call_args_list[2].args[0].endswith("/999/subscriptions")
    assert meta_readback.get.call_args_list[2].kwargs["headers"] == {"Authorization": "Bearer 999|synthetic-app-secret"}
    assert meta_readback.get.call_args_list[2].kwargs["params"] is None
    assert "synthetic-app-secret" not in str(result)


@pytest.mark.parametrize("scenario", [
    "wrong_callback", "wrong_override", "inactive", "missing_messages", "missing_object", "missing_active",
    "missing_callback", "malformed_fields", "malformed_data", "duplicate_subscription", "duplicate_waba_app",
    "malformed_waba_app", "malformed_override",
])
def test_meta_rejects_unverified_webhook_readback(meta_readback, scenario):
    subscription = meta_readback.subscription
    if scenario == "wrong_callback":
        subscription["callback_url"] = "https://old.example.test/webhook"
    elif scenario == "wrong_override":
        meta_readback.waba_app["override_callback_uri"] = "https://old.example.test/webhook"
    elif scenario == "inactive":
        subscription["active"] = False
    elif scenario == "missing_messages":
        subscription["fields"] = [{"name": "message_template_status_update"}]
    elif scenario.startswith("missing_"):
        subscription.pop({"missing_object": "object", "missing_active": "active", "missing_callback": "callback_url"}[scenario])
    elif scenario == "malformed_fields":
        subscription["fields"] = "messages"
    elif scenario == "malformed_data":
        meta_readback.app["data"] = None
    elif scenario == "duplicate_subscription":
        meta_readback.app["data"].append(dict(subscription))
    elif scenario == "duplicate_waba_app":
        meta_readback.waba["data"].append(dict(meta_readback.waba_app))
    elif scenario == "malformed_waba_app":
        meta_readback.waba_app["whatsapp_business_api_data"] = "999"
    elif scenario == "malformed_override":
        meta_readback.waba_app["override_callback_uri"] = {"url": "https://example.test/webhook"}
    with pytest.raises(ValueError) as error:
        verification.verify_meta_connection("123", "456", "synthetic-user-token")
    assert "synthetic-app-secret" not in str(error.value)


@pytest.mark.parametrize("missing", ["WHATSAPP_META_APP_ID", "WHATSAPP_META_APP_SECRET", "PUBLIC_BASE_URL"])
def test_meta_missing_server_configuration_cannot_be_verified(meta_readback, monkeypatch, missing):
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(ValueError):
        verification.verify_meta_connection("123", "456", "synthetic-user-token")
    meta_readback.get.assert_not_called()


@pytest.mark.parametrize("setup", ["whatsapp"], indirect=True)
@pytest.mark.parametrize("unavailable", [False, True])
def test_meta_webhook_verification_failure_keeps_incumbent(setup, meta_readback, monkeypatch, unavailable):
    if unavailable:
        meta_readback.get.side_effect = [provider_response({"data": [meta_readback.phone]}),
                                        provider_response(meta_readback.waba), requests.Timeout("synthetic-app-secret")]
    else:
        meta_readback.waba_app["override_callback_uri"] = "https://old.example.test/webhook"
    monkeypatch.setattr(meta, "verify_meta_connection", verification.verify_meta_connection)
    result, status = invoke(meta, "complete_embedded_signup", setup.body)
    assert status == (502 if unavailable else 400)
    assert result["data"]["id"] == 2
    assert result["data"]["connection_status"] == "failed"
    assert setup.rows[1]["is_active"] is True
    assert setup.rows[1]["connection_status"] == "connected"
    assert "synthetic-app-secret" not in str(result)
    setup.activate.assert_not_called()




@pytest.mark.parametrize("provider", ["whatsapp"])
def test_delivery_and_reconnect_deny_cross_tenant_rows(monkeypatch, provider):
    module = meta
    monkeypatch.setattr(module, "verify_chatbot_access", Mock(return_value={"company_id": 2}))
    monkeypatch.setattr(module, f"get_{provider}_channel_by_id", Mock(return_value={"id": 8, "company_id": 99, "chatbot_id": 4}))
    check = Mock()
    monkeypatch.setattr(module, "verify_meta_connection", check)
    for handler in (f"{provider}_delivery", f"reconnect_{provider}"):
        _, status = invoke(module, handler, channel_id=8)
        assert status == 403
    check.assert_not_called()


@pytest.mark.parametrize("provider", ["whatsapp"])
def test_repository_lists_latest_attempt_before_creation_order(monkeypatch, provider):
    repository = meta_repository
    query = Mock()
    for name in ("select", "eq", "order"):
        getattr(query, name).return_value = query
    query.execute.return_value = SimpleNamespace(data=[
        {"id": 1, "created_at": "2026-09-10", "connection_attempted_at": "2026-09-15"},
        {"id": 2, "created_at": "2026-09-14", "connection_attempted_at": "2026-09-14"},
    ])
    monkeypatch.setattr(repository, "supabase", Mock(table=Mock(return_value=query)))
    result = getattr(repository, f"get_{provider}_channels_by_chatbot")(4)
    assert [row["id"] for row in result] == [1, 2]


def test_sensitive_provider_response_body_is_never_in_exception(monkeypatch):
    monkeypatch.setattr(verification.requests, "get", Mock(return_value=provider_response({"error": "secret-key"}, 401)))
    with pytest.raises(ValueError) as error:
        verification._provider_get("https://example.invalid", "synthetic", {})
    assert "secret-key" not in str(error.value)


@pytest.mark.parametrize("failure", [False, True])
def test_rechecking_current_connection_does_not_interrupt_service(setup, monkeypatch, failure):
    current = setup.rows[1]
    current.update(api_key="synthetic-key", access_token="synthetic-key", phone_number_id="123",
                   waba_id="456", display_phone_number="+601112223333", phone_number="+601112223333")
    monkeypatch.setattr(setup.module, f"get_{setup.provider}_channel_by_id", Mock(return_value=dict(current)))
    if failure:
        setup.check.side_effect = requests.Timeout("private-token")
    result, status = invoke(setup.module, f"reconnect_{setup.provider}", {"personal_access_token": "synthetic-pat"}, channel_id=1)
    assert status == (502 if failure else 200)
    assert setup.rows[1]["is_active"] is True
    assert setup.rows[1]["connection_status"] == "connected"
    setup.activate.assert_not_called()
    assert "synthetic-pat" not in str(setup.rows)
    assert "synthetic-key" not in str(result)


def test_stale_verification_cannot_write_or_activate_newer_attempt(setup):
    def supersede(*args):
        setup.rows[2]["connection_attempted_at"] = "2026-09-15T00:00:00+00:00"
        return setup.check.return_value
    setup.check.side_effect = supersede
    result, status = invoke(setup.module, setup.handler, setup.body)
    assert status == 409
    assert result["code"] == "connection_superseded"
    assert setup.rows[1]["is_active"]
    setup.activate.assert_not_called()


@pytest.mark.parametrize("provider", ["whatsapp"])
def test_inactive_delivery_does_not_read_old_provider_credentials(monkeypatch, provider):
    module = meta
    monkeypatch.setattr(module, "verify_chatbot_access", Mock(return_value={"company_id": 2}))
    monkeypatch.setattr(module, f"get_{provider}_channel_by_id", Mock(return_value={
        "id": 1, "company_id": 2, "chatbot_id": 4, "is_active": False, "connection_status": "disconnected",
    }))
    check = Mock()
    monkeypatch.setattr(module, "verify_meta_connection", check)
    result, status = invoke(module, f"{provider}_delivery", channel_id=1)
    assert status == 200
    assert result["data"]["delivery_status"] == "unknown"
    check.assert_not_called()


@pytest.mark.parametrize("provider", ["whatsapp"])
def test_inbound_repository_ignores_pending_and_duplicate_owners(monkeypatch, provider):
    repository = meta_repository
    query = Mock()
    for name in ("select", "eq", "limit"):
        getattr(query, name).return_value = query
    query.execute.return_value = SimpleNamespace(data=[{"id": 1}, {"id": 2}])
    monkeypatch.setattr(repository, "supabase", Mock(table=Mock(return_value=query)))
    getter = repository.get_whatsapp_channel_by_phone_number_id
    assert getter("synthetic-id") is None
    query.eq.assert_any_call("connection_status", "connected")
    query.eq.assert_any_call("is_active", True)
