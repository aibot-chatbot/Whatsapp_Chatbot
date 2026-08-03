-- Migration: Add Flow State Tracking to Conversations
-- This enables stateful flow execution (Memory) for the Omnichat-style Flow Builder V2

ALTER TABLE public.conversations 
ADD COLUMN IF NOT EXISTS active_flow_id bigint REFERENCES public.flows(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS current_node_id text;

-- Add a comment to the columns for clarity
COMMENT ON COLUMN public.conversations.active_flow_id IS 'The ID of the flow the user is currently navigating.';
COMMENT ON COLUMN public.conversations.current_node_id IS 'The node ID (from Drawflow JSON) where the user is currently waiting for input.';
