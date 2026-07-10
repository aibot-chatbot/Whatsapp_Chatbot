-- ============================================================================
-- DATA REPAIR SQL - FOR REVIEW ONLY
-- ============================================================================
-- 
-- This SQL repairs the duplicate subscription included AI credit for an affected 
-- company by:
-- 1. Identifying the duplicate ledger entries
-- 2. Reversing only the duplicate RM60 (60,000,000 micro-MYR) that was incorrectly
--    added to the top-up bucket via add_ai_credit_topup RPC
-- 3. Restoring correct balances:
--    - included_balance_micro_myr = 60,000,000 (RM60)
--    - topup_balance_micro_myr = 2,000,000 (RM2)
--    - total = 62,000,000 (RM62)
--
-- No changes are made automatically. Replace <COMPANY_ID>, <ORDER_REFERENCE>,
-- and other placeholders with actual values after verification.
-- ============================================================================

-- Step 1: Identify the duplicate transactions
-- Replace <COMPANY_ID> with the actual company ID
-- Run this first to verify the exact transactions before making changes
/*
SELECT 
    id,
    transaction_type,
    included_delta_micro_myr,
    topup_delta_micro_myr,
    included_balance_after_micro_myr,
    topup_balance_after_micro_myr,
    total_balance_after_micro_myr,
    description,
    idempotency_key,
    payment_reference,
    created_at
FROM ai_credit_transactions
WHERE company_id = <COMPANY_ID>
  AND created_at BETWEEN '<START_ISO>' AND '<END_ISO>'
ORDER BY created_at;
*/

-- Step 2: Check current credit balances
/*
SELECT 
    company_id,
    included_balance_micro_myr,
    topup_balance_micro_myr,
    (COALESCE(included_balance_micro_myr, 0) + COALESCE(topup_balance_micro_myr, 0)) AS total_balance_micro_myr
FROM company_ai_credit_balances
WHERE company_id = <COMPANY_ID>;
*/

-- Step 3: Reverse the duplicate grant
-- This assumes the duplicate topup_delta is 60000000 (RM60)
-- and was identified by checking that the idempotency_key does NOT match
-- the subscription's activation_sequence_key prefix.
--
-- WARNING: Verify the exact transaction_id before running this.
/*
-- Insert a reversal transaction
INSERT INTO ai_credit_transactions (
    company_id,
    transaction_type,
    included_delta_micro_myr,
    topup_delta_micro_myr,
    included_balance_after_micro_myr,
    topup_balance_after_micro_myr,
    description,
    payment_reference,
    idempotency_key,
    reversal_of_transaction_id,
    period_start,
    period_end
)
SELECT
    t.company_id,
    'reversal' AS transaction_type,
    0 AS included_delta_micro_myr,
    -t.topup_delta_micro_myr AS topup_delta_micro_myr,
    b.included_balance_micro_myr AS included_balance_after_micro_myr,
    b.topup_balance_micro_myr - t.topup_delta_micro_myr AS topup_balance_after_micro_myr,
    'Reversal: duplicate subscription included credit removed' AS description,
    'repair-duplicate-' || t.payment_reference AS payment_reference,
    'reverse-' || t.idempotency_key AS idempotency_key,
    t.id AS reversal_of_transaction_id,
    b.period_start,
    b.period_end
FROM ai_credit_transactions t
JOIN company_ai_credit_balances b ON b.company_id = t.company_id
WHERE t.id = <DUPLICATE_TRANSACTION_ID>
  AND t.company_id = <COMPANY_ID>;

-- Update the balance to reverse the topup delta
UPDATE company_ai_credit_balances
SET
    topup_balance_micro_myr = COALESCE(topup_balance_micro_myr, 0) - <DUPLICATE_AMOUNT>,
    updated_at = NOW()
WHERE company_id = <COMPANY_ID>;
*/

-- Step 4: Verify the corrected balances
/*
SELECT 
    company_id,
    included_balance_micro_myr,
    topup_balance_micro_myr,
    (COALESCE(included_balance_micro_myr, 0) + COALESCE(topup_balance_micro_myr, 0)) AS total_balance_micro_myr
FROM company_ai_credit_balances
WHERE company_id = <COMPANY_ID>;
*/
