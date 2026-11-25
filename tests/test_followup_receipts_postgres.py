"""Exercise the receipts migration on a disposable PostgreSQL cluster without a listener."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import pytest


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


@pytest.mark.skipif(os.getenv("RUN_LOCAL_POSTGRES_TESTS") != "1", reason="isolated PostgreSQL check is opt-in")
def test_receipts_match_company_phone_once_and_restore_previous_view():
    binaries = Path(os.environ.get("POSTGRES_BIN", r"C:\Program Files\PostgreSQL\18\bin"))
    if not (binaries / "postgres.exe").is_file():
        pytest.skip("local PostgreSQL binaries unavailable")
    fixture = """
        CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;
        CREATE TABLE companies(id bigint PRIMARY KEY);
        CREATE TABLE chatbots(id bigint PRIMARY KEY, company_id bigint);
        CREATE TABLE whatsapp_channels(id bigint PRIMARY KEY);
        CREATE TABLE conversations(id bigint, chatbot_id bigint, source_channel text, platform_user_id text, customer_phone text);
        CREATE TABLE messages(id bigint, conversation_id bigint, sender_type text, delivery_status text, message_type text,
                              ai_generated boolean, follow_up_sent_at timestamptz);
        CREATE TABLE follow_ups(id bigint, company_id bigint, chatbot_id bigint, conversation_id bigint,
                                platform text, legacy_touch_times timestamptz[]);
        CREATE TABLE marketing_consents(company_id bigint, platform text, platform_user_id text, phone_digits text,
                                        status text, withdrawn_at timestamptz);
        INSERT INTO chatbots VALUES (2,1);
        INSERT INTO conversations VALUES (3,2,'whatsapp_link','555123@lid','+60123456789'),
                                         (4,2,'telegram','123','+60123456789'),
                                         (5,2,'whatsapp','60111111111','+60111111111');
        INSERT INTO messages VALUES (8,3,'bot','sent','text',true,'2026-11-01'),
                                    (9,4,'bot','sent','text',true,'2026-11-01'),
                                    (10,5,'bot','read','template',false,'2026-11-01');
        INSERT INTO follow_ups VALUES (6,1,2,3,'whatsapp_link',ARRAY['2026-11-02'::timestamptz]);
        INSERT INTO marketing_consents VALUES
            (1,'whatsapp_link','60123456789@c.us','60123456789','withdrawn','2026-11-03'),
            (1,'whatsapp','60123456789','60123456789','withdrawn','2026-11-04'),
            (2,'whatsapp','60123456789','60123456789','withdrawn','2026-11-05'),
            (1,'whatsapp_link','555123@lid',NULL,'granted',NULL),
            (1,'whatsapp','60111111111',NULL,'withdrawn','2026-11-06');
    """
    snapshot = """
        CREATE TEMP VIEW metadata AS SELECT oid,relowner,reloptions,relacl FROM pg_class
        WHERE oid='public.follow_up_receipts'::regclass;
        CREATE TEMP TABLE original AS SELECT *,pg_get_viewdef(oid) AS definition FROM metadata;
    """
    checks = """
        DO $$ BEGIN
          IF (SELECT count(*) FROM follow_up_receipts) <> 4 OR
             (SELECT count(*) FROM follow_up_receipts WHERE conversation_id=3 AND withdrawn_at='2026-11-04') <> 2 OR
             (SELECT count(*) FROM follow_up_receipts WHERE conversation_id=4 AND withdrawn_at IS NULL) <> 1 OR
             (SELECT count(*) FROM follow_up_receipts WHERE conversation_id=5 AND withdrawn_at='2026-11-06') <> 1
          THEN RAISE EXCEPTION 'incorrect receipt count or withdrawal'; END IF;
          IF EXISTS (SELECT * FROM metadata EXCEPT SELECT oid,relowner,reloptions,relacl FROM original)
          THEN RAISE EXCEPTION 'view permissions or identity changed'; END IF;
        END $$;
    """
    restored = """
        DO $$ BEGIN
          IF EXISTS (SELECT *,pg_get_viewdef(oid) FROM metadata EXCEPT SELECT * FROM original)
          THEN RAISE EXCEPTION 'rollback did not restore view'; END IF;
        END $$;
    """
    with TemporaryDirectory(prefix="receipts-pg-", dir=ROOT) as directory:
        subprocess.run([binaries / "initdb.exe", "-D", directory, "-U", "postgres", "-A", "trust",
                        "--no-locale", "-E", "UTF8"], capture_output=True, check=True, timeout=60)

        previous = (DATA / "091_whatsapp_templates.sql").read_text()
        migration = (DATA / "095_followup_receipts_phone_withdrawals.sql").read_text()
        rollback = (DATA / "095_followup_receipts_phone_withdrawals_rollback.sql").read_text()
        sql = fixture + previous + snapshot + migration + checks + rollback + restored
        statement = "\n".join(line for line in sql.splitlines() if line.strip()) + "\n\n"
        result = subprocess.run([binaries / "postgres.exe", "--single", "-j", "-D", directory, "postgres"],
                                input=statement, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert "ERROR:" not in result.stderr and "FATAL:" not in result.stderr, result.stderr
