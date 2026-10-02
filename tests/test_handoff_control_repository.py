"""HO-2 persistence: what storage is allowed to tell the domain.

Every test runs against a fake PostgREST client. Nothing here opens a
connection, and 060 is an unapplied draft, so a test that needed a real
database would be testing a table that does not exist yet.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.database import chat_history_repository
from app.database import handoff_control_repository as repo
from app.services import handoff_service


COMPANY_ID = 1
OTHER_COMPANY_ID = 2
CHATBOT_ID = 3
CONVERSATION_ID = 8


def _stored_row(**overrides):
    """A control row exactly as 060 stores it, timestamps included: the
    mapper must ignore the columns the domain has no field for."""
    row = {
        "conversation_id": CONVERSATION_ID,
        "company_id": COMPANY_ID,
        "chatbot_id": CHATBOT_ID,
        "handling_mode": "human_active",
        "resolution_status": "resolved",
        "assignee_user_id": 7,
        "episode_id": 2,
        "version": 5,
        "automation_epoch": 4,
        "source": "staff_takeover",
        "created_at": "2026-09-22T00:00:00+00:00",
        "updated_at": "2026-09-22T01:00:00+00:00",
    }
    row.update(overrides)
    return row


# ── fake client ───────────────────────────────────────────────────────────

class _Query:
    """Enough of the PostgREST builder for the reads these modules make."""

    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self._rows = [row for row in self._rows if row.get(column) == value]
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, count):
        self._rows = self._rows[:count]
        return self

    def execute(self):
        return SimpleNamespace(data=list(self._rows))


class FakeSupabase:
    def __init__(self, **tables):
        self.tables = {
            repo.TABLE_NAME: [],
            "conversations": [{"id": CONVERSATION_ID, "chatbot_id": CHATBOT_ID}],
            "messages": [],
        }
        self.tables.update(tables)
        self.read_error = None
        self.rpc_calls = []
        self.rpc_result = {"won": True}

    def table(self, name):
        if self.read_error is not None:
            raise self.read_error
        return _Query(self.tables[name])

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        if isinstance(self.rpc_result, Exception):
            raise self.rpc_result
        # A losing call must not touch the store; a winning one is not
        # replayed into it either, because the function -- not this fake --
        # is what these tests are pinning the contract against.
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.rpc_result))


@pytest.fixture
def fake(monkeypatch):
    client = FakeSupabase()
    monkeypatch.setattr(repo, "supabase", client)
    monkeypatch.setattr(
        repo, "get_bot_by_id",
        lambda bot_id: {"id": bot_id, "company_id": COMPANY_ID} if bot_id == CHATBOT_ID else None,
    )
    return client


# ── load ──────────────────────────────────────────────────────────────────

def test_a_conversation_that_was_never_escalated_reads_as_the_initial_control(fake):
    # No row is not "unknown": it is the state the domain names, or the very
    # first escalation could never be written.
    control = repo.load(CONVERSATION_ID)

    assert control == handoff_service.initial_control(COMPANY_ID, CHATBOT_ID, CONVERSATION_ID)
    assert control.mode == handoff_service.AI_ACTIVE
    assert control.resolution == handoff_service.OPEN
    assert control.version == 0
    assert control.assignee_user_id is None


def test_a_stored_row_maps_onto_every_field_of_the_control(fake):
    fake.tables[repo.TABLE_NAME] = [_stored_row()]

    # Construction validates the types: a float counter or an unknown mode
    # raises inside ConversationControl rather than reaching the domain.
    assert repo.load(CONVERSATION_ID) == handoff_service.ConversationControl(
        company_id=COMPANY_ID,
        chatbot_id=CHATBOT_ID,
        conversation_id=CONVERSATION_ID,
        mode=handoff_service.HUMAN_ACTIVE,
        resolution=handoff_service.RESOLVED,
        assignee_user_id=7,
        episode_id=2,
        version=5,
        automation_epoch=4,
        source=handoff_service.SOURCE_STAFF_TAKEOVER,
    )


def test_a_read_failure_is_unreadable_and_the_gate_refuses(fake):
    fake.read_error = RuntimeError("PostgREST is unreachable")

    control = repo.load(CONVERSATION_ID)
    assert control is None

    # The point of returning None rather than a default: the send boundary
    # must deny, not wave the model through on a guess.
    admission = handoff_service.automation_admission(control, epoch_at_dispatch=0)
    assert admission.allowed is False
    assert admission.code == handoff_service.ADMISSION_UNREADABLE


def test_a_row_the_domain_rejects_is_unreadable_not_a_default(fake):
    fake.tables[repo.TABLE_NAME] = [_stored_row(handling_mode="paused")]

    assert repo.load(CONVERSATION_ID) is None


def test_a_conversation_with_no_resolvable_owner_is_unreadable(fake):
    fake.tables["conversations"] = []

    assert repo.load(CONVERSATION_ID) is None


# ── compare_and_set ───────────────────────────────────────────────────────

def _loser():
    stored = repo._to_control(_stored_row())
    return stored, replace(stored, resolution=handoff_service.OPEN, version=stored.version + 1)


def test_a_win_sends_the_version_it_read_never_the_one_it_wants(fake):
    stored, updated = _loser()
    fake.rpc_result = {"won": True, "control": _stored_row(resolution_status="open", version=6)}

    assert repo.compare_and_set(stored.version, updated) is True

    name, params = fake.rpc_calls[0]
    assert name == "handoff_control_compare_and_set"
    assert params == {
        "p_conversation_id": CONVERSATION_ID,
        "p_company_id": COMPANY_ID,
        "p_chatbot_id": CHATBOT_ID,
        # 5, not updated.version (6): the function derives the new version.
        "p_expected_version": 5,
        "p_handling_mode": "human_active",
        "p_resolution_status": "open",
        "p_assignee_user_id": 7,
        "p_episode_id": 2,
        "p_automation_epoch": 4,
        "p_source": "staff_takeover",
    }


def test_a_version_conflict_loses_and_leaves_the_store_alone(fake):
    stored, updated = _loser()
    fake.tables[repo.TABLE_NAME] = [_stored_row()]
    fake.rpc_result = {"won": False, "reason": "VERSION_CONFLICT", "control": _stored_row()}

    assert repo.compare_and_set(stored.version, updated) is False
    assert repo.load(CONVERSATION_ID) == stored


def test_a_cross_tenant_write_loses(fake):
    stored, updated = _loser()
    fake.rpc_result = {"won": False, "reason": "CROSS_TENANT", "control": None}

    assert repo.compare_and_set(stored.version, updated) is False


@pytest.mark.parametrize("payload", [
    None,
    [],
    [{"won": True}],
    {},
    {"control": None},
    {"reason": "VERSION_CONFLICT"},
    {"won": "true"},
    {"won": 1},
    "won",
], ids=["null", "empty-list", "wrapped-in-list", "empty-dict", "null-control",
        "no-won-key", "won-as-string", "won-as-int", "not-json"])
def test_a_malformed_outcome_is_never_read_as_a_win(fake, payload):
    stored, updated = _loser()
    fake.rpc_result = payload

    assert repo.compare_and_set(stored.version, updated) is False


@pytest.mark.parametrize("error", [
    # A refusal the function decides is a payload; a CHECK violation is not.
    # 23514 is how an unknown mode, a negative counter or an assignee on a
    # conversation no human holds comes back, and the caller must still see
    # a plain refusal rather than an exception past its conflict branches.
    RuntimeError('{"code":"23514","message":'
                 '"new row violates check constraint '
                 '\\"handoff_control_assignee_requires_human\\""}'),
    RuntimeError("the function is not deployed"),
], ids=["check-violation", "transport-failure"])
def test_a_raising_call_loses_rather_than_escaping(fake, error):
    stored, updated = _loser()
    fake.rpc_result = error

    assert repo.compare_and_set(stored.version, updated) is False


# ── the module is the repository the service asks for ─────────────────────

def test_the_service_drives_a_first_escalation_straight_through_this_module(fake):
    fake.rpc_result = {"won": True, "control": _stored_row(
        handling_mode="waiting_human", resolution_status="open",
        assignee_user_id=None, episode_id=1, version=1, source="customer_request")}

    result = handoff_service.HandoffService(repo).request_human(
        CONVERSATION_ID, company_id=COMPANY_ID)

    assert result.ok is True
    assert result.code == handoff_service.HUMAN_REQUESTED
    _, params = fake.rpc_calls[0]
    # Expected version 0 is the function's insert-if-absent sentinel, which
    # is exactly what a conversation with no row must send.
    assert params["p_expected_version"] == 0
    assert params["p_handling_mode"] == "waiting_human"
    assert params["p_assignee_user_id"] is None
    assert params["p_source"] == "customer_request"


def test_a_first_escalation_claimed_by_the_wrong_tenant_never_reaches_the_write(fake):
    # The command with no staff actor is the one that used to skip the
    # ownership check entirely. The owner load() resolved from storage --
    # not a company_id off the caller -- is what has to be believed.
    stored = _stored_row(handling_mode="ai_active", resolution_status="open",
                         assignee_user_id=None, version=3)
    fake.tables[repo.TABLE_NAME] = [stored]

    result = handoff_service.HandoffService(repo).request_human(
        CONVERSATION_ID, company_id=OTHER_COMPANY_ID)

    assert result.ok is False
    assert result.code == handoff_service.CROSS_TENANT
    # The refusal carries no control: it must not disclose company A's mode,
    # assignee or version to company B.
    assert result.control is None
    # Refused before the RPC, and the row is exactly as it was.
    assert fake.rpc_calls == []
    assert repo.load(CONVERSATION_ID) == repo._to_control(stored)


# ── transcript authorship ─────────────────────────────────────────────────

def test_a_staff_reply_is_replayed_to_the_model_as_the_assistant(monkeypatch):
    # Newest first, the way the query orders them; the repository reverses.
    client = FakeSupabase(messages=[
        {"conversation_id": CONVERSATION_ID, "sender_type": "human",
         "message_text": "I'll refund you", "created_at": "3"},
        {"conversation_id": CONVERSATION_ID, "sender_type": "bot",
         "message_text": "One moment", "created_at": "2"},
        {"conversation_id": CONVERSATION_ID, "sender_type": "customer",
         "message_text": "I want a refund", "created_at": "1"},
    ])
    monkeypatch.setattr(chat_history_repository, "supabase", client)

    history = chat_history_repository.get_recent_chat_history(CONVERSATION_ID)

    assert [turn["role"] for turn in history] == ["user", "assistant", "assistant"]
    assert history[2]["content"] == "I'll refund you"
