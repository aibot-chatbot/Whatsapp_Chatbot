# Training Data Pipeline — Audit & Redesign

**Date:** 2026-08-04
**Scope:** `app/routes/knowledge_routes.py`, `frontend/new_linkdocs.html`
**Status:** findings verified by reading handler bodies; fix #1 applied, fixes #2–#3 outstanding

> Line numbers below are as-of commit `ccb1682` (before fix #1). Applying fix #1
> added 4 lines at `:369`, so every reference after that point is now +4 —
> e.g. `scrape-embed` is at `:427`, its quota gate at `:449`.

---

## Summary

Website-knowledge ingestion is split across five client-driven endpoints. The
browser — not the server — orchestrates the pipeline, and the extracted text
lives only in browser memory between two HTTP calls. A closed tab or dropped
connection destroys training data the client has already paid an LLM call for.

This is the root cause of the recurring "the bot isn't learning from my data"
and "I don't understand if my bot is trained" client reports.

---

## The five endpoints

| Endpoint | Line | Persists? |
|---|---|---|
| `POST /api/knowledge/scrape` | 212 | — |
| `POST /api/knowledge/scrape-analyze` | 258 | — |
| `POST /api/knowledge/scrape-batch` | 298 | — |
| `POST /api/knowledge/scrape-extract` | 346 | **No** — returns text to browser |
| `POST /api/knowledge/scrape-embed` | 423 | **Yes** — first and only write |

Frontend chains extract → embed as separate awaits:
`frontend/new_linkdocs.html:2642`, `:2700`, `:2734`.

---

## Finding 1 — training data can be silently lost (HIGH)

`scrape_extract_website` calls the LLM refiner and returns the result to the
client without persisting it:

```python
refined_text = extract_business_knowledge(combined_text, chatbot_id=chatbot_id)  # :399  billed LLM call
return jsonify({"data": {"extracted_text": refined_text, ...}})                  # :401  returned, not saved
```

`scrape_embed_website` takes that text back from the request body and only then
writes it:

```python
text_content = data["text_content"]           # :447  from client
result = save_refined_knowledge_chunks(...)   # :453  first write
```

**Failure mode:** tab closed / navigation / network drop between the two calls
loses the extraction entirely. The client is billed for the LLM call regardless.

---

## Finding 2 — split billing gates charge for discarded work (HIGH)

Quota is checked in two different places, in the wrong order relative to spend:

| Step | Gate | Line |
|---|---|---|
| `scrape-extract` | `can_use_plan_feature(company_id, "batch_website_scraping")` | 368 |
| `scrape-embed` | `can_upload_knowledge_file(company_id)` | 445 |

A client at their knowledge-file limit passes the extract gate, burns an LLM
call, then receives `403` at embed. Money spent, nothing saved.

**Fix applied:** `can_upload_knowledge_file` is now also called in
`scrape-extract` before the LLM runs. The check at `:445` is retained as the
authoritative gate at write time (state may change between calls).

---

## Finding 3 — `text_content` is unverified client input (LOW)

`scrape-embed` stores whatever text the client posts, tagged with the supplied
`primary_url` (`:447-457`). Nothing verifies the text originated from that URL,
so recorded provenance is not trustworthy. Not a cross-tenant issue.

---

## Not a finding — tenant isolation is correct on this path

`verify_chatbot_access(chatbot_id)` is present on both endpoints (`:366`, `:442`).
Both are additionally guarded by `@token_required` and
`@role_required("admin", "owner")`.

---

## Proposed replacement

Make ingestion one server-owned job. The client sends URLs and polls; it never
holds the payload.

```
POST /api/knowledge/sources        -> {job_id}    quota checked HERE, before any LLM spend
GET  /api/knowledge/jobs/{job_id}  -> {state, stage, progress, error}
GET  /api/knowledge/readiness      -> {sources, embedded, ready}
```

Server performs scrape -> extract -> chunk -> embed as one unit, persisting the
scraped text before the LLM step so a crash resumes rather than restarts.

Properties gained:

- a closed tab cannot destroy training data
- quota is enforced before spend
- `readiness` gives the dashboard one honest "is my bot trained?" signal

Keep the five existing endpoints during migration so `new_linkdocs.html` does not
break; switch the UI once `/sources` is proven.

---

## UI implication

The Training Data page currently exposes four competing mental models: files,
the five-step scrape pipeline, knowledge-graph node/edge editing (`:484`-`:1186`),
and refinement Q&A (`:663`, `:853`). Manual graph editing is a data-engineering
task and is the main comprehension cliff for a business client.

Proposed: one readiness bar driven by `/readiness`, with graph editing and
refinement moved behind an **Advanced** disclosure.

```
2  Training Data   ##########--  10/12 embedded - Indexing...
                   [ Add source ]        [ Advanced > ]
```

---

## Outstanding work

1. ~~Move quota check before the LLM call~~ — **done**
2. Build `/sources` + `/jobs/{id}` + `/readiness`
3. Rewire Training Data UI to the readiness bar

Note: `frontend/flows.html` (Flow Builder) is mid-rewrite upstream — commit
`4f77d66` "renew flow builder and not complete yet". Do not build UI against it
until that lands.
