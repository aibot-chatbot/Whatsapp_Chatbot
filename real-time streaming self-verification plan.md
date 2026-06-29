# Real-Time Streaming Self-Verification Plan

This plan updates the Knowledge Refinement feature with a **Self-Verification Layer** and **Real-Time Progress Logs**. The backend will stream its progress using Server-Sent Events (SSE) as it performs vector audits on graph gaps, and the frontend will display these logs in real-time.

---

## User Review Required

> [!IMPORTANT]
> * **Server-Sent Events (SSE)**: We will convert `/api/knowledge/refinement/questions` into a streaming endpoint. Instead of a single JSON response, it will stream text lines prefixed with `data: ` containing JSON objects.
> * **Self-Verification Logic**:
>   1. Draft Questions: The AI draft questions based on Graph gaps.
>   2. Vector Lookups: For each question, we run similarity matching against PDF chunks in Supabase.
>   3. Semantic Check: The AI checks if the question is answerable using the matched chunks.
>   4. Auto-Resolution: If it is answerable (e.g. "registration is free"), it is automatically answered and filtered out. If it is genuinely missing, it is displayed to the admin.

---

## Proposed Changes

### Backend APIs

#### [MODIFY] [knowledge_routes.py](file:///c:/Users/User/Desktop/Part_Time/Whatsapp_Chatbot/app/routes/knowledge_routes.py)
* Update `/api/knowledge/refinement/questions` to return a `Response` streaming generator:
  - **Yields progress updates** at each phase:
    - `"Analyzing Knowledge Graph structure for gaps..."`
    - `"Found X candidate questions. Checking PDF text..."`
    - For each candidate question:
      - `"Auditing: {question}..."`
      - If resolved: `"Auto-resolved: {question} -> {answer} (Filtered)"`
      - If ambiguous: `"Retained: {question}"`
  - **Yields final results** at the end:
    - `{"status": "complete", "data": [remaining_unresolved_questions]}`

---

### Frontend Dashboard

#### [MODIFY] [new_linkdocs.html](file:///c:/Users/User/Desktop/Part_Time/Whatsapp_Chatbot/frontend/new_linkdocs.html)
* Add a `logs` state variable array to track progress messages.
* Use a streaming reader (like `EventSource` or `fetch` stream reader) to read from the SSE endpoint.
* While loading is active, render a **real-time terminal-like log screen** showing the progress messages appearing one by one with a spinner.
* Once the stream receives `"complete"`, render the final unresolved questions for the admin to answer.

---

## Verification Plan

### Manual Verification
1. Click **Scan Graph for Gaps**.
2. Verify that a live console log appears, printing each step of the AI's analysis.
3. Check that questions already answered in the PDF (e.g., registration fees) are marked as **Auto-resolved** in the logs and do *not* appear in the final questionnaire form.
4. Verify that truly missing questions are shown, and submitting answers embeds them successfully in Supabase.
