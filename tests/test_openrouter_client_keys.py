"""Clients share OpenRouter keys in small groups, so a blocked key stops a group and not everyone."""
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
import requests
from cryptography.fernet import Fernet

from app.database import openrouter_key_repository as repository
from app.jobs import check_openrouter_keys as job
from app.services import ai_router, chat_pipeline_service, email_service, openrouter_service
from app.services import openrouter_key_service as keys
from app.services.channel_delivery_service import HandoffAcknowledgement

SHARED = "sk-shared-synthetic"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(monkeypatch):
    state = SimpleNamespace(keys=[], assigned={}, created=0, credit={})

    def create_key(key_hash, encrypted_key, label):
        row = {"id": len(state.keys) + 1, "key_hash": key_hash, "encrypted_key": encrypted_key,
               "label": label, "status": "active"}
        state.keys.append(row)
        return row

    def get_company_key(company_id):
        return next((k for k in state.keys if k["id"] == state.assigned.get(company_id)), None)

    def list_keys(status):
        return [{**k, "clients": sum(1 for v in state.assigned.values() if v == k["id"])}
                for k in state.keys if k["status"] == status]

    def assign_company(company_id, key_id):
        state.assigned.setdefault(company_id, key_id)

    def mark_disabled(key_id):
        next(k for k in state.keys if k["id"] == key_id)["status"] = "disabled"

    def mark_active(key_id):
        next(k for k in state.keys if k["id"] == key_id)["status"] = "active"

    def create_on_openrouter(_url, **kwargs):
        state.created += 1
        state.sent = kwargs
        response = MagicMock(status_code=201)
        response.json.return_value = {"key": "sk-client-%d" % state.created, "data": {"hash": "hash-%d" % state.created}}
        return response

    for name, function in (("create_key", create_key), ("get_company_key", get_company_key),
                           ("list_keys", list_keys), ("assign_company", assign_company),
                           ("mark_disabled", mark_disabled), ("mark_active", mark_active),
                           ("month_credit_micro_myr", lambda key_id, _start: state.credit.get(key_id, 0))):
        monkeypatch.setattr(repository, name, function)
    monkeypatch.setattr(keys.requests, "post", create_on_openrouter)
    monkeypatch.setattr(keys, "_cache", {})
    monkeypatch.setattr(keys, "_closed_to_new_clients", frozenset())
    monkeypatch.setenv("OPENROUTER_CLIENT_KEYS_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_API_KEY", "synthetic-management-key")
    monkeypatch.setenv("AI_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OPENROUTER_KEY_MONTHLY_LIMIT_USD", "25")
    monkeypatch.setenv("AI_USD_TO_MYR_RATE_MICRO_MYR_PER_USD", "4000000")
    monkeypatch.delenv("MAX_CLIENTS_PER_KEY", raising=False)
    return state


def test_with_the_feature_off_every_call_uses_the_shared_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_CLIENT_KEYS_ENABLED", raising=False)
    monkeypatch.setattr(repository, "get_company_key", Mock(side_effect=AssertionError("database touched")))

    assert keys.key_for_company(1, SHARED) == SHARED


def test_a_call_with_no_client_uses_the_shared_key(store):
    assert keys.key_for_company(None, SHARED) == SHARED
    assert store.created == 0


def test_the_first_client_gets_a_new_key_with_a_monthly_cap(store):
    assert keys.key_for_company(1, SHARED) == "sk-client-1"
    assert store.sent["json"]["limit"] == 25.0
    assert store.sent["json"]["limit_reset"] == "monthly"
    assert store.sent["headers"]["Authorization"] == "Bearer synthetic-management-key"


def test_a_stored_key_is_encrypted(store):
    keys.key_for_company(1, SHARED)

    assert "sk-client-1" not in store.keys[0]["encrypted_key"]


def test_twenty_clients_share_a_key_and_the_next_one_gets_a_new_key(store):
    used = {company: keys.key_for_company(company, SHARED) for company in range(1, 22)}

    assert {used[company] for company in range(1, 21)} == {"sk-client-1"}
    assert used[21] == "sk-client-2"
    assert store.created == 2


def test_the_group_size_is_a_setting(store, monkeypatch):
    monkeypatch.setenv("MAX_CLIENTS_PER_KEY", "1")

    assert keys.key_for_company(1, SHARED) != keys.key_for_company(2, SHARED)


def test_a_repeat_call_does_not_touch_the_database(store, monkeypatch):
    keys.key_for_company(1, SHARED)
    monkeypatch.setattr(repository, "get_company_key", Mock(side_effect=AssertionError("database touched")))

    assert keys.key_for_company(1, SHARED) == "sk-client-1"


def test_a_database_failure_falls_back_without_logging_a_key(store, monkeypatch, caplog):
    monkeypatch.setattr(repository, "get_company_key", Mock(side_effect=RuntimeError("database down")))

    with caplog.at_level(logging.ERROR):
        assert keys.key_for_company(1, SHARED) == SHARED

    assert "Client OpenRouter key unavailable" in caplog.text
    assert SHARED not in caplog.text


def test_a_missing_master_key_falls_back(store, monkeypatch):
    monkeypatch.delenv("AI_KEY_ENCRYPTION_KEY")

    assert keys.key_for_company(1, SHARED) == SHARED


def test_a_client_on_a_disabled_key_is_never_moved_to_the_shared_key(store):
    keys.key_for_company(1, SHARED)
    store.keys[0]["status"] = "disabled"
    keys._cache.clear()

    assert keys.key_for_company(1, SHARED) == "sk-client-1"


def test_a_new_client_never_joins_a_disabled_key(store):
    keys.key_for_company(1, SHARED)
    store.keys[0]["status"] = "disabled"

    assert keys.key_for_company(2, SHARED) == "sk-client-2"


def test_a_rotated_master_key_still_opens_stored_keys(store, monkeypatch):
    keys.key_for_company(1, SHARED)
    monkeypatch.setenv("AI_KEY_ENCRYPTION_KEY",
                       Fernet.generate_key().decode() + "," + os.environ["AI_KEY_ENCRYPTION_KEY"])
    keys._cache.clear()

    assert keys.key_for_company(1, SHARED) == "sk-client-1"


def test_a_thread_that_waited_for_the_lock_reuses_the_result(store, monkeypatch):
    class FilledWhileWaiting:
        def __enter__(self):
            keys._cache[1] = ("sk-from-the-other-thread", float("inf"))

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(keys, "_lock", FilledWhileWaiting())

    assert keys.key_for_company(1, SHARED) == "sk-from-the-other-thread"
    assert store.created == 0


def test_a_real_request_carries_the_key_of_its_client(monkeypatch):
    post = Mock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(openrouter_service.requests, "post", post)
    monkeypatch.setattr(openrouter_service.openrouter_key_service, "key_for_company",
                        lambda company_id, shared: "sk-client-%s" % company_id)

    openrouter_service.post_chat_completion({"model": "m"}, api_key=SHARED, company_id=7)

    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-client-7"


# A spent key stops its own group and says so.

def refusal(status=403, limit_source="openrouter_key_limit"):
    """The shape OpenRouter documents under Budget errors."""
    metadata = {"limit_source": limit_source} if limit_source else {}
    body = {"error": {"code": status, "message": "Limit exceeded.", "metadata": metadata}}
    response = MagicMock(status_code=status, ok=False, text=json.dumps(body))
    response.json.return_value = body
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


@pytest.fixture
def chat(monkeypatch):
    from app.database import agent_action_repository, conversation_repository
    from app.services import channel_delivery_service as delivery
    from app.services import company_status_service

    world = SimpleNamespace(saved=[], post=Mock(return_value=refusal()), staff=Mock(return_value=True),
                            owner=Mock(return_value=True))

    def save(**fields):
        world.saved.append(fields)
        return {"id": 40 + len(world.saved)}

    monkeypatch.setattr(company_status_service, "ensure_company_operational", Mock())
    monkeypatch.setattr(ai_router, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(chat_pipeline_service, "get_bot_by_id", Mock(return_value={"id": 3, "company_id": 1}))
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot", lambda conversation_id, chatbot_id: {
        "id": conversation_id, "chatbot_id": chatbot_id, "source_channel": "telegram"})
    monkeypatch.setattr(agent_action_repository, "is_conversation_escalated",
                        lambda conversation_id, *_, **__: any(r["conversation_id"] == conversation_id for r in world.saved))
    monkeypatch.setattr(delivery, "is_pending_handoff_action", lambda *_: True)
    monkeypatch.setattr(chat_pipeline_service, "save_agent_action", Mock(side_effect=save))
    monkeypatch.setattr(chat_pipeline_service, "create_crm_lead_from_agent_signal", Mock())
    monkeypatch.setattr(chat_pipeline_service, "_after_reply", lambda _label, work: work())
    monkeypatch.setattr(chat_pipeline_service, "_outage_email_sent_at", {})
    monkeypatch.setattr(email_service, "send_handoff_notification_email", world.staff)
    monkeypatch.setattr(email_service, "send_openrouter_key_alert_email", world.owner)
    monkeypatch.setattr(ai_router, "_try_process_flow_message", Mock(return_value=SimpleNamespace(
        handled=False, should_handoff_to_ai=True, reply=None)))
    monkeypatch.setattr(ai_router, "_route_for_enforcement", Mock(return_value=("openai", "openai/gpt-6-luna")))
    monkeypatch.setattr(ai_router, "_check_ai_credit_before_provider", Mock())
    monkeypatch.setattr(ai_router, "_make_usage_log", Mock())
    monkeypatch.setattr(ai_router, "prepare_chat_prompt", Mock(return_value={
        "direct_reply": None, "prompt": "built prompt", "intent": "question"}))
    monkeypatch.setattr(openrouter_service, "OPENROUTER_API_KEY", SHARED)
    monkeypatch.setattr(openrouter_service.requests, "post", world.post)
    monkeypatch.setattr(openrouter_service, "_moderation_alert_sent_at", {})
    monkeypatch.setattr(openrouter_service, "_in_background", lambda work: work())
    return world


def customer_message(**kwargs):
    return ai_router.generate_response("a question", "60123456789", 3, source_channel="telegram",
                                       conversation_id=8, **kwargs)


@pytest.mark.parametrize("status", [402, 403])
def test_a_spent_key_hands_the_chat_to_staff_and_tells_the_owner(chat, status):
    chat.post.return_value = refusal(status)

    reply = customer_message()

    assert isinstance(reply, HandoffAcknowledgement)
    assert chat.saved[0]["payload"] == {"trigger": "key_limit"}
    assert chat.staff.call_args.kwargs["trigger"] == "key_limit"
    chat.owner.assert_called_once()


def test_a_customer_is_not_told_about_the_limit(chat):
    assert customer_message() == chat_pipeline_service.AI_UNAVAILABLE_HANDOFF_REPLY


def test_a_burst_on_a_spent_key_emails_the_owner_once(chat):
    customer_message()
    customer_message()

    chat.owner.assert_called_once()


def test_a_spent_key_reminds_the_owner_daily_not_every_few_minutes(chat, monkeypatch):
    customer_message()
    an_hour_later = time.monotonic() + 60 * 60
    monkeypatch.setattr(openrouter_service.time, "monotonic", lambda: an_hour_later)

    customer_message()

    chat.owner.assert_called_once()


@pytest.mark.parametrize("status, limit_source", [(402, None), (403, "openrouter_workspace_budget")])
def test_other_refusals_stay_an_outage(chat, status, limit_source):
    chat.post.return_value = refusal(status, limit_source)

    customer_message()

    assert chat.saved[0]["payload"] == {"trigger": "ai_unavailable"}
    chat.owner.assert_not_called()


def test_a_test_chat_on_a_spent_key_gets_a_plain_message(chat):
    reply = customer_message(operation_type=ai_router.OPERATION_TEST_BOT)

    assert reply == chat_pipeline_service.KEY_LIMIT_PLAIN_REPLY
    assert chat.saved == []


# The scheduled check

def listing(*items):
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": list(items)}
    return Mock(return_value=response)


@pytest.fixture
def watched(store, monkeypatch):
    keys.key_for_company(1, SHARED)
    alert = Mock(return_value=True)
    disable = Mock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(job, "send_openrouter_key_alert_email", alert)
    monkeypatch.setattr(keys.requests, "patch", disable)
    monkeypatch.setattr(job, "_alerted_at", {})
    return SimpleNamespace(store=store, alert=alert, disable=disable, monkeypatch=monkeypatch)


def test_the_check_does_nothing_with_the_feature_off(monkeypatch):
    monkeypatch.delenv("OPENROUTER_CLIENT_KEYS_ENABLED", raising=False)
    monkeypatch.setattr(keys.requests, "get", Mock(side_effect=AssertionError("network touched")))

    assert job.check_keys() == 0


def test_a_disabled_key_is_recorded_and_the_owner_is_told(watched):
    watched.monkeypatch.setattr(keys.requests, "get", listing({"hash": "hash-1", "disabled": True}))

    assert job.check_keys() == 1
    assert watched.store.keys[0]["status"] == "disabled"
    assert "disabled" in watched.alert.call_args.kwargs["problem"]


def test_the_check_asks_openrouter_for_disabled_keys(watched):
    """OpenRouter hides them unless asked, which would blind this whole check."""
    read = listing({"hash": "hash-1", "disabled": False})
    watched.monkeypatch.setattr(keys.requests, "get", read)

    job.check_keys()

    assert read.call_args.kwargs["params"]["include_disabled"] == "true"


def test_a_key_missing_from_openrouter_counts_as_disabled(watched):
    watched.monkeypatch.setenv("MAX_CLIENTS_PER_KEY", "1")
    keys.key_for_company(2, SHARED)
    watched.monkeypatch.setattr(keys.requests, "get", listing({"hash": "hash-2", "disabled": False}))

    assert job.check_keys() == 1
    assert [key["status"] for key in watched.store.keys] == ["disabled", "active"]


def test_a_listing_with_none_of_our_keys_changes_nothing(watched, caplog):
    watched.monkeypatch.setattr(keys.requests, "get", listing({"hash": "someone-else", "disabled": False}))

    with caplog.at_level(logging.ERROR):
        assert job.check_keys() == 1

    assert watched.store.keys[0]["status"] == "active"
    watched.alert.assert_not_called()
    assert "listed none" in caplog.text


def test_a_response_with_no_data_changes_nothing(watched):
    response = MagicMock(status_code=200)
    response.json.return_value = {}
    watched.monkeypatch.setattr(keys.requests, "get", Mock(return_value=response))

    with pytest.raises(KeyError):
        job.check_keys()

    assert watched.store.keys[0]["status"] == "active"


def test_a_failed_email_about_a_disabled_key_is_tried_again(watched):
    watched.alert.return_value = False
    watched.monkeypatch.setattr(keys.requests, "get", listing({"hash": "hash-1", "disabled": True}))

    assert [job.check_keys(), job.check_keys()] == [1, 1]
    assert watched.alert.call_count == 2


def test_a_key_turned_back_on_becomes_active_again(watched):
    watched.store.keys[0]["status"] = "disabled"
    watched.monkeypatch.setattr(keys.requests, "get", listing({"hash": "hash-1", "disabled": False}))

    assert job.check_keys() == 0
    assert watched.store.keys[0]["status"] == "active"


def test_a_key_near_its_cap_takes_no_new_clients(watched):
    watched.monkeypatch.setattr(keys.requests, "get", listing(
        {"hash": "hash-1", "disabled": False, "limit": 25, "limit_remaining": 4}))

    job.check_keys()

    assert keys.key_for_company(2, SHARED) == "sk-client-2"


def test_a_failed_disable_call_does_not_stop_the_check(watched):
    watched.store.assigned.clear()
    watched.disable.side_effect = requests.ConnectionError()

    assert job.check_keys() == 0
    assert watched.store.keys[0]["status"] == "disabled"


def test_a_failed_alert_email_is_tried_again(watched):
    watched.alert.return_value = False
    watched.monkeypatch.setattr(keys.requests, "get", listing(
        {"hash": "hash-1", "disabled": False, "limit": 25, "limit_remaining": 4}))

    job.check_keys()
    job.check_keys()

    assert watched.alert.call_count == 2


def test_every_page_of_keys_is_read(watched):
    filler = [{"hash": "other-%d" % n, "disabled": False} for n in range(keys.PAGE_SIZE)]
    pages = [MagicMock(status_code=200), MagicMock(status_code=200)]
    pages[0].json.return_value = {"data": filler}
    pages[1].json.return_value = {"data": [{"hash": "hash-1", "disabled": False, "limit": 25}]}
    read = Mock(side_effect=pages)
    watched.monkeypatch.setattr(keys.requests, "get", read)

    assert job.check_keys() == 0
    assert read.call_args.kwargs["params"]["offset"] == keys.PAGE_SIZE


def test_a_key_is_disabled_once_its_last_client_has_left(watched):
    watched.store.assigned.clear()
    watched.monkeypatch.setattr(keys.requests, "get", listing())

    assert job.check_keys() == 0
    assert watched.disable.call_args.kwargs["json"] == {"disabled": True}
    assert watched.disable.call_args.args[0].endswith("/hash-1")
    assert watched.store.keys[0]["status"] == "disabled"
    watched.alert.assert_not_called()


def test_a_key_that_still_has_a_client_is_never_disabled(watched):
    watched.monkeypatch.setattr(keys.requests, "get", listing({"hash": "hash-1", "disabled": False, "limit": 25}))

    job.check_keys()

    watched.disable.assert_not_called()
    assert watched.store.keys[0]["status"] == "active"


def test_a_key_near_its_cap_warns_the_owner_once(watched):
    watched.monkeypatch.setattr(keys.requests, "get", listing(
        {"hash": "hash-1", "disabled": False, "limit": 25, "limit_remaining": 4, "usage_monthly": 21}))

    job.check_keys()
    job.check_keys()

    watched.alert.assert_called_once()


def test_a_healthy_key_raises_nothing_and_logs_its_usage(watched, caplog):
    watched.monkeypatch.setattr(keys.requests, "get", listing(
        {"hash": "hash-1", "disabled": False, "limit": 25, "limit_remaining": 20, "usage_monthly": 5}))

    with caplog.at_level(logging.INFO):
        assert job.check_keys() == 0

    watched.alert.assert_not_called()
    assert "usage_monthly=5" in caplog.text
    assert "sk-client" not in caplog.text


# The cap follows what the Clients on a key can pay for.

def key_usage(**fields):
    return listing({"hash": "hash-1", "disabled": False, "limit": 25, "limit_remaining": 20, **fields})


def rm(amount):
    return amount * 1_000_000


def test_the_cap_rises_with_the_credit_of_the_clients_on_the_key(watched):
    watched.store.credit[1] = rm(100)
    watched.monkeypatch.setattr(keys.requests, "get", key_usage())

    job.check_keys()

    assert watched.disable.call_args.kwargs["json"] == {"limit": 38}
    assert watched.disable.call_args.args[0].endswith("/hash-1")


def test_the_cap_never_drops_below_the_minimum(watched):
    watched.store.credit[1] = rm(1)
    watched.monkeypatch.setattr(keys.requests, "get", key_usage())

    job.check_keys()

    watched.disable.assert_not_called()


def test_spending_never_raises_the_cap(watched):
    """The cap comes from Client credit only, so a runaway cannot lift its own limit."""
    watched.monkeypatch.setattr(keys.requests, "get", key_usage(limit_remaining=1, usage_monthly=24))

    assert job.check_keys() == 1

    watched.disable.assert_not_called()
    watched.alert.assert_called_once()


def test_a_spent_key_recovers_while_its_clients_have_paid_for_more(watched):
    watched.store.credit[1] = rm(400)
    watched.monkeypatch.setattr(keys.requests, "get", key_usage(limit=100, limit_remaining=0, usage_monthly=100))

    assert job.check_keys() == 0

    assert watched.disable.call_args.kwargs["json"] == {"limit": 150}
    watched.alert.assert_not_called()


def test_a_raised_key_can_warn_again_the_same_day(watched):
    watched.monkeypatch.setattr(keys.requests, "get", key_usage(limit_remaining=1, usage_monthly=24))
    job.check_keys()
    watched.store.credit[1] = rm(1000)
    job.check_keys()
    watched.store.credit[1] = 0

    job.check_keys()

    assert watched.alert.call_count == 2


def test_a_key_with_no_cap_gets_one(watched):
    watched.monkeypatch.setattr(keys.requests, "get", key_usage(limit=None, limit_remaining=None))

    job.check_keys()

    assert watched.disable.call_args.kwargs["json"] == {"limit": 25}


def test_a_cap_is_never_set_at_or_below_what_is_spent(watched):
    watched.monkeypatch.setattr(keys.requests, "get", key_usage(limit=None, limit_remaining=None, usage_monthly=200))

    job.check_keys()

    watched.disable.assert_not_called()


def test_the_cap_does_not_fall_during_the_month(watched):
    watched.monkeypatch.setattr(job, "_is_start_of_month", lambda: False)
    watched.monkeypatch.setattr(keys.requests, "get", key_usage(limit=300, limit_remaining=290))

    job.check_keys()

    watched.disable.assert_not_called()


def test_the_cap_falls_in_the_first_hour_of_the_month(watched):
    watched.monkeypatch.setattr(job, "_is_start_of_month", lambda: True)
    watched.monkeypatch.setattr(keys.requests, "get", key_usage(limit=300, limit_remaining=300, usage_monthly=0))

    job.check_keys()

    assert watched.disable.call_args.kwargs["json"] == {"limit": 25}


@pytest.mark.parametrize("day, hour, expected", [(1, 0, True), (1, 1, False), (2, 0, False)])
def test_the_start_of_the_month_is_its_first_hour(monkeypatch, day, hour, expected):
    monkeypatch.setattr(job, "_now", lambda: datetime(2026, 12, day, hour, 30, tzinfo=timezone.utc))

    assert job._is_start_of_month() is expected


def test_the_month_starts_at_midnight_utc(monkeypatch):
    monkeypatch.setattr(job, "_now", lambda: datetime(2026, 12, 15, 9, 30, 5, 7, tzinfo=timezone.utc))

    assert job._month_start() == "2026-12-01T00:00:00+00:00"


def test_the_cap_never_falls_below_what_is_already_spent(watched):
    watched.monkeypatch.setattr(job, "_is_start_of_month", lambda: True)
    watched.monkeypatch.setattr(keys.requests, "get", key_usage(limit=300, limit_remaining=270, usage_monthly=30))

    job.check_keys()

    watched.disable.assert_not_called()


def test_a_failed_cap_change_does_not_stop_the_alerts(watched):
    watched.store.credit[1] = rm(1000)
    watched.disable.side_effect = requests.ConnectionError()
    watched.monkeypatch.setattr(keys.requests, "get", key_usage(limit_remaining=1, usage_monthly=24))

    assert job.check_keys() == 1

    watched.alert.assert_called_once()


def test_a_missing_exchange_rate_leaves_the_cap_alone(watched):
    watched.monkeypatch.setenv("AI_USD_TO_MYR_RATE_MICRO_MYR_PER_USD", "")
    watched.store.credit[1] = rm(1000)
    watched.monkeypatch.setattr(keys.requests, "get", key_usage())

    assert job.check_keys() == 0

    watched.disable.assert_not_called()


def ledger_query(*pages):
    ledger = MagicMock()
    query = ledger.select.return_value.in_.return_value.eq.return_value.gte.return_value.order.return_value
    query.range.return_value.execute.side_effect = [SimpleNamespace(data=page) for page in pages]
    return ledger, query


def credit_tables(monkeypatch, ledger):
    assignments, balances = MagicMock(), MagicMock()
    assignments.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"company_id": 1}, {"company_id": 2}])
    balances.select.return_value.in_.return_value.execute.return_value = SimpleNamespace(data=[
        {"included_balance_micro_myr": rm(5), "topup_balance_micro_myr": rm(1)},
        {"included_balance_micro_myr": rm(2), "topup_balance_micro_myr": 0},
    ])
    tables = {repository.ASSIGNMENTS_TABLE: assignments, repository.BALANCES_TABLE: balances,
              repository.LEDGER_TABLE: ledger}
    monkeypatch.setattr(repository, "supabase", MagicMock(table=Mock(side_effect=tables.get)))
    return balances


def test_month_credit_is_credit_left_plus_what_was_charged(monkeypatch):
    ledger, _query = ledger_query([{"customer_charge_micro_myr": rm(3)}, {"customer_charge_micro_myr": None}])
    balances = credit_tables(monkeypatch, ledger)

    assert repository.month_credit_micro_myr(9, "2026-12-01T00:00:00+00:00") == rm(11)
    assert balances.select.return_value.in_.call_args.args == ("company_id", [1, 2])
    assert ledger.select.return_value.in_.return_value.eq.call_args.args == ("transaction_type", "usage_debit")


def test_every_page_of_the_ledger_is_counted(monkeypatch):
    full_page = [{"customer_charge_micro_myr": 1}] * repository.LEDGER_PAGE_SIZE
    ledger, query = ledger_query(full_page, [{"customer_charge_micro_myr": 1}])
    credit_tables(monkeypatch, ledger)

    assert repository.month_credit_micro_myr(9, "2026-12-01T00:00:00+00:00") == rm(8) + repository.LEDGER_PAGE_SIZE + 1
    assert query.range.call_args.args == (repository.LEDGER_PAGE_SIZE, repository.LEDGER_PAGE_SIZE * 2 - 1)


def test_month_credit_on_an_empty_key_is_zero(monkeypatch):
    assignments = MagicMock()
    assignments.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[])
    monkeypatch.setattr(repository, "supabase", MagicMock(table=Mock(return_value=assignments)))

    assert repository.month_credit_micro_myr(9, "2026-12-01T00:00:00+00:00") == 0


def test_the_owner_alert_goes_to_the_owner_with_only_the_label(monkeypatch):
    monkeypatch.setenv("SMTP_SENDER_EMAIL", "noreply@example.test")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "synthetic-password")
    monkeypatch.setenv("PLATFORM_ALERT_EMAIL", "owner@example.test")
    smtp = Mock()
    monkeypatch.setattr(email_service.smtplib, "SMTP", Mock(return_value=smtp))

    assert email_service.send_openrouter_key_alert_email(label="omnexa-pool-1", problem="near its cap") is True
    assert smtp.sendmail.call_args.args[1] == "owner@example.test"
    assert "omnexa-pool-1" in smtp.sendmail.call_args.args[2]


@pytest.mark.parametrize("embedded, clients", [([{"count": 3}], 3), ([{"count": 0}], 0), ([], 0)])
def test_the_client_count_comes_from_the_embedded_count(monkeypatch, embedded, clients):
    query = MagicMock()
    query.select.return_value.eq.return_value.order.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": 1, "key_hash": "h", repository.ASSIGNMENTS_TABLE: embedded}])
    monkeypatch.setattr(repository, "supabase", MagicMock(table=Mock(return_value=query)))

    assert repository.list_keys("active") == [{"id": 1, "key_hash": "h", "clients": clients}]


# The balance alert

def credit_response(body):
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": body}
    return Mock(return_value=response)


def test_the_balance_alert_reads_the_whole_account(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_API_KEY", "synthetic-management-key")
    read = credit_response({"total_credits": 100, "total_usage": 92.5})
    monkeypatch.setattr(openrouter_service.requests, "get", read)

    status = openrouter_service.get_key_status()

    assert read.call_args.args[0] == openrouter_service.OPENROUTER_CREDITS_URL
    assert read.call_args.kwargs["headers"]["Authorization"] == "Bearer synthetic-management-key"
    assert status["limit_remaining"] == 7.5


def test_a_low_account_balance_raises_the_alert(monkeypatch, caplog):
    from app.jobs import check_ai_provider_balance as balance_job

    monkeypatch.setenv("OPENROUTER_MANAGEMENT_API_KEY", "synthetic-management-key")
    monkeypatch.setattr(openrouter_service.requests, "get",
                        credit_response({"total_credits": 100, "total_usage": 97}))

    with caplog.at_level(logging.ERROR):
        assert balance_job.check_balance() == 1

    assert caplog.records


def test_an_unreadable_credit_figure_is_unknown_not_empty(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_API_KEY", "synthetic-management-key")
    monkeypatch.setattr(openrouter_service.requests, "get", credit_response({"total_credits": None}))

    assert openrouter_service.get_key_status() is None


def test_without_the_management_key_the_balance_alert_reads_the_shared_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MANAGEMENT_API_KEY", raising=False)
    monkeypatch.setattr(openrouter_service, "OPENROUTER_API_KEY", SHARED)
    read = credit_response({"limit_remaining": 42.0})
    monkeypatch.setattr(openrouter_service.requests, "get", read)

    assert openrouter_service.get_key_status() == {"limit_remaining": 42.0}
    assert read.call_args.args[0] == openrouter_service.OPENROUTER_KEY_URL


# Release safety

def test_new_modules_ship_in_the_image():
    allowlist = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for module in ("app/database/openrouter_key_repository.py", "app/services/openrouter_key_service.py",
                   "app/jobs/check_openrouter_keys.py"):
        assert "!" + module in allowlist


def test_the_key_tables_are_closed_to_clients():
    sql = (ROOT / "data" / "081_openrouter_client_keys.sql").read_text(encoding="utf-8")

    assert sql.count("ENABLE ROW LEVEL SECURITY") == 2
    assert "CREATE POLICY" not in sql
    assert "GRANT SELECT, INSERT, UPDATE ON public.openrouter_client_keys TO service_role;" in sql
    assert "GRANT SELECT, INSERT ON public.openrouter_key_assignments TO service_role;" in sql
    assert (ROOT / "data" / "081_openrouter_client_keys_rollback.sql").exists()
