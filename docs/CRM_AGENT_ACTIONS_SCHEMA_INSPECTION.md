# CRM Leads and Agent Actions Live Inspection

## Purpose

Use
[`scripts/platform_crm_agent_actions_schema_inspection.sql`](../scripts/platform_crm_agent_actions_schema_inspection.sql)
to inspect the live definitions, privileges, tenant attribution, and aggregate
data quality of `public.agent_actions` and `public.crm_leads`.

The SQL is read-only. It contains catalog queries and aggregate `SELECT`
statements only. It intentionally excludes customer names, phone numbers,
emails, notes, message text, reasons, payload contents, and other sensitive
row content.

## Run it

1. Open the Supabase project and select **SQL Editor**.
2. Open the inspection SQL file and copy it into a new editor tab.
3. Run the sections in order. If the editor retains only one result grid, run
   one labelled section at a time.
4. Copy every result grid back without changing values, headings, empty
   results, or ordering.
5. Copy any SQL error back exactly, including the section label and complete
   error text. Do not work around an error by changing live data or schema.

The catalog sections tolerate missing target tables by returning no rows.
Aggregate sections require the live `agent_actions`, `crm_leads`, `chatbots`,
and `conversations` tables. Optional columns are read through `to_jsonb`, but
the monthly and later-signal checks expect `created_at` values to be
timestamp-compatible.

## Stop after inspection

Do not clean historical rows, add constraints or indexes, change grants or RLS,
or introduce signal lifecycle behavior yet. The returned evidence will be used
to decide whether later reviewed work is needed for:

- historical company-ownership cleanup;
- `NOT NULL` and foreign-key enforcement;
- supporting or duplicate-prevention indexes;
- RLS policies and grants;
- AI Signal lifecycle design;
- inferred signal-to-lead relationships; and
- duplicate prevention.

No row-level sample query is included because aggregate output should be
sufficient for the first review.
