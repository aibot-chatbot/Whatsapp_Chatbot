"use strict";
const superadminKeys = (() => {
  const usd = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });
  const reasons = { ours: "Disabled for a Client", openrouter: "Disabled by OpenRouter", manual_replacement: "Replaced manually" };
  const maskedLabel = value => /^sk-or-v1-[0-9a-f]{3}\.\.\.[0-9a-f]{4}$/.test(value) ? value : null;
  const keyName = key => maskedLabel(key.label) || `Key #${key.id} (ending unavailable)`;
  const money = value => Number.isFinite(value) ? usd.format(value) : "Unknown";
  const clock = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kuala_Lumpur", timeStyle: "medium", hour12: false });
  const resets = { daily: "Resets daily", weekly: "Resets weekly", monthly: "Resets monthly" };
  let manualRefreshes = 0;

  function usage(key) {
    const remaining = key.limit_remaining, cap = key.limit;
    const spent = key.limit_reset === "monthly" && Number.isFinite(key.usage_monthly) ? key.usage_monthly
      : Number.isFinite(cap) && Number.isFinite(remaining) ? Math.max(0, cap - remaining)
      : key.limit_reset ? null : key.usage;
    const bar = Number.isFinite(spent) && Number.isFinite(cap) && cap > 0
      ? `<progress class="key-progress" aria-label="Key limit used" max="${cap}" value="${Math.min(cap, Math.max(0, spent))}"></progress>` : "";
    return `<div class="key-usage"><span class="number">${money(spent)} / ${money(cap)}</span>${bar}
      <span class="metric-change">${Number.isFinite(remaining) ? money(remaining) + " remaining" : "Remaining unavailable"}</span>
      ${Object.hasOwn(resets, key.limit_reset) ? `<span class="metric-change">${resets[key.limit_reset]}</span>` : ""}</div>`;
  }

  function accountStrip(account) {
    if (!account) return '<p class="overview-period">Balance unavailable</p>';
    const values = [["Credits remaining (USD)", account.remaining], ["Used (USD)", account.total_usage], ["Purchased (USD)", account.total_credits]];
    return `<div class="metrics">${values.map(([label, value]) => `<div class="metric"><div class="metric-label">${label}</div>
      <div class="metric-value number">${money(value)}</div></div>`).join("")}</div>`;
  }

  function paintRows(keys) {
    const content = $("#key-list-content");
    const rows = keys.map(key => {
      const reason = reasons[key.disabled_reason];
      const full = key.clients >= key.max_clients ? " " + badge("full") : "";
      const replace = key.disabled_reason === "manual_replacement" ? "" : button("replace-key", "Replace key", key.id);
      return `<tr data-key-id="${esc(key.id)}"><td>${esc(keyName(key))}</td><td>${badge(key.status)}${reason ? `<small>${esc(reason)}</small>` : ""}</td>
        <td>${count(key.clients)} / ${count(key.max_clients)}${full}</td><td>${usage(key)}</td>
        <td><div class="header-actions">${button("key-details", "Details", key.id)}${replace}</div></td></tr>`;
    });
    const html = rows.length ? table(["Key", "Status", "Clients", "Usage / cap (USD)", "Actions"], rows, "Client keys")
      : empty("No Client keys", "Add a key to make it available for new Clients.");
    if (!document.activeElement || !content.contains(document.activeElement)) { content.innerHTML = html; return; }
    // Keep the focused control and scrollable table attached while live values change.
    const next = document.createElement("template");
    next.innerHTML = html;
    const body = content.querySelector("tbody");
    const nextIds = new Set(Array.from(next.content.querySelectorAll("tbody tr"), row => row.dataset.keyId));
    // A removed key or an empty list cannot be patched in place: repaint and keep focus on the page.
    if (!body || !nextIds.size || Array.from(body.rows).some(row => !nextIds.has(row.dataset.keyId))) {
      content.innerHTML = html;
      $("#key-result").focus();
      return;
    }
    const existing = new Map(Array.from(body.rows, row => [row.dataset.keyId, row]));
    for (const [index, row] of [...next.content.querySelectorAll("tbody tr")].entries()) {
      const old = existing.get(row.dataset.keyId);
      if (!old) { body.insertBefore(row, body.rows[index] || null); continue; }
      existing.delete(row.dataset.keyId);
      Array.from(row.cells).forEach((cell, i) => {
        if (!old.cells[i].contains(document.activeElement)) old.cells[i].innerHTML = cell.innerHTML;
      });
    }
    const total = next.content.querySelector(".table-total");
    if (total) content.querySelector(".table-total > span").textContent = total.firstElementChild.textContent;
  }

  const active = sequence => sequence === viewSequence && identity?.platform_role === "super_admin" && routeInfo().route === "api-keys";
  const canPoll = () => document.visibilityState === "visible" && !$("#detail-dialog").open && !$("#confirm-dialog").open;

  async function refresh(sequence, automatic = false) {
    if (automatic && manualRefreshes) return;
    if (!automatic) manualRefreshes += 1;
    try {
      const data = await shell.runRequest("view", signal => api.listOpenRouterKeys(signal));
      if (!active(sequence) || (automatic && !canPoll())) return;
      listRows = requireRows(data, "keys");
      $("#key-account").innerHTML = accountStrip(data.account);
      paintRows(listRows);
      $("#updated-at").innerHTML = `<span>Updated</span> ${clock.format(new Date())}`;
    } catch (error) {
      if (active(sequence) && !handleAuthorization(error) && !automatic) $("#key-list-content").innerHTML = errorPanel(error);
    } finally {
      if (!automatic) manualRefreshes -= 1;
    }
  }

  async function list(sequence) {
    $("#main").innerHTML = heading("API Key Management", "Manage OpenRouter keys and Client limits.",
      button("add-key", "+ Add key", "", "button primary") + button("refresh", "Refresh")) +
      '<p id="key-result" role="status" tabindex="-1"></p><section id="key-account" aria-label="OpenRouter account balance"></section><div id="key-list-content">' + loading("Loading keys…") + "</div>";
    await refresh(sequence);
    if (!active(sequence)) return;
    let pending = false;
    keyRefreshTimer = setInterval(async () => {
      if (!active(sequence) || !canPoll() || pending) return;
      pending = true;
      try { await refresh(sequence, true); } finally { pending = false; }
    }, 30000);
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

  function passwordToggle(form, input, toggle) {
    function show(visible) {
      input.type = visible ? "text" : "password";
      toggle.setAttribute("aria-pressed", String(visible));
      toggle.textContent = visible ? "Hide" : "Show";
    }
    toggle.addEventListener("click", () => show(input.type === "password"));
    form.addEventListener("focusout", event => {
      if (event.relatedTarget !== input && event.relatedTarget !== toggle) show(false);
    });
    return show;
  }

  function add() {
    details("Add key", "API Key Management",
      `<form id="add-key-form" method="post" autocomplete="off" novalidate><div class="field"><label for="added-key">OpenRouter key</label>
      <input id="added-key" type="password" autocomplete="off" spellcheck="false" autocapitalize="none" aria-describedby="add-key-error" required>
      <button type="button" id="show-added-key" class="button" aria-controls="added-key" aria-pressed="false">Show</button>
      <p id="add-key-error" class="field-error" role="alert"></p></div>
      <div class="field"><label for="added-limit">Client limit</label><input id="added-limit" type="number" min="1" max="20" step="1" inputmode="numeric" value="20" aria-describedby="add-limit-error" required>
      <p id="add-limit-error" class="field-error" role="alert"></p></div>
      <div class="detail-actions"><button type="submit" class="button primary">Continue</button>
      <button type="button" id="cancel-add-key" class="button">Cancel</button></div></form>`);
    const form = $("#add-key-form"), input = $("#added-key");
    const show = passwordToggle(form, input, $("#show-added-key"));
    $("#detail-dialog").addEventListener("close", () => { input.value = ""; }, { once: true });
    $("#cancel-add-key").addEventListener("click", () => { input.value = ""; dirty = false; closeDetail(); });
    form.addEventListener("submit", event => {
      event.preventDefault();
      if (mutating || identity?.platform_role !== "super_admin") return;
      $("#add-key-error").textContent = ""; $("#add-limit-error").textContent = "";
      if (!validate("added-key", "add-key-error", () => /^sk-or-v1-[0-9a-f]{64}$/.test(input.value), "Paste a valid OpenRouter key.")) return;
      if (!validate("added-limit", "add-limit-error", value => Number.isInteger(Number(value)) && Number(value) >= 1 && Number(value) <= 20,
        "Enter a whole number from 1 to 20.")) return;
      const limit = Number($("#added-limit").value);
      show(false);
      confirmAction({
        title: "Add this key?", description: "New Clients are assigned automatically up to the selected Client limit.",
        summary: `${limit} / 20`, label: "Add key", reason: false,
        action: async () => {
          await shell.runRequest("add-key", signal => api.addOpenRouterKey({ api_key: input.value, max_clients: limit }, signal));
          input.value = "";
          if (!identity || !$("#detail-dialog").open) return;
          dirty = false; $("#detail-dialog").close();
          await render();
          if (identity) toast("Key added.");
        }
      });
    });
    input.focus();
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
    const show = passwordToggle(form, input, toggle);
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
  return { list, refresh, detail, add, replace };
})();
