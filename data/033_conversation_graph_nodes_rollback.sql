-- 033_conversation_graph_nodes_rollback.sql
-- Reverses data/033_conversation_graph_nodes.sql.
--
-- DESTRUCTIVE: dropping the table discards every remembered conversation fact.
-- Those rows are customer personal data (names, contact details) and are not
-- reconstructible -- the producer only ever saw them in transit. Capture a
-- backup first if the data has any retention obligation:
--
--     CREATE TABLE public.conversation_graph_nodes_backup_033 AS
--     SELECT * FROM public.conversation_graph_nodes;
--
-- 033 created a NEW relation and altered nothing pre-existing, so this rollback
-- touches nothing else. In particular it does not reference
-- knowledge_graph_nodes or knowledge_graph_edges, which 033 also left alone.
--
-- Application prerequisite: deploy a build without
-- app/services/conversation_memory_service.py's call sites BEFORE running this,
-- or every reply path logs a PostgREST 42P01. Retrieval degrades rather than
-- failing (rag_service catches and logs), but the log noise is per-turn.
--
-- LOCK PROFILE -- this rollback locks harder than the migration it reverses.
-- Referential integrity is implemented as triggers on BOTH sides of a foreign
-- key, so dropping this table must also drop the RI triggers it installed on its
-- parents. DROP TABLE therefore takes ACCESS EXCLUSIVE on public.conversations
-- and public.chatbots, not just on conversation_graph_nodes. ACCESS EXCLUSIVE
-- blocks reads as well as writes: for as long as it is held or queued, every
-- inbound message stalls. 033's forward direction only took SHARE ROW EXCLUSIVE
-- on those tables, which blocks writes but not reads.
--
-- Consequence: run this in a maintenance window, and keep the lock_timeout so a
-- wait aborts the rollback instead of stalling the product behind a queued
-- ACCESS EXCLUSIVE request. Aborting is safe -- nothing below is partial.

BEGIN;

SET LOCAL lock_timeout = '5s';

-- Redundant before DROP TABLE (the trigger goes with the relation) but harmless,
-- and it makes the rollback correct if the table was dropped by hand first:
-- DROP TRIGGER IF EXISTS on a missing relation issues a notice and skips.
DROP TRIGGER IF EXISTS trg_conversation_graph_nodes_updated_at
    ON public.conversation_graph_nodes;

-- Takes the table, its PRIMARY KEY, the UNIQUE (conversation_id, label)
-- constraint and its btree, idx_conversation_graph_nodes_chatbot, both CHECK
-- constraints, both foreign keys, the COMMENTs, the table and sequence grants,
-- and the bigserial-owned sequence public.conversation_graph_nodes_id_seq.
-- Nothing from 033 survives it except the function dropped below.
DROP TABLE IF EXISTS public.conversation_graph_nodes;

DROP FUNCTION IF EXISTS public.touch_conversation_graph_nodes_updated_at();

COMMIT;
