"""Opt-in migration drill against an explicitly named, empty local QA database."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from threading import Barrier

import pytest


@pytest.mark.skipif(not os.getenv("LOCAL_WEB_WIDGET_POSTGRES_QA_PORT"),
                    reason="requires an explicitly supplied isolated local PostgreSQL database")
def test_open_web_session_uniqueness_under_concurrent_first_messages():
    database = os.environ["LOCAL_WEB_WIDGET_POSTGRES_QA_DATABASE"]
    assert database.startswith("widget_uniqueness_qa_"), "Only an empty throwaway database is allowed"
    binaries = Path(os.environ.get("POSTGRES_BIN", r"C:\Program Files\PostgreSQL\18\bin"))

    def sql(statement, *, check=True):
        result = subprocess.run(
            [str(binaries / "psql.exe"), "-XAtq", "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose",
             "-h", "127.0.0.1", "-p", os.environ["LOCAL_WEB_WIDGET_POSTGRES_QA_PORT"],
             "-U", "postgres", "-d", database, "-f", "-"],
            input=statement, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PGCLIENTENCODING": "UTF8"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if check:
            assert result.returncode == 0, result.stderr
        return result

    sql("""CREATE TABLE public.conversations (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        chatbot_id bigint NOT NULL, platform_user_id text, customer_phone text,
        source_channel text, source_channel_id bigint, conversation_status text DEFAULT 'open'
    );
    CREATE UNIQUE INDEX legacy_phone_key ON conversations(chatbot_id,customer_phone,source_channel)
      WHERE conversation_status='open' AND source_channel_id IS NULL;
    """)
    migration = Path(__file__).parents[1] / "data" / "061_web_widget_session_uniqueness.sql"
    sql(migration.read_text(encoding="utf-8"))
    barrier = Barrier(2)

    def first_message(_):
        barrier.wait(timeout=5)
        return sql("INSERT INTO conversations(chatbot_id,platform_user_id,source_channel) "
                   "VALUES(7,'web_same_visitor','web') RETURNING id", check=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(first_message, range(2)))
    assert sum(result.returncode == 0 for result in outcomes) == 1
    assert "23505" in next(result.stderr for result in outcomes if result.returncode != 0)
    assert sql("SELECT count(*) FROM conversations").stdout.strip() == "1"

    sql("""INSERT INTO conversations(chatbot_id,platform_user_id,source_channel) VALUES
       (8,'web_same_visitor','web'), (7,'web_other_visitor','web'),
       (7,'web_same_visitor','telegram');
       UPDATE conversations SET conversation_status='closed'
         WHERE chatbot_id=7 AND platform_user_id='web_same_visitor' AND source_channel='web';
       INSERT INTO conversations(chatbot_id,platform_user_id,source_channel)
         VALUES(7,'web_same_visitor','web');
    """)
    assert sql("SELECT count(*) FROM conversations").stdout.strip() == "5"
    assert sql("SELECT count(*) FROM conversations WHERE chatbot_id=7 AND platform_user_id='web_same_visitor' "
               "AND source_channel='web' AND conversation_status='open'").stdout.strip() == "1"
    assert sql("SELECT indisvalid AND indisunique FROM pg_index "
               "WHERE indexrelid='public.unique_open_web_widget_session'::regclass").stdout.strip() == "t"
