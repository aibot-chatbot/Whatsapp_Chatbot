"""The final-admission gate stays a no-op until HANDOFF_CONTROL_ENABLED is on."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.services import channel_delivery_service as delivery
from app.services import handoff_service


CONVERSATION = {"id": 8, "chatbot_id": 3}


def _control(mode=handoff_service.AI_ACTIVE, *, automation_epoch=0, assignee_user_id=None):
    base = handoff_service.initial_control(1, CONVERSATION["chatbot_id"], CONVERSATION["id"])
    return replace(base, mode=mode, automation_epoch=automation_epoch, assignee_user_id=assignee_user_id)


def _human_active():
    return _control(handoff_service.HUMAN_ACTIVE, assignee_user_id=7)


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv("HANDOFF_CONTROL_ENABLED", raising=False)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("HANDOFF_CONTROL_ENABLED", "true")


@pytest.mark.parametrize("paused", [True, False])
def test_flag_off_without_control_matches_todays_verdict(flag_off, paused):
    assert delivery.automatic_reply_allowed(CONVERSATION, "Hi", paused=paused) is not paused


@pytest.mark.parametrize("paused", [True, False])
def test_flag_off_ignores_a_control_that_would_deny(flag_off, paused):
    # Off means off: a caller that starts passing control early changes nothing.
    assert delivery.automatic_reply_allowed(
        CONVERSATION, "Hi", paused=paused,
        control=_human_active(), epoch_at_dispatch=0) is not paused


@pytest.mark.parametrize("paused", [True, False])
def test_flag_on_without_control_leaves_paused_authoritative(flag_on, paused):
    assert delivery.automatic_reply_allowed(CONVERSATION, "Hi", paused=paused) is not paused


def test_flag_on_denies_a_takeover_the_paused_boolean_has_not_noticed(flag_on):
    assert delivery.automatic_reply_allowed(
        CONVERSATION, "Hi", paused=False,
        control=_human_active(), epoch_at_dispatch=0) is False


def test_flag_on_denies_a_turn_dispatched_in_a_stale_epoch(flag_on):
    assert delivery.automatic_reply_allowed(
        CONVERSATION, "Hi", paused=False,
        control=_control(automation_epoch=1), epoch_at_dispatch=0) is False


def test_flag_on_allows_ai_active_with_a_matching_epoch(flag_on):
    assert delivery.automatic_reply_allowed(
        CONVERSATION, "Hi", paused=False,
        control=_control(automation_epoch=1), epoch_at_dispatch=1) is True


def test_the_gate_can_never_grant_what_paused_denied(flag_on):
    assert delivery.automatic_reply_allowed(
        CONVERSATION, "Hi", paused=True,
        control=_control(automation_epoch=1), epoch_at_dispatch=1) is False


@pytest.mark.parametrize("pending,expected", [(True, True), (False, False)])
def test_handoff_acknowledgement_is_unchanged_with_the_flag_off(flag_off, monkeypatch, pending, expected):
    monkeypatch.setattr(delivery, "is_pending_handoff_action", Mock(return_value=pending))
    reply = delivery.HandoffAcknowledgement("Escalated", action_id=4, conversation_id=CONVERSATION["id"],
                                            chatbot_id=CONVERSATION["chatbot_id"], company_id=1)
    assert delivery.automatic_reply_allowed(CONVERSATION, reply, paused=True) is expected
    assert delivery.automatic_reply_allowed(CONVERSATION, reply, paused=True,
                                            control=_human_active(), epoch_at_dispatch=0) is expected
