# Coding Behavior and Code Review Guidelines

Behavioral guidelines to reduce common coding mistakes when working with LLMs, Codex, or team members. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

---

## 1. Think Before Coding

*Do not assume. Do not hide confusion. Surface tradeoffs before implementation.*

Before implementing:

- State assumptions explicitly.
- If the requirement is unclear, ask before changing code.
- If multiple interpretations exist, present them instead of silently choosing one.
- If a simpler approach exists, mention it and prefer the simpler option.
- Push back when the requested change may break existing design, logic, or database behavior.
- If something is confusing, stop and name what is confusing.

For this project, always understand the connected flow before editing:

- Frontend page involved, such as `index.html`, `crm.html`, `conversations.html`, `integration.html`, or `model_settings.html`.
- Backend route involved, such as analytics, conversation, knowledge, Telegram, WhatsApp, or AI routing routes.
- Repository or service involved, such as conversation repository, message repository, knowledge service, RAG service, or AI router.
- Database table involved, especially Supabase tables using `company_id`, `chatbot_id`, `conversation_id`, or integration/channel records.

Do not modify first and understand later.

---

## 2. Simplicity First

*Minimum code that solves the problem. Nothing speculative.*

Rules:

- No features beyond what was asked.
- No abstractions for single-use code.
- No unnecessary configurability.
- No major rewrite when a small fix is enough.
- No new UI pattern if the current design already works.
- No extra error handling for impossible scenarios.
- If the solution becomes too long, re-check whether it can be simplified.

Ask:

> Would a senior engineer say this is overcomplicated?

If yes, simplify it.

For this project, prefer:

- Small HTML/CSS/JS fixes instead of full page rewrites.
- Route-level fixes instead of changing the whole backend structure.
- Repository/service-level fixes only when the bug belongs there.
- Reusing existing UI classes and layout patterns.
- Keeping the current design unless the task is specifically about redesign.

---

## 3. Surgical Changes

*Touch only what is necessary. Clean up only your own mess.*

When editing existing code:

- Do not improve unrelated code.
- Do not refactor things that are not broken.
- Do not change unrelated comments or formatting.
- Match the existing style, even if another style looks better.
- If unrelated dead code is found, mention it but do not delete it unless asked.
- Every changed line should trace directly to the requested task.

When your changes create unused code:

- Remove imports, variables, or functions made unused by your change.
- Do not remove pre-existing dead code unless the task asks for cleanup.

The test:

> Can every changed line be explained by the user request?

If no, the change is too wide.

For this project, be extra careful when editing shared files:

- Shared CSS may affect multiple frontend pages.
- Shared sidebar JavaScript may affect navigation across the whole system.
- `rag_service.py` may affect all AI providers.
- `ai_router.py` may affect Gemini, DeepSeek, Groq, Grok, Cloudflare, OpenRouter, and other model providers.
- Conversation repository changes may affect dashboard history, CRM view conversation, and conversation history pages.
- Analytics changes may affect dashboard cards, recent history, usage analytics, and chatbot-specific filtering.

---

## 4. Goal-Driven Execution

*Define success criteria. Loop until verified.*

Transform vague tasks into verifiable goals:

- “Fix the bug” → reproduce the bug, apply the smallest fix, then verify the bug is gone.
- “Add validation” → test invalid input, valid input, and empty input.
- “Improve UI” → check layout, spacing, responsiveness, and console errors.
- “Refactor” → verify behavior before and after the change.
- “Connect API” → verify frontend request, backend route, database response, and UI display.

For multi-step tasks, use a brief plan:

1. Identify the affected file and feature → verify by reading current code.
2. Apply the smallest necessary change → verify with focused testing.
3. Check related pages or APIs → verify existing features still work.
4. Review the diff → verify no unrelated changes were added.

Strong success criteria reduce repeated fixes. Weak criteria like “make it work” usually cause confusion.

---

## 5. Frontend Coding Behavior

*Protect existing design while fixing the function.*

Before editing frontend files:

- Check where the page is linked from.
- Check whether CSS classes are shared with other pages.
- Check whether JavaScript depends on specific IDs, class names, or DOM structure.
- Check whether buttons, modals, tables, filters, or search bars already have existing behavior.

When editing frontend:

- Keep the current design style unless redesign is requested.
- Avoid large CSS rewrites.
- Avoid changing layout structure unless required.
- Do not remove working buttons, links, filters, or hidden fields accidentally.
- Preserve responsive behavior.
- Preserve loading, empty state, error state, and success state behavior.

After editing frontend, check:

- Browser console has no errors.
- Buttons still click correctly.
- Forms still submit correctly.
- Tables still align correctly.
- Modals still open and close correctly.
- Search/filter/sort still work if the page has them.
- Page still looks acceptable on smaller screen sizes.

For this project, always be careful with:

- Dashboard cards and recent history.
- CRM table action buttons.
- Conversation history search and transcript tools.
- Integration pages for Telegram, WhatsApp, and WhatsApp (linked device).
- Model settings page and provider selection UI.
- Login, forgot password, reset password, and show-password behavior.

---

## 6. Backend Coding Behavior

*Check route, service, repository, and database flow together.*

Before editing backend:

- Identify the route being called by the frontend.
- Identify the service layer used by the route.
- Identify the repository/database query used by the service.
- Check whether the route needs authentication.
- Check whether the route must filter by `company_id`, `chatbot_id`, or user ownership.

When editing backend:

- Do not bypass access control.
- Do not hardcode `company_id`, `chatbot_id`, or user-specific values unless it is clearly test-only code.
- Keep route responses consistent with existing frontend expectations.
- Keep error response format consistent.
- Avoid changing response field names unless frontend is updated together.
- Avoid modifying all providers/services when only one provider has a bug.

After editing backend, check:

- Server starts without error.
- API returns expected status code.
- API response contains expected fields.
- Frontend can still consume the response.
- Terminal logs do not show unexpected exceptions.
- Supabase query returns the correct data.

---

## 7. Database and Supabase Review Behavior

*Always check data filtering and relationship safety.*

Before changing database-related code:

- Identify the table being queried.
- Check whether the query must filter by `company_id`.
- Check whether the query must filter by `chatbot_id`.
- Check whether old records may have missing fields.
- Check whether the frontend expects nullable values.

When editing Supabase queries:

- Avoid broad queries that can load other company data.
- Avoid removing ownership filters.
- Avoid changing table relationships without checking affected pages.
- Avoid assuming every record has complete data.
- Handle empty result properly.

For this project, be careful with:

- `conversations`
- `messages`
- `chatbots`
- `knowledge_files`
- `knowledge_chunks`
- `telegram_channels`
- `channel_server_channels`
- analytics-related data
- CRM-related records

After editing database logic, verify:

- Correct company data is loaded.
- Correct chatbot data is loaded.
- Empty state works.
- Deleted or inactive records are handled properly.
- No cross-company data leakage happens.

---

## 8. Omnexa and RAG Review Behavior

*Changes to AI logic can affect every model provider.*

Before editing AI-related files:

- Check whether the issue belongs to provider routing, prompt construction, RAG retrieval, response formatting, or frontend display.
- Check whether the bug affects one provider or all providers.
- Check whether the active chatbot and active knowledge file are used correctly.

When editing AI logic:

- Do not change all providers if only one provider has an issue.
- Do not break fallback behavior.
- Do not remove useful logging.
- Do not make prompts too complicated without reason.
- Do not make RAG retrieval too strict if it causes the bot to fail on normal questions.
- Keep general fallback behavior when no relevant knowledge is found.

For this project, check these areas carefully:

- `ai_router.py`
- `chat_logic_service.py`
- `rag_service.py`
- provider services such as Gemini, DeepSeek, Groq, Grok, Cloudflare, and OpenRouter
- knowledge file service
- knowledge chunk repository
- response formatter

After editing AI logic, test:

- Normal question.
- Question related to uploaded knowledge.
- Question not found in knowledge.
- Different AI provider if the change affects routing.
- Empty or inactive knowledge file scenario.

---

## 9. Integration Review Behavior

*External integrations need both setup checking and user-friendly flow checking.*

Before editing integration code:

- Check whether the integration is Telegram, WhatsApp Cloud API, WhatsApp (linked device), or another provider.
- Check whether the issue is frontend setup, backend route, webhook, token validation, database storage, or message delivery.
- Check whether the user needs to reconnect, disconnect, change token, or view setup status.

When editing integration code:

- Do not expose secrets or tokens in frontend unnecessarily.
- Do not remove reconnect/disconnect behavior.
- Do not assume setup is complete when pending status exists.
- Keep user instructions clear and simple.
- Handle failed connection states clearly.

After editing integration code, verify:

- Connect flow works.
- Disconnect flow works.
- Token update flow works.
- Webhook/message receiving still works if applicable.
- UI status matches backend/database status.

---

## 10. Manual Testing Behavior

*Do not only test the new feature. Test nearby old features too.*

After each change, check:

- The changed feature works.
- The previous related feature still works.
- No console error appears.
- No backend terminal error appears.
- No unexpected Supabase query issue appears.
- Page layout is not broken.
- Empty state still works.
- Error state still works.

Preferred testing flow:

1. Test the exact feature changed.
2. Test the page reload state.
3. Test an empty or missing data case.
4. Test one related feature nearby.
5. Check browser console.
6. Check backend terminal logs.
7. Check Supabase data if needed.

Example:

If `conversations.html` is changed, also check:

- CRM “View Conversation” link.
- Conversation search.
- Copy transcript.
- Download transcript.
- URL deep-link behavior.
- Empty conversation state.

---

## 11. Commit Behavior

*Commit only after focused review.*

Before committing:

- Review the diff.
- Confirm changed files are expected.
- Confirm no unrelated formatting changes are included.
- Confirm no secret, token, or local path is committed.
- Confirm the app still starts.
- Confirm the modified feature works.
- Confirm related features are not broken.

Commit message style:

- Use clear human language.
- Mention the actual feature or fix.
- Avoid vague messages like `update`, `fix bug`, or `changes`.

Good examples:

```txt
Fix CRM action button layout and view conversation link
```

```txt
Improve conversation history search and transcript tools
```

```txt
Add AI provider selection handling for chatbot responses
```

```txt
Fix dashboard recent history filtering by selected chatbot
```

---

## 12. Common Mistakes to Avoid

Avoid these common mistakes:

- Changing too many files at once.
- Refactoring unrelated code.
- Breaking UI design while fixing logic.
- Testing only the new feature and ignoring old related features.
- Forgetting `company_id` or `chatbot_id` filtering.
- Hardcoding values that should come from session, database, or selected chatbot.
- Changing backend response fields without updating frontend.
- Removing existing fallback logic.
- Assuming all database records are complete.
- Deleting files just because they look unused without confirming references.
- Asking Codex to modify too broadly.
- Committing before checking the diff.

---

## 13. How to Ask Codex or an LLM to Modify Code

When asking Codex or another LLM to modify code, be specific.

Bad prompt:

```txt
Fix this page.
```

Better prompt:

```txt
Modify only frontend/conversations.html.
Fix the message search highlight bug without changing the existing design.
Do not refactor unrelated code.
Preserve Copy Link, Copy Transcript, Download .txt, URL sync, and deep-link behavior.
After editing, check for unused variables created by this change only.
```

Best prompt structure:

```txt
Task:
[What needs to be fixed]

Files allowed to edit:
[List files]

Do not change:
[Design, unrelated files, existing features]

Must preserve:
[Important old behavior]

Verification:
[What to test after change]
```

---

## 14. Final Rule

Code slowly, check carefully, and commit only when the change is small, understandable, and verified.

These guidelines are working if:

- Diffs become smaller.
- Fewer unrelated changes appear.
- Fewer rewrites are needed.
- UI breaks happen less often.
- Clarifying questions happen before implementation, not after mistakes.
- Each commit has a clear purpose.
