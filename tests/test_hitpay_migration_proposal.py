"""Static safety contract for the un-applied HitPay migration proposal."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_migration_051_preflights_duplicates_and_adds_composite_uniqueness():
    sql = (ROOT / "data" / "051_unique_subscription_gateway_order.sql").read_text()

    assert "HAVING COUNT(*) > 1" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in sql
    assert "(payment_gateway, gateway_order_id)" in sql
    assert "Migration 049" in sql


def test_migration_051_rollback_only_drops_its_own_index():
    sql = (
        ROOT / "data" / "051_unique_subscription_gateway_order_rollback.sql"
    ).read_text()

    assert "DROP INDEX IF EXISTS public.uq_cso_payment_gateway_order_id" in sql
    assert "DROP TABLE" not in sql.upper()
