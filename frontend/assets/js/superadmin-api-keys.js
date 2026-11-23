"use strict";
const superadminKeys = (() => {
  const usd = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });
  const reasons = { ours: "Disabled for a Client", openrouter: "Disabled by OpenRouter", manual_replacement: "Replaced manually" };
  const maskedLabel = value => /^sk-or-v1-[0-9a-f]{3}\.\.\.[0-9a-f]{4}$/.test(value) ? value : null;
  const keyName = key => maskedLabel(key.label) || `Key #${key.id} (ending unavailable)`;
  const money = value => Number.isFinite(value) ? usd.format(value) : "Unknown";

  async function list(sequence) {
    $("#main").innerHTML = heading("API Key Management", "Manage Client limits and replace OpenRouter keys.", button("refresh", "Refresh")) +
      '<p id="key-result" role="status" tabindex="-1"></p><div id="key-list-content">' + loading("Loading keys…") + "</div>";
    try {
      const data = await shell.runRequest("view", signal => api.listOpenRouterKeys(signal));
      if (sequence !== viewSequence || identity?.platform_role !== "super_admin") return;
      listRows = requireRows(data, "keys");
      const rows = listRows.map(key => {
        const reason = reasons[key.disabled_reason];
        const full = key.clients >= key.max_clients ? " " + badge("full") : "";
        const replace = key.disabled_reason === "manual_replacement" ? "" : button("replace-key", "Replace key", key.id);
        return `<tr><td>${esc(keyName(key))}</td><td>${badge(key.status)}${reason ? `<small>${esc(reason)}</small>` : ""}</td>
          <td>${count(key.clients)} / ${count(key.max_clients)}${full}</td><td>${money(key.usage)} / ${money(key.limit)}</td>
          <td><div class="header-actions">${button("key-details", "Details", key.id)}${replace}</div></td></tr>`;
      });
      $("#key-list-content").innerHTML = rows.length ? table(["Key", "Status", "Clients", "Usage / cap (USD)", "Actions"], rows, "Client keys")
        : empty("No Client keys", "Keys appear here when assigned.");
      $("#updated-at").textContent = "Records loaded " + date(new Date());
    } catch (error) {
      if (sequence === viewSequence && !handleAuthorization(error)) $("#key-list-content").innerHTML = errorPanel(error);
    }
  }

  function detail(key) {
    return loadDetail(keyName(key), signal => api.getOpenRouterKeyCompanies(key.id, signal), data => {
      const rows = requireRows(data, "companies").map(company => `<tr><td>${esc(company.name)}</td><td>${esc(company.id)}</td><td>${esc(date(company.assigned_at))}</td></tr>`);
      const disabled = key.status !== "active" ? "disabled" : "";
      details(keyName(key), "API key details",
        `<p>${count(data.clients)} ${data.clients === 1 ? "company" : "companies"} connected</p>` +
        (rows.length ? table(["Company name", "Company ID", "Connected since"], rows, "Connected companies") : empty("No companies connected", "This key has no current assignments.")) +
        `<form id="key-limit-form" novalidate class="detail-section"><div class="field"><label for="client-limit">Client limit</label>
        <input id="client-limit" type="number" min="1" max="20" step="1" inputmode="numeric" value="${esc(data.max_clients)}" aria-describedby="limit-error" required ${disabled}></div>
        <p id="limit-error" class="field-error" role="alert"></p><button type="submit" class="button primary" ${disabled}>Save</button></form>`);
      $("#key-limit-form").addEventListener("submit", event => {
        event.preventDefault();
        if (mutating || disabled || identity?.platform_role !== "super_admin") return;
        if (!validate("client-limit", "limit-error", value => Number.isInteger(Number(value)) && Number(value) >= 1 && Number(value) <= 20,
          "Enter a whole number from 1 to 20.")) return;
        $("#limit-error").textContent = "";
        const limit = Number($("#client-limit").value);
        confirmAction({
          title: "Change Client limit?",
          description: limit < data.clients
            ? `This key keeps its current Clients and takes no new ones until it has fewer than ${limit}.`
            : `This key can serve up to ${limit} ${limit === 1 ? "Client" : "Clients"}.`,
          summary: `${keyName(key)} · ${data.max_clients} → ${limit}`, label: "Save limit", reason: false,
          action: async () => {
            await shell.runRequest("key-limit", signal => api.setOpenRouterKeyMaxClients(key.id, limit, signal));
            if (!identity || !$("#detail-dialog").open) return;
            dirty = false;
            await Promise.all([render(), detail(key)]);
            if (identity && $("#detail-dialog").open) toast("Client limit saved.");
          }
        });
      });
    });
  }

  function replace(key) {
    details("Replace key", keyName(key),
      `<form id="replace-form" method="post" autocomplete="off"><div class="field"><label for="replacement-key">New OpenRouter key</label>
      <input id="replacement-key" type="password" autocomplete="off" spellcheck="false" autocapitalize="none" maxlength="73" required>
      <button id="show-key" type="button" class="button" aria-controls="replacement-key" aria-pressed="false">Show</button></div>
      <div class="field"><label for="replacement-reason">Reason for replacement</label><input id="replacement-reason" type="text" maxlength="240" required></div>
      <p id="key-error" class="field-error" role="alert"></p><div class="detail-actions"><button type="submit" class="button primary">Save</button>
      <button type="button" id="cancel-key" class="button">Cancel</button></div></form>`);
    const form = $("#replace-form"), input = $("#replacement-key"), reason = $("#replacement-reason"), toggle = $("#show-key");
    function show(visible) {
      input.type = visible ? "text" : "password";
      toggle.setAttribute("aria-pressed", String(visible));
      toggle.textContent = visible ? "Hide" : "Show";
    }
    toggle.addEventListener("click", () => show(input.type === "password"));
    form.addEventListener("focusout", event => {
      if (event.relatedTarget !== input && event.relatedTarget !== toggle) show(false);
    });
    $("#cancel-key").addEventListener("click", () => {
      show(false);
      input.value = ""; reason.value = ""; dirty = false;
      closeDetail();
    });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (mutating || identity?.platform_role !== "super_admin") return;
      await commit(event.currentTarget, "key-error", () => {
        show(false);
        const pending = shell.runRequest("replace-key", signal => api.replaceOpenRouterKey(key.id, { api_key: input.value, reason: reason.value }, signal));
        input.value = "";
        return pending;
      }, async saved => {
        if (!identity || !$("#detail-dialog").open) return;
        $("#detail-dialog").close();
        await render();
        const result = $("#key-result");
        if (!result || !identity) return;
        result.textContent = `Saved ${maskedLabel(saved.label) || "replacement key"}. Clients moved: ${count(saved.moved_count)}.` +
          (saved.old_key_disabled ? "" : " OpenRouter did not confirm that the old key was disabled. Check it in OpenRouter.");
        result.focus();
      }, error => error.status === 429 ? "Too many attempts. Wait a minute before trying again."
        : error.status === 400 ? "Check the key and the reason. Use an active, capped key from this account."
        : "The change could not be confirmed. Refresh the list before trying again.");
    });
    input.focus();
  }
  return { list, detail, replace };
})();
