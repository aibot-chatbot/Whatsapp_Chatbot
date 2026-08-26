-- Harden service_role privileges on temporary supporting-PDF candidates.
-- Migration 045 created the table and candidate linkage. This follow-up
-- removes any broader service_role privileges, then grants only the CRUD
-- operations used by backend repository code.

revoke all privileges on table public.knowledge_pdf_candidates
    from service_role;

grant select, insert, update, delete on table public.knowledge_pdf_candidates
    to service_role;
