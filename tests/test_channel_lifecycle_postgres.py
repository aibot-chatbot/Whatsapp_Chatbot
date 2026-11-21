"""Opt-in isolated PostgreSQL validation; no network or application credentials."""

import os
from pathlib import Path
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.mark.skipif(os.getenv("RUN_LOCAL_POSTGRES_TESTS") != "1", reason="isolated PostgreSQL check is opt-in")
def test_channel_lifecycle_transaction_and_origin_guards():
    binaries = Path(os.environ.get("POSTGRES_BIN", r"C:\Program Files\PostgreSQL\18\bin"))
    if not (binaries / "postgres.exe").is_file():
        pytest.skip("PostgreSQL binaries unavailable")
    # Keep the isolated database as reproducible evidence. Nothing listens on a
    # socket and no production service/environment configuration is loaded.
    directory = Path(tempfile.mkdtemp(prefix="unified-channel-sql-"))
    initialized = subprocess.run([str(binaries / "initdb.exe"), "-D", str(directory), "-U", "postgres",
                                  "-A", "trust", "--no-locale", "-E", "UTF8"],
                                 capture_output=True, text=True, check=False)
    assert initialized.returncode == 0, initialized.stderr
    fixture = """
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;
CREATE TABLE public.companies(id bigint PRIMARY KEY);
CREATE TABLE public.chatbots(id bigint PRIMARY KEY,company_id bigint,status text DEFAULT 'active',deleted_at timestamptz);
CREATE TABLE public.telegram_channels(id bigint PRIMARY KEY,company_id bigint,chatbot_id bigint,telegram_bot_id text,connection_status text,is_active boolean,created_at timestamptz DEFAULT now(),last_error text);
CREATE TABLE public.whatsapp_channels(id bigint PRIMARY KEY,company_id bigint,chatbot_id bigint,phone_number_id text UNIQUE,connection_status text,is_active boolean,created_at timestamptz DEFAULT now(),last_error text);
CREATE TABLE public.legacy_channels(id bigint PRIMARY KEY,company_id bigint,chatbot_id bigint,session_id text,phone_number text,connection_status text,is_active boolean,created_at timestamptz DEFAULT now(),last_error text);
CREATE TABLE public.conversations(id bigint PRIMARY KEY,chatbot_id bigint,customer_phone text,platform_user_id text,source_channel text,conversation_status text);
CREATE UNIQUE INDEX unique_open_conversation_per_channel ON public.conversations(chatbot_id,customer_phone,source_channel) WHERE conversation_status='open';
CREATE TABLE public.agent_actions(id bigint PRIMARY KEY,chatbot_id bigint,company_id bigint,conversation_id bigint,intent text,status text);
INSERT INTO public.companies VALUES(1),(2);
INSERT INTO public.chatbots(id,company_id) VALUES(10,1),(11,1),(20,2);
"""
    migration = (Path(__file__).parents[1] / "data" / "058_unified_channel_lifecycle.sql").read_text(encoding="utf-8")
    # Resolve the retired table name from the historical DDL to run the migration verbatim.
    import re
    legacy_table = re.search(r"ALTER TABLE public\.(\w+_channels)[^;]+ADD COLUMN IF NOT EXISTS provider_user_id", migration, re.I).group(1)
    fixture = fixture.replace("legacy_channels", legacy_table)
    checks = """
INSERT INTO public.telegram_channels(id,company_id,chatbot_id,telegram_bot_id,connection_status,is_active,connection_attempted_at,verified_at)
VALUES (1,1,10,'old','connected',true,'2026-09-10','2026-09-10'),(2,1,10,'new','pending',true,'2026-09-14','2026-09-14'),
(3,1,10,'reservation','pending',true,'2026-09-13',null),(4,1,11,'quota','pending',true,'2026-09-14','2026-09-14');
DO $test$ DECLARE result jsonb; BEGIN
  result := public.activate_verified_channel('telegram',2,10,1,1,'2026-09-14');
  IF result->>'id' <> '2' THEN RAISE EXCEPTION 'replacement failed'; END IF;
  IF (SELECT is_active FROM public.telegram_channels WHERE id=1) THEN RAISE EXCEPTION 'old still active'; END IF;
  IF NOT (SELECT is_active FROM public.telegram_channels WHERE id=3) THEN RAISE EXCEPTION 'reservation lost'; END IF;
  BEGIN
    PERFORM public.activate_verified_channel('telegram',4,11,1,1,'2026-09-14');
    RAISE EXCEPTION 'quota not enforced';
  EXCEPTION WHEN raise_exception THEN IF SQLERRM <> 'channel_limit_reached' THEN RAISE; END IF; END;
  BEGIN
    PERFORM public.activate_verified_channel('telegram',4,11,2,10,'2026-09-14');
    RAISE EXCEPTION 'tenant bypass';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  IF public.activate_verified_channel('telegram',3,10,1,10,NULL) IS NOT NULL THEN RAISE EXCEPTION 'unverified activation'; END IF;
  IF public.activate_verified_channel('telegram',4,11,1,10,'2026-09-15') IS NOT NULL THEN RAISE EXCEPTION 'stale same-row activation'; END IF;
  UPDATE public.telegram_channels SET verified_at='2026-09-14' WHERE id=3;
  IF public.activate_verified_channel('telegram',3,10,1,10,'2026-09-13') IS NOT NULL THEN RAISE EXCEPTION 'older replaced newer'; END IF;
  IF (SELECT connection_status FROM public.telegram_channels WHERE id=3) <> 'failed' THEN RAISE EXCEPTION 'stale attempt hidden'; END IF;
  BEGIN
    UPDATE public.telegram_channels SET telegram_bot_id='other' WHERE id=2;
    RAISE EXCEPTION 'identity mutable';
  EXCEPTION WHEN check_violation THEN NULL; END;
  IF has_function_privilege('authenticated','public.activate_verified_channel(text,bigint,bigint,bigint,integer,timestamptz)','EXECUTE') THEN RAISE EXCEPTION 'browser activation permitted'; END IF;
END; $test$;
INSERT INTO public.legacy_channels(id,company_id,chatbot_id,session_id,connection_status,is_active,connection_attempted_at,verified_at)
VALUES(5,1,11,'s1','pending',true,'2026-09-14','2026-09-14');
DO $test$ BEGIN
  IF public.activate_verified_channel('legacy',5,11,1,10,NULL) IS NOT NULL THEN RAISE EXCEPTION 'missing identity activated'; END IF;
END; $test$;
INSERT INTO public.legacy_channels(id,company_id,chatbot_id,phone_number,connection_status,is_active)
VALUES(6,1,10,'+60 123456789','connected',true);
DO $test$ BEGIN
  BEGIN
    INSERT INTO public.legacy_channels(id,company_id,chatbot_id,phone_number,provider_user_id,connection_status,is_active)
    VALUES(7,2,20,'+60123456789','+60123456789','pending',true);
    RAISE EXCEPTION 'legacy provider reservation bypass';
  EXCEPTION WHEN unique_violation THEN NULL; END;
END; $test$;
INSERT INTO public.conversations(id,chatbot_id,customer_phone,source_channel,conversation_status,source_channel_id,source_provider_id)
VALUES(100,10,'customer','telegram','open',1,'old'),(101,10,'customer','telegram','open',2,'new'),(102,10,'customer','telegram','open',NULL,NULL);
INSERT INTO public.conversations(id,chatbot_id,customer_phone,platform_user_id,source_channel,conversation_status,source_channel_id,source_provider_id)
VALUES(103,10,NULL,'-1001','telegram','open',2,'new'),(104,10,NULL,'-1002','telegram','open',2,'new'),
(105,10,NULL,'123','telegram','open',2,'new'),(107,10,NULL,'456','telegram','open',2,'new');
INSERT INTO public.agent_actions VALUES(20,10,1,100,'handoff_request','detected'),(21,10,1,100,'complaint','detected');
DO $test$ DECLARE result jsonb; BEGIN
  BEGIN
    UPDATE public.conversations SET source_channel_id=2,source_provider_id='new' WHERE id=100;
    RAISE EXCEPTION 'origin mutable';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN
    UPDATE public.conversations SET platform_user_id='123' WHERE id=103;
    RAISE EXCEPTION 'Telegram chat destination mutable';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN
    UPDATE public.conversations SET platform_user_id=NULL WHERE id=103;
    RAISE EXCEPTION 'Telegram chat destination removable';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN
    INSERT INTO public.conversations(id,chatbot_id,platform_user_id,source_channel,conversation_status,source_channel_id,source_provider_id)
    VALUES(106,10,'-1001','telegram','open',2,'new');
    RAISE EXCEPTION 'duplicate Telegram chat allowed';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  UPDATE public.conversations SET customer_phone='+60123456789' WHERE id=105;
  IF (SELECT platform_user_id FROM public.conversations WHERE id=105) <> '123' THEN RAISE EXCEPTION 'phone changed destination'; END IF;
  -- Telegram phone text is profile data: another chat cannot reserve it.
  UPDATE public.conversations SET customer_phone='+60123456789' WHERE id=107;
  IF (SELECT count(*) FROM public.conversations WHERE id IN (105,107) AND customer_phone='+60123456789') <> 2 THEN
    RAISE EXCEPTION 'Telegram phone profile blocked another chat';
  END IF;
  INSERT INTO public.conversations(id,chatbot_id,customer_phone,source_channel,conversation_status,source_channel_id,source_provider_id)
  VALUES(108,10,'+60123456789','whatsapp','open',2,'meta-number');
  BEGIN
    INSERT INTO public.conversations(id,chatbot_id,customer_phone,source_channel,conversation_status,source_channel_id,source_provider_id)
    VALUES(109,10,'+60123456789','whatsapp','open',2,'meta-number');
    RAISE EXCEPTION 'duplicate WhatsApp phone identity allowed';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  result := public.resolve_conversation_escalation(20,10,1);
  IF result->>'changed'<>'true' OR result->>'ai_resumed'<>'false' THEN RAISE EXCEPTION 'early AI resume'; END IF;
  result := public.resolve_conversation_escalation(21,10,1);
  IF result->>'ai_resumed'<>'true' THEN RAISE EXCEPTION 'AI still paused'; END IF;
  result := public.resolve_conversation_escalation(21,10,1);
  IF result->>'changed'<>'false' THEN RAISE EXCEPTION 'duplicate resolve notification'; END IF;
  IF public.resolve_conversation_escalation(21,10,2) IS NOT NULL THEN RAISE EXCEPTION 'resolve tenant bypass'; END IF;
END; $test$;
INSERT INTO public.agent_actions VALUES(22,10,1,102,'handoff_request','detected');
DO $test$ DECLARE result jsonb; BEGIN
  result := public.resolve_conversation_escalation(21,10,1);
  IF result->>'ai_resumed'<>'false' THEN RAISE EXCEPTION 'legacy handoff bypass'; END IF;
END; $test$;
SELECT 'UNIFIED_LIFECYCLE_SQL_PASSED';
"""
    sql = "\n".join(line for line in (fixture + migration + checks.replace("legacy_channels", legacy_table).replace("'legacy'", repr(legacy_table.removesuffix("_channels")))).splitlines() if line.strip()) + "\n\n"
    result = subprocess.run([str(binaries / "postgres.exe"), "--single", "-j", "-D", str(directory), "postgres"],
                            input=sql, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "ERROR:" not in result.stderr and "FATAL:" not in result.stderr, result.stderr
    assert "UNIFIED_LIFECYCLE_SQL_PASSED" in result.stdout, result.stdout
    print(f"Isolated SQL evidence retained at {directory}")


@pytest.mark.skipif(os.getenv("LOCAL_POSTGRES_QA_PORT") is None, reason="requires explicitly supplied isolated QA database")
def test_simultaneous_activation_quota_and_final_resolve():
    binaries = Path(os.environ.get("POSTGRES_BIN", r"C:\Program Files\PostgreSQL\18\bin"))
    port = os.environ["LOCAL_POSTGRES_QA_PORT"]

    def sql(command):
        return subprocess.run([str(binaries / "psql.exe"), "-XAtq", "-v", "ON_ERROR_STOP=1",
                               "-h", "127.0.0.1", "-p", port, "-U", "postgres", "-d", "postgres"],
                              input=command, capture_output=True, text=True, check=False)

    # This opt-in database was created by the preceding isolated fixture. Apply
    # the current migration again to validate its safe rerun behavior as well.
    migration = (Path(__file__).parents[1] / "data" / "058_unified_channel_lifecycle.sql").read_text(encoding="utf-8")
    result = sql(migration)
    assert result.returncode == 0, result.stderr
    result = sql("""
INSERT INTO companies VALUES(30),(40);
INSERT INTO chatbots(id,company_id) VALUES(30,30),(31,30),(40,40);
INSERT INTO telegram_channels(id,company_id,chatbot_id,telegram_bot_id,is_active,connection_status,connection_attempted_at,verified_at)
VALUES(30,30,30,'concurrent-tg',true,'pending','2026-09-14','2026-09-14');
INSERT INTO whatsapp_channels(id,company_id,chatbot_id,phone_number_id,is_active,connection_status,connection_attempted_at,verified_at)
VALUES(31,30,31,'concurrent-meta',true,'pending','2026-09-14','2026-09-14');
INSERT INTO conversations(id,chatbot_id,customer_phone,source_channel,conversation_status) VALUES(400,40,'test','web','open');
INSERT INTO agent_actions VALUES(400,40,40,400,'handoff_request','detected'),(401,40,40,400,'complaint','detected');
INSERT INTO telegram_channels(id,company_id,chatbot_id,telegram_bot_id,is_active,connection_status,connection_attempted_at,verified_at)
VALUES(40,40,40,'older-concurrent',true,'pending','2026-09-13','2026-09-14'),(41,40,40,'newer-concurrent',true,'pending','2026-09-14','2026-09-14');
INSERT INTO companies VALUES(50);
INSERT INTO chatbots(id,company_id) VALUES(50,50),(51,50);
INSERT INTO telegram_channels(id,company_id,chatbot_id,telegram_bot_id,is_active,connection_status,connection_attempted_at,verified_at,connection_slot_reserved)
VALUES(50,50,50,'repairing',true,'pending','2026-09-14','2026-09-14',true);
INSERT INTO whatsapp_channels(id,company_id,chatbot_id,phone_number_id,is_active,connection_status,connection_attempted_at,verified_at)
VALUES(51,50,51,'cannot-steal-repair-slot',true,'pending','2026-09-14','2026-09-14');
DO $test$ BEGIN
  BEGIN
    PERFORM activate_verified_channel('whatsapp',51,51,50,1,NULL);
    RAISE EXCEPTION 'repair slot lost';
  EXCEPTION WHEN raise_exception THEN IF SQLERRM <> 'channel_limit_reached' THEN RAISE; END IF; END;
  IF activate_verified_channel('telegram',50,50,50,1,NULL)->>'id' <> '50' THEN RAISE EXCEPTION 'repair rejected at limit'; END IF;
END; $test$;
""")
    assert result.returncode == 0, result.stderr
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sql, "BEGIN; SELECT id FROM companies WHERE id=30 FOR UPDATE; SELECT pg_sleep(0.3); SELECT activate_verified_channel('telegram',30,30,30,1,NULL); COMMIT;")
        second = pool.submit(sql, "SELECT activate_verified_channel('whatsapp',31,31,30,1,NULL);")
        outcomes = [first.result(), second.result()]
    assert sum(outcome.returncode == 0 for outcome in outcomes) == 1, [(o.stdout,o.stderr) for o in outcomes]
    assert any("channel_limit_reached" in outcome.stderr for outcome in outcomes)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sql, "SELECT activate_verified_channel('telegram',40,40,40,3,NULL);")
        second = pool.submit(sql, "SELECT activate_verified_channel('telegram',41,40,40,3,NULL);")
        outcomes = [first.result(), second.result()]
    assert all(outcome.returncode == 0 for outcome in outcomes), [o.stderr for o in outcomes]
    assert sql("SELECT id FROM telegram_channels WHERE chatbot_id=40 AND is_active AND connection_status='connected';").stdout.strip() == '41'
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sql, "SELECT resolve_conversation_escalation(400,40,40)->>'ai_resumed';")
        second = pool.submit(sql, "SELECT resolve_conversation_escalation(401,40,40)->>'ai_resumed';")
        outcomes = [first.result(), second.result()]
    assert all(outcome.returncode == 0 for outcome in outcomes), [o.stderr for o in outcomes]
    assert sorted(outcome.stdout.strip() for outcome in outcomes) == ['false','true']
