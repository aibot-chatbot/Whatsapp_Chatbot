"""HO-2 staff API: the seven /handoff routes beside the three live ones.

Everything here runs against a fake repository and a fake PostgREST client.
060 is still an unapplied draft, so a test that needed a real database would
be testing tables that do not exist yet.

Two properties are worth more than the rest and are asserted repeatedly:

* with HANDOFF_CONTROL_ENABLED off (the default) the surface is dark AND no
  repository call is made at all; and
* the actor is the authenticated session, so a user_id, company_id or role in
  the request body changes nothing.
"""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import create_app
from app.routes import agent_routes
from app.services import handoff_service
from app.services.handoff_service import ConversationControl, HandoffService


COMPANY_ID = 42
OTHER_COMPANY_ID = 99
CHATBOT_ID = 3
CONVERSATION_ID = 8
STAFF_ID = 7
OTHER_STAFF_ID = 9

BASE = f"/api/conversations/{CONVERSATION_ID}/handoff"

# Every state-changing route, with a body that is valid apart from the thing
# each test is probing.
STATE_CHANGING = [
    ("claim", {}),
    ("assign", {"to_user_id": OTHER_STAFF_ID}),
    ("resolve", {}),
    ("reopen", {}),
    ("resume-ai", {}),
]

ALL_ROUTES = [
    ("POST", f"{BASE}/claim", {"chatbot_id": CHATBOT_ID, "expected_version": 3}),
    ("POST", f"{BASE}/assign", {"chatbot_id": CHATBOT_ID, "expected_version": 3, "to_user_id": OTHER_STAFF_ID}),
    ("POST", f"{BASE}/resolve", {"chatbot_id": CHATBOT_ID, "expected_version": 3}),
    ("POST", f"{BASE}/reopen", {"chatbot_id": CHATBOT_ID, "expected_version": 3}),
    ("POST", f"{BASE}/resume-ai", {"chatbot_id": CHATBOT_ID, "expected_version": 3}),
    ("POST", f"{BASE}/notes", {"chatbot_id": CHATBOT_ID, "text": "Customer sounds upset."}),
    ("GET", f"{BASE}/state?chatbot_id={CHATBOT_ID}", None),
]


# ── fixtures and fakes ────────────────────────────────────────────────────

def control(mode=handoff_service.AI_ACTIVE, *, resolution=handoff_service.OPEN,
            assignee=None, version=3, company_id=COMPANY_ID, epoch=0):
    return ConversationControl(
        company_id=company_id, chatbot_id=CHATBOT_ID, conversation_id=CONVERSATION_ID,
        mode=mode, resolution=resolution, assignee_user_id=assignee,
        episode_id=1, version=version, automation_epoch=epoch,
    )


def waiting(**kwargs):
    return control(handoff_service.WAITING_HUMAN, **kwargs)


def held_by(user_id, **kwargs):
    return control(handoff_service.HUMAN_ACTIVE, assignee=user_id, **kwargs)


class FakeHandoffRepository:
    """The two-function protocol HandoffService asks for, and nothing else.

    `controls` is the sequence `load()` walks: one entry means every load sees
    the same state, two means the second load (the one `_commit` makes after a
    lost compare-and-set) sees the winner.
    """

    def __init__(self, *controls, wins=True):
        self._controls = list(controls) or [None]
        self.wins = wins
        self.loads = []
        self.writes = []

    def load(self, conversation_id):
        self.loads.append(conversation_id)
        return self._controls[min(len(self.loads) - 1, len(self._controls) - 1)]

    def compare_and_set(self, expected_version, new_control):
        self.writes.append((expected_version, new_control))
        return self.wins

    @property
    def touched(self):
        return bool(self.loads or self.writes)


class RacingRepository:
    """One stored row that two claimants really contend for."""

    def __init__(self, stored):
        self.stored = stored

    def load(self, conversation_id):
        return self.stored

    def compare_and_set(self, expected_version, new_control):
        if self.stored.version != expected_version:
            return False
        self.stored = new_control
        return True


class FakeSupabase:
    """Just enough PostgREST for the one RPC the notes route makes."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.payload))


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("HANDOFF_CONTROL_ENABLED", "true")


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv("HANDOFF_CONTROL_ENABLED", raising=False)


@pytest.fixture
def install(monkeypatch):
    """Put a fake repository behind both the service and the direct load()."""

    def _install(repository):
        monkeypatch.setattr(agent_routes, "handoff_control_repository", repository)
        monkeypatch.setattr(agent_routes, "_handoff", HandoffService(repository))
        return repository

    return _install


@pytest.fixture
def client(monkeypatch, handed_over_staff_chat):
    """A test client authenticated as one staff account."""

    def _client(role="member", user_id=STAFF_ID, company_id=COMPANY_ID):
        monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode",
                            lambda *a, **k: {"user_id": user_id})
        monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _: {
            "id": user_id, "company_id": company_id, "role": role, "status": "active"})
        monkeypatch.setattr(agent_routes, "verify_chatbot_access",
                            lambda chatbot_id: {"id": chatbot_id, "company_id": company_id})
        app = create_app()
        app.config["TESTING"] = True
        return app.test_client()

    return _client


@pytest.fixture
def no_outbound(monkeypatch):
    """Every way this module could reach a customer, wired to fail loudly."""
    mocks = {}
    for name in ("save_message", "_dispatch_conversation_reply", "send_telegram_message",
                 "send_whatsapp_message", "send_wasender_text_message"):
        mocks[name] = Mock(name=name)
        monkeypatch.setattr(agent_routes, name, mocks[name])
    return mocks


def call(test_client, method, path, body):
    headers = {"Authorization": "Bearer synthetic"}
    if method == "GET":
        return test_client.get(path, headers=headers)
    return test_client.post(path, headers=headers, json=body)


# ── 1. the flag is the whole gate ─────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", ALL_ROUTES)
def test_flag_off_by_default_answers_503_and_reads_nothing(flag_off, client, install, method, path, body):
    repository = install(FakeHandoffRepository(held_by(STAFF_ID)))
    response = call(client(), method, path, body)
    assert response.status_code == 503
    assert response.get_json()["code"] == "HANDOFF_CONTROL_DISABLED"
    # The point of a dark surface: not one row of the unapplied 060 is read.
    assert repository.touched is False


# ── 2. happy path per route ───────────────────────────────────────────────

def test_claim_takes_an_unclaimed_escalation(flag_on, client, install):
    install(FakeHandoffRepository(waiting()))
    response = call(client(), "POST", f"{BASE}/claim", {"chatbot_id": CHATBOT_ID, "expected_version": 3})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == handoff_service.CLAIMED
    assert payload["data"]["control"] == {
        "conversation_id": CONVERSATION_ID, "chatbot_id": CHATBOT_ID,
        "mode": handoff_service.HUMAN_ACTIVE, "resolution": handoff_service.OPEN,
        "assignee_user_id": STAFF_ID, "episode_id": 1, "version": 4,
        "automation_epoch": 0, "source": None,
    }


def test_assign_hands_the_conversation_to_a_colleague(flag_on, client, install):
    install(FakeHandoffRepository(held_by(STAFF_ID)))
    response = call(client(), "POST", f"{BASE}/assign",
                    {"chatbot_id": CHATBOT_ID, "expected_version": 3, "to_user_id": OTHER_STAFF_ID})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == handoff_service.ASSIGNED
    assert payload["data"]["control"]["assignee_user_id"] == OTHER_STAFF_ID
    assert payload["data"]["control"]["version"] == 4


def test_resolve_finishes_the_work_without_resuming_the_model(flag_on, client, install):
    install(FakeHandoffRepository(held_by(STAFF_ID)))
    response = call(client(), "POST", f"{BASE}/resolve", {"chatbot_id": CHATBOT_ID, "expected_version": 3})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == handoff_service.CONVERSATION_RESOLVED
    assert payload["data"]["control"]["resolution"] == handoff_service.RESOLVED
    # Resolution is not a mode change: the human still holds the conversation.
    assert payload["data"]["control"]["mode"] == handoff_service.HUMAN_ACTIVE


def test_reopen_returns_a_resolved_conversation_to_open(flag_on, client, install):
    install(FakeHandoffRepository(held_by(STAFF_ID, resolution=handoff_service.RESOLVED)))
    response = call(client(), "POST", f"{BASE}/reopen", {"chatbot_id": CHATBOT_ID, "expected_version": 3})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == handoff_service.CONVERSATION_REOPENED
    assert payload["data"]["control"]["resolution"] == handoff_service.OPEN
    assert payload["data"]["control"]["assignee_user_id"] == STAFF_ID


def test_resume_ai_hands_back_and_moves_the_epoch(flag_on, client, install):
    install(FakeHandoffRepository(held_by(STAFF_ID, epoch=4)))
    response = call(client(), "POST", f"{BASE}/resume-ai", {"chatbot_id": CHATBOT_ID, "expected_version": 3})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == handoff_service.AI_RESUMED
    assert payload["data"]["control"]["mode"] == handoff_service.AI_ACTIVE
    assert payload["data"]["control"]["assignee_user_id"] is None
    # Anything queued before the handback is now stale.
    assert payload["data"]["control"]["automation_epoch"] == 5


def test_state_reads_the_current_control(flag_on, client, install):
    install(FakeHandoffRepository(held_by(OTHER_STAFF_ID, version=11)))
    response = call(client(), "GET", f"{BASE}/state?chatbot_id={CHATBOT_ID}", None)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == "CONTROL_READ"
    assert payload["data"]["control"]["assignee_user_id"] == OTHER_STAFF_ID
    assert payload["data"]["control"]["version"] == 11


# ── 3. expected_version is required ───────────────────────────────────────

@pytest.mark.parametrize("route,extra", STATE_CHANGING)
def test_a_missing_expected_version_is_a_400_not_a_blind_write(flag_on, client, install, route, extra):
    repository = install(FakeHandoffRepository(held_by(STAFF_ID)))
    response = call(client(), "POST", f"{BASE}/{route}", {"chatbot_id": CHATBOT_ID, **extra})
    assert response.status_code == 400
    assert response.get_json()["code"] == "EXPECTED_VERSION_REQUIRED"
    assert repository.writes == []


@pytest.mark.parametrize("value", ["3", None, -1, True, 3.0])
def test_a_non_version_is_refused_rather_than_coerced(flag_on, client, install, value):
    repository = install(FakeHandoffRepository(waiting()))
    response = call(client(), "POST", f"{BASE}/claim",
                    {"chatbot_id": CHATBOT_ID, "expected_version": value})
    assert response.status_code == 400
    assert repository.writes == []


# ── 4. concurrency: the loser learns who won ──────────────────────────────

def test_two_claims_race_and_the_loser_sees_the_winner(flag_on, client, install):
    install(RacingRepository(waiting()))
    body = {"chatbot_id": CHATBOT_ID, "expected_version": 3}

    won = call(client(user_id=STAFF_ID), "POST", f"{BASE}/claim", body)
    assert won.status_code == 200
    assert won.get_json()["data"]["control"]["assignee_user_id"] == STAFF_ID

    # Same expected_version, read before the winner committed.
    lost = call(client(user_id=OTHER_STAFF_ID), "POST", f"{BASE}/claim", body)
    assert lost.status_code == 409
    payload = lost.get_json()
    assert payload["code"] == handoff_service.CONFLICT
    assert payload["data"]["control"]["assignee_user_id"] == STAFF_ID


def test_a_lost_compare_and_set_also_returns_the_winner(flag_on, client, install):
    # The other kind of race: the version still matched at read time and the
    # conditional write is what lost.
    repository = install(FakeHandoffRepository(
        waiting(), waiting(), held_by(OTHER_STAFF_ID, version=4), wins=False))
    response = call(client(), "POST", f"{BASE}/claim", {"chatbot_id": CHATBOT_ID, "expected_version": 3})
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["code"] == handoff_service.CONFLICT
    assert payload["data"]["control"]["assignee_user_id"] == OTHER_STAFF_ID
    assert len(repository.writes) == 1


def test_claiming_a_conversation_nobody_asked_about_is_409(flag_on, client, install):
    install(FakeHandoffRepository(control()))
    response = call(client(), "POST", f"{BASE}/claim", {"chatbot_id": CHATBOT_ID, "expected_version": 3})
    assert response.status_code == 409
    assert response.get_json()["code"] == handoff_service.INVALID_STATE


# ── 5. cross tenant ───────────────────────────────────────────────────────

@pytest.mark.parametrize("route,extra", STATE_CHANGING)
def test_another_companys_conversation_is_403_and_discloses_nothing(flag_on, client, install, route, extra):
    repository = install(FakeHandoffRepository(held_by(OTHER_STAFF_ID, company_id=OTHER_COMPANY_ID)))
    response = call(client(), "POST", f"{BASE}/{route}",
                    {"chatbot_id": CHATBOT_ID, "expected_version": 3, **extra})
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["code"] == handoff_service.CROSS_TENANT
    # A refusal that echoed the control would leak the other tenant's assignee.
    assert payload["data"]["control"] is None
    assert repository.writes == []


def test_state_of_another_companys_conversation_is_403(flag_on, client, install):
    install(FakeHandoffRepository(held_by(OTHER_STAFF_ID, company_id=OTHER_COMPANY_ID)))
    response = call(client(), "GET", f"{BASE}/state?chatbot_id={CHATBOT_ID}", None)
    assert response.status_code == 403
    assert response.get_json()["code"] == handoff_service.CROSS_TENANT
    assert response.get_json()["data"]["control"] is None


@pytest.mark.parametrize("method,path,body", ALL_ROUTES)
def test_another_chatbots_conversation_is_403_without_reads_or_writes_leaking(
        flag_on, client, install, monkeypatch, method, path, body):
    repository = install(FakeHandoffRepository(
        replace(held_by(STAFF_ID), chatbot_id=CHATBOT_ID + 1)))
    fake_db = FakeSupabase({"created": True, "note": {"id": 5}})
    monkeypatch.setattr(agent_routes, "supabase", fake_db)

    response = call(client(), method, path, body)

    assert response.status_code == 403
    assert response.get_json()["code"] == "CHATBOT_MISMATCH"
    assert response.get_json()["data"]["control"] is None
    assert repository.writes == []
    assert fake_db.calls == []


@pytest.mark.parametrize("method,path,body", ALL_ROUTES)
def test_a_chatbot_the_caller_does_not_own_is_403(flag_on, client, install, monkeypatch, method, path, body):
    repository = install(FakeHandoffRepository(held_by(STAFF_ID)))

    def denied(_chatbot_id):
        raise PermissionError("You do not have access to this chatbot.")

    test_client = client()
    monkeypatch.setattr(agent_routes, "verify_chatbot_access", denied)
    response = call(test_client, method, path, body)
    assert response.status_code == 403
    assert repository.touched is False


@pytest.mark.parametrize("method,path,body", ALL_ROUTES)
def test_a_missing_chatbot_id_is_400(flag_on, client, install, method, path, body):
    repository = install(FakeHandoffRepository(held_by(STAFF_ID)))
    stripped = None if body is None else {k: v for k, v in body.items() if k != "chatbot_id"}
    response = call(test_client := client(), method, path.split("?")[0], stripped)
    assert response.status_code == 400
    assert response.get_json()["code"] == "CHATBOT_ID_REQUIRED"
    assert repository.touched is False


# ── 6. assignee vs supervisor ─────────────────────────────────────────────

def test_a_non_assignee_may_not_act_on_someone_elses_conversation(flag_on, client, install):
    repository = install(FakeHandoffRepository(held_by(OTHER_STAFF_ID)))
    response = call(client(role="member"), "POST", f"{BASE}/resolve",
                    {"chatbot_id": CHATBOT_ID, "expected_version": 3})
    assert response.status_code == 403
    assert response.get_json()["code"] == handoff_service.NOT_ASSIGNEE
    assert repository.writes == []


def test_a_member_cannot_grant_themselves_an_override(flag_on, client, install):
    repository = install(FakeHandoffRepository(held_by(OTHER_STAFF_ID)))
    response = call(client(role="member"), "POST", f"{BASE}/resolve",
                    {"chatbot_id": CHATBOT_ID, "expected_version": 3, "supervisor_override": True})
    assert response.status_code == 403
    assert response.get_json()["code"] == handoff_service.NOT_SUPERVISOR
    assert repository.writes == []


def test_a_supervisor_override_succeeds_and_says_so(flag_on, client, install):
    install(FakeHandoffRepository(held_by(OTHER_STAFF_ID)))
    response = call(client(role="admin"), "POST", f"{BASE}/resolve",
                    {"chatbot_id": CHATBOT_ID, "expected_version": 3, "supervisor_override": True})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == handoff_service.CONVERSATION_RESOLVED
    # The override is recorded in the answer, not only in the domain result.
    assert payload["data"]["override"] is True


def test_a_supervisor_without_the_flag_is_still_not_the_assignee(flag_on, client, install):
    install(FakeHandoffRepository(held_by(OTHER_STAFF_ID)))
    response = call(client(role="admin"), "POST", f"{BASE}/resume-ai",
                    {"chatbot_id": CHATBOT_ID, "expected_version": 3})
    assert response.status_code == 403
    assert response.get_json()["code"] == handoff_service.NOT_ASSIGNEE


@pytest.mark.parametrize("value", ["true", 1, "yes"])
def test_a_truthy_override_is_not_an_override(flag_on, client, install, value):
    install(FakeHandoffRepository(held_by(OTHER_STAFF_ID)))
    response = call(client(role="admin"), "POST", f"{BASE}/resolve",
                    {"chatbot_id": CHATBOT_ID, "expected_version": 3, "supervisor_override": value})
    assert response.status_code == 403
    assert response.get_json()["code"] == handoff_service.NOT_ASSIGNEE


# ── 7. unreadable control never defaults open ─────────────────────────────

@pytest.mark.parametrize("method,path,body", ALL_ROUTES)
def test_an_unreadable_control_is_503_on_every_route(flag_on, client, install, method, path, body):
    repository = install(FakeHandoffRepository(None))
    response = call(client(), method, path, body)
    assert response.status_code == 503
    assert response.get_json()["code"] == handoff_service.CONTROL_UNREADABLE
    assert repository.writes == []


# ── 8. the actor comes from the session, never the body ───────────────────

def test_identity_fields_in_the_body_are_ignored(flag_on, client, install):
    repository = install(FakeHandoffRepository(waiting()))
    response = call(client(role="member", user_id=STAFF_ID), "POST", f"{BASE}/claim", {
        "chatbot_id": CHATBOT_ID, "expected_version": 3,
        "user_id": OTHER_STAFF_ID, "company_id": OTHER_COMPANY_ID, "role": "owner",
    })
    assert response.status_code == 200
    # The claim landed on the authenticated session, not on the body's user_id.
    assert response.get_json()["data"]["control"]["assignee_user_id"] == STAFF_ID
    _, written = repository.writes[0]
    assert written.assignee_user_id == STAFF_ID
    assert written.company_id == COMPANY_ID


def test_a_body_company_id_cannot_reach_another_tenant(flag_on, client, install):
    install(FakeHandoffRepository(held_by(OTHER_STAFF_ID, company_id=OTHER_COMPANY_ID)))
    response = call(client(), "POST", f"{BASE}/claim", {
        "chatbot_id": CHATBOT_ID, "expected_version": 3, "company_id": OTHER_COMPANY_ID,
    })
    assert response.status_code == 403
    assert response.get_json()["code"] == handoff_service.CROSS_TENANT


def test_a_body_role_cannot_buy_a_supervisor_override(flag_on, client, install):
    install(FakeHandoffRepository(held_by(OTHER_STAFF_ID)))
    response = call(client(role="member"), "POST", f"{BASE}/resolve", {
        "chatbot_id": CHATBOT_ID, "expected_version": 3,
        "supervisor_override": True, "role": "admin",
    })
    assert response.status_code == 403
    assert response.get_json()["code"] == handoff_service.NOT_SUPERVISOR


# ── 9. a note is stored and never sent ────────────────────────────────────

def test_a_note_is_stored_and_reaches_no_customer(flag_on, client, install, no_outbound, monkeypatch):
    install(FakeHandoffRepository(held_by(OTHER_STAFF_ID)))
    stored = {"id": 5, "conversation_id": CONVERSATION_ID, "company_id": COMPANY_ID,
              "author_user_id": STAFF_ID, "note_text": "Customer sounds upset."}
    fake_db = FakeSupabase({"created": True, "note": stored})
    monkeypatch.setattr(agent_routes, "supabase", fake_db)

    response = call(client(role="member"), "POST", f"{BASE}/notes",
                    {"chatbot_id": CHATBOT_ID, "text": "Customer sounds upset."})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["code"] == handoff_service.NOTE_INTERNAL_ONLY
    assert payload["data"]["note"] == stored

    # Written through 060's function with the session's author, never the body.
    name, params = fake_db.calls[0]
    assert name == "create_conversation_internal_note"
    assert params == {
        "p_conversation_id": CONVERSATION_ID, "p_chatbot_id": CHATBOT_ID,
        "p_author_user_id": STAFF_ID, "p_note_text": "Customer sounds upset.",
    }

    # The thing that makes it internal: no transcript row, no provider call.
    for name, mock in no_outbound.items():
        assert mock.call_count == 0, f"{name} was called for an internal note"


def test_an_empty_note_is_refused_before_it_is_written(flag_on, client, install, no_outbound, monkeypatch):
    install(FakeHandoffRepository(held_by(STAFF_ID)))
    fake_db = FakeSupabase({"created": True})
    monkeypatch.setattr(agent_routes, "supabase", fake_db)
    response = call(client(), "POST", f"{BASE}/notes", {"chatbot_id": CHATBOT_ID, "text": "   "})
    assert response.status_code == 400
    assert response.get_json()["code"] == handoff_service.NOTE_EMPTY
    assert fake_db.calls == []
    assert no_outbound["save_message"].call_count == 0


def test_a_note_the_function_refuses_is_not_reported_as_written(flag_on, client, install, monkeypatch):
    install(FakeHandoffRepository(held_by(STAFF_ID)))
    monkeypatch.setattr(agent_routes, "supabase",
                        FakeSupabase({"created": False, "reason": handoff_service.CROSS_TENANT}))
    response = call(client(), "POST", f"{BASE}/notes", {"chatbot_id": CHATBOT_ID, "text": "Hello"})
    assert response.status_code == 403
    assert response.get_json()["code"] == handoff_service.CROSS_TENANT


def test_an_unrecognised_note_payload_is_not_a_success(flag_on, client, install, monkeypatch):
    install(FakeHandoffRepository(held_by(STAFF_ID)))
    monkeypatch.setattr(agent_routes, "supabase", FakeSupabase(None))
    response = call(client(), "POST", f"{BASE}/notes", {"chatbot_id": CHATBOT_ID, "text": "Hello"})
    assert response.status_code == 503
    assert response.get_json()["code"] == "NOTE_UNWRITABLE"


# ── 10. the three live routes are untouched ───────────────────────────────

def test_listing_escalations_is_unchanged_with_the_flag_on(flag_on, client, monkeypatch):
    escalations = [{"id": 1, "conversation_id": CONVERSATION_ID, "status": "detected"}]
    listed = Mock(return_value=escalations)
    monkeypatch.setattr(agent_routes, "get_pending_escalations", listed)
    response = client(role="member").get(f"/api/agent/escalations?chatbot_id={CHATBOT_ID}",
                                         headers={"Authorization": "Bearer synthetic"})
    assert response.status_code == 200
    assert response.get_json()["data"] == escalations
    listed.assert_called_once_with(CHATBOT_ID, COMPANY_ID)


def test_resolve_escalation_still_refuses_a_member(flag_on, client):
    response = client(role="member").post("/api/agent/escalations/10/resolve",
                                          headers={"Authorization": "Bearer synthetic"},
                                          json={"chatbot_id": CHATBOT_ID})
    assert response.status_code == 403


def test_resolve_escalation_still_reports_its_own_shape(flag_on, client, monkeypatch):
    monkeypatch.setattr(agent_routes, "resolve_escalation",
                        Mock(return_value=({"id": 10, "conversation_id": CONVERSATION_ID}, True)))
    monkeypatch.setattr(agent_routes, "is_conversation_escalated", Mock(return_value=False))
    monkeypatch.setattr(agent_routes, "get_conversation_by_id_and_chatbot",
                        Mock(return_value={"id": CONVERSATION_ID, "source_channel": "web"}))
    response = client(role="admin").post("/api/agent/escalations/10/resolve",
                                         headers={"Authorization": "Bearer synthetic"},
                                         json={"chatbot_id": CHATBOT_ID})
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["ai_resumed"] is True
    assert data["handoff_state"] == "ai"
    assert data["notification_status"] == "not_sent"


def test_agent_reply_still_sends_then_persists(flag_on, client, monkeypatch):
    dispatch = Mock()
    save = Mock()
    monkeypatch.setattr(agent_routes, "_dispatch_conversation_reply", dispatch)
    monkeypatch.setattr(agent_routes, "save_message", save)
    monkeypatch.setattr(agent_routes, "get_conversation_by_id_and_chatbot",
                        Mock(return_value={"id": CONVERSATION_ID, "source_channel": "telegram"}))
    response = client(role="member").post(
        f"/api/conversations/{CONVERSATION_ID}/agent-reply",
        headers={"Authorization": "Bearer synthetic"},
        json={"chatbot_id": CHATBOT_ID, "text": "On my way."})
    assert response.status_code == 200
    assert response.get_json()["data"]["delivery_status"] == "sent"
    dispatch.assert_called_once()
    save.assert_called_once()


def test_agent_reply_still_needs_chatbot_id_and_text(flag_on, client):
    response = client().post(f"/api/conversations/{CONVERSATION_ID}/agent-reply",
                             headers={"Authorization": "Bearer synthetic"},
                             json={"chatbot_id": CHATBOT_ID})
    assert response.status_code == 400
