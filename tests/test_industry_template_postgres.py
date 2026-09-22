"""Opt-in migration check in an isolated, socket-free PostgreSQL process."""

import os
from pathlib import Path
import subprocess
import tempfile

import pytest


@pytest.mark.skipif(os.getenv("RUN_LOCAL_POSTGRES_TESTS") != "1", reason="isolated PostgreSQL check is opt-in")
def test_industry_migration_is_additive_repeatable_and_keeps_draft_separate():
    binaries = Path(os.environ.get("POSTGRES_BIN", r"C:\Program Files\PostgreSQL\18\bin"))
    if not (binaries / "postgres.exe").is_file():
        pytest.skip("PostgreSQL binaries unavailable")
    directory = Path(tempfile.mkdtemp(prefix="industry-template-sql-"))
    initialized = subprocess.run(
        [str(binaries / "initdb.exe"), "-D", str(directory), "-U", "postgres",
         "-A", "trust", "--no-locale", "-E", "UTF8"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert initialized.returncode == 0, initialized.stderr
    migration = (Path(__file__).parents[1] / "data/062_chatbot_industry_templates.sql").read_text(encoding="utf-8")
    fixture = """
CREATE TABLE public.chatbots(id bigint PRIMARY KEY, company_id bigint, draft_pdf_path text, deployed_profile_name text);
INSERT INTO public.chatbots VALUES(1,10,'data/menu.pdf','Handwritten profile'),(2,20,'data/clinic.pdf','Other tenant');
"""
    checks = """
DO $test$ BEGIN
  IF (SELECT count(*) FROM public.chatbots WHERE industry_template_draft='{}'::jsonb AND industry_template_published='{}'::jsonb) <> 2 THEN
    RAISE EXCEPTION 'migration silently selected an industry';
  END IF;
  BEGIN
    UPDATE public.chatbots SET industry_template_draft='[]'::jsonb WHERE id=1;
    RAISE EXCEPTION 'draft accepted a non-object';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN
    UPDATE public.chatbots SET industry_template_published='[]'::jsonb WHERE id=1;
    RAISE EXCEPTION 'published accepted a non-object';
  EXCEPTION WHEN check_violation THEN NULL; END;
END; $test$;
UPDATE public.chatbots SET industry_template_draft='{"proposal_id":"a","template_id":"restaurant","source_path":"data/menu.pdf"}'::jsonb WHERE id=1 AND company_id=10;
UPDATE public.chatbots SET industry_template_published='{"proposal_id":"a","template_id":"restaurant","template_version":"1.0.0"}'::jsonb WHERE id=1 AND company_id=10 AND industry_template_draft->>'proposal_id'='a' AND draft_pdf_path='data/menu.pdf' AND industry_template_published->>'proposal_id' IS NULL;
UPDATE public.chatbots SET industry_template_published='{"proposal_id":"a","template_id":"clinic"}'::jsonb WHERE id=1 AND company_id=10 AND industry_template_draft->>'proposal_id'='a' AND industry_template_published->>'proposal_id' IS NULL;
UPDATE public.chatbots SET industry_template_draft='{"proposal_id":"b","template_id":"clinic","source_path":"data/new.pdf"}'::jsonb, draft_pdf_path='data/new.pdf' WHERE id=1;
UPDATE public.chatbots SET industry_template_published='{"proposal_id":"a","template_id":"general"}'::jsonb WHERE id=1 AND company_id=10 AND industry_template_draft->>'proposal_id'='a' AND draft_pdf_path='data/menu.pdf';
DO $test$ BEGIN
  IF (SELECT industry_template_published->>'template_id' FROM public.chatbots WHERE id=1) <> 'restaurant' THEN
    RAISE EXCEPTION 'new draft or stale confirmation changed the active template';
  END IF;
  IF (SELECT deployed_profile_name FROM public.chatbots WHERE id=1) <> 'Handwritten profile' THEN
    RAISE EXCEPTION 'industry update changed the custom profile';
  END IF;
  IF (SELECT industry_template_published FROM public.chatbots WHERE id=2) <> '{}'::jsonb THEN
    RAISE EXCEPTION 'other tenant changed';
  END IF;
END; $test$;
SELECT 'INDUSTRY_TEMPLATE_SQL_PASSED';
"""
    sql = "\n".join(line for line in (fixture + migration + migration + checks).splitlines() if line.strip()) + "\n\n"
    result = subprocess.run(
        [str(binaries / "postgres.exe"), "--single", "-j", "-D", str(directory), "postgres"],
        input=sql, capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ERROR:" not in result.stderr and "FATAL:" not in result.stderr, result.stderr
    assert "INDUSTRY_TEMPLATE_SQL_PASSED" in result.stdout, result.stdout
