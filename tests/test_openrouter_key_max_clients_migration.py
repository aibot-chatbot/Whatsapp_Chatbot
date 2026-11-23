import sqlite3
from pathlib import Path

import pytest


DATA = Path(__file__).resolve().parents[1] / "data"


def replacement(sql):
    return sql.split("FUNCTION public.replace_openrouter_client_key(", 1)[1].split("$$;", 1)[0]


def test_limit_rpc_and_column_contract():
    sql = (DATA / "089_openrouter_key_max_clients.sql").read_text(encoding="utf8")
    setter = sql.split("CREATE OR REPLACE FUNCTION", 1)[0]
    compact = " ".join(setter.lower().split())
    for clause in (
        "begin; set local lock_timeout = '3s'; set local statement_timeout = '30s';",
        "max_clients smallint not null default 20",
        "constraint openrouter_client_keys_max_clients_check check (max_clients between 1 and 20)",
        "p_key_id bigint, p_max_clients integer, p_actor_id bigint",
        "returns smallint language plpgsql security invoker set search_path = ''",
        "where id = p_actor_id and is_active and platform_role = 'super_admin' for share",
        "if p_max_clients is null or p_max_clients not between 1 and 20 then raise",
        "where id = p_key_id for update",
        "if not found then raise exception 'the selected key no longer exists.' using errcode = 'pt404'",
        "if old_status <> 'active' then raise exception 'key is unavailable.' using errcode = 'pt409'",
        "set max_clients = p_max_clients where id = p_key_id",
        "'platform_admin.openrouter_key.set_max_clients', 'openrouter_client_keys'",
        "'endpoint', '/api/platform-admin/openrouter-keys/<key_id>/max-clients'",
        "'http_method', 'patch', 'outcome', 'success'",
        "'previous_max_clients', previous_limit, 'max_clients', p_max_clients",
        "return previous_limit;",
        "from public, anon, authenticated", "to service_role",
    ):
        assert clause in compact
    assert compact.count("insert into public.platform_admin_audit_events") == 1
    assert "openrouter_key_assignments" not in setter


def test_existing_key_defaults_to_twenty_and_column_enforces_both_bounds():
    sql = (DATA / "089_openrouter_key_max_clients.sql").read_text(encoding="utf8")
    alter = "ALTER TABLE " + sql.split("ALTER TABLE ", 1)[1].split(";", 1)[0]
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE openrouter_client_keys (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO openrouter_client_keys VALUES (1)")
        db.execute(alter.replace("public.", ""))
        assert db.execute("SELECT max_clients FROM openrouter_client_keys").fetchone() == (20,)
        for valid in (1, 20):
            db.execute("UPDATE openrouter_client_keys SET max_clients = ?", (valid,))
        for invalid in (0, 21, None):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("UPDATE openrouter_client_keys SET max_clients = ?", (invalid,))


def test_replacement_only_changes_insert_to_copy_max_clients_and_rollback_restores_088():
    original = replacement((DATA / "088_replace_openrouter_client_key.sql").read_text(encoding="utf8"))
    migration = (DATA / "089_openrouter_key_max_clients.sql").read_text(encoding="utf8")
    rollback = (DATA / "089_openrouter_key_max_clients_rollback.sql").read_text(encoding="utf8")
    assert replacement(migration) == original.replace(
        "(key_hash, encrypted_key, label)\n        VALUES (p_hash, p_encrypted, p_label)",
        "(key_hash, encrypted_key, label, max_clients)\n"
        "        SELECT p_hash, p_encrypted, p_label, max_clients FROM public.openrouter_client_keys\n"
        "        WHERE id = p_old_id",
    )
    assert replacement(rollback) == original
    assert "DROP FUNCTION IF EXISTS public.set_openrouter_key_max_clients(bigint, integer, bigint);" in rollback
    assert "DROP COLUMN IF EXISTS max_clients;" in rollback
