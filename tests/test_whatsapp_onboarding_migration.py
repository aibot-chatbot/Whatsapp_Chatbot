from pathlib import Path


def test_meta_onboarding_migration_and_rollback_contract():
    directory = Path(__file__).resolve().parents[1] / "data"
    def sql(suffix):
        path = directory / f"090_whatsapp_onboarding_type{suffix}.sql"
        return " ".join(path.read_text(encoding="utf-8").lower().split())

    forward, rollback = sql(""), sql("_rollback")
    for script in (forward, rollback):
        assert script.startswith("begin; set local lock_timeout")
        assert script.endswith("commit;")
        assert "alter table public.whatsapp_channels" in script
        assert "grant " not in script and "revoke " not in script
    assert "add column onboarding_type text not null default 'standard'" in forward
    assert "check (onboarding_type in ('standard', 'coexistence'))" in forward
    assert "add column register_pin_encrypted text;" in forward
    assert "create unique index whatsapp_channels_registration_uidx" in forward
    assert "connection_status = 'pending' and register_pin_encrypted is not null" in forward
    assert "drop index public.whatsapp_channels_registration_uidx" in rollback
    assert "drop column onboarding_type" in rollback
    assert "drop column register_pin_encrypted" in rollback
    # Dropping stored PINs would leave registered numbers with a two-step PIN nobody knows.
    guard = ("if exists (select 1 from public.whatsapp_channels where register_pin_encrypted is not null) "
             "then raise exception")
    assert guard in rollback
    assert rollback.index(guard) < rollback.index("drop column register_pin_encrypted")
