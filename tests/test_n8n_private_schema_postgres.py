"""Provision n8n as a non-superuser in an isolated local PostgreSQL cluster."""
from pathlib import Path

from tests.test_analysis_postgres import pg  # noqa: F401


def test_non_superuser_provisioning_releases_access_and_rolls_back_on_guard_failure(pg):
    script = (Path(__file__).parents[1] / "deploy/agent-automation/n8n-private-schema.sql").read_text(encoding="utf-8")
    pg("""CREATE ROLE n8n_provisioner LOGIN NOSUPERUSER NOCREATEDB CREATEROLE
        NOREPLICATION NOBYPASSRLS NOINHERIT;
        GRANT CREATE ON DATABASE postgres TO n8n_provisioner;""")
    as_admin = "SET SESSION AUTHORIZATION n8n_provisioner; SET createrole_self_grant='';\n"
    pg(as_admin + script)

    # CREATE ROLE's automatic ADMIN grant stays available for password rotation;
    # temporary schema-owner privileges and SET ROLE must not survive the script.
    assert pg("""SELECT bool_or(m.admin_option) AND NOT bool_or(m.inherit_option)
        AND NOT bool_or(m.set_option) FROM pg_auth_members m
        WHERE m.roleid='agent_n8n'::regrole AND m.member='n8n_provisioner'::regrole;""").stdout.strip() == "t"
    assert "42501" in pg(as_admin + "SET ROLE agent_n8n;", check=False).stderr
    pg(as_admin + "ALTER ROLE agent_n8n PASSWORD NULL;")
    assert pg("SELECT nspowner='agent_n8n'::regrole FROM pg_namespace WHERE nspname='agent_n8n';").stdout.strip() == "t"
    assert pg("""SELECT NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
        AND NOT rolreplication AND NOT rolbypassrls FROM pg_roles WHERE rolname='agent_n8n';""").stdout.strip() == "t"
    as_n8n = "SET SESSION AUTHORIZATION agent_n8n;\n"
    pg(as_n8n + "CREATE TABLE agent_n8n.probe(id integer); INSERT INTO agent_n8n.probe VALUES(1);")
    for statement in ("SELECT * FROM public.companies;", "SET ROLE n8n_provisioner;",
                      "SELECT public.claim_automation_events_v1('n8n');"):
        assert "42501" in pg(as_n8n + statement, check=False).stderr
    for role in ("anon", "authenticated", "service_role"):
        assert "42501" in pg("SELECT * FROM agent_n8n.probe;", role=role, check=False).stderr

    # Clean only this disposable cluster, then force the production guard to fail.
    pg("DROP SCHEMA agent_n8n CASCADE; DROP OWNED BY agent_n8n; DROP ROLE agent_n8n;")
    pg("CREATE TABLE public.n8n_guard_probe(id integer); GRANT SELECT ON public.n8n_guard_probe TO PUBLIC;")
    failed = pg(as_admin + script, check=False)
    assert failed.returncode != 0 and "n8n role inherits app access through PUBLIC" in failed.stderr
    assert pg("SELECT count(*) FROM pg_roles WHERE rolname='agent_n8n';").stdout.strip() == "0"
    assert pg("SELECT count(*) FROM pg_namespace WHERE nspname='agent_n8n';").stdout.strip() == "0"
