# Industry expansion: five new industry profiles

Status: design approved by the owner on 2026-09-26; spec awaiting review.

## Context

A business uploads its main knowledge file. The same AI call that derives the bot
persona (`persona_derivation_service.py`) also suggests an industry and must quote
1–3 verbatim sentences as evidence. `normalize_suggestion` rejects ungrounded
suggestions, the suggestion is saved as a draft, and the owner confirms it in Bot
settings. A confirmed profile adds industry rules to chatbot answers
(`industry_prompt`) and industry sections to Analysis reports.

Only four profiles exist: `restaurant`, `clinic`, `tuition_center`, and `general`
as the fallback. The owner wants more industry-specific behaviour. Detection
already works from uploaded files, so this is a catalog extension. No MCP server
is involved. Industry action tools (booking and similar) are a separate, later
project (`INDUSTRY_AGENT_CODEX_PLAN`, phase IA-3).

## Goals

- Five new profiles that detection can suggest and owners can confirm:
  `beauty_salon`, `property_agent`, `car_workshop`, `retail_shop`, `travel_agency`.
- A future industry needs catalog entries and tests only: no migration, schema-enum
  or frontend change (the observation prompt's examples are optional wording).
- Bots already confirmed on the four existing profiles behave exactly as before.

## Non-goals

- No booking, ordering, payment or other action tools for any industry.
- No industry-specific Analysis metrics for the new industries. They get the
  general report sections, exactly as `general` does today.
- No change to how detection is triggered, the owner-confirmation step,
  billing, or the AI provider.

## Blockers found in the current code

| Where | Problem | Fix |
|---|---|---|
| `persona_derivation_service.py:119,122` | The AI's JSON-schema enum lists the four IDs, so the model cannot return a new one. | Build the enum from the catalog. |
| `data/065_business_observations.sql:113`, `analysis_apply_business_observation` | Rejects any `industry_id` outside the four. Every recorded request from a new-industry bot would fail and go to `needs_review`. | Migration 071 (below). |
| `industry_template_catalog.py`, `TEMPLATE_VERSION` | One version shared by all templates. `industry_prompt` returns no rules when a bot's stored version differs, so bumping it would silently strip rules from every confirmed bot. | Per-template versions (below). |
| `frontend/assets/js/analysis.js:36` | Industry display names hard-coded for four IDs. New IDs show a humanized ID. | The Analysis API returns the catalog name; JS prefers it. |

## Design

### 1. Catalog (`app/services/industry_template_catalog.py`)

Each template gains three fields:

- `version`: the template's own version. The existing four keep `"1.0.0"` and the
  new five start at `"1.0.0"`.
- `classification_hint`: one or two sentences for detection: the evidence
  needed and what not to confuse the industry with.
- `lead_rule`: what "qualified" means for a lead in this industry. The Lead
  qualifier will be the first consumer; it is carried now so the next project
  reads it from here.

`get_template(id, version)` and `industry_prompt(published)` compare against that
template's own `version`. `TEMPLATE_VERSION` stays as a constant equal to `"1.0.0"`
for existing callers and tests; no code may bump it to add industries.

Rule, stated in the module docstring: never edit an existing template's rules in
place. A rule change needs a new version with the old one kept resolvable. That
mechanism is not built now, because no existing template changes in this project.

`CLASSIFICATION_INSTRUCTIONS` is built from the catalog:

- the allowed-ID list comes from the catalog;
- the existing disambiguation text is kept word for word;
- each template's `classification_hint` is appended;
- "outside the three specialized industries" becomes "outside the specialized
  industries".

The JSON keys and the output contract are unchanged.

A new helper `template_ids()` returns the allowed IDs, in catalog order.

### 2. The five profiles

Shared by all five, as for the existing profiles: `_COMMON_RULES`. Knowledge
answers only, no tools, no claimed actions, and the customer's language.

**beauty_salon, "Beauty salon & spa"**
- Questions: branch; treatment or service; preferred date; preferred time.
- Required information: salon name, branches, hours; treatment menu with
  durations and prices; booking, deposit, late-arrival and cancellation policies.
- Unavailable actions: checking live slots or booking, changing or cancelling
  appointments; taking deposits or payments; skin, medical or allergy advice;
  guaranteeing treatment results.
- Classification hint: needs hair, nail, facial, massage or spa services.
  Aesthetic clinics where doctors perform medical procedures are `clinic`. Shops
  that only sell beauty products are `retail_shop`.
- Lead rule: the customer wants a specific treatment AND asks to book or asks
  about availability.

**property_agent, "Property agent"**
- Questions: buy or rent; area; budget; property type and bedrooms.
- Required information: agency name and REN/REA/PEA registration number;
  service areas; listings with price or rent, size and status; viewing,
  commission and fee policies.
- Unavailable actions: confirming a unit is still available; arranging or
  confirming viewings; guaranteeing loan approval or giving legal, tax or
  financial advice; collecting identity documents, booking fees or deposits;
  promising negotiation outcomes.
- Classification hint: needs listing, sale or rental brokerage context
  (developer sales galleries also fit). Homestays and hotels are
  `travel_agency`. Renovation and construction contractors are `general`.
- Lead rule: an area plus a budget or property type, AND the customer wants a
  viewing or to proceed.

**car_workshop, "Car workshop"**
- Questions: car make, model and year; service or problem; branch; preferred
  date and time.
- Required information: workshop name, branches, hours; service packages and
  prices; makes serviced; warranty, appointment and towing policies.
- Unavailable actions: confirming parts stock; quoting a final repair price
  before inspection; booking, changing or cancelling service appointments;
  certain diagnosis. For a safety-critical symptom (brakes, steering, smoke,
  overheating), the bot says not to drive and to contact the workshop.
- Classification hint: needs car servicing, repair, tyres, battery or
  detailing context. Car dealers and showrooms selling vehicles are
  `retail_shop`. Car rental is `travel_agency` or `general`.
- Lead rule: a specific car and service need, AND the customer wants a booking
  or a quotation.

**retail_shop, "Retail / online shop"**
- Questions: product; size, colour or variant; quantity; delivery area or
  pickup branch.
- Required information: shop name and sales channels (physical store,
  marketplaces, website); catalogue with prices; shipping, return, refund,
  warranty and payment-method policies.
- Unavailable actions: confirming live stock or reserving items; placing
  orders or taking payment; checking order status or tracking; promising
  delivery dates beyond policy; inventing discounts. For pharmacy or health
  products: no dosage or medical advice.
- Classification hint: needs a product catalogue or selling context,
  including online marketplaces. Businesses selling prepared food for dining
  or delivery are `restaurant`.
- Lead rule: a specific product, AND the customer asks about stock, price,
  shipping or how to order.

**travel_agency, "Travel agency"**
- Questions: destination; travel dates; number of adults and children;
  budget or package type.
- Required information: agency name and MOTAC licence number; packages
  (including Umrah) with inclusions, prices and dates; deposit, payment and
  cancellation policies; accommodation details where the business is a hotel
  or homestay.
- Unavailable actions: confirming seat or room availability or holding
  bookings; issuing tickets; taking payments; stating visa, immigration or
  health-entry requirements as authoritative (the bot points to official
  sources); guaranteeing prices.
- Classification hint: needs tour, travel package, ticketing, pilgrimage or
  accommodation-booking context. A business that merely mentions travel,
  such as a delivery area, is not travel.
- Lead rule: a destination or package plus dates, AND the customer wants to
  book or get a quote.

The existing four profiles gain `classification_hint` and `lead_rule` values
matching their current behaviour. Their other fields, rules text and version are
unchanged. For reference, the lead rules for the existing profiles:

- clinic: wants to book, change or ask about an appointment;
- tuition_center: wants a trial class, enrolment or registration;
- restaurant: wants a reservation, order or event booking;
- general: a clear need AND wants to proceed soon.

### 3. Detection schema (`persona_derivation_service.py`)

The `template_id` and `candidate_ids` enums come from `template_ids()`.
`normalize_suggestion` already validates against the catalog and needs no change.

### 4. Migration 071 (`data/071_business_observation_industries.sql`)

`CREATE OR REPLACE` `public.analysis_apply_business_observation` with the same
signature, security, grants and body as the live definition, except the industry
check. The four-name `IN` list becomes a format check,
`p_output->>'industry_id' ~ '^[a-z][a-z_]{1,39}$'`.

The catalog is the allowlist. The worker resolves the ID through `get_template`
before calling the RPC, and only `service_role` may execute the RPC. Supplying
the ID from the catalog keeps future industries free of migrations.

Before writing the migration, read the live definition with
`pg_get_functiondef` and confirm that it matches migration 065. If it has drifted,
stop and reconcile. The migration also includes a rollback file. Deploy order:
migration first. It only widens, so the running code is unaffected.

### 5. Business observations (`business_observation_service.py`)

The classifier prompt's `booking` examples add salon appointments, property
viewings, workshop service appointments and travel package bookings. The
`order` examples add retail orders. `_ACTIONS` is unchanged.

### 6. Analysis page name

The Analysis API adds the catalog `name` to the industry object it returns.
`analysis.js` prefers `industry.name`, then falls back to the existing map, then
to `humanize`.

## Compatibility

- Stored profiles `(clinic|restaurant|tuition_center|general, "1.0.0")` resolve
  and produce identical `industry_prompt` text. A test pins the exact text of
  each.
- Old worker images resolve unknown IDs to `general`
  (`analysis_report_service._industry` catches `ValueError`). Until the worker is
  redeployed, a new-industry bot's observations are therefore recorded as
  `general`, not failed.

## Testing

- **Catalog:**
  - nine templates;
  - per-template versions;
  - the existing four at `1.0.0` with unchanged prompt text;
  - `industry_prompt` non-empty for all nine;
  - `normalize_suggestion` accepts new IDs with grounded evidence and rejects
    ungrounded ones;
  - `CLASSIFICATION_INSTRUCTIONS` lists every ID and hint;
  - every template has a non-empty `lead_rule`.
- **Grounding fixtures:** for each new industry, an English, a Malay and a
  Chinese snippet that `normalize_suggestion` must accept, plus confusion cases
  that must stay unselected unless the evidence quotes support them:
  - aesthetic clinic vs salon;
  - dealer vs workshop;
  - homestay vs property agent;
  - food seller vs retail.
- **Persona derivation:** the schema enum equals `template_ids()`.
- **Migration 071:** a SQL-text test in the style of
  `test_analysis_schedule_migration_070.py`: format check present, four-name
  list absent, grants and security unchanged.
- **Observations:** a new-industry bot's outcome carries its `industry_id`.
- **Analysis:** the route returns `name`, and the browser test shows the catalog
  name.
- **Live detection check** (manual, not CI): 15 sample documents (5 industries ×
  EN/MS/ZH) through the real classification prompt using the dev OpenRouter
  key. Record the suggested ID for each; the target is at least 13/15 correct
  with no wrong confident pick in the confusion cases.
- Full pytest via `.venv/Scripts/python.exe`, `git diff --check`.

## Rollout

1. Apply migration 071 to production (explicit approval).
2. Deploy Flask from `release/2026-09-26`. It must contain `268996b`, the live
   Cloudflare pricing release.
3. Redeploy the worker with `APP_IMAGE` set to the new Flask digest, so
   observations use the new catalog.
4. Verify on a test bot: upload a salon document, then check the suggestion,
   confirmation and a chatbot answer carrying salon rules.

## Risks

- Detection confusion between neighbouring industries. This is mitigated by
  the classification hints, evidence grounding and owner confirmation. Nothing
  is published without the owner.
- Longer classification prompt: nine hints add about 600 tokens per persona
  derivation. This is acceptable, and each is a one-off per uploaded primary
  document.
