import json
import re
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests
from cryptography.fernet import Fernet
from flask import Flask

from app.routes.platform_admin_routes import platform_admin_bp
from app.services import openrouter_key_service as keys


URL = "/api/platform-admin/openrouter-keys"
HEADERS = {"Authorization": "Bearer test-token"}
FAKE = "sk-or-v1-" + "0" * 64
MASK = "sk-or-v1-000...0000"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.decorators.auth_decorator.get_jwt_secret", lambda: "test-secret")
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *a, **kw: {"user_id": 7})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda *_: {
        "id": 7, "company_id": 12, "status": "active", "role": "member",
    })
    mapping = {"id": 3, "user_id": 7, "is_active": True, "platform_role": "super_admin",
               "modules": {"billing": True, "customers": True, "support": True}}
    monkeypatch.setattr("app.decorators.platform_admin_decorator.get_active_platform_admin_by_user_id",
                        lambda *_: mapping)
    app = Flask(__name__)
    app.register_blueprint(platform_admin_bp)
    return app.test_client(), mapping


@pytest.fixture
def repo(monkeypatch):
    repository = Mock()
    monkeypatch.setattr(keys, "_repository", lambda: repository)
    return repository


@pytest.mark.parametrize("online", [True, False])
@pytest.mark.parametrize("credits_online", [True, False])
def test_list_is_masked_with_optional_usage(client, repo, monkeypatch, online, credits_online, caplog):
    repo.list_admin_keys.return_value = [
        {"id": 1, "key_hash": "old", "label": "omnexa-pool-example", "status": "disabled",
         "clients": 2, "max_clients": 1, "disabled_reason": "ours", "culprit_company_id": 12, "encrypted_key": "ciphertext"},
        {"id": 2, "key_hash": "new", "label": MASK, "status": "active", "clients": 0, "max_clients": 17,
         "disabled_reason": None, "culprit_company_id": None},
    ]
    remote = Mock(return_value=[{"hash": "new", "label": MASK, "usage": 3, "limit": 9,
                                 "limit_remaining": 7, "limit_reset": "monthly", "usage_monthly": 2},
                                {"hash": "old", "label": FAKE, "usage": 7, "limit": 12,
                                 "limit_remaining": True, "limit_reset": "unexpected", "usage_monthly": -1}])
    if not online:
        remote.side_effect = RuntimeError(FAKE)
    monkeypatch.setattr(keys, "list_openrouter_keys", remote)
    credits = Mock(status_code=200)
    credits.json.return_value = {"data": {"total_credits": 25, "total_usage": 3.5}}
    http_get = Mock(return_value=credits, side_effect=None if credits_online else requests.ConnectionError(FAKE))
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_API_KEY", "test-management-only")
    monkeypatch.setattr(keys.requests, "get", http_get)
    response = client[0].get(URL, headers=HEADERS)
    assert response.status_code == 200
    rows = response.json["data"]["keys"]
    http_get.assert_called_once_with("https://openrouter.ai/api/v1/credits",
                                     headers={"Authorization": "Bearer test-management-only"},
                                     timeout=keys.KEY_API_TIMEOUT_SECONDS, allow_redirects=False)
    assert response.json["data"]["account"] == (
        {"total_credits": 25, "total_usage": 3.5, "remaining": 21.5} if credits_online else None)
    assert rows == [
        {"id": 1, "label": None, "status": "disabled", "clients": 2, "max_clients": 1, "disabled_reason": "ours",
         "culprit_company_id": 12, "usage": 7 if online else None, "limit": 12 if online else None,
         "limit_remaining": None, "limit_reset": None, "usage_monthly": None},
        {"id": 2, "label": MASK, "status": "active", "clients": 0, "max_clients": 17, "disabled_reason": None,
         "culprit_company_id": None, "usage": 3 if online else None, "limit": 9 if online else None,
         "limit_remaining": 7 if online else None, "limit_reset": "monthly" if online else None,
         "usage_monthly": 2 if online else None},
    ]
    assert FAKE not in response.text + caplog.text
    assert "ciphertext" not in response.text


@pytest.mark.parametrize("status,credits,usage", [
    (200, "10", 1), (200, 2, True), (200, None, 1), (200, float("inf"), 1),
    (200, 1, -1), (307, 2, 1), (403, 2, 1),
])
def test_list_ignores_unusable_account_credit_response(repo, monkeypatch, status, credits, usage):
    repo.list_admin_keys.return_value = []
    monkeypatch.setattr(keys, "list_openrouter_keys", list)
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_API_KEY", "test-management-only")
    provider = Mock(status_code=status)
    provider.json.return_value = {"data": {"total_credits": credits, "total_usage": usage}}
    monkeypatch.setattr(keys.requests, "get", Mock(return_value=provider))
    assert keys.list_admin_keys() == {"account": None, "keys": []}


@pytest.fixture
def replacement(repo, monkeypatch):
    monkeypatch.setenv("AI_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OPENROUTER_KEY_MONTHLY_LIMIT_USD", "10")
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_API_KEY", "test-management-only")
    monkeypatch.setattr(keys, "_cache", {12: "previous", 13: "previous", 17: "unrelated"})
    repo.get_replacement_source.return_value = {"key_hash": "old", "disabled_reason": "ours"}
    repo.has_key_hash.return_value = False
    repo.month_credit_micro_myr.return_value = 100_000_000
    monkeypatch.setattr("app.services.ai_credit_service.get_ai_usd_to_myr_rate_micro_myr_per_usd",
                        lambda: 5_000_000)
    own = {"label": MASK, "workspace_id": "workspace", "creator_user_id": "creator", "limit": 9,
           "is_management_key": False, "expires_at": None}
    remote = [{**own, "hash": "new", "disabled": False}]
    self_response = Mock(status_code=200)
    self_response.json.return_value = {"data": own}
    management_response = Mock(status_code=200)
    management_response.json.return_value = {"data": remote}
    http_get = Mock(side_effect=[self_response, management_response])
    http_patch = Mock(return_value=Mock(status_code=200))
    monkeypatch.setattr(keys.requests, "get", http_get)
    monkeypatch.setattr(keys.requests, "patch", http_patch)
    repo.replace_key.return_value = [12, 13]
    return own, remote, self_response, http_get, http_patch


def replace(client, **overrides):
    return client[0].post(URL + "/8/replace", headers=HEADERS,
                          json={"api_key": FAKE, "reason": "Provider rejected this key.", **overrides})


def test_add_imports_an_encrypted_key_after_applying_the_monthly_pool_cap(client, repo, replacement, caplog):
    _, _, _, _, http_patch = replacement

    def add_rpc(key_hash, encrypted, label, max_clients, actor_id):
        http_patch.assert_called_once_with(keys.OPENROUTER_KEYS_URL + "/new",
                                          headers={"Authorization": "Bearer test-management-only"},
                                          json={"limit": 10, "limit_reset": "monthly"},
                                          timeout=keys.KEY_API_TIMEOUT_SECONDS, allow_redirects=False)
        assert (key_hash, label, max_clients, actor_id) == ("new", MASK, 8, 3)
        assert keys._fernet().decrypt(encrypted.encode()).decode() == FAKE
        return 42

    repo.add_key.side_effect = add_rpc
    response = client[0].post(URL, headers=HEADERS, json={"api_key": FAKE, "max_clients": 8, "actor_id": 99})
    assert response.status_code == 200
    assert response.json["data"] == {"id": 42, "label": MASK, "max_clients": 8}
    repo.add_key.assert_called_once()
    assert FAKE not in response.text + caplog.text


@pytest.mark.parametrize("case", ["format", "missing limit", "zero", "too large", "string", "bool", "float",
                                  "not owned", "duplicate", "staff", "signed out"])
def test_add_rejects_invalid_or_unauthorized_requests_before_cap_or_insert(case, client, repo, replacement, caplog):
    _, remote, _, http_get, http_patch = replacement
    payload = {"api_key": FAKE, "max_clients": 20}
    limits = {"zero": 0, "too large": 21, "string": "1", "bool": True, "float": 1.0}
    if case in limits:
        payload["max_clients"] = limits[case]
    elif case == "missing limit":
        del payload["max_clients"]
    elif case == "format":
        payload["api_key"] = "invalid"
    elif case == "not owned":
        remote.clear()
    elif case == "duplicate":
        repo.has_key_hash.return_value = True
    elif case == "staff":
        client[1]["platform_role"] = "admin"
    result = client[0].post(URL, json=payload, headers={} if case == "signed out" else HEADERS)
    assert result.status_code == {"duplicate": 409, "staff": 403, "signed out": 401}.get(case, 400)
    if case not in ("not owned", "duplicate"):
        http_get.assert_not_called()
    http_patch.assert_not_called()
    repo.add_key.assert_not_called()
    assert FAKE not in result.text + caplog.text


@pytest.mark.parametrize(("operation", "code", "status"), [
    ("rpc", "PT400", 400), ("rpc", "PT403", 403), ("rpc", "PT409", 409),
    ("rpc", "unknown", 503), ("cap", None, 503),
])
def test_add_masks_rpc_and_cap_failures(operation, code, status, client, repo, replacement, caplog):
    from postgrest.exceptions import APIError
    if operation == "cap":
        replacement[-1].side_effect = requests.ConnectionError(FAKE)
    else:
        repo.add_key.side_effect = APIError({"code": code, "message": FAKE, "details": "", "hint": ""})
    response = client[0].post(URL, headers=HEADERS, json={"api_key": FAKE, "max_clients": 1})
    assert response.status_code == status
    if operation == "cap":
        repo.add_key.assert_not_called()
    assert FAKE not in response.text + caplog.text


def test_add_rate_limited_to_five_per_minute_before_provider(client, replacement):
    from app.rate_limit import init_limiter, limiter
    app = client[0].application
    app.config.update(RATELIMIT_ENABLED=True, RATELIMIT_STORAGE_URI="memory://")
    with patch.dict(vars(limiter)):
        init_limiter(app)
        for status in (400, 400, 400, 400, 400, 429):
            assert client[0].post(URL, headers=HEADERS, json={}).status_code == status
    replacement[3].assert_not_called()


def test_add_key_repository_calls_only_the_service_rpc(db):
    from app.database import openrouter_key_repository as repository
    db.rpc.return_value.execute.return_value.data = 42
    assert repository.add_key("new", "test-ciphertext", MASK, 20, 3) == 42
    db.rpc.assert_called_once_with("add_openrouter_client_key", {
        "p_key_hash": "new", "p_encrypted_key": "test-ciphertext", "p_label": MASK,
        "p_max_clients": 20, "p_actor_id": 3})
    db.table.assert_not_called()


@pytest.mark.parametrize("disable_fails", [False, True])
def test_replace_encrypts_caps_and_evicts_every_moved_client(client, repo, replacement, disable_fails, caplog):
    _, _, _, http_get, http_patch = replacement
    if disable_fails:
        http_patch.side_effect = [Mock(status_code=200), requests.ConnectionError(FAKE)]
    response = replace(client)
    assert response.status_code == 200
    assert response.json["data"] == {"label": MASK, "moved_count": 2, "old_key_disabled": not disable_fails}
    args = http_get.call_args_list[0]
    assert args.args == ("https://openrouter.ai/api/v1/key",)
    assert args.kwargs["headers"] == {"Authorization": "Bearer " + FAKE}
    assert args.kwargs["allow_redirects"] is False and 0 < args.kwargs["timeout"] <= 10
    assert http_patch.call_args_list[0].kwargs["json"] == {"limit": 30, "limit_reset": "monthly"}
    assert http_patch.call_args_list[0].args[0].endswith("/keys/new")
    assert http_patch.call_args_list[1].args[0].endswith("/keys/old")
    assert http_patch.call_args_list[1].kwargs["json"] == {"disabled": True}
    old_id, new_hash, encrypted, label, actor, reason = repo.replace_key.call_args.args
    assert (old_id, new_hash, label, actor, reason) == (8, "new", MASK, 3, "Provider rejected this key.")
    assert encrypted != FAKE and keys._fernet().decrypt(encrypted.encode()).decode() == FAKE
    assert keys._cache == {17: "unrelated"}
    assert FAKE not in response.text + caplog.text


@pytest.mark.parametrize("case", [
    "format", "missing reason", "401", "redirect", "management", "legacy management", "no limit",
    "expired", "zero matches", "two matches", "wrong workspace", "wrong creator", "missing identity",
    "wrong self mask", "disabled", "stored hash", "already replaced", "reason contains key",
    "remote no limit", "hash contains key",
])
def test_unsafe_replacement_makes_no_changes(case, client, repo, replacement, caplog):
    own, remote, response, http_get, http_patch = replacement
    payload = {}
    if case == "format":
        payload["api_key"] = "not-a-key"
    elif case == "missing reason":
        payload["reason"] = " "
    elif case == "reason contains key":
        payload["reason"] = FAKE
    elif case == "401":
        response.status_code = 401
    elif case == "redirect":
        response.status_code = 307
    elif case == "management":
        own["is_management_key"] = True
    elif case == "legacy management":
        own["is_provisioning_key"] = True
    elif case == "no limit":
        own["limit"] = None
    elif case == "expired":
        own["expires_at"] = "2000-01-01T00:00:00Z"
    elif case == "zero matches":
        remote.clear()
    elif case == "two matches":
        remote.append(dict(remote[0], hash="different"))
    elif case == "wrong workspace":
        remote[0]["workspace_id"] = "other"
    elif case == "wrong creator":
        remote[0]["creator_user_id"] = "other"
    elif case == "missing identity":
        own["creator_user_id"] = remote[0]["creator_user_id"] = None
    elif case == "wrong self mask":
        own["label"] = "other"
    elif case == "disabled":
        remote[0]["disabled"] = True
    elif case == "stored hash":
        repo.has_key_hash.return_value = True
    elif case == "already replaced":
        repo.get_replacement_source.return_value["disabled_reason"] = "manual_replacement"
    elif case == "remote no limit":
        remote[0]["limit"] = None
    elif case == "hash contains key":
        remote[0]["hash"] = FAKE
    result = replace(client, **payload)
    assert result.status_code == (409 if case in ("stored hash", "already replaced") else 400)
    http_patch.assert_not_called()
    repo.replace_key.assert_not_called()
    if case in ("format", "missing reason", "reason contains key"):
        http_get.assert_not_called()
    assert FAKE not in result.text + caplog.text


@pytest.mark.parametrize("operation", ["self", "management", "cap", "database", "list database"])
def test_backend_error_text_is_never_exposed(operation, client, repo, replacement, caplog):
    _, _, _, http_get, http_patch = replacement
    failure = RuntimeError(FAKE)
    if operation == "self":
        http_get.side_effect = failure
    elif operation == "management":
        http_get.side_effect = [next(http_get.side_effect), failure]
    elif operation == "cap":
        http_patch.side_effect = failure
    elif operation == "database":
        repo.replace_key.side_effect = failure
    else:
        repo.list_admin_keys.side_effect = failure
    result = client[0].get(URL, headers=HEADERS) if operation == "list database" else replace(client)
    assert result.status_code == 503
    assert FAKE not in result.text + caplog.text
    assert "RuntimeError" in caplog.text
    if operation == "database":
        assert not keys._cache


def test_staff_cannot_list_or_replace_even_with_all_modules(client, repo, replacement):
    client[1]["platform_role"] = "admin"
    assert client[0].get(URL, headers=HEADERS).status_code == 403
    assert replace(client).status_code == 403
    assert not repo.mock_calls
    replacement[3].assert_not_called()


def test_database_moves_all_clients_and_audits_in_one_service_only_transaction():
    sql = (Path(__file__).resolve().parents[1] / "data/088_replace_openrouter_client_key.sql").read_text()
    sql = " ".join(sql.lower().split())
    for clause in ("security invoker", "for update", "insert into public.openrouter_client_keys",
                   "update public.openrouter_key_assignments set key_id = new_id where key_id = p_old_id returning company_id",
                   "disabled_reason = 'manual_replacement'", "replacement_reason = p_reason",
                   "platform_role = 'super_admin'", "from public, anon, authenticated",
                   "to service_role", "return moved_ids"):
        assert clause in sql
    assert sql.count("insert into public.platform_admin_audit_events") == 1
    audit = sql.split("insert into public.platform_admin_audit_events")[1].split("return moved_ids")[0]
    assert "p_label" in audit and "new_id" in audit and "p_old_id" in audit
    assert not any(field in audit for field in ("p_hash", "p_encrypted", "p_reason"))


def test_rollback_restores_082_without_reassigning_clients_or_touching_audit_history():
    path = Path(__file__).resolve().parents[1] / "data/088_replace_openrouter_client_key_rollback.sql"
    sql = " ".join(line for line in path.read_text(encoding="utf-8").lower().splitlines()
                   if not line.lstrip().startswith("--"))
    sql = " ".join(sql.split())
    assert sql.startswith("begin;") and sql.endswith("commit;")
    assert "drop function if exists public.replace_openrouter_client_key(bigint, text, text, text, bigint, text)" in sql
    assert "set disabled_reason = null where disabled_reason = 'manual_replacement'" in sql
    assert "drop column if exists replacement_reason" in sql
    assert "check (disabled_reason in ('ours', 'openrouter'))" in sql
    assert not any(term in sql for term in ("openrouter_key_assignments", "platform_admin_audit_events",
                                            "set status", "delete from", "truncate"))


def test_replacement_dml_moves_culprit_and_writes_one_safe_audit(client, repo, replacement):
    # Execute the migration's DML on a fixture. Only PL/pgSQL variable and RETURNING syntax differ.
    sql = (Path(__file__).resolve().parents[1] / "data/088_replace_openrouter_client_key.sql").read_text()
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE openrouter_client_keys(id INTEGER PRIMARY KEY, key_hash UNIQUE, encrypted_key,
            label, status DEFAULT 'active', disabled_reason, replacement_reason, culprit_company_id);
        CREATE TABLE openrouter_key_assignments(company_id PRIMARY KEY, key_id);
        CREATE TABLE platform_admin_audit_events(platform_admin_user_id, action, resource_type, resource_id, metadata);
        INSERT INTO openrouter_client_keys(id, key_hash, status, disabled_reason, culprit_company_id)
            VALUES (8, 'old', 'disabled', 'ours', 12), (3, 'other', 'active', NULL, NULL);
        INSERT INTO openrouter_key_assignments VALUES (12, 8), (13, 8), (17, 3);
    """)

    def statement(start, end=";"):
        query = start + sql.split(start, 1)[1].split(end, 1)[0]
        query = query.replace("public.", "").replace("p_old_id::text", "CAST(p_old_id AS text)")
        return re.sub(r"\b(p_\w+|new_id)\b", r":\1", query).replace("jsonb_build_object", "json_object")

    def transaction(old_id, key_hash, cipher, label, actor, reason):
        params = dict(p_old_id=old_id, p_hash=key_hash, p_encrypted=cipher, p_label=label,
                      p_actor_id=actor, p_reason=reason)
        with db:
            created = db.execute(statement("INSERT INTO public.openrouter_client_keys", " INTO new_id"), params)
            params["new_id"] = created.fetchone()[0]
            moved = db.execute(statement("UPDATE public.openrouter_key_assignments", "\n    )"), params).fetchall()
            db.execute(statement("UPDATE public.openrouter_client_keys"), params)
            db.execute(statement("INSERT INTO public.platform_admin_audit_events"), params)
        return [row[0] for row in moved]

    repo.replace_key.side_effect = transaction
    try:
        assert replace(client).status_code == 200
        new_id, cipher = db.execute("SELECT id, encrypted_key FROM openrouter_client_keys WHERE key_hash='new'").fetchone()
        assert keys._fernet().decrypt(cipher.encode()).decode() == FAKE
        assert db.execute("SELECT * FROM openrouter_key_assignments ORDER BY company_id").fetchall() == [
            (12, new_id), (13, new_id), (17, 3)]
        assert db.execute("SELECT status, disabled_reason FROM openrouter_client_keys WHERE id=8").fetchone() == (
            "disabled", "manual_replacement")
        [(actor, action, resource, old_id, metadata)] = db.execute("SELECT * FROM platform_admin_audit_events")
        assert (actor, action, resource, old_id) == (3, "platform_admin.openrouter_key.replace", "openrouter_client_keys", "8")
        assert json.loads(metadata)["masked_label"] == MASK and json.loads(metadata)["replacement_id"] == new_id
        assert FAKE not in metadata
    finally:
        db.close()


def test_frontend_masks_input_and_only_links_super_admins():
    root = Path(__file__).resolve().parents[1]
    page = (root / "web/src/pages/superadmin.astro").read_text(encoding="utf-8")
    js = (root / "frontend/assets/js/superadmin-api-keys.js").read_text(encoding="utf-8")
    portal = (root / "frontend/assets/js/superadmin-portal.js").read_text(encoding="utf-8")
    assert 'superadmin-api-keys.js' in page
    assert 'type="password"' in js and 'aria-pressed="false"' in js
    assert 'autocomplete="off"' in js and 'spellcheck="false"' in js
    assert 'input.type = visible ? "text" : "password"' in js
    assert 'toggle.setAttribute("aria-pressed", String(visible))' in js
    assert 'input.value = ""' in js and "localStorage" not in js and "console." not in js
    assert 'id !== "api-keys" || identity?.platform_role === "super_admin"' in portal


def test_rate_limit_stops_repeated_writes_before_checking_any_key(client, replacement):
    from app.rate_limit import init_limiter, limiter

    app = client[0].application
    app.config.update(RATELIMIT_ENABLED=True, RATELIMIT_RETRY="2/minute", RATELIMIT_STORAGE_URI="memory://")
    # init_app binds storage and enables the process-wide limiter for every decorated route.
    with patch.dict(vars(limiter)):
        init_limiter(app)
        for _ in range(2):
            assert replace(client, api_key="invalid").status_code == 400
        assert replace(client, api_key="invalid").status_code == 429
    replacement[3].assert_not_called()


def test_repository_pages_all_rows_without_selecting_ciphertext(monkeypatch):
    from app.database import openrouter_key_repository as repository

    db = Mock()
    monkeypatch.setattr(repository, "supabase", db)
    monkeypatch.setattr(repository, "LEDGER_PAGE_SIZE", 1)
    query = db.table.return_value.select.return_value.order.return_value
    query.range.return_value.execute.side_effect = [
        Mock(data=[{"id": 1, repository.ASSIGNMENTS_TABLE: [{"count": 2}]}]),
        Mock(data=[{"id": 2, repository.ASSIGNMENTS_TABLE: [{"count": 0}]}]), Mock(data=[]),
    ]
    rows = repository.list_admin_keys()
    assert [(row["id"], row["clients"]) for row in rows] == [(1, 2), (2, 0)]
    assert [args.args for args in query.range.call_args_list] == [(0, 0), (1, 1), (2, 2)]
    assert "encrypted_key" not in db.table.return_value.select.call_args.args[0]


def test_audit_schema_only_accepts_a_masked_label_and_ids():
    from app.database.platform_admin_repository import validate_audit_event

    args = (3, "platform_admin.openrouter_key.replace", "openrouter_client_keys", "8")
    metadata = {"outcome": "success", "endpoint": URL + "/<key_id>/replace",
                "http_method": "POST", "replacement_id": 9, "masked_label": MASK}
    validate_audit_event(*args, metadata)
    with pytest.raises(ValueError):
        validate_audit_event(*args, {**metadata, "masked_label": FAKE})


def test_added_key_audit_accepts_only_masked_label_and_valid_limit():
    from app.database.platform_admin_repository import validate_audit_event
    args = (3, "platform_admin.openrouter_key.add", "openrouter_client_keys", "42")
    metadata = {"outcome": "success", "endpoint": URL, "http_method": "POST",
                "masked_label": MASK, "max_clients": 8}
    validate_audit_event(*args, metadata)
    for invalid in ({"masked_label": FAKE}, {"max_clients": 21}, {"encrypted_key": "test-ciphertext"}):
        with pytest.raises(ValueError):
            validate_audit_event(*args, {**metadata, **invalid})


@pytest.fixture
def db(monkeypatch):
    from app.database import openrouter_key_repository
    mock = Mock()
    monkeypatch.setattr(openrouter_key_repository, "supabase", mock)
    return mock


@pytest.mark.parametrize("value", [1, 20])
def test_limit_patch_calls_rpc_with_server_actor_and_returns_counts(client, db, value):
    db.rpc.return_value.execute.return_value.data = 7
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"company_id": 10}, {"company_id": 11}]
    result = client[0].patch(URL + "/8/max-clients", headers=HEADERS,
                             json={"max_clients": value, "actor_id": 999})
    assert result.status_code == 200
    assert result.json["data"] == {"id": 8, "max_clients": value, "previous_max_clients": 7, "clients": 2}
    db.rpc.assert_called_once_with("set_openrouter_key_max_clients", {
        "p_key_id": 8, "p_max_clients": value, "p_actor_id": 3})
    db.table.return_value.select.return_value.eq.assert_called_once_with("key_id", 8)


@pytest.mark.parametrize("payload", [
    {"max_clients": value} for value in (0, 21, -1, "5", 5.0, True, None, 10**30)
] + [{}, []])
def test_limit_patch_rejects_invalid_json_values_before_db(client, db, payload):
    result = client[0].patch(URL + "/8/max-clients", headers=HEADERS, json=payload)
    assert result.status_code == 400
    assert result.json["message"] == "Enter a whole number from 1 to 20."
    assert not db.mock_calls


@pytest.mark.parametrize(("code", "status"), [("PT404", 404), ("PT409", 409), ("PT403", 403)])
def test_limit_patch_maps_locked_rpc_outcomes_without_exposing_db_text(client, db, code, status):
    from postgrest.exceptions import APIError
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    db.rpc.return_value.execute.side_effect = APIError({"message": FAKE, "code": code, "details": "", "hint": ""})
    response = client[0].patch(URL + "/8/max-clients", headers=HEADERS, json={"max_clients": 2})
    assert response.status_code == status
    db.rpc.assert_called_once()
    assert FAKE not in response.text


def test_staff_cannot_see_key_companies_or_change_limits(client, db):
    client[1]["platform_role"] = "admin"
    assert client[0].get(URL + "/8/companies", headers=HEADERS).status_code == 403
    assert client[0].patch(URL + "/8/max-clients", headers=HEADERS, json={"max_clients": 20}).status_code == 403
    assert not db.mock_calls


@pytest.mark.parametrize("size", [None, 0, 2])
def test_key_companies_are_scoped_sorted_and_safe(client, db, size):
    from app.database.openrouter_key_repository import ASSIGNMENTS_TABLE, KEYS_TABLE
    query = db.table.return_value.select.return_value
    rows = [{"company_id": 4, "assigned_at": "2026-11-13T00:00:00+00:00", "companies": {"company_name": "B"}},
            {"company_id": 3, "assigned_at": "2026-11-12T00:00:00+00:00", "companies": {"company_name": "A"}}]
    query.eq.return_value.limit.return_value.execute.return_value.data = [] if size is None else [
        {"max_clients": 1, ASSIGNMENTS_TABLE: rows[:size], "key_hash": "private-hash", "encrypted_key": FAKE}]
    response = client[0].get(URL + "/8/companies", headers=HEADERS)
    db.table.assert_called_once_with(KEYS_TABLE)
    query.eq.assert_called_once_with("id", 8)
    selected = db.table.return_value.select.call_args.args[0]
    assert "encrypted_key" not in selected and "key_hash" not in selected and "*" not in selected
    if size is None:
        assert response.status_code == 404
    else:
        assert response.status_code == 200
        assert response.json["data"] == {"key_id": 8, "max_clients": 1, "clients": size, "companies": [
            {"id": 3, "name": "A", "assigned_at": rows[1]["assigned_at"]},
            {"id": 4, "name": "B", "assigned_at": rows[0]["assigned_at"]},
        ][:size]}
    assert FAKE not in response.text and "private-hash" not in response.text


def test_limit_patch_rate_limited_before_db(client, db):
    from app.rate_limit import init_limiter, limiter
    app = client[0].application
    app.config.update(RATELIMIT_ENABLED=True, RATELIMIT_RETRY="2/minute", RATELIMIT_STORAGE_URI="memory://")
    with patch.dict(vars(limiter)):
        init_limiter(app)
        for status in (400, 400, 429):
            result = client[0].patch(URL + "/8/max-clients", headers=HEADERS, json={"max_clients": 0})
            assert result.status_code == status
    assert not db.mock_calls
