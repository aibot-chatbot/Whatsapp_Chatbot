"""Replacement keeps the serving channel until the new provider is verified."""

import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
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
