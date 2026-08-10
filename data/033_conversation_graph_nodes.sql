-- 033_conversation_graph_nodes.sql
-- Conversation-scoped graph memory: facts the bot learns mid-chat (the
-- customer's name, a contact detail, a stated interest) persisted as nodes that
-- a later turn in the SAME conversation can recall by keyword.
--
-- This is a NEW relation. It deliberately does not extend
-- public.knowledge_graph_nodes / public.knowledge_graph_edges. Two reasons, both
-- blocking:
--
--   1. No CREATE TABLE for either document-graph table exists anywhere in
--      data/. Their real column list, types, constraints and existing indexes
--      are unknown, so no ALTER against them can be safely specified from the
--      repository layer alone. (Compare data/030_bot_media_attachments.sql:5-8,
--      which reconstructs a table's DDL from its repository and says so; that
--      was viable because 030's table had a single writer. Here the required
--      change would be to a UNIQUE KEY, which reconstruction cannot verify.)
--   2. knowledge_graph_repository.upsert_node upserts on the key
--      (chatbot_id, name). Two concurrent conversations that each learn a
--      customer name would collide on one row and overwrite each other -- a
--      cross-conversation leak of personal data. Storing conversation facts in
--      that table is not merely awkward, it is incorrect.
--
-- Consumed by:
--   app/database/conversation_graph_repository.py
--   app/services/conversation_memory_service.py
--   app/services/rag_service.py  (retrieve_relevant_chunks, conversation_id arg)
--
-- APPLY PREREQUISITE: run scripts/conversation_graph_nodes_preflight.sql and
-- attach its output to the change record. public.chatbots and public.conversations
-- have no CREATE TABLE anywhere in this repository, so the bigint column types
-- and the ON DELETE behaviour assumed below are unverified until that capture
-- exists.

BEGIN;

-- Both inline foreign keys take SHARE ROW EXCLUSIVE on public.conversations and
-- public.chatbots for the duration of the CREATE TABLE. That lock conflicts with
-- ROW EXCLUSIVE, i.e. it blocks INSERT/UPDATE/DELETE on the product's two hottest
-- tables, and while this statement waits it queues ahead of every new writer.
-- The hold itself is instant (nothing is scanned; the referencing table is
-- empty), so the only real risk is waiting behind a long-running transaction.
-- Fail fast rather than build a pile-up; re-run in a quieter window.
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.conversation_graph_nodes (
    id                bigserial PRIMARY KEY,

    -- Tenancy. Denormalised from public.conversations.chatbot_id, and filtered
    -- alongside conversation_id on every SELECT and DELETE in the repository, so
    -- a conversation id belonging to another tenant selects zero rows on read.
    --
    -- It is NOT a predicate on the write path, and this schema does not enforce
    -- that it agrees with the parent conversation. See "TENANCY IS NOT ENFORCED
    -- BY THIS SCHEMA" below before treating it as an isolation boundary.
    chatbot_id        bigint NOT NULL
                          REFERENCES public.chatbots (id) ON DELETE CASCADE,

    -- The conversation binding. This column IS the scope: a fact belongs to
    -- exactly one conversation and is invisible outside it.
    conversation_id   bigint NOT NULL
                          REFERENCES public.conversations (id) ON DELETE CASCADE,

    -- Keyword handle, stored lowercase and whitespace-collapsed by
    -- conversation_graph_repository.normalize_label. Query words are reduced to
    -- the same form, which is what makes the lookup a plain equality match.
    label             text NOT NULL,

    -- The remembered value ("Alice", "ORD-4417"). Capped by the application at
    -- 500 chars; the CHECK below is the backstop.
    value             text NOT NULL,

    fact_type         text NOT NULL DEFAULT 'attribute',
    properties        jsonb NOT NULL DEFAULT '{}'::jsonb,

    created_at        timestamp with time zone NOT NULL DEFAULT now(),
    updated_at        timestamp with time zone NOT NULL DEFAULT now(),

    CONSTRAINT conversation_graph_nodes_label_not_blank
        CHECK (btrim(label) <> ''),
    CONSTRAINT conversation_graph_nodes_label_len
        CHECK (char_length(label) <= 120),
    CONSTRAINT conversation_graph_nodes_value_len
        CHECK (char_length(value) <= 500),

    -- Idempotency, and the keyword index. See the note below.
    CONSTRAINT conversation_graph_nodes_conversation_label_key
        UNIQUE (conversation_id, label)
);

-- ---------------------------------------------------------------------------
-- TENANCY IS NOT ENFORCED BY THIS SCHEMA -- KNOWN RESIDUAL RISK
-- ---------------------------------------------------------------------------
-- chatbot_id is denormalised. The authoritative tenant of a fact is
-- public.conversations.chatbot_id for its conversation_id; nothing above checks
-- that the two agree. Two consequences, both real:
--
--   1. The write path is not chatbot-filtered. conversation_graph_repository
--      .upsert_conversation_fact upserts with the conflict target
--      (conversation_id, label) -- chatbot_id is a payload column, not a
--      predicate. An upsert carrying a mismatched (chatbot_id, conversation_id)
--      pair therefore does NOT select zero rows: it takes the DO UPDATE branch,
--      overwrites the existing value, and rewrites that row's chatbot_id,
--      re-tenanting another chatbot's fact. Read and delete ARE chatbot-filtered
--      and do select zero rows.
--   2. Independently of any upsert, no constraint stops a row being inserted
--      with a conversation_id whose conversation belongs to another chatbot.
--
-- Not reachable from untrusted input today: the only producer is
-- chat_pipeline_service.prepare_chat_prompt, which derives conversation_id from
-- get_or_create_conversation(chatbot_id=...). No request-supplied conversation
-- id reaches this table. So this is a missing invariant, not a live exploit --
-- but the value column holds customer names and contact details, and a future
-- caller that accepts a conversation id from a request turns it into one.
--
-- Closing it needs a composite foreign key, whose parent key does not exist yet:
--
--     ALTER TABLE public.conversations
--         ADD CONSTRAINT conversations_id_chatbot_id_key UNIQUE (id, chatbot_id);
--     ALTER TABLE public.conversation_graph_nodes
--         ADD CONSTRAINT conversation_graph_nodes_conversation_tenant_fkey
--         FOREIGN KEY (conversation_id, chatbot_id)
--         REFERENCES public.conversations (id, chatbot_id) ON DELETE CASCADE;
--
-- Deliberately NOT done in this migration. The first statement takes ACCESS
-- EXCLUSIVE on public.conversations and builds an index over every row of the
-- product's hottest table, so it needs its own migration, its own window, and
-- the catalog capture in scripts/conversation_graph_nodes_preflight.sql to
-- confirm conversations.chatbot_id's name, type and nullability first. 027
-- declined the same composite FK for the same missing-parent-key reason -- see
-- data/027_harden_crm_agent_actions.sql:304-306.

-- ---------------------------------------------------------------------------
-- THE KEYWORD INDEX
-- ---------------------------------------------------------------------------
-- The lookup this must serve is exactly one query shape, from
-- conversation_graph_repository.get_conversation_facts_by_labels:
--
--     WHERE chatbot_id = $1 AND conversation_id = $2 AND label IN ($3, $4, ...)
--
-- The UNIQUE constraint above already creates a btree on
-- (conversation_id, label). That index serves this query: conversation_id = $2
-- is a leading equality and label = ANY($3..) is a ScalarArrayOp the btree
-- takes as an index condition, so both become Index Cond. chatbot_id is not in
-- the index, so it lands as a Filter on the heap tuples the index returns.
--
-- The recheck is bounded by the schema, not by an assumption about usage. The
-- UNIQUE constraint permits at most ONE row per (conversation_id, label), and
-- conversation_memory_service.MAX_KEYWORD_TERMS caps the IN list at 24 terms.
-- Rows fetched is therefore <= 24 whatever the conversation's total fact count,
-- so the filter cost does not grow with the table or with a chatty customer.
-- ("A conversation holds few facts" would be a weaker argument -- it is
-- unmeasured, and this query does not depend on it.)
--
-- A separate (chatbot_id, conversation_id, label) index would be redundant with
-- this one: it would cost an extra write per fact and remove at most 24 heap
-- filter evaluations. It is deliberately NOT created.
--
-- Why btree equality and not a text-pattern or trigram index:
--   * Labels are normalised to lowercase at write time AND query words are
--     normalised identically at read time, so the predicate is `=` / `IN`,
--     never LIKE or ILIKE. Equality and IN on a btree are collation
--     independent, so this needs no text_pattern_ops opclass.
--   * `LIKE 'foo%'` would have required text_pattern_ops (or the C collation);
--     `ILIKE '%foo%'` would have required a pg_trgm GIN/GiST index. There is no
--     CREATE EXTENSION anywhere in data/, so pg_trgm's availability on this
--     database is UNVERIFIED. Had the query been written as ILIKE, the index
--     would have failed to create on a database without the extension, and the
--     query would have silently degraded to a sequential scan over every
--     conversation fact for the tenant. Normalised equality avoids that
--     dependency entirely.
--   * Full-text search (tsvector) is the wrong tool: labels are single short
--     handles, not documents. Ranking and stemming buy nothing here.
--
-- Consequence to accept: matching is exact on the normalised label. A query
-- asking for a "phone number" does not match a label stored as "contact".
-- Synonym handling, if it is ever wanted, belongs in the application's term
-- expansion (conversation_memory_service._label_words), not in the index.

-- Explicit cleanup (delete_conversation_facts) and the conversation_id ON DELETE
-- CASCADE both filter on conversation_id, which is the UNIQUE index's leading
-- column, so neither needs an index of its own.
--
-- The chatbot_id cascade does. Deleting a chatbot fires the referential action
--     DELETE FROM public.conversation_graph_nodes WHERE chatbot_id = $1
-- and (conversation_id, label) cannot serve it -- chatbot_id is not the leading
-- column and is not in the index at all. Unindexed, that cascade is a sequential
-- scan over every tenant's facts, taken inside the transaction of
-- public.permanently_delete_archived_chatbot. This is the one query shape the
-- UNIQUE index does not cover, and it is the reason the index-every-foreign-key
-- rule is not optional. Mirrors idx_bot_media_attachments_company in 030.
CREATE INDEX IF NOT EXISTS idx_conversation_graph_nodes_chatbot
    ON public.conversation_graph_nodes (chatbot_id);

-- Keep updated_at honest; the application upserts and does not set it.
--
-- Fires exactly where it should. PostgREST's merge-duplicates upsert is
-- INSERT ... ON CONFLICT (conversation_id, label) DO UPDATE, and the DO UPDATE
-- branch fires BEFORE UPDATE row triggers; the plain-insert branch does not, and
-- there the column DEFAULT now() already supplies the value. The upsert payload
-- omits id and created_at, so neither is disturbed on the update branch.
--
-- search_path is pinned: now() would otherwise resolve through the caller's
-- search_path, and an unpinned function body is what Supabase's
-- function_search_path_mutable advisory flags. Matches 029's
-- reject_platform_support_case_event_mutation.
CREATE OR REPLACE FUNCTION public.touch_conversation_graph_nodes_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path TO pg_catalog
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_conversation_graph_nodes_updated_at
    ON public.conversation_graph_nodes;

CREATE TRIGGER trg_conversation_graph_nodes_updated_at
    BEFORE UPDATE ON public.conversation_graph_nodes
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_conversation_graph_nodes_updated_at();

-- Tenant isolation: the backend uses the service-role key, but RLS is enabled
-- so any future anon/authenticated access is denied by default. Matches the
-- posture established in 025_enable_platform_admin_rls.sql, 029 and 030.
-- NOTE: RLS is a backstop, not the enforcement layer, and it protects nothing
-- the backend does. service_role holds rolbypassrls, so every policy-less table
-- is fully readable and writable by the application regardless. Tenant scoping
-- is enforced in the application, by filtering chatbot_id AND conversation_id --
-- on reads and deletes. NOT on writes: see "TENANCY IS NOT ENFORCED BY THIS
-- SCHEMA" above. Enabling RLS here buys exactly one thing, denial of any future
-- anon/authenticated PostgREST access, and the REVOKEs below buy the same thing
-- a second way.
ALTER TABLE public.conversation_graph_nodes ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.conversation_graph_nodes IS
    'Conversation-scoped facts learned mid-chat. Lifetime is the conversation''s: both FKs cascade on delete.';
COMMENT ON COLUMN public.conversation_graph_nodes.label IS
    'Normalised lowercase keyword handle; matched by equality against normalised query words.';
COMMENT ON COLUMN public.conversation_graph_nodes.value IS
    'CUSTOMER PERSONAL DATA. Names and contact details land here; treat exports accordingly.';

-- Privileges: see the equivalent note in 029/030. service_role needs explicit
-- DML plus sequence USAGE (the PK is bigserial, so INSERT fails without it).
--
-- anon and authenticated get nothing, and that is stated rather than assumed.
-- Supabase's bootstrap runs ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL
-- ON TABLES/SEQUENCES TO anon, authenticated, service_role, so a new public
-- table is granted to the browser roles at creation time unless revoked. RLS
-- with no policy still returns them zero rows, but the grant alone publishes a
-- PostgREST endpoint and its column names for a table whose value column is
-- customer personal data, and RLS does not protect sequences at all. 030 and
-- 029_web_widget_support relied on the RLS backstop alone; 027 and
-- 029_create_platform_admin_support_cases revoke explicitly. Follow the latter.
REVOKE ALL PRIVILEGES ON TABLE public.conversation_graph_nodes
    FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES ON SEQUENCE public.conversation_graph_nodes_id_seq
    FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.conversation_graph_nodes TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.conversation_graph_nodes_id_seq TO service_role;

COMMIT;
