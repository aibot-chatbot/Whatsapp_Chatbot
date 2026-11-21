from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.database import channel_lifecycle_repository as lifecycle


@pytest.fixture
def rpc(monkeypatch):
    rpc = Mock(return_value=SimpleNamespace(execute=lambda: SimpleNamespace(data={"id": 7})))
    monkeypatch.setattr(lifecycle, "supabase", SimpleNamespace(rpc=rpc))
    monkeypatch.setattr("app.services.billing_guard._resolve_company_subscription",
                        lambda _: {"plan": {"channel_limit": 2}})
    return rpc


@pytest.mark.parametrize("provider", ["telegram", "whatsapp", "whatsapp_link"])
def test_verified_activation_passes_scoped_limit_and_attempt_to_atomic_rpc(rpc, provider):
    assert lifecycle.activate_channel(provider, 7, 8, 9, expected_attempt_at="2026-09-14T00:00:00Z") == {"id": 7}
    rpc.assert_called_once_with("activate_verified_channel", {
        "p_provider": provider, "p_channel_id": 7, "p_chatbot_id": 8, "p_company_id": 9,
        "p_channel_limit": 2, "p_expected_attempt_at": "2026-09-14T00:00:00Z",
    })


def test_absent_entitlement_never_activates(rpc, monkeypatch):
    monkeypatch.setattr("app.services.billing_guard._resolve_company_subscription", lambda _: None)
    with pytest.raises(lifecycle.ChannelActivationError) as error:
        lifecycle.activate_channel("telegram", 7, 8, 9)
    assert error.value.code == "no_subscription"
    rpc.assert_not_called()


@pytest.mark.parametrize("message,code", [("channel_limit_reached", "channel_limit"),
                                         ("private credential details", "activation_unavailable")])
def test_rpc_failure_is_safe_and_fail_closed(rpc, message, code):
    rpc.side_effect = RuntimeError(message)
    with pytest.raises(lifecycle.ChannelActivationError) as error:
        lifecycle.activate_channel("telegram", 7, 8, 9)
    assert error.value.code == code
    assert "private" not in str(error.value)


def test_stale_verification_does_not_report_connected(rpc):
    rpc.return_value.execute = lambda: SimpleNamespace(data=None)
    assert lifecycle.activate_channel("whatsapp_link", 7, 8, 9) is None


def test_unsupported_provider_never_reaches_database(rpc):
    with pytest.raises(ValueError, match="Unsupported"):
        lifecycle.activate_channel("arbitrary_table", 7, 8, 9)
    rpc.assert_not_called()
