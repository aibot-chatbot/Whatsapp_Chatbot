"""HTTP contract of self-service workspace deletion under /api/user/account-deletion.

Real JWTs and the real token_required decorator are used (no mocked decode), so
the session-death test proves what the auth layer actually does after the row
is gone. The service's collaborators are replaced; no Supabase, no email.
"""

import datetime
from unittest.mock import patch

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from app.rate_limit import limiter
from app.routes.user_routes import user_bp
from app.services import account_deletion_service as svc
from app.utils.auth_token import create_auth_token

pytestmark = pytest.mark.real_auth_token

BASE = "/api/user/account-deletion"
NOW = datetime.datetime(2026, 10, 17, 9, 0, 0, tzinfo=datetime.timezone.utc)
PASSWORD_HASH = generate_password_hash("Password1!")


def make_user(user_id, role):
    return {
        "id": user_id, "company_id": 42, "full_name": f"User {user_id}",
        "email": f"user{user_id}@example.test", "role": role, "status": "active",
        "is_verified": True, "password_hash": PASSWORD_HASH,
    }


class World:
    """A tiny in-memory database behind the repository seams."""

    def __init__(self):
        self.issued = {7: make_user(7, "admin"), 8: make_user(8, "member")}
        self.users = dict(self.issued)
        self.blockers = {}            # user_id -> blocker code
        self.codes = {}
        self.sent = []
        self.rpc_calls = []
        self.email_ok = True
        self.deleted_company = False

    def auth(self, user_id=7):
        """Bearer header for a user as they were when they signed in."""
        return {"Authorization": f"Bearer {create_auth_token(self.issued[user_id])}"}

    def blocker(self, company_id, user_id):
        return self.blockers.get(user_id)

    def upsert(self, user_id, code_hash, expires_at):
        self.codes[user_id] = {"user_id": user_id, "code_hash": code_hash, "expires_at": expires_at, "attempts": 0}

    def rpc(self, company_id, user_id):
        self.rpc_calls.append((company_id, user_id))
        if self.blockers.get(user_id):
            return {"status": "error", "code": self.blockers[user_id], "message": "x"}
        # What the database does: the company, every user and the codes go.
        self.deleted_company = True
        self.users = {uid: u for uid, u in self.users.items() if u["company_id"] != company_id}
        self.codes = {}
        return {"status": "success", "code": "deleted", "message": "ok", "deleted_counts": {"users": 2}}


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setenv("JWT_SECRET", "route-test-secret-for-account-deletion-0123456789")
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda uid: w.users.get(uid))
    monkeypatch.setattr("app.routes.user_routes.get_user_by_id", lambda uid: w.users.get(uid))
    monkeypatch.setattr(svc, "get_deletion_blocker", w.blocker)
    monkeypatch.setattr(svc, "upsert_deletion_code", w.upsert)
    monkeypatch.setattr(svc, "get_deletion_code", lambda uid: dict(w.codes[uid]) if uid in w.codes else None)
    def claim(uid, code_hash, seen):
        row = w.codes.get(uid)
        if not row or row["code_hash"] != code_hash or row["attempts"] != seen:
            return False
        w.codes[uid] = {**row, "attempts": seen + 1}
        return True

    monkeypatch.setattr(svc, "claim_deletion_code_attempt", claim)
    monkeypatch.setattr(svc, "delete_deletion_code", lambda uid: w.codes.pop(uid, None))
    monkeypatch.setattr(svc, "list_company_storage_files", lambda cid: {"knowledge": [], "media": []})
    # The real cleanup thread runs here; it must never touch real folders.
    monkeypatch.setattr(svc.document_storage, "delete_tree", lambda *args, **kwargs: None)
    monkeypatch.setattr(svc.document_storage, "delete_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(svc, "delete_company_account_rpc", w.rpc)
    monkeypatch.setattr(svc, "get_company_by_id", lambda cid: {"id": cid, "company_name": "Acme Sdn Bhd"})

    def send(recipient_email, otp_code, recipient_name="User", company_name=None):
        w.sent.append((recipient_email, otp_code))
        return w.email_ok

    monkeypatch.setattr(svc, "send_account_deletion_code_email", send)
    return w


@pytest.fixture
def client(world):
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(user_bp)
    return app.test_client()


def request_code(client, world, user_id=7, code="123456"):
    with patch.object(svc.secrets, "randbelow", return_value=int(code)):
        return client.post(f"{BASE}/code", headers=world.auth(user_id))


# ------------------------------------------------------------------ authentication

@pytest.mark.parametrize("method,path", [
    ("get", BASE), ("post", f"{BASE}/code"), ("post", f"{BASE}/confirm"),
])
def test_every_endpoint_requires_a_token(client, method, path):
    response = getattr(client, method)(path, json={"code": "123456"})

    assert response.status_code == 401


# ---------------------------------------------------------------------- status

def test_the_owner_sees_an_eligible_workspace(client, world):
    response = client.get(BASE, headers=world.auth())

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success", "eligible": True, "reason_code": None,
        "is_owner": True, "company_name": "Acme Sdn Bhd",
    }


def test_a_non_owner_gets_a_200_that_says_so_instead_of_an_error(client, world):
    world.blockers[8] = "not_owner"

    body = client.get(BASE, headers=world.auth(8)).get_json()

    assert body["eligible"] is False
    assert body["is_owner"] is False
    assert body["reason_code"] == "not_owner"


def test_a_blocked_owner_is_told_why(client, world):
    world.blockers[7] = "payment_history"

    body = client.get(BASE, headers=world.auth()).get_json()

    assert (body["eligible"], body["is_owner"], body["reason_code"]) == (False, True, "payment_history")


def test_a_suspended_company_cannot_use_any_of_it(client, world, monkeypatch):
    monkeypatch.setattr("app.services.company_status_service.get_company_status_by_id",
                        lambda cid: {"id": cid, "status": "suspended"})

    assert client.get(BASE, headers=world.auth()).status_code == 403
    assert client.post(f"{BASE}/code", headers=world.auth()).status_code == 403
    assert client.post(f"{BASE}/confirm", headers=world.auth(), json={"code": "123456"}).status_code == 403
    assert world.sent == [] and world.rpc_calls == []


# ------------------------------------------------------------------------- code

def test_requesting_a_code_emails_the_owner_and_never_returns_it(client, world):
    response = request_code(client, world, code="048213")

    assert response.status_code == 200
    assert world.sent == [("user7@example.test", "048213")]
    assert "048213" not in response.get_data(as_text=True)
    assert response.get_json()["expires_in_minutes"] == 10


def test_a_non_owner_cannot_request_a_code(client, world):
    world.blockers[8] = "not_owner"

    response = client.post(f"{BASE}/code", headers=world.auth(8))

    assert response.status_code == 403
    body = response.get_json()
    assert body["code"] == "not_owner" and body["reason_code"] == "not_owner"
    assert world.sent == []


@pytest.mark.parametrize("reason", ["payment_history", "protected", "support_records"])
def test_a_blocked_owner_gets_409_with_the_reason_code_and_no_email(client, world, reason):
    world.blockers[7] = reason

    response = client.post(f"{BASE}/code", headers=world.auth())

    assert response.status_code == 409
    body = response.get_json()
    assert body["status"] == "error"
    assert body["reason_code"] == reason
    assert "support" in body["message"].lower()
    assert world.sent == []


def test_an_email_that_cannot_be_sent_is_a_503_and_leaves_no_code(client, world):
    world.email_ok = False

    response = client.post(f"{BASE}/code", headers=world.auth())

    assert response.status_code == 503
    assert response.get_json()["code"] == "email_unavailable"
    assert world.codes == {}


# ----------------------------------------------------------------------- confirm

def test_confirm_requires_a_json_body_with_a_string_code(client, world):
    headers = world.auth()

    assert client.post(f"{BASE}/confirm", headers=headers).status_code == 400
    assert client.post(f"{BASE}/confirm", headers=headers, json={}).status_code == 400
    assert client.post(f"{BASE}/confirm", headers=headers, json=[]).status_code == 400
    assert client.post(f"{BASE}/confirm", headers=headers, json={"code": 123456}).status_code == 400
    assert world.rpc_calls == []


def test_a_wrong_code_is_a_400_and_deletes_nothing(client, world):
    request_code(client, world)

    response = client.post(f"{BASE}/confirm", headers=world.auth(), json={"code": "000000"})

    assert response.status_code == 400
    assert response.get_json()["code"] == "code_invalid"
    assert world.rpc_calls == []


def test_the_fifth_wrong_code_is_a_429(client, world):
    request_code(client, world)
    headers = world.auth()
    codes = [client.post(f"{BASE}/confirm", headers=headers, json={"code": "000000"}).status_code for _ in range(5)]

    assert codes == [400, 400, 400, 400, 429]


def test_the_company_id_in_the_body_is_ignored(client, world):
    request_code(client, world)

    client.post(f"{BASE}/confirm", headers=world.auth(), json={"code": "123456", "company_id": 99, "user_id": 8})

    assert world.rpc_calls == [(42, 7)], "tenant and actor come from the authenticated user, never the body"


def test_confirm_deletes_the_workspace_and_the_session_dies_with_it(client, world):
    headers = world.auth()
    assert client.get("/api/user", headers=headers).status_code == 200
    request_code(client, world)

    response = client.post(f"{BASE}/confirm", headers=headers, json={"code": "123456"})

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
    assert world.rpc_calls == [(42, 7)]
    assert world.deleted_company is True
    # token_required re-reads the user on every request. A deleted user is
    # refused with 403 account_inactive (not 401); the frontend's
    # authenticatedFetch logs out on a 401 and on this 403 alike.
    after = client.get("/api/user", headers=headers)
    assert after.status_code == 403
    assert after.get_json()["code"] == "account_inactive"
    assert client.get(BASE, headers=headers).status_code == 403
    assert client.post(f"{BASE}/code", headers=headers).status_code == 403


def test_a_blocked_workspace_cannot_be_deleted_even_with_a_valid_code(client, world):
    request_code(client, world)
    world.blockers[7] = "payment_history"

    response = client.post(f"{BASE}/confirm", headers=world.auth(), json={"code": "123456"})

    assert response.status_code == 409
    assert response.get_json()["reason_code"] == "payment_history"
    assert world.deleted_company is False


def test_another_users_code_is_useless_to_a_member(client, world):
    request_code(client, world)
    world.blockers[8] = "not_owner"

    response = client.post(f"{BASE}/confirm", headers=world.auth(8), json={"code": "123456"})

    assert response.status_code == 403
    assert world.rpc_calls == []


# ------------------------------------------------------------------- error hygiene

def test_an_unexpected_failure_is_a_generic_500_with_no_internals(client, world, monkeypatch):
    request_code(client, world)

    def explode(company_id, user_id):
        raise RuntimeError("postgrest https://secret-ref.supabase.co/rest/v1/rpc failed: account_deletion_incomplete")

    monkeypatch.setattr(svc, "delete_company_account_rpc", explode)

    response = client.post(f"{BASE}/confirm", headers=world.auth(), json={"code": "123456"})

    assert response.status_code == 500
    text = response.get_data(as_text=True)
    assert "secret-ref" not in text and "account_deletion_incomplete" not in text
    body = response.get_json()
    assert body["status"] == "error"
    assert "could not delete the workspace" in body["message"] and "contact support" in body["message"]
    assert "nothing was changed" not in body["message"].lower(), "a timeout can land after the commit"


def test_a_failure_while_reading_status_is_also_generic(client, world, monkeypatch):
    def explode(company_id, user_id):
        raise RuntimeError("boom internal")

    monkeypatch.setattr(svc, "get_deletion_blocker", explode)

    response = client.get(BASE, headers=world.auth())

    assert response.status_code == 500
    assert "boom internal" not in response.get_data(as_text=True)


# ------------------------------------------------------------------- rate limiting

@pytest.fixture
def limited_client(world):
    app = Flask(__name__)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=True, RATELIMIT_STORAGE_URI="memory://",
                      RATELIMIT_OTP="2/hour")
    limiter.init_app(app)
    app.register_blueprint(user_bp)
    yield app.test_client()
    limiter.reset()
    # The limiter is a process-wide singleton: hand it back switched off, as the other suites expect.
    quiet = Flask(__name__)
    quiet.config.update(RATELIMIT_ENABLED=False, RATELIMIT_STORAGE_URI="memory://")
    limiter.init_app(quiet)


def test_code_requests_are_limited_per_user_not_per_address(limited_client, world):
    statuses = [
        limited_client.post(f"{BASE}/code", headers=world.auth(7),
                            environ_base={"REMOTE_ADDR": f"198.51.100.{i}"}).status_code
        for i in range(1, 4)
    ]

    assert statuses == [200, 200, 429], "rotating the client address must not reset the budget"
    assert len(world.sent) == 2


def test_one_users_budget_does_not_lock_out_another_user(limited_client, world):
    for _ in range(3):
        limited_client.post(f"{BASE}/code", headers=world.auth(7))

    other = limited_client.post(f"{BASE}/code", headers=world.auth(8))

    assert other.status_code != 429


def test_confirm_attempts_are_limited_per_user_not_per_address(limited_client, world):
    request_code(limited_client, world)
    statuses = [
        limited_client.post(f"{BASE}/confirm", headers=world.auth(7), json={"code": "000000"},
                            environ_base={"REMOTE_ADDR": f"203.0.113.{i}"}).status_code
        for i in range(1, 4)
    ]

    assert statuses == [400, 400, 429], "rotating the client address must not reset the guess budget"
    assert world.rpc_calls == []


def test_one_users_wrong_guesses_do_not_lock_out_another_users_confirmation(limited_client, world):
    request_code(limited_client, world)
    for _ in range(3):
        limited_client.post(f"{BASE}/confirm", headers=world.auth(7), json={"code": "000000"})

    other = limited_client.post(f"{BASE}/confirm", headers=world.auth(8), json={"code": "000000"})

    assert other.status_code != 429
