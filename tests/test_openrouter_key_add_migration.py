from pathlib import Path


DATA = Path(__file__).resolve().parents[1] / "data"
SIGNATURE = "public.add_openrouter_client_key(text, text, text, integer, bigint)"
ASSIGNMENT_TRIGGER = "mark_openrouter_key_assigned"


def test_add_key_migration_and_rollback_contract():
    migration = (DATA / "093_openrouter_key_add.sql").read_text(encoding="utf8")
    sql = " ".join(migration.lower().split())
    for clause in (
        "begin; set local lock_timeout = '3s'; set local statement_timeout = '30s';",
        "create function public.add_openrouter_client_key(",
        "p_key_hash text, p_encrypted_key text, p_label text, p_max_clients integer, p_actor_id bigint",
        "returns bigint language plpgsql security definer set search_path = public, pg_temp",
        "where id = p_actor_id and is_active and platform_role = 'super_admin' for share",
        "errcode = 'pt403'",
        "p_max_clients is null or p_max_clients not between 1 and 20",
        "errcode = 'pt400'",
        r"p_label !~ '^sk-or-v1-[0-9a-f]{3}\.\.\.[0-9a-f]{4}$'",
        "add column awaiting_first_client boolean not null default false",
        "(key_hash, encrypted_key, label, status, max_clients, awaiting_first_client)",
        "values (p_key_hash, p_encrypted_key, p_label, 'active', p_max_clients, true)",
        "on conflict (key_hash) do nothing returning id into new_id",
        "errcode = 'pt409'",
        f"revoke all on function {SIGNATURE} from public, anon, authenticated;",
        f"grant execute on function {SIGNATURE} to service_role;",
        f"create trigger {ASSIGNMENT_TRIGGER} after insert or update of key_id on public.openrouter_key_assignments",
        f"for each row execute function public.{ASSIGNMENT_TRIGGER}()",
        "set awaiting_first_client = false where id = new.key_id and awaiting_first_client",
        f"revoke all on function public.{ASSIGNMENT_TRIGGER}() from public, anon, authenticated;",
    ):
        assert clause in sql
    rpc = sql.split("create function public.add_openrouter_client_key(", 1)[1].split("$$;", 1)[0]
    assert "openrouter_key_assignments" not in rpc
    audit = sql.split("insert into public.platform_admin_audit_events", 1)[1].split(";", 1)[0]
    assert "'platform_admin.openrouter_key.add', 'openrouter_client_keys', new_id::text" in audit
    assert "'masked_label', p_label" in audit
    assert "'max_clients', p_max_clients" in audit
    assert "p_key_hash" not in audit
    assert "p_encrypted_key" not in audit
    assert "return new_id;" in sql
    assert sql.endswith("commit;")

    rollback = (DATA / "093_openrouter_key_add_rollback.sql").read_text(encoding="utf8")
    statements = [line for line in rollback.lower().splitlines() if not line.startswith("--")]
    assert " ".join(" ".join(statements).split()) == (
        "begin; set local lock_timeout = '3s'; set local statement_timeout = '30s'; "
        f"drop function if exists {SIGNATURE}; "
        f"drop trigger if exists {ASSIGNMENT_TRIGGER} on public.openrouter_key_assignments; "
        f"drop function if exists public.{ASSIGNMENT_TRIGGER}(); "
        "alter table public.openrouter_client_keys drop column if exists awaiting_first_client; commit;"
    )
