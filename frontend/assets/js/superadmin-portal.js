"use strict";
const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const paths = {
  home: '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/>',
  payments: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 10h18M7 15h3"/>',
  customers: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/><circle cx="9" cy="7" r="4"/>',
  subscriptions: '<path d="M20 7h-5V2M4 17h5v5M20 7a8 8 0 0 0-14-3M4 17a8 8 0 0 0 14 3M20 7v5M4 17v-5"/>',
  support: '<path d="M3 14v-3a9 9 0 0 1 18 0v3M3 13h4v7H4a1 1 0 0 1-1-1Zm18 0h-4v7h3a1 1 0 0 0 1-1ZM17 20c0 2-3 2-5 2"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  approvals: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M8 12l3 3 5-6"/>',
  team: '<circle cx="8" cy="7" r="3"/><path d="M2 20v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3M17 8h5M19.5 5.5v5M17 16h5"/>',
  book: '<path d="M12 5c-4-3-8-2-10-1v15c3-1 6-1 10 1 4-2 7-2 10-1V4c-2-1-6-2-10 1Zm0 0v15"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  settings: '<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm-3-5h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1Z"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  x: '<path d="m6 6 12 12M6 18 18 6"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  arrowUp: '<path d="m6 16 12-12M6 4h12v12"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  shield: '<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Z"/><path d="m8 12 3 3 5-6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  edit: '<path d="m14 5 5 5M3 21l5-1L21 7l-5-5L3 15Z"/>',
  message: '<path d="M21 15a3 3 0 0 1-3 3H8l-5 4V6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3Z"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>',
  file: '<path d="M14 2H5v20h14V7Zm0 0v5h5M8 12h8M8 16h6"/>'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.info}</svg>`;
function hydrateIcons(root = document) { root.querySelectorAll("[data-icon]").forEach(node => { node.innerHTML = icon(node.dataset.icon); }); }

const api = window.PlatformAdminApi;
const helpApi = window.PlatformAdminHelpApi;
const shell = window.PlatformAdminShell;
const navigation = [
  ["overview", "Overview", "home", ""], ["payments", "Payments", "payments", "Workspace"],
  ["customers", "Customers", "customers", ""], ["subscriptions", "Subscriptions", "subscriptions", ""],
  ["support", "Help Desk", "support", ""], ["approvals", "Approvals", "approvals", "Administration"],
  ["team", "Team & permissions", "team", ""], ["help", "Help articles", "book", ""],
  ["activity", "Activity log", "activity", ""], ["settings", "Settings", "settings", ""]
];
const labels = Object.fromEntries(navigation.map(([id, name]) => [id, name]));
const pageSize = 25;
let identity = null, listData = null, listRows = [], detailData = null;
let viewSequence = 0, detailSequence = 0, detailOpener = null, confirmation = null, toastTimer;
let dirty = false, mutating = false, searchTimer, searchComposing = false, acceptedHash = location.hash || "#overview";
const routeSearch = new Map();
const count = value => Number.isSafeInteger(value) && value >= 0 ? new Intl.NumberFormat("en-MY").format(value) : "Not available";
const date = value => value && Number.isFinite(new Date(value).getTime()) ? new Intl.DateTimeFormat("en-MY", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kuala_Lumpur" }).format(new Date(value)) : "Not available";
const titleCase = value => String(value || "Not recorded").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
const microMyr = value => Number.isSafeInteger(value) ? new Intl.NumberFormat("en-MY", { style: "currency", currency: "MYR" }).format(value / 1000000) : "Not available";
function routeInfo() {
  const [raw, query] = (location.hash.slice(1) || "overview").split("?");
  const params = new URLSearchParams(query);
  // Search text is transient. Remove legacy search fragments without reusing them.
  if (params.has("q")) {
    params.delete("q");
    acceptedHash = `#${raw}${params.size ? `?${params}` : ""}`;
    history.replaceState(null, "", acceptedHash);
  }
  const offset = Number(params.get("offset") || 0);
  return { route: Object.hasOwn(labels, raw) ? raw : "overview", params, offset: Number.isSafeInteger(offset) && offset > 0 ? offset : 0 };
}
function searchText(route = routeInfo().route) { return routeSearch.get(route) || ""; }
function setSearch(value, route = routeInfo().route) {
  value = String(value).slice(0, 100);
  value ? routeSearch.set(route, value) : routeSearch.delete(route);
  if (route === routeInfo().route && ["customers", "help"].includes(route)) setParam("offset", "", false);
}
function requireRows(data, key) {
  if (!data || !Array.isArray(data[key])) throw Object.assign(new Error("Malformed response"), { category: "unavailable" });
  return data[key];
}
function badge(value) {
  const tone = /^(paid|credited|active|approved|published|resolved)$/.test(value) ? "success" : /^(failed|rejected|inactive|suspended)$/.test(value) ? "danger" : /^(pending|waiting_for_tenant|high|urgent|past_due)$/.test(value) ? "warning" : "";
  return `<span class="status ${tone}">${esc(titleCase(value))}</span>`;
}
function button(action, text, id = "", className = "button") { return `<button type="button" class="${className}" data-action="${action}" data-id="${esc(id)}">${esc(text)}</button>`; }
function heading(name, description, actions = "") { return `<div class="page-header"><div><h1>${esc(name)}</h1><p>${esc(description)}</p></div><div class="header-actions">${actions}</div></div>`; }
function notice(text) { return `<p class="permission-note">${icon("info")}<span>${esc(text)}</span></p>`; }
function empty(text, hint = "New records will appear here when available.") { return `<div class="empty"><h3>${esc(text)}</h3><p>${esc(hint)}</p></div>`; }
function loading(label) { return `<div class="loading-state" role="status" aria-busy="true"><span class="loading-line"></span><p>${esc(label)}</p></div>`; }
function errorText(error) {
  if (error?.code === "gateway_recheck_unavailable") return "This payment requires a verified gateway callback. Rechecking from this portal is unavailable.";
  if (error?.status === 409) return "This record changed. Refresh it before trying again.";
  if (error?.code === "platform_admin_audit_unavailable") return "Activity logging is unavailable. This action could not be confirmed.";
  if (error?.category === "validation") return "The server could not accept these changes. Check the fields and the record's current status.";
  if (error?.category === "not_found") return "This record is no longer available.";
  return "Records could not be loaded or changes confirmed. Check your connection and retry.";
}
function errorPanel(error, retry = "refresh") { return `<div class="error-state" role="alert"><h3>Unable to complete this request</h3><p>${esc(errorText(error))}</p>${retry ? button(retry, "Retry") : ""}</div>`; }
function handleAuthorization(error) {
  if (error?.category === "aborted") return true;
  if (["unauthenticated", "access_denied"].includes(error?.category)) {
    identity = null; dirty = false; confirmation = null; listRows = []; listData = null; detailData = null; routeSearch.clear(); clearTimeout(searchTimer);
    $("#global-search").value = ""; $("#global-clear").hidden = true;
    $("#confirm-reason").value = ""; $("#confirm-summary").textContent = ""; $("#detail-title").textContent = ""; $("#toast").hidden = true;
    $("#detail-dialog").close(); $("#confirm-dialog").close();
    shell.handleError(error); return true;
  }
  return false;
}
function renderNavigation() {
  const current = routeInfo().route;
  $("#navigation").innerHTML = navigation.map(([id, name, symbol, section]) => `${section ? `<p class="nav-section-label">${section}</p>` : ""}<a class="nav-item ${id === current ? "active" : ""}" href="#${id}" ${id === current ? 'aria-current="page"' : ""}>${icon(symbol)}<span>${name}</span></a>`).join("");
}
function toast(message) {
  clearTimeout(toastTimer);
  const node = $("#toast");
  ($( "#detail-dialog").open ? $("#detail-dialog") : document.body).append(node);
  node.textContent = message; node.hidden = false;
  toastTimer = setTimeout(() => { node.hidden = true; }, 5000);
}
function table(headers, rows, label, pagination = null, pagingAction = "page") {
  const pages = pagination || { offset: 0, returned: rows.length, total: rows.length, has_more: false };
  return `<div class="panel"><div class="table-wrap" role="region" tabindex="0" aria-label="${esc(label)}"><table><thead><tr>${headers.map(value => `<th scope="col">${value}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>${rows.length ? "" : empty("No matching records", "Change the filters or refresh to check for new records.")}</div><div class="table-total"><span>${count(pages.total)} records · ${rows.length ? `${count(pages.offset + 1)}–${count(pages.offset + rows.length)}` : "0 shown"}</span><div class="pagination"><button class="button" data-action="${pagingAction}" data-offset="${Math.max(0, pages.offset - pageSize)}" ${pages.offset > 0 ? "" : "disabled"}>Previous</button><button class="button" data-action="${pagingAction}" data-offset="${pages.offset + pageSize}" ${pages.has_more ? "" : "disabled"}>Next</button></div></div></div>`;
}
function metric(label, value, hint) { return `<div class="metric"><p class="metric-label">${esc(label)}</p><div class="metric-value number">${count(value)}</div><p class="metric-note">${esc(hint)}</p></div>`; }
function countBars(rows, unit) {
  const valid = value => Number.isSafeInteger(value) && value >= 0;
  const knownRows = rows.filter(row => valid(row.value));
  const maximum = Math.max(0, ...knownRows.map(row => row.value));
  return `<div class="chart-bars">${knownRows.length ? `<div class="chart-scale" aria-hidden="true"><span>0</span><span>${count(maximum)} ${esc(unit)}</span></div>` : '<p class="chart-unavailable">Chart counts are unavailable.</p>'}<ul class="chart-bar-list">${rows.map(row => {
    const known = valid(row.value), width = known && maximum > 0 ? row.value / maximum * 100 : 0;
    return `<li class="chart-bar-row"><div class="chart-row-label"><span>${esc(row.label)}</span><strong class="number">${count(row.value)}</strong></div><div class="chart-track ${known ? "" : "chart-track-unavailable"}" aria-hidden="true"><span class="chart-bar" style="width:${width}%;background:var(${row.color || "--accent"})"></span></div></li>`;
  }).join("")}</ul>${rows.every(row => row.value === 0) ? '<p class="chart-empty-note">No records in these categories.</p>' : ""}</div>`;
}
function subscriptionStatusChart(source) {
  const rows = [
    { key: "active", label: "Active", color: "--success" },
    { key: "trialing", label: "Trialing", color: "--accent" },
    { key: "past_due", label: "Past due", color: "--warning" },
    { key: "expired", label: "Expired", color: "--danger" },
    { key: "cancelled", label: "Cancelled", color: "--subtle" }
  ].map(row => ({ ...row, value: source?.[row.key] }));
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  const complete = rows.every(row => Number.isSafeInteger(row.value) && row.value >= 0) && Number.isSafeInteger(total);
  let angle = 0;
  const segments = complete && total > 0 ? rows.map(row => {
    const start = angle; angle += row.value / total * 360;
    return `var(${row.color}) ${start}deg ${angle}deg`;
  }).join(",") : null;
  return `<div class="status-chart">${complete ? `<div class="status-donut" role="img" aria-label="${count(total)} subscriptions by reported status. Exact counts follow." ${segments ? `style="background:conic-gradient(${segments})"` : ""}><div class="status-center"><strong class="number">${count(total)}</strong><span>subscriptions</span></div></div>` : '<p class="chart-unavailable">Chart unavailable: some status counts are missing.</p>'}<ul class="status-legend">${rows.map(row => `<li><a href="#subscriptions?status=${row.key}" class="status-chart-link"><span class="chart-swatch" style="background:var(${row.color})" aria-hidden="true"></span><span>${row.label}</span><strong class="number">${count(row.value)}</strong></a></li>`).join("")}</ul>${complete && total === 0 ? '<p class="chart-empty-note">No subscriptions yet.</p>' : ""}</div>`;
}
function chartFootnote(description, timestamp) {
  return `<p class="panel-footnote chart-footnote"><span>${esc(description)}</span><span>${timestamp ? `Updated ${esc(date(timestamp))}` : "Update time not available"}</span></p>`;
}
function companyLink(item, action = "company", id = item.id ?? item.company_id) {
  const name = item.company_name || `Company ${id}`;
  return `<div class="cell-main"><span class="company-mark">${esc(name.slice(0, 2).toUpperCase())}</span><button class="text-button" data-action="${action}" data-id="${esc(id)}"><strong>${esc(name)}</strong><small>Company ${esc(id)}</small></button></div>`;
}
function detailList(entries) { return `<dl class="detail-list">${entries.map(([key, value]) => `<dt>${esc(key)}</dt><dd>${value}</dd>`).join("")}</dl>`; }
function options(items, selected, all = true) { return `${all ? '<option value="">All statuses</option>' : ""}${items.map(value => `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(titleCase(value))}</option>`).join("")}`; }
function toolbar(route) {
  const { params } = routeInfo(), q = searchText(route), status = params.get("status") || "";
  const statuses = { customers: ["active", "inactive"], payments: ["trialing", "active", "past_due", "expired", "cancelled"], subscriptions: ["trialing", "active", "past_due", "expired", "cancelled"], support: ["open", "in_progress", "waiting_for_tenant", "resolved", "closed"], approvals: ["pending", "approved", "rejected"], team: ["active", "inactive"], help: ["published", "draft"] }[route] || [];
  return `<div class="list-toolbar"><div class="local-search">${icon("search")}<label class="sr-only" for="list-search">${route === "customers" ? "Search all customers" : "Filter the current page"}</label><input id="list-search" type="search" maxlength="100" placeholder="${route === "customers" ? "Search customers…" : "Filter this page…"}" value="${esc(q)}" autocomplete="off"><button class="icon-button" data-action="clear-search" aria-label="Clear list search" ${q ? "" : "hidden"}>${icon("x")}</button></div>${statuses.length ? `<label class="sr-only" for="status-filter">Status</label><select id="status-filter">${options(statuses, status)}</select>` : ""}<span class="filter-summary">${route === "customers" ? "Searches all companies" : "Text search filters this page"}</span></div><div id="list-content">${loading("Loading records…")}</div>`;
}
async function overview(sequence) {
  const settled = await shell.runRequest("view", signal => Promise.allSettled([api.getOverview({ signal }), api.getBillingOverview({ signal }), api.listApprovalRequests({ limit: 5, offset: 0, status: "pending", signal })]));
  if (sequence !== viewSequence || !identity) return;
  for (const result of settled) if (result.status === "rejected" && handleAuthorization(result.reason)) return;
  const operation = settled[0].status === "fulfilled" ? settled[0].value : null;
  const billing = settled[1].status === "fulfilled" ? settled[1].value : null;
  const approvals = settled[2].status === "fulfilled" ? settled[2].value : null;
  const plans = operation?.subscriptions?.by_plan;
  const planRows = Array.isArray(plans) ? plans.map(plan => ({ label: plan?.name || plan?.code || "Unknown plan", value: plan?.count })).sort((a, b) => (Number.isSafeInteger(b.value) ? b.value : -1) - (Number.isSafeInteger(a.value) ? a.value : -1)) : null;
  const paymentRows = [
    { label: "Pending", value: billing?.subscription_orders?.pending_count, color: "--warning" },
    { label: "Failed", value: billing?.subscription_orders?.failed_count, color: "--danger" },
    { label: "Reconciliation required", value: billing?.subscription_orders?.reconciliation_required_count, color: "--accent" }
  ];
  const alerts = operation?.operational_alerts?.alerts;
  const requests = approvals && Array.isArray(approvals.requests) ? approvals.requests : [];
  $("#main").innerHTML = heading("Overview", "The platform at a glance. Your next decisions, in one place.", button("refresh", "Refresh records")) +
    `<div class="overview-period"><span>Current platform state</span><span>${operation ? `Updated ${esc(date(operation.generated_at))}` : "Some totals are unavailable"}</span></div><div class="metrics">${metric("Active companies", operation?.companies?.active, "Across the platform")}${metric("Active subscriptions", operation?.subscriptions?.by_status?.active, "Current subscription status")}${metric("Payments needing review", billing?.subscription_orders?.reconciliation_required_count, "Reconciliation required")}${metric("Awaiting approval", approvals?.pagination?.total, "Pending staff requests")}</div>` +
    `<div class="analytics-grid"><section class="panel chart-panel" aria-labelledby="plan-chart-title"><div class="panel-heading"><h2 id="plan-chart-title">Subscriptions by plan</h2><a href="#subscriptions" class="text-button">View subscriptions ${icon("arrow")}</a></div>${planRows ? (planRows.length ? countBars(planRows, "subscriptions") : empty("No subscriptions with a listed plan", "Current records contain no plan breakdown.")) : errorPanel(settled[0].reason)}${chartFootnote("Latest subscription per company with a listed plan.", operation?.generated_at)}</section>` +
    `<section class="panel chart-panel" aria-labelledby="status-chart-title"><div class="panel-heading"><h2 id="status-chart-title">Subscription status</h2><span class="chart-caption">Current snapshot</span></div>${operation ? subscriptionStatusChart(operation.subscriptions?.by_status) : errorPanel(settled[0].reason)}${chartFootnote("Reported statuses for each company's latest subscription.", operation?.generated_at)}</section>` +
    `<section class="panel chart-panel" aria-labelledby="payment-chart-title"><div class="panel-heading"><h2 id="payment-chart-title">Payment follow-up</h2><a href="#payments" class="text-button">Review payments ${icon("arrow")}</a></div>${billing ? countBars(paymentRows, "orders") : errorPanel(settled[1].reason)}${chartFootnote("All subscription orders. Pending includes new orders; queues may overlap.", billing?.generated_at)}</section>` +
    `<section class="panel attention-panel"><div class="panel-heading"><h2>Needs attention</h2><a class="text-button" href="#approvals">Review</a></div>${Array.isArray(alerts) ? (alerts.length ? alerts.map(alert => `<a class="attention-row" href="#${alert.company_id ? `customers?company=${encodeURIComponent(alert.company_id)}` : "support"}"><span>${icon("info")}</span><div><strong>${esc(alert.title || titleCase(alert.type))}</strong><p>${esc(alert.summary || alert.message || "Review this platform alert.")}</p></div>${icon("arrow")}</a>`).join("") : empty("No operational alerts")) : errorPanel(settled[0].reason)}</section></div>` +
    `<div class="section-heading"><h2>Approval queue</h2><a href="#approvals" class="text-button">View all ${icon("arrow")}</a></div>${approvals ? table(["Request", "Company", "Status", "Submitted"], requests.map(request => `<tr><td>${button("approval", titleCase(request.type), request.id, "text-button")}</td><td>${esc(request.company_name || `Company ${request.company_id}`)}</td><td>${badge(request.status)}</td><td>${esc(date(request.created_at))}</td></tr>`), "Recent approval requests") : errorPanel(settled[2].reason)}`;
}
async function loadList(route, signal) {
  const { params, offset } = routeInfo(), status = params.get("status") || undefined;
  const config = { limit: pageSize, offset, signal };
  if (route === "customers") return { data: await api.listCompanies({ ...config, sortBy: "created_at", sortOrder: "desc", search: searchText(route) || undefined, status }), key: "companies" };
  if (route === "payments" || route === "subscriptions") return { data: await api.listBillingCompanies({ ...config, subscriptionStatus: status }), key: "companies" };
  if (route === "support") return params.get("tab") === "incoming" ? { data: await api.listTenantSupportRequests(config), key: "requests" } : { data: await api.listSupportCases({ ...config, status }), key: "cases" };
  if (route === "approvals") return { data: await api.listApprovalRequests({ ...config, status }), key: "requests" };
  if (route === "team") return { data: await api.listPlatformAdminUsers({ ...config, isActive: status ? status === "active" : undefined }), key: "platform_admin_users" };
  if (route === "activity") return { data: await api.listAuditEvents(config), key: "audit_events" };
  if (route === "help") {
    const all = await helpApi.listArticles({ signal });
    const query = searchText(route).toLowerCase();
    const filtered = all.filter(article => (!status || article.is_published === (status === "published")) && (!query || `${article.title} ${article.category}`.toLowerCase().includes(query)));
    return { data: { articles: filtered.slice(offset, offset + pageSize), pagination: { offset, total: filtered.length, returned: Math.min(pageSize, Math.max(0, filtered.length - offset)), has_more: offset + pageSize < filtered.length } }, key: "articles" };
  }
  throw new Error("Unknown route");
}
function renderRows(route, items) {
  if (route === "customers") return [["Company", "Account status", "Contact", "Created", ""], items.map(item => `<tr><td>${companyLink(item)}</td><td>${badge(item.status)}</td><td>${esc(item.contact_email || "Not recorded")}</td><td>${esc(date(item.created_at))}</td><td>${button("company", "View", item.id, "text-button")}</td></tr>`)];
  if (route === "payments") return [["Customer", "Subscription", "Pending orders", "Failed orders", "Review required", ""], items.map(item => `<tr><td>${companyLink(item, "orders")}</td><td>${badge(item.subscription_status)}</td><td class="number">${count(item.subscription_order_attention?.pending_count)}</td><td class="number">${count(item.subscription_order_attention?.failed_count)}</td><td class="number">${count(item.subscription_order_attention?.reconciliation_required_count)}</td><td>${button("orders", "View payments", item.company_id, "text-button")}</td></tr>`)];
  if (route === "subscriptions") return [["Customer", "Plan", "Status", "Period ends", "AI credit balance", ""], items.map(item => `<tr><td>${companyLink(item, "subscription")}</td><td>${esc(item.current_plan?.name || "No plan")}</td><td>${badge(item.subscription_status)}</td><td>${esc(date(item.current_period_end))}</td><td class="number">${microMyr(item.ai_credit_total_balance_micro_myr)}</td><td>${button("subscription", "View", item.company_id, "text-button")}</td></tr>`)];
  if (route === "support") { items = items.map(item => ({ ...item, id: item.id ?? item.request_id })); return [["Case", "Company", "Status", "Priority", "Updated", ""], items.map(item => `<tr><td>${button(routeInfo().params.get("tab") === "incoming" ? "incoming" : "ticket", item.title || item.subject || `Request ${item.id}`, item.id, "text-button")}</td><td>${esc(item.company?.company_name || `Company ${item.company_id}`)}</td><td>${badge(item.status)}</td><td>${badge(item.priority || item.category)}</td><td>${esc(date(item.updated_at || item.created_at))}</td><td>${button(routeInfo().params.get("tab") === "incoming" ? "incoming" : "ticket", "Open", item.id, "text-button")}</td></tr>`)];
  }
  if (route === "approvals") return [["Request", "Company", "Requested by", "Status", "Submitted", ""], items.map(item => `<tr><td>${button("approval", titleCase(item.type), item.id, "text-button")}</td><td>${esc(item.company_name || `Company ${item.company_id}`)}</td><td>${esc(item.requested_by_email || `Staff ${item.requester_platform_admin_user_id}`)}</td><td>${badge(item.status)}</td><td>${esc(date(item.created_at))}</td><td>${button("approval", "Review", item.id, "text-button")}</td></tr>`)];
  if (route === "team") return [["Team member", "Role", "Assigned modules", "Access", "Last activity", ""], items.map(item => `<tr><td><strong>${esc(item.user_full_name || item.user_email || `User ${item.user_id}`)}</strong><small class="cell-secondary">${esc(item.user_email)}</small></td><td>${esc(titleCase(item.platform_role))}</td><td>${item.platform_role === "super_admin" ? "All modules" : esc(["billing", "support", "customers"].filter(key => item.modules?.[key] === true).map(titleCase).join(", ") || "None assigned")}</td><td>${badge(item.is_active ? "active" : "inactive")}</td><td>${esc(date(item.recent_platform_admin_activity_at))}</td><td>${button("permissions", "Edit access", item.platform_admin_user_id, "text-button")}</td></tr>`)];
  if (route === "help") return [["Article", "Category", "Status", "Updated", ""], items.map(item => `<tr><td>${button("article", item.title, item.id, "text-button")}</td><td>${esc(titleCase(item.category))}</td><td>${badge(item.is_published ? "published" : "draft")}</td><td>${esc(date(item.updated_at))}</td><td>${button("edit-article", "Edit", item.id, "text-button")}</td></tr>`)];
  return [["Event", "Resource", "Actor", "Recorded", ""], items.map(item => `<tr><td>${esc(item.action)}</td><td>${esc(item.resource_type)} <span class="number">${esc(item.resource_id)}</span></td><td>${esc(item.actor_user_id ?? item.platform_admin_user_id ?? "Not available")}</td><td>${esc(date(item.created_at))}</td><td>${button("event", "Details", item.id, "text-button")}</td></tr>`)];
}
function paintList() {
  const { route } = routeInfo(), q = searchText(route).trim().toLowerCase();
  const filtered = route === "customers" || route === "help" || !q ? listRows : listRows.filter(item => JSON.stringify(item).toLowerCase().includes(q));
  const [headers, rows] = renderRows(route, filtered);
  $("#list-content").innerHTML = table(headers, rows, labels[route], listData.pagination);
}
async function render() {
  if (!identity) return;
  const sequence = ++viewSequence, { route, params } = routeInfo();
  renderNavigation(); listData = null; listRows = [];
  const descriptions = { payments: "Review payment records and investigate customer billing.", customers: "Account summaries, subscriptions, and support history.", subscriptions: "Plans, renewal periods, and subscription status.", support: "Work customer requests and internal support cases.", approvals: "Review staff requests. A decision does not execute a financial or account change.", team: "Assign staff modules and manage platform access.", help: "Write and maintain articles for the customer help centre.", activity: "A record of platform access and administrative changes." };
  if (route === "settings") {
    $("#main").innerHTML = settingsView();
    return;
  }
  if (route === "overview") { $("#main").innerHTML = heading("Overview", "The platform at a glance.") + loading("Loading platform overview…"); try { await overview(sequence); } catch (error) { if (sequence === viewSequence && !handleAuthorization(error)) $("#main").innerHTML += errorPanel(error); } return; }
  $("#main").innerHTML = heading(labels[route], descriptions[route], `${route === "help" ? button("new-article", "New article", "", "button primary") : ""}${button("refresh", "Refresh records")}${button("export", "Export page")}`) +
    (route === "support" ? `<nav class="tabs" aria-label="Help Desk views"><a class="tab ${params.get("tab") !== "incoming" ? "active" : ""}" href="#support">Support cases</a><a class="tab ${params.get("tab") === "incoming" ? "active" : ""}" href="#support?tab=incoming">Incoming requests</a></nav>` : "") +
    (route === "payments" ? notice("Choose a customer to see their payment orders. Counts include subscription orders; an order marked paid is not a refund or payout record.") : "") + (route === "team" ? `<div class="section-heading">${button("new-staff", "Add existing user", "", "button primary")}</div>` : "") + toolbar(route);
  try {
    const result = await shell.runRequest("view", signal => loadList(route, signal));
    if (sequence !== viewSequence || !identity) return;
    listRows = requireRows(result.data, result.key); listData = result.data;
    if (!listData.pagination || !Number.isSafeInteger(listData.pagination.total)) throw Object.assign(new Error("Missing pagination"), { category: "unavailable" });
    paintList(); $("#updated-at").textContent = `Records loaded ${date(new Date())}`;
    if (params.get("company") && route === "customers") await companyDetail(Number(params.get("company")));
  } catch (error) { if (sequence === viewSequence && !handleAuthorization(error)) $("#list-content").innerHTML = errorPanel(error); }
}

function details(title, eyebrow, html) {
  const dialog = $("#detail-dialog");
  $("#detail-title").textContent = title; $("#detail-eyebrow").textContent = eyebrow;
  $("#detail-content").innerHTML = html; dirty = false;
  if (!dialog.open) { detailOpener = document.activeElement; dialog.showModal(); }
  $("[data-action=close-detail]").focus({ preventScroll: true });
}
async function loadDetail(title, factory, painter) {
  if (!identity) return;
  const sequence = ++detailSequence;
  details(title, "Loading record", loading("Loading details…"));
  try {
    const data = await shell.runRequest("detail", factory);
    if (sequence !== detailSequence || !$("#detail-dialog").open || !identity) return;
    detailData = data; painter(data);
  } catch (error) { if (sequence === detailSequence && $("#detail-dialog").open && !handleAuthorization(error)) { $("#detail-eyebrow").textContent = "Request failed"; $("#detail-content").innerHTML = errorPanel(error, "") + button("close-detail", "Close and try again"); } }
}
function confirmAction({ title, description, summary, label, action, reason = true, danger = false }) {
  if (mutating) return;
  confirmation = { action, reason };
  $("#confirm-title").textContent = title; $("#confirm-description").textContent = description;
  $("#confirm-summary").textContent = summary; $("#confirm-submit").textContent = label;
  $("#confirm-submit").className = `button ${danger ? "danger" : "primary"}`;
  $("#reason-field").hidden = !reason; $("#confirm-reason").value = "";
  $("#confirm-reason").removeAttribute("aria-invalid"); $("#confirm-error").textContent = "";
  $("#confirm-dialog").showModal(); $("[data-action=cancel-confirm]").focus();
}
function closeDetail() {
  if (mutating) return;
  const close = () => { dirty = false; ++detailSequence; $("#detail-dialog").close(); };
  if (dirty) confirmAction({ title: "Discard your changes?", description: "Your unsaved text will be lost.", summary: $("#detail-title").textContent, label: "Discard changes", reason: false, danger: true, action: close });
  else close();
}
function companyDetail(id) {
  return loadDetail("Customer", signal => Promise.allSettled([api.getCompany(id, { signal }), api.getCompanySubscription(id, { signal }), api.getCompanyAiCreditUsage(id, { signal })]), results => {
    const firstFailure = results.find(result => result.status === "rejected" && ["unauthenticated", "access_denied"].includes(result.reason?.category));
    if (firstFailure && handleAuthorization(firstFailure.reason)) return;
    if (results[0].status !== "fulfilled") { $("#detail-content").innerHTML = errorPanel(results[0].reason, ""); return; }
    const company = results[0].value, subscription = results[1].status === "fulfilled" ? results[1].value.subscription : null, credit = results[2].status === "fulfilled" ? results[2].value : null;
    detailData = { kind: "company", company };
    details(company.company_name, `Customer · ${id}`, detailList([["Account", badge(company.status)], ["Contact email", esc(company.contact_email || "Not recorded")], ["Contact phone", esc(company.contact_phone || "Not recorded")], ["Business", esc(company.business_type || "Not recorded")], ["Created", esc(date(company.created_at))]]) +
      `<div class="detail-section"><h3>Subscription & usage</h3>${results[1].status === "fulfilled" ? detailList([["Plan", esc(subscription?.plan?.name || "No current plan")], ["Subscription", badge(subscription?.status)], ["Period ends", esc(date(subscription?.current_period_end))]]) : errorPanel(results[1].reason, "")}${credit ? detailList([["AI credit balance", credit.credit_balance?.initialized ? microMyr(credit.credit_balance.total_balance_micro_myr) : "Not initialized"], ["Usage period", `${esc(date(credit.period?.start))} – ${esc(date(credit.period?.end))}`]]) : errorPanel(results[2].reason, "")}</div><div class="detail-actions">${button("orders", "View payments", id)}${button("company-support", "Support history", id)}</div>` + notice("Customer conversations remain restricted. Contact editing is not available in this portal.") + `<div class="detail-section"><h3>Account access</h3><p>Inactive accounts cannot use the customer workspace.</p>${button(company.status === "active" ? "suspend-company" : "restore-company", company.status === "active" ? "Suspend company" : "Restore company", id, `button ${company.status === "active" ? "danger" : "primary"}`)}</div>`);
  });
}
function ordersDetail(id, offset = 0) {
  return loadDetail("Payment orders", signal => api.listCompanyBillingOrders(id, { signal, limit: pageSize, offset }), data => {
    const rows = requireRows(data, "billing_orders"); detailData = { kind: "orders", companyId: id, rows, offset };
    details("Payment orders", `Company ${id}`, notice("Amounts are shown in the stored unit (sen). Currency is not supplied by this record. Refresh reads saved records; the separate Recheck payment action verifies gateway status.") + table(["Order", "Amount", "Status", "Created", ""], rows.map(order => `<tr><td class="number">${esc(order.id)}</td><td class="number">${count(order.amount_sen)} sen</td><td>${badge(order.status)}</td><td>${esc(date(order.created_at))}</td><td>${button("payment", "Details", order.id, "text-button")}</td></tr>`), "Company payment orders", data.pagination, "orders-page") + `<div class="detail-actions">${button("orders", "Refresh stored records", id)}</div>`);
  });
}
function paymentDetail(id) {
  const record = detailData?.rows?.find(row => String(row.id) === String(id));
  if (!record) return;
  const companyId = detailData.companyId, rows = detailData.rows;
  details(`Payment ${record.id}`, `Company ${companyId}`, `<div class="detail-amount number">${count(record.amount_sen)} <small>sen</small></div>${badge(record.status)}${detailList([["Plan", esc(record.new_plan?.name || "Not recorded")], ["Activation", badge(record.activation_status)], ["Reconciliation", record.reconciliation_required ? "Required" : "Not required"], ["Created", esc(date(record.created_at))], ["Paid", esc(date(record.paid_at))], ["Updated", esc(date(record.updated_at))]])}${notice("Refunds and manual payment approvals cannot be executed here. Review staff requests in Approvals; financial execution remains separate.")}<div class="detail-actions">${button("orders", "Back to payment orders", companyId)}${button("recheck", "Recheck payment", record.id)}</div><p id="detail-operation-error" class="field-error" role="alert"></p>`);
  detailData = { kind: "payment", record, companyId, rows };
}
function subscriptionDetail(id) {
  return loadDetail("Subscription", signal => api.getCompanySubscription(id, { signal }), data => {
    const sub = data.subscription;
    details(data.company?.company_name || `Company ${id}`, "Subscription", sub ? detailList([["Plan", esc(sub.plan?.name || "Not recorded")], ["Status", badge(sub.status)], ["Period starts", esc(date(sub.current_period_start))], ["Period ends", esc(date(sub.current_period_end))], ["Cancellation effective", esc(date(sub.cancellation_effective_at))], ["Plan change effective", esc(date(sub.plan_change_effective_at))]]) + notice("Plan changes require a reviewed request and a separate subscription operation. No plan change is executed by recording approval.") + button("orders", "View payment history", id) : empty("No current subscription"));
  });
}
function approvalDetail(id) {
  return loadDetail("Approval request", signal => api.getApprovalRequest(id, { signal }), data => {
    const request = data.request;
    if (!request || !request.id) throw new Error("Invalid approval response");
    detailData = { kind: "approval", request };
    details(titleCase(request.type), `Request ${request.id} · Company ${request.company_id}`, badge(request.status) + `<div class="detail-section"><h3>${esc(request.summary)}</h3><p class="preserve-lines">${esc(request.reason)}</p></div>` + detailList([["Requested by", `Staff ${esc(request.requester_platform_admin_user_id)}`], ["Submitted", esc(date(request.created_at))], ["Decision reason", esc(request.decision_reason || "Not reviewed")], ["Reviewed", esc(date(request.reviewed_at))], ["Execution", "Not executed"]]) + notice("Approval records a decision only. It does not issue a refund, approve payment, change a plan, or update the account.") + (request.status === "pending" ? `<div class="detail-actions">${button("approve", "Approve request", id, "button primary")}${button("reject", "Reject request", id, "button danger")}</div>` : notice("This request has already been decided. Repeated decisions are blocked.")));
  });
}
function permissionsDetail(id) {
  return loadDetail("Staff access", signal => api.getPlatformAdminUser(id, { signal }), data => {
    const person = data.platform_admin_user;
    if (!person) throw new Error("Missing staff record");
    detailData = { kind: "permissions", person };
    details(person.user_full_name || person.user_email || `User ${person.user_id}`, "Team & permissions", `<p class="muted">${esc(person.user_email)}</p><form id="permissions-form" novalidate><div class="field"><label for="staff-role">Platform role</label><select id="staff-role"><option value="admin" ${person.platform_role === "admin" ? "selected" : ""}>Admin</option><option value="super_admin" ${person.platform_role === "super_admin" ? "selected" : ""}>Super Admin</option></select></div><div class="detail-section"><h3>Assigned modules</h3><p>Super Admin receives every module. Admin receives only the modules selected below.</p>${["billing", "support", "customers"].map(key => `<label class="permission-row"><span><strong>${({ billing: "Billing", support: "Help Desk", customers: "Customer Management" })[key]}</strong><p>${({ billing: "View payment records and check stored status.", support: "Work support cases, replies and internal notes.", customers: "View permitted customer summaries." })[key]}</p></span><input class="switch" type="checkbox" id="module-${key}" ${person.platform_role === "super_admin" || person.modules?.[key] ? "checked" : ""} ${person.platform_role === "super_admin" ? "disabled" : ""}></label>`).join("")}</div><p class="field-error" id="permissions-error" role="alert"></p><div class="detail-actions"><button class="button primary" type="submit">Review permission changes</button>${button("close-detail", "Cancel")}</div></form><div class="detail-section"><h3>Account access</h3>${badge(person.is_active ? "active" : "inactive")}<p>Changing staff access does not delete the underlying user.</p>${button("staff-active", person.is_active ? "Deactivate access" : "Activate access", id, `button ${person.is_active ? "danger" : "primary"}`)}</div>`);
  });
}
function historyMessage(item, isNote) { return `<article class="support-message ${isNote ? "private" : ""}"><div><strong>${isNote ? item.redacted_note ? "Internal note · Team only" : "Internal activity · Team only" : "Customer-visible reply"}</strong><span>${esc(date(item.created_at))}</span></div><p>${esc(isNote ? item.redacted_note || titleCase(item.event_type) : item.redacted_body)}</p></article>`; }
function ticketDetail(id, mode = "reply", offset = 0) {
  return loadDetail("Support case", signal => Promise.allSettled([api.getSupportCase(id, { signal, eventLimit: pageSize, eventOffset: offset }), api.listSupportCaseReplies(id, { signal, limit: pageSize, offset }), api.listSupportCaseAssignees({ signal })]), results => {
    const failure = results.find(result => result.status === "rejected" && ["unauthenticated", "access_denied"].includes(result.reason?.category));
    if (failure && handleAuthorization(failure.reason)) return;
    if (results[0].status !== "fulfilled") { $("#detail-content").innerHTML = errorPanel(results[0].reason, ""); return; }
    const data = results[0].value, ticket = data.case;
    const replyData = results[1].status === "fulfilled" ? results[1].value : null;
    const assignees = results[2].status === "fulfilled" ? requireRows(results[2].value, "assignees") : [];
    detailData = { kind: "ticket", data, ticket, mode, offset };
    const canReply = Boolean(data.source_tenant_request && replyData), transitions = Array.isArray(data.status_transitions) ? data.status_transitions : [];
    details(ticket.title, `Case ${id} · ${ticket.company?.company_name || `Company ${ticket.company_id}`}`, `<div class="article-meta">${badge(ticket.status)}${badge(ticket.priority)}</div><p class="preserve-lines">${esc(ticket.redacted_summary)}</p>${supportTrail(data.source_tenant_request?.escalation_context)}<form id="ticket-settings" novalidate><div class="assignment"><label for="ticket-assignee">Assignee</label><select id="ticket-assignee" ${results[2].status !== "fulfilled" ? "disabled" : ""}><option value="">Unassigned</option>${assignees.map(person => `<option value="${esc(person.id)}" ${person.id === ticket.assigned_platform_admin_user_id ? "selected" : ""}>${esc(person.user_full_name || person.user_email || `Staff ${person.id}`)}</option>`).join("")}</select><button class="button" type="submit" ${results[2].status !== "fulfilled" ? "disabled" : ""}>Assign</button></div><p class="field-error" id="assignment-error" role="alert"></p></form>${results[2].status !== "fulfilled" ? errorPanel(results[2].reason, "") : ""}<div class="detail-actions">${transitions.map(status => `<button class="button" data-action="ticket-status" data-id="${id}" data-status="${esc(status)}">${esc(status === "in_progress" && ["closed", "resolved"].includes(ticket.status) ? "Reopen case" : titleCase(status))}</button>`).join("")}</div><div class="detail-section"><h3>Customer replies</h3>${replyData ? (requireRows(replyData, "replies").map(item => historyMessage(item, false)).join("") || empty("No replies yet")) : errorPanel(results[1].reason, "")}</div><div class="detail-section"><h3>Internal activity</h3>${requireRows(data, "events").map(item => historyMessage(item, true)).join("") || empty("No internal activity")}</div><div class="pagination">${button("ticket-history-prev", "Previous history", id)}${button("ticket-history-next", "Next history", id)}</div><p class="muted">History starts at record ${offset + 1}. Up to ${pageSize} entries per history section.</p><div class="detail-section"><div class="reply-modes"><button class="reply-mode ${mode === "reply" ? "active" : ""}" data-action="reply-mode" data-mode="reply" ${canReply ? "" : "disabled"}>Reply to customer</button><button class="reply-mode ${mode === "note" ? "active" : ""}" data-action="reply-mode" data-mode="note">Private note</button></div>${!canReply ? notice("Customer replies are available only for a linked customer request with loaded reply history. Internal notes are still available.") : ""}<form id="ticket-message" novalidate><div class="field"><label for="message-body">${mode === "note" || !canReply ? "Internal note · Team only" : "Reply · Visible to customer"}</label><textarea id="message-body" rows="5" maxlength="2000" aria-describedby="message-error message-help"></textarea><p id="message-help" class="muted">Keep account secrets and sensitive payment information out of support messages.</p><p class="field-error" id="message-error" role="alert"></p></div><button class="button primary" type="submit">${mode === "note" || !canReply ? "Save private note" : "Review customer reply"}</button></form></div>`);
    if (!canReply) detailData.mode = "note";
    $("[data-action=ticket-history-prev]").disabled = offset === 0;
    $("[data-action=ticket-history-next]").disabled = !data.events_pagination?.has_more && !replyData?.pagination?.has_more;
  });
}
function supportTrail(context) {
  if (!context || typeof context !== "object") return "";
  const rows = [["searches", "Searched"], ["viewed", "Opened"], ["unhelpful", "Did not help"]].flatMap(([key, label]) => {
    const values = Array.isArray(context[key]) ? context[key].filter(value => typeof value === "string") : [];
    return values.length ? [[label, esc(values.join("; "))]] : [];
  });
  if (typeof context.from_page === "string" && context.from_page) rows.push(["Came from", esc(context.from_page)]);
  return rows.length ? `<section class="detail-section" aria-label="Self-service trail"><h3>Self-service trail</h3>${detailList(rows)}</section>` : "";
}
function incomingDetail(id) {
  return loadDetail("Customer request", signal => api.getTenantSupportRequest(id, { signal }), data => {
    const request = data.request;
    if (!request) throw new Error("Missing support request");
    details(request.title || `Request ${id}`, `Company ${request.company_id}`, badge(request.status) + `<div class="detail-section"><h3>${esc(titleCase(request.category))}</h3><p class="preserve-lines">${esc(request.redacted_description)}</p></div>` + supportTrail(request.escalation_context) + notice("Convert this customer request to a support case to assign staff, reply, and add internal notes.") + button("convert-request", "Open as support case", id, "button primary"));
  });
}
function companySupport(id, offset = 0) {
  return loadDetail("Support history", signal => api.listSupportCases({ companyId: id, limit: pageSize, offset, signal }), data => {
    detailData = { kind: "company-support", companyId: id, offset };
    details("Support history", `Company ${id}`, table(["Case", "Status", "Updated"], requireRows(data, "cases").map(item => `<tr><td>${button("ticket", item.title, item.id, "text-button")}</td><td>${badge(item.status)}</td><td>${esc(date(item.updated_at))}</td></tr>`), "Company support cases", data.pagination, "company-support-page") + notice("This history contains support cases. Customer bot conversations are restricted."));
  });
}
function articleDetail(id, edit = false) {
  const item = listRows.find(article => article.id === id);
  if (!item) { toast("Refresh the article list before opening this record."); return; }
  detailData = { kind: "article", article: item };
  details(item.title, "Help article", edit ? articleForm(item) : `<div class="article-meta">${badge(item.is_published ? "published" : "draft")}<span>${esc(titleCase(item.category))}</span></div><div class="article-content">${esc(item.body)}</div><div class="detail-actions">${button("edit-article", "Edit article", id)}${button("publish-article", item.is_published ? "Unpublish" : "Publish", id, "button primary")}${button("delete-article", "Delete article", id, "button danger")}</div>`);
}
function articleForm(item = {}) {
  return `<form id="article-form" novalidate data-id="${esc(item.id || "")}"><div class="field"><label for="article-title">Title</label><input id="article-title" value="${esc(item.title)}" maxlength="200" aria-describedby="article-error"></div><div class="field"><label for="article-category">Category</label><select id="article-category">${helpApi.CATEGORIES.map(category => `<option value="${category.value}" ${category.value === item.category ? "selected" : ""}>${category.label}</option>`).join("")}</select></div><div class="field"><label for="article-slug">URL slug</label><input id="article-slug" value="${esc(item.slug)}" maxlength="200" placeholder="Optional: generated from the title" aria-describedby="article-error"></div><div class="field"><label for="article-body">Article content</label><textarea id="article-body" rows="14" maxlength="8000" aria-describedby="article-error">${esc(item.body)}</textarea></div><div class="field"><label for="article-sort-order">Display order</label><input id="article-sort-order" type="number" min="0" max="2147483647" step="1" value="${esc(item.sort_order ?? 0)}" aria-describedby="article-order-help article-error"><p id="article-order-help" class="muted">Lower numbers appear first.</p></div><p id="article-error" class="field-error" role="alert"></p>${item.is_published ? notice("This article is published. Saving changes updates the customer help centre.") : notice("Saved drafts stay private until published.")}<div class="detail-actions"><button class="button primary" type="submit">${item.is_published ? "Review article changes" : "Save draft"}</button>${button("close-detail", "Cancel")}</div></form>`;
}
function settingsView() {
  return heading("Settings", "Your platform access and reporting preferences.") + `<div class="settings-layout"><nav class="settings-menu" aria-label="Settings sections"><a class="active" href="#settings">Platform preferences</a><a href="#team">Team & permissions</a><a href="#activity">Activity log</a></nav><div><section class="settings-section"><h2>Platform details</h2><p>Current configuration for this control panel.</p>${detailList([["Platform", "Omnexa"], ["Reporting timezone", "Asia/Kuala_Lumpur"], ["Account", esc(identity.user?.email || "Not available")], ["Platform role", "Super Admin"], ["Billing display", "Use each record's reported currency and units"]])}</section><section class="settings-section"><h2>Notifications & preferences</h2>${notice("Editing platform preferences and notification subscriptions is not available yet. Approval requests can be reviewed in the Approvals page.")}<div class="detail-actions"><a class="button" href="#approvals">Review approvals</a><a class="button" href="#team">Manage staff permissions</a></div></section></div></div>`;
}

function setParam(key, value, resetOffset = true) {
  const { route, params } = routeInfo();
  value ? params.set(key, String(value)) : params.delete(key);
  if (resetOffset && key !== "offset") params.delete("offset");
  params.delete("company");
  const hash = `#${route}${params.size ? `?${params}` : ""}`;
  history.replaceState(null, "", hash); acceptedHash = hash;
}
function setBusy(form, value) {
  if (!value && form.getAttribute("aria-busy") !== "true") return;
  form.setAttribute("aria-busy", String(value));
  form.querySelectorAll("button,input,textarea,select").forEach(control => {
    if (value) { control.dataset.wasDisabled = String(control.disabled); control.disabled = true; }
    else { control.disabled = control.dataset.wasDisabled === "true"; delete control.dataset.wasDisabled; }
  });
}
async function commit(form, errorId, operation, after) {
  if (mutating || !identity) return;
  mutating = true; setBusy(form, true);
  const errorNode = document.getElementById(errorId);
  if (errorNode) errorNode.textContent = "";
  try {
    const result = await operation();
    dirty = false;
    mutating = false; setBusy(form, false);
    if (after) await after(result);
  } catch (error) {
    if (!handleAuthorization(error) && errorNode) errorNode.textContent = errorText(error) + " If this action could have been saved, refresh the record before retrying.";
  } finally { mutating = false; setBusy(form, false); }
}
function validate(id, errorId, condition, message) {
  const field = document.getElementById(id);
  const valid = condition(field.value.trim());
  field.setAttribute("aria-invalid", String(!valid));
  if (!valid) { document.getElementById(errorId).textContent = message; field.focus(); }
  return valid;
}
function exportPage() {
  if (!listData || !listRows.length) { toast("Load a page with records before exporting."); return; }
  const route = routeInfo().route, q = searchText(route).trim().toLowerCase();
  const rows = (route === "customers" || route === "help" || !q) ? listRows : listRows.filter(item => JSON.stringify(item).toLowerCase().includes(q));
  const fields = ({ customers: ["id", "company_name", "status", "contact_email", "created_at"], payments: ["company_id", "company_name", "subscription_status"], subscriptions: ["company_id", "company_name", "subscription_status", "current_period_start", "current_period_end"], support: ["id", "request_id", "title", "company_id", "status", "priority"], approvals: ["id", "type", "company_id", "summary", "status", "execution_status", "created_at"], team: ["platform_admin_user_id", "user_email", "platform_role", "is_active"], help: ["id", "title", "category", "is_published", "updated_at"], activity: ["id", "action", "resource_type", "resource_id", "created_at"] })[route];
  if (!fields) return;
  const csvCell = value => `"${String(value ?? "").replace(/^[\s]*[=+@-]/, "'$&").replace(/"/g, '""')}"`;
  const csv = [fields, ...rows.map(row => fields.map(field => row[field]))].map(row => row.map(csvCell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a"); link.href = url; link.download = `omnexa-${route}-page.csv`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Current page exported. Other pages are not included.");
}
function menuOpen(open) {
  $("#sidebar").classList.toggle("open", open); $("#sidebar-scrim").hidden = !open;
  $(".workspace").inert = open;
  $("#menu-toggle").setAttribute("aria-expanded", String(open));
  $("#menu-toggle").setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
  if (open) $(".nav-item").focus();
}
document.addEventListener("click", async event => {
  const control = event.target.closest("[data-action]");
  if (!control || control.disabled || mutating) return;
  const { action, id } = control.dataset, numericId = Number(id);
  if (action === "logout") { identity = null; shell.clearPlatformState(); window.logout(); return; }
  if (!identity) return;
  if (action === "refresh") { await render(); return; }
  if (action === "page") { setParam("offset", control.dataset.offset, false); await render(); $("#main").focus(); return; }
  if (action === "clear-search") { clearTimeout(searchTimer); setSearch(""); await render(); $("#list-search")?.focus(); return; }
  if (action === "close-detail") { closeDetail(); return; }
  if (action === "cancel-confirm") { confirmation = null; $("#confirm-dialog").close(); return; }
  if (action === "export") { exportPage(); return; }
  if (action === "company") { await companyDetail(numericId); return; }
  if (action === "orders") { await ordersDetail(numericId); return; }
  if (action === "orders-page") { await ordersDetail(detailData.companyId, Number(control.dataset.offset)); return; }
  if (action === "payment") { paymentDetail(id); return; }
  if (action === "subscription") { await subscriptionDetail(numericId); return; }
  if (action === "approval") { await approvalDetail(numericId); return; }
  if (action === "permissions") { await permissionsDetail(numericId); return; }
  if (action === "ticket") { await ticketDetail(numericId); return; }
  if (action === "incoming") { await incomingDetail(numericId); return; }
  if (action === "company-support") { await companySupport(numericId); return; }
  if (action === "company-support-page") { await companySupport(detailData.companyId, Number(control.dataset.offset)); return; }
  if (action === "ticket-history-prev" || action === "ticket-history-next") { await ticketDetail(numericId, detailData.mode, Math.max(0, detailData.offset + (action.endsWith("next") ? pageSize : -pageSize))); return; }
  if (action === "reply-mode") {
    const apply = () => ticketDetail(detailData.ticket.id, control.dataset.mode, detailData.offset);
    if (dirty) confirmAction({ title: "Discard unsaved message?", description: "Switching modes will discard the text in this composer.", summary: detailData.ticket.title, label: "Switch mode", reason: false, action: apply });
    else await apply();
    return;
  }
  if (action === "ticket-status") {
    const ticket = detailData.ticket, status = control.dataset.status;
    if (!detailData.data.status_transitions.includes(status)) return;
    confirmAction({ title: `${titleCase(status)} case?`, description: "The case status will be updated for the support team and linked customer request.", summary: ticket.title, label: titleCase(status), reason: false, action: async () => { await api.updateSupportCaseStatus(numericId, { status }); await ticketDetail(numericId); toast("Case status updated."); } }); return;
  }
  if (action === "approve" || action === "reject") {
    const request = detailData.request;
    if (request?.status !== "pending") return;
    confirmAction({ title: action === "approve" ? "Approve this request?" : "Reject this request?", description: "This records your decision only. It does not execute any money, subscription or account operation.", summary: request.summary, label: action === "approve" ? "Approve request" : "Reject request", danger: action === "reject", action: async reason => { await api.decideApprovalRequest(numericId, { status: action === "approve" ? "approved" : "rejected", reason }); await approvalDetail(numericId); toast("Decision recorded. The requested operation has not been executed."); } }); return;
  }
  if (action === "suspend-company" || action === "restore-company") {
    const company = detailData.company, suspend = action === "suspend-company";
    confirmAction({ title: `${suspend ? "Suspend" : "Restore"} ${company.company_name}?`, description: suspend ? "Customer users will lose access to this company's workspace. Existing records are retained." : "Customer users will regain workspace access subject to their account permissions.", summary: `Company ${company.id}`, label: suspend ? "Suspend company" : "Restore company", reason: false, danger: suspend, action: async () => { await (suspend ? api.suspendCompany(numericId) : api.restoreCompany(numericId)); await companyDetail(numericId); toast(suspend ? "Company suspended." : "Company restored."); } }); return;
  }
  if (action === "staff-active") {
    const person = detailData.person;
    confirmAction({ title: `${person.is_active ? "Deactivate" : "Activate"} staff access?`, description: person.is_active ? "This staff member will lose access to the platform administration portals." : "This staff member will regain their assigned platform access.", summary: person.user_email || `User ${person.user_id}`, label: person.is_active ? "Deactivate access" : "Activate access", danger: person.is_active, reason: false, action: async () => { await api.setPlatformAdminUserActive(numericId, !person.is_active); await permissionsDetail(numericId); toast("Staff access updated."); } }); return;
  }
  if (action === "convert-request") {
    confirmAction({ title: "Open a support case?", description: "This request will be linked to a case where staff can assign work and reply to the customer.", summary: `Request ${id}`, label: "Open support case", reason: false, action: async () => { const result = await api.convertTenantSupportRequest(numericId); const caseId = result.converted_platform_support_case_id; if (caseId) await ticketDetail(caseId); else { dirty = false; $("#detail-dialog").close(); location.hash = "#support"; } toast("Customer request converted to a support case."); } }); return;
  }
  if (action === "recheck") {
    const context = detailData;
    confirmAction({ title: "Recheck this payment?", description: "Verify gateway status and retry activation of a paid order if needed. This does not start a new charge or issue a refund.", summary: `Payment ${id} · Company ${context.companyId}`, label: "Recheck payment", reason: false, action: async () => {
      const result = await api.recheckCompanyBillingOrder(context.companyId, numericId);
      if (!result.order || result.source !== "existing_reconciliation") throw new Error("Invalid status source");
      context.rows = context.rows.map(row => String(row.id) === String(id) ? result.order : row); detailData = context; paymentDetail(id);
      $("#detail-operation-error").textContent = `Recheck result: ${titleCase(result.outcome)}. Review the recorded payment and activation status.`;
      toast("Payment recheck completed. Review the result before taking further action.");
    } }); return;
  }
  if (action === "new-staff") {
    details("Add existing user", "Team & permissions", `<form id="staff-create-form" novalidate><p>Select an existing protected account by its user ID. The new Admin starts with no assigned modules.</p><div class="field"><label for="staff-user-id">Existing user ID</label><input id="staff-user-id" type="number" min="1" step="1" inputmode="numeric" aria-describedby="staff-create-error"></div><p id="staff-create-error" class="field-error" role="alert"></p><button class="button primary" type="submit">Review access creation</button></form>`); return;
  }
  if (action === "new-article") { detailData = { kind: "article", article: null }; details("New article", "Help centre", articleForm()); return; }
  if (action === "article" || action === "edit-article") { articleDetail(numericId, action === "edit-article"); return; }
  if (action === "publish-article" || action === "delete-article") {
    const article = detailData.article, deleting = action === "delete-article";
    const publishing = !article.is_published;
    confirmAction({ title: `${deleting ? "Delete" : publishing ? "Publish" : "Unpublish"} this article?`, description: deleting ? "This permanently removes the help article." : publishing ? "This article becomes visible in the customer help centre." : "This article will no longer be visible to customers.", summary: article.title, label: deleting ? "Delete article" : publishing ? "Publish article" : "Unpublish article", danger: deleting, reason: false, action: async () => { if (deleting) await helpApi.removeArticle(numericId); else await helpApi.updateArticle(numericId, { is_published: publishing }); dirty = false; $("#detail-dialog").close(); await render(); toast(deleting ? "Article deleted." : publishing ? "Article published." : "Article unpublished."); } }); return;
  }
  if (action === "event") {
    const item = listRows.find(row => String(row.id) === String(id));
    if (!item) return;
    details("Activity details", `Event ${item.id}`, detailList([["Action", esc(item.action)], ["Resource", esc(item.resource_type)], ["Resource ID", esc(item.resource_id)], ["Recorded", esc(date(item.created_at))]]) + `<pre class="audit-data">${esc(JSON.stringify(item.metadata || {}, null, 2))}</pre>`);
  }
});
document.addEventListener("submit", async event => {
  const form = event.target;
  if (!form.matches("#global-search-form,#confirm-form,#permissions-form,#ticket-settings,#ticket-message,#article-form,#staff-create-form")) return;
  event.preventDefault();
  if (!identity || mutating) return;
  if (form.id === "global-search-form") { clearTimeout(searchTimer); setSearch($("#global-search").value.trim(), "customers"); if (location.hash === "#customers") await render(); else location.hash = "#customers"; return; }
  if (form.id === "staff-create-form") {
    if (!validate("staff-user-id", "staff-create-error", value => Number.isSafeInteger(Number(value)) && Number(value) > 0, "Enter the existing account's positive user ID.")) return;
    const userId = Number($("#staff-user-id").value);
    confirmAction({ title: "Add this platform staff account?", description: "An existing protected account will gain Admin portal access with no assigned modules. Configure its permissions after creation.", summary: `User ${userId}`, label: "Create Admin access", reason: false, action: async () => {
      const result = await api.createPlatformAdminUser(userId);
      const mappingId = result.platform_admin_user?.platform_admin_user_id;
      dirty = false;
      if (mappingId) await permissionsDetail(mappingId); else { $("#detail-dialog").close(); await render(); }
      toast("Admin access created. Assign modules to finish configuration.");
    } }); return;
  }
  if (form.id === "confirm-form") {
    if (!confirmation) return;
    if (confirmation.reason && !validate("confirm-reason", "confirm-error", value => value.length >= 3, "Add a reason of at least 3 characters.")) return;
    const pending = confirmation, reason = $("#confirm-reason").value.trim();
    await commit(form, "confirm-error", async () => {
      // Release the UI busy flag only after the server mutation inside the action resolves.
      // Detail refreshes are blocked while a mutation is pending; queue them afterward.
      await pending.action(reason);
    }, () => { confirmation = null; $("#confirm-dialog").close(); });
    return;
  }
  if (form.id === "permissions-form") {
    const person = detailData.person, role = $("#staff-role").value;
    const modules = Object.fromEntries(["billing", "support", "customers"].map(key => [key, role === "super_admin" || $(`#module-${key}`).checked]));
    confirmAction({ title: "Apply these permissions?", description: role === "super_admin" ? "Super Admin grants full control of platform accounts, permissions, and approval decisions." : "This Admin will have access only to the selected modules. Removed modules become inaccessible immediately.", summary: `${person.user_email || `User ${person.user_id}`} · ${titleCase(role)} · ${Object.keys(modules).filter(key => modules[key]).map(titleCase).join(", ") || "No modules"}`, label: "Apply permissions", action: async reason => { await api.updatePlatformAdminAccess(person.platform_admin_user_id, { platform_role: role, modules, reason }); dirty = false; await permissionsDetail(person.platform_admin_user_id); toast("Permissions updated."); } }); return;
  }
  if (form.id === "ticket-settings") {
    const id = detailData.ticket.id, selected = $("#ticket-assignee").value;
    await commit(form, "assignment-error", () => api.assignSupportCase(id, { assigned_platform_admin_user_id: selected ? Number(selected) : null }), async () => { await ticketDetail(id); toast("Assignment updated."); }); return;
  }
  if (form.id === "ticket-message") {
    if (!validate("message-body", "message-error", value => value.length > 0, "Write a message before saving.")) return;
    const id = detailData.ticket.id, message = $("#message-body").value.trim(), note = detailData.mode === "note";
    if (note) await commit(form, "message-error", () => api.addSupportCaseNote(id, { redacted_note: message }), async () => { await ticketDetail(id, "note"); toast("Private note saved for the support team."); });
    else confirmAction({ title: "Send this customer reply?", description: "This reply is visible to the customer and may notify their account owner.", summary: message, label: "Send reply", reason: false, action: async () => { await api.createSupportCaseReply(id, { redacted_body: message }); dirty = false; await ticketDetail(id); toast("Customer-visible reply saved. Notification delivery is tracked separately."); } });
    return;
  }
  if (form.id === "article-form") {
    if (!validate("article-title", "article-error", value => value.length > 0, "Enter an article title.")) return;
    if (!validate("article-body", "article-error", value => value.length > 0, "Enter the article content.")) return;
    if (!validate("article-slug", "article-error", value => !value || helpApi.SLUG_PATTERN.test(value), "Use lowercase words separated by hyphens for the URL slug.")) return;
    if (!validate("article-sort-order", "article-error", value => value !== "" && Number.isInteger(Number(value)) && Number(value) >= 0 && Number(value) <= 2147483647, "Enter a whole display order from 0 to 2147483647.")) return;
    const id = Number(form.dataset.id), payload = { sort_order: Number($("#article-sort-order").value), title: $("#article-title").value.trim(), body: $("#article-body").value.trim(), category: $("#article-category").value, slug: $("#article-slug").value.trim() };
    const save = () => id ? helpApi.updateArticle(id, payload) : helpApi.createArticle({ ...payload, is_published: false });
    const after = async () => { dirty = false; $("#detail-dialog").close(); await render(); toast(id ? "Article updated." : "Draft created."); };
    if (detailData.article?.is_published) confirmAction({ title: "Update the published article?", description: "Customers will see these changes in the help centre.", summary: payload.title, label: "Update article", reason: false, action: async () => { await save(); await after(); } });
    else await commit(form, "article-error", save, after);
  }
});
document.addEventListener("input", event => {
  if (event.target.closest("#detail-content form")) dirty = true;
  if (event.target.id === "global-search") $("#global-clear").hidden = !event.target.value;
  if (event.target.id === "list-search") {
    clearTimeout(searchTimer);
    const value = event.target.value;
    $("[data-action=clear-search]").hidden = !value;
    setSearch(value);
    if (event.isComposing || searchComposing) return;
    searchTimer = setTimeout(refreshListSearch, 300);
  }
});
async function refreshListSearch() {
  const { route } = routeInfo();
  if (!identity) return;
  if (route !== "customers" && route !== "help") { if (listData) paintList(); return; }
  const sequence = ++viewSequence;
  $("#list-content").innerHTML = loading("Searching records…");
  try {
    const result = await shell.runRequest("view", signal => loadList(route, signal));
    if (sequence !== viewSequence || !identity) return;
    listRows = requireRows(result.data, result.key); listData = result.data; paintList();
  } catch (error) { if (sequence === viewSequence && !handleAuthorization(error)) $("#list-content").innerHTML = errorPanel(error); }
}
document.addEventListener("compositionstart", event => { if (event.target.id === "list-search") { searchComposing = true; clearTimeout(searchTimer); } });
document.addEventListener("compositionend", event => { if (event.target.id === "list-search") { searchComposing = false; clearTimeout(searchTimer); setSearch(event.target.value); searchTimer = setTimeout(refreshListSearch, 300); } });
document.addEventListener("change", event => {
  if (event.target.id === "status-filter") { setParam("status", event.target.value); render(); }
  if (event.target.closest("#detail-content form")) dirty = true;
  if (event.target.id === "staff-role") ["billing", "support", "customers"].forEach(key => { const input = $(`#module-${key}`); input.disabled = event.target.value === "super_admin"; if (input.disabled) input.checked = true; });
});
$("#global-clear").addEventListener("click", () => { $("#global-search").value = ""; $("#global-clear").hidden = true; $("#global-search").focus(); });
$("#menu-toggle").addEventListener("click", () => menuOpen(!$("#sidebar").classList.contains("open")));
$("#sidebar-scrim").addEventListener("click", () => { menuOpen(false); $("#menu-toggle").focus(); });
$(".skip-link").addEventListener("click", event => { event.preventDefault(); $("#main").focus(); });
$("#detail-dialog").addEventListener("cancel", event => { event.preventDefault(); closeDetail(); });
$("#detail-dialog").addEventListener("close", () => { ++detailSequence; dirty = false; $("#detail-content").replaceChildren(); if (detailOpener?.isConnected) detailOpener.focus(); else $("#main").focus(); });
$("#confirm-dialog").addEventListener("cancel", event => { if (mutating) event.preventDefault(); else confirmation = null; });
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && $("#sidebar").classList.contains("open")) { menuOpen(false); $("#menu-toggle").focus(); }
  if (event.key === "/" && !event.target.closest("input,textarea,select,[contenteditable=true]") && !$("#detail-dialog").open) { event.preventDefault(); $("#global-search").focus(); }
});
window.addEventListener("hashchange", () => {
  const next = location.hash;
  if (mutating) { history.replaceState(null, "", acceptedHash); return; }
  if (dirty) {
    history.replaceState(null, "", acceptedHash);
    confirmAction({ title: "Discard changes and leave?", description: "Your unsaved edits will be lost.", summary: $("#detail-title").textContent, label: "Leave page", reason: false, danger: true, action: () => { dirty = false; $("#detail-dialog").close(); location.hash = next; } });
    return;
  }
  acceptedHash = next; clearTimeout(searchTimer); ++detailSequence; $("#detail-dialog").close(); menuOpen(false); render();
});
window.addEventListener("beforeunload", event => { if (dirty || mutating) { event.preventDefault(); event.returnValue = ""; } });
window.addEventListener("pagehide", () => { identity = null; listData = null; listRows = []; detailData = null; dirty = false; routeSearch.clear(); clearTimeout(searchTimer); $("#global-search").value = ""; $("#global-clear").hidden = true; ++viewSequence; ++detailSequence; $("#detail-dialog").close(); $("#confirm-dialog").close(); });
async function authorize() {
  shell.start({ onAuthorized: async current => {
    if (current?.platform_role !== "super_admin") {
      shell.clearPlatformState();
      if (current?.platform_role === "admin") { window.location.replace("admin.html"); return; }
      shell.handleError({ category: "access_denied" }); return;
    }
    identity = current;
    $("#operator-name").textContent = current.user?.full_name || "Super Admin";
    $("#operator-email").textContent = current.user?.email || "";
    await render();
  } });
}
window.addEventListener("pageshow", event => { if (event.persisted) authorize(); });
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState !== "visible" || !identity || mutating) return;
  try {
    const current = await shell.runRequest("reauthorize", signal => api.getMe({ signal }));
    if (current?.platform_role !== "super_admin") { handleAuthorization({ category: "access_denied" }); return; }
    identity = current;
  } catch (error) { if (!handleAuthorization(error)) { identity = null; shell.clearPlatformState(); shell.handleError({ category: "unavailable" }); } }
});
hydrateIcons();
authorize();
