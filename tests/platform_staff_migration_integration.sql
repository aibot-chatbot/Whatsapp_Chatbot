-- Run only against an empty, disposable PostgreSQL database as its test owner.
-- psql -v ON_ERROR_STOP=1 -f tests/platform_staff_migration_integration.sql
\set ON_ERROR_STOP on
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role NOLOGIN BYPASSRLS; END IF;
END $$;
CREATE TABLE public.companies(id bigint PRIMARY KEY);
CREATE TABLE public.users(id bigint PRIMARY KEY, company_id bigint REFERENCES companies(id), status text, role text, full_name text, email text);
GRANT SELECT, UPDATE ON public.users TO service_role;
GRANT SELECT ON public.companies TO service_role;
\ir ../data/023_create_platform_admin_users.sql
\ir ../data/024_create_platform_admin_audit_events.sql
\ir ../data/025_enable_platform_admin_rls.sql
\ir ../data/026_enforce_platform_admin_audit_append_only.sql
\ir ../data/034_platform_admin_user_management.sql
\ir ../data/053_platform_staff_roles_approvals.sql
-- Reapplying must be safe and retain the existing objects.
\ir ../data/053_platform_staff_roles_approvals.sql

INSERT INTO public.companies VALUES (100),(200);
INSERT INTO public.users VALUES
 (10,100,'active','member','Test Super','super@example.test'),
 (20,100,'active','member','Test Billing','billing@example.test'),
 (30,100,'active','member','Test Empty','empty@example.test'),
 (40,100,'active','member','Test New Staff','new@example.test'),
 (50,200,'active','owner','Test Tenant','tenant@example.test');
INSERT INTO public.platform_admin_protected_companies(company_id) VALUES (100);
INSERT INTO public.platform_admin_users(user_id,platform_role,modules) VALUES
 (10,'super_admin','{"billing":true,"support":true,"customers":true}'),
 (20,'admin','{"billing":true,"support":false,"customers":false}'),
 (30,'admin','{"billing":false,"support":false,"customers":false}');

DO $$ BEGIN
 IF has_function_privilege('anon','public.set_platform_staff_access(bigint,bigint,text,jsonb,text,boolean)','EXECUTE')
 OR has_function_privilege('authenticated','public.create_platform_approval_request(bigint,text,bigint,text,text)','EXECUTE')
 OR has_function_privilege('anon','public.protect_platform_staff_account_status()','EXECUTE')
 OR has_function_privilege('authenticated','public.protect_platform_staff_account_status()','EXECUTE')
 OR has_table_privilege('authenticated','public.platform_approval_requests','SELECT') THEN
   RAISE EXCEPTION 'Tenant role has staff privileges';
 END IF;
 IF (SELECT prosecdef FROM pg_proc WHERE oid='public.protect_platform_staff_account_status()'::regprocedure)
 OR NOT has_table_privilege('service_role','public.platform_admin_users','SELECT')
 OR NOT has_table_privilege('service_role','public.platform_admin_users','UPDATE') THEN
   RAISE EXCEPTION 'Status guard privilege boundary is incorrect';
 END IF;
 IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid='public.platform_approval_requests'::regclass) THEN
   RAISE EXCEPTION 'RLS is disabled';
 END IF;
END $$;
SET ROLE service_role;
DO $$ BEGIN
 BEGIN
   PERFORM public.create_platform_admin_user_mapping(2,40);
   RAISE EXCEPTION 'Admin was allowed to create staff';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
   PERFORM public.create_platform_admin_user_mapping(1,50);
   RAISE EXCEPTION 'Tenant was allowed as platform staff';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM public.create_platform_admin_user_mapping(1,40);
 IF NOT EXISTS(SELECT 1 FROM platform_admin_users WHERE user_id=40 AND platform_role='admin'
   AND modules='{"billing":false,"support":false,"customers":false}'::jsonb) THEN
   RAISE EXCEPTION 'New staff did not start with zero grants';
 END IF;
 BEGIN
   PERFORM public.create_platform_approval_request(3,'refund',200,'Test refund','Test reason');
   RAISE EXCEPTION 'Unassigned billing access was allowed';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
   PERFORM public.set_platform_staff_access(1,1,'admin','{"billing":true,"support":true,"customers":true}','Test self demotion');
   RAISE EXCEPTION 'Self demotion was allowed';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
   PERFORM public.set_platform_staff_access(1,2,'admin','{"billing":"true","support":true,"customers":true}','Test invalid grant');
   RAISE EXCEPTION 'String boolean was allowed';
 EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 PERFORM public.set_platform_staff_access(1,2,'admin','{"billing":true,"support":true,"customers":false}','Test grant update');
 PERFORM public.create_platform_approval_request(2,'refund',200,'Test refund','Test approval reason');
 BEGIN
   PERFORM public.decide_platform_approval_request(2,1,'approved','Test unauthorized decision');
   RAISE EXCEPTION 'Admin decided an approval';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 PERFORM public.decide_platform_approval_request(1,1,'approved','Test accepted decision');
 BEGIN
   PERFORM public.decide_platform_approval_request(1,1,'rejected','Test conflicting decision');
   RAISE EXCEPTION 'Already decided approval changed';
 EXCEPTION WHEN unique_violation THEN NULL; END;
 IF (SELECT status FROM public.platform_approval_requests WHERE id=1) <> 'approved' THEN
   RAISE EXCEPTION 'Original decision was not retained';
 END IF;
 IF (SELECT count(*) FROM public.platform_admin_audit_events) <> 4 THEN
   RAISE EXCEPTION 'Denied writes changed audit state or successful audit missing';
 END IF;
END $$;
RESET ROLE;
REVOKE INSERT ON public.platform_admin_audit_events FROM service_role;
SET ROLE service_role;
DO $$ BEGIN
 BEGIN
   PERFORM public.set_platform_staff_access(1,2,'admin','{"billing":false,"support":false,"customers":true}','Test unavailable audit');
   RAISE EXCEPTION 'Write succeeded without an audit';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF (SELECT modules FROM public.platform_admin_users WHERE id=2) <> '{"billing":true,"support":true,"customers":false}'::jsonb THEN
   RAISE EXCEPTION 'Permission write did not roll back with failed audit';
 END IF;
END $$;
RESET ROLE;
GRANT INSERT ON public.platform_admin_audit_events TO service_role;
SET ROLE service_role;
DO $$ DECLARE v_user_id bigint; BEGIN
 -- The sole Super and every active staff mapping are protected, regardless of
 -- their underlying tenant role or whether the writer uses a platform RPC.
 FOREACH v_user_id IN ARRAY ARRAY[10,20,30,40] LOOP
   BEGIN
     UPDATE public.users SET status='inactive' WHERE id=v_user_id;
     RAISE EXCEPTION 'Tenant status write deactivated active platform staff';
   EXCEPTION WHEN insufficient_privilege THEN
     IF SQLERRM <> 'platform_staff_account_protected' THEN RAISE; END IF;
   END;
 END LOOP;
 BEGIN
   UPDATE public.users SET status=NULL WHERE id=10;
   RAISE EXCEPTION 'NULL status disabled the sole Super';
 EXCEPTION WHEN insufficient_privilege THEN
   IF SQLERRM <> 'platform_staff_account_protected' THEN RAISE; END IF;
 END;
 -- A bulk update also rolls back ordinary users when a protected user matches.
 BEGIN
   UPDATE public.users SET status='inactive' WHERE id IN (10,50);
   RAISE EXCEPTION 'Bulk status write disabled platform staff';
 EXCEPTION WHEN insufficient_privilege THEN
   IF SQLERRM <> 'platform_staff_account_protected' THEN RAISE; END IF;
 END;
 IF EXISTS (SELECT 1 FROM public.users WHERE status IS DISTINCT FROM 'active') THEN
   RAISE EXCEPTION 'Rejected status changes were not atomic';
 END IF;
 UPDATE public.users SET status='inactive' WHERE id=50;
 IF (SELECT status FROM public.users WHERE id=50) <> 'inactive' THEN
   RAISE EXCEPTION 'Ordinary tenant deactivation was blocked';
 END IF;
 UPDATE public.users SET status='active' WHERE id=50;
 UPDATE public.users SET status='active', full_name='Test Super renamed' WHERE id=10;
 -- Revocation must happen first through the audited Super-only lifecycle RPC.
 PERFORM public.set_platform_admin_user_active(1,3,FALSE);
 UPDATE public.users SET status='inactive' WHERE id=30;
 IF (SELECT status FROM public.users WHERE id=30) <> 'inactive' THEN
   RAISE EXCEPTION 'Revoked staff could not be deactivated';
 END IF;
 BEGIN
   PERFORM public.set_platform_admin_user_active(1,3,TRUE);
   RAISE EXCEPTION 'Inactive identity regained an active mapping';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 UPDATE public.users SET status='active' WHERE id=30;
 PERFORM public.set_platform_admin_user_active(1,3,TRUE);
 IF NOT EXISTS (SELECT 1 FROM public.platform_admin_users m JOIN public.users u ON u.id=m.user_id
                WHERE m.platform_role='super_admin' AND m.is_active AND u.status='active') THEN
   RAISE EXCEPTION 'No usable Super remains';
 END IF;
END $$;
RESET ROLE;
SELECT 'PASS: migration reapplied; role/module/tenant gates; audited grants; decisions; audit rollback; staff account protection' AS result;
