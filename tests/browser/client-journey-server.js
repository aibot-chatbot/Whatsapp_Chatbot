"use strict";

// Loopback-only synthetic review. This process never imports Flask, loads .env,
// or calls AI, storage, billing, or messaging providers.
const fs = require("fs");
const http = require("http");
const path = require("path");

const defaultRoots = [
  path.resolve(__dirname, "..", "..", "web", "dist"),
  path.resolve(__dirname, "..", "..", "frontend")
];
const ARTIFACTS = path.resolve(__dirname, "../../output/client-journey-review");
const TOKEN = "synthetic-client-journey-token";
const BOT_ID = 901;
const PUBLIC_KEY = "wgt_synthetic_client_journey";
const ASSETS = [
  ["react.js", "https://unpkg.com/react@18.3.1/umd/react.production.min.js", "https://unpkg.com/react@18/umd/react.production.min.js"],
  ["react-dom.js", "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js", "https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"],
  ["babel.js", "https://unpkg.com/@babel/standalone@7.28.4/babel.min.js", "https://unpkg.com/@babel/standalone/babel.min.js"],
  ["vis.js", "https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js", "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"],
  ["lucide.js", "https://unpkg.com/lucide@1.31.0", "https://unpkg.com/lucide@1.31.0"],
];

async function prepareAssets() {
  const dir = path.join(ARTIFACTS, "vendor");
  fs.mkdirSync(dir, { recursive: true });
  await Promise.all(ASSETS.map(async ([name, url]) => {
    const target = path.join(dir, name);
    if (fs.existsSync(target)) return;
    const response = await fetch(url, { signal: AbortSignal.timeout(30000) });
    if (!response.ok) throw new Error(`Fixture asset ${url}: HTTP ${response.status}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.length < 1000) throw new Error(`Fixture asset ${name} is incomplete`);
    fs.writeFileSync(target, bytes);
  }));
}

function createWorld() {
  return {
    bot: null, files: [], profiles: [], storedMatch: null,
    deployedProfile: "", deployedPdf: "", validationMatch: true,
    uploadStarted: false, matchStarted: false, uploadGate: null, matchGate: null,
    widget: { id: 1, chatbot_id: BOT_ID, company_id: 7, public_key: PUBLIC_KEY,
      is_enabled: false, display_name: "Acme Support", allowed_domains: [],
      welcome_message: "Hello, how can we help?", suggested_questions: [],
      primary_color: "#3e9c89", text_color: "#ffffff", launcher_position: "right",
      show_branding: true, collect_lead: false, max_messages_per_session: 50 },
    calls: [], unexpected: [], messages: [], widgetWrites: [],
  };
}

function json(response, data, status = 200) {
  response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
  response.end(JSON.stringify(data));
}

async function readBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 2 * 1024 * 1024) throw new Error("Synthetic uploads must be smaller than 2MB");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

async function mockApi(request, response, url, world) {
  const raw = await readBody(request);
  const upload = url.pathname === "/upload-pdf";
  const body = raw.length && !upload ? JSON.parse(raw.toString()) : {};
  const method = request.method;
  const endpoint = url.pathname;
  world.calls.push({ method, path: endpoint, query: url.search, body });
  const ok = (data, extra = {}) => json(response, { status: "success", data, ...extra });
  const error = (message, status = 400) => json(response, { status: "error", message }, status);
  if (request.headers.authorization !== `Bearer ${TOKEN}`) return error("Synthetic session required", 401);

  if (endpoint === "/api/bots") {
    if (method === "GET") return ok(world.bot ? [world.bot] : []);
    if (method === "POST") {
      if (!body.bot_name?.trim()) return error("Bot name is required");
      world.bot = { ...body, id: BOT_ID, company_id: 7, is_active: true,
        draft_profile_name: "", draft_pdf_file_name: "", draft_pdf_path: "",
        deployed_profile_name: "", ai_provider: "openai", model_name: "gpt-4o-mini",
        temperature: 0.7, welcome_menu_labels: [], telegram_buttons_enabled: true,
        telegram_markdown_enabled: true };
      world.widget.display_name = body.bot_name;
      return json(response, { status: "success", data: world.bot }, 201);
    }
  }
  if (endpoint === "/api/billing/usage") return ok({ usage: {
    chatbots: { used: world.bot ? 1 : 0, limit: 3 }, channels: { used: 0, limit: 2 },
  } });
  if (endpoint === "/api/billing/subscription") return ok({ status: "active", plan: {
    code: "pro", model_access_tier: "premium", feature_flags: {
      single_website_scraping: true, knowledge_graph: true, ai_assisted_menu_generation: true,
    },
  } });
  if (endpoint === "/api/ai-models") return ok({ openai: { label: "OpenAI", models: [
    { value: "gpt-4o-mini", label: "GPT-4o mini", tier: "standard", access: "paid" },
  ] } }, { read_only: false, access_allowed: true });
  if (endpoint === `/api/bots/${BOT_ID}` && method === "GET") {
    return world.bot ? ok(world.bot) : error("Chatbot not found", 404);
  }
  if (!world.bot) return error("Create a synthetic bot first", 404);

  if (endpoint === `/api/bots/${BOT_ID}/widget`) {
    if (method === "PUT") {
      if ("public_key" in body || ("is_enabled" in body && typeof body.is_enabled !== "boolean")) {
        return error("Invalid widget update");
      }
      world.widgetWrites.push(body);
      Object.assign(world.widget, body);
    }
    const base = "https://bot.example.test";
    return ok({ widget: world.widget, embed: {
      base_url: base, script_url: `${base}/widget.js`,
      share_url: `${base}/chat/${PUBLIC_KEY}`, iframe_url: `${base}/widget/${PUBLIC_KEY}`,
      script_snippet: `<script src="${base}/widget.js" data-chatbot-key="${PUBLIC_KEY}"></script>`,
      iframe_snippet: `<iframe src="${base}/widget/${PUBLIC_KEY}"></iframe>`,
      delivery: { base_configured: true, base_kind: "permanent", persistent_url: true,
        reachability: "not_checked", message: "Synthetic configured address; no reachability check was made." },
    } });
  }
  if (endpoint === "/api/whatsapp/embedded-signup/config") return error("WhatsApp is not configured in this synthetic review.", 500);

  if (url.searchParams.get("chatbot_id") !== String(BOT_ID)) return error("chatbot_id is required and must match the fixture bot");
  if (/^\/api\/(telegram|whatsapp|wasender|whatchimp)\/channels$/.test(endpoint)) return ok([]);
  if (endpoint === "/api/knowledge/files") return world.knowledgeReadFailure ? error("Synthetic knowledge lookup unavailable", 503) : ok(world.files);
  if (endpoint === "/api/knowledge/active") return ok(world.activeFileOverride || world.files.find(file => file.is_active) || {});
  if (endpoint === "/api/knowledge/graph") return ok({ nodes: [], edges: [] });
  if (endpoint === "/api/knowledge/refinement/questions") return ok({ questions: [] });
  if (endpoint === "/api/dashboard/health") return ok({
    channels: { connected_count: Number(world.widget.is_enabled) },
    knowledge: { match_result: world.storedMatch, match_reason: world.storedMatch ? "Synthetic matching business and PDF." : "" },
  });
  if (upload && method === "POST") {
    const multipart = raw.toString();
    const filename = multipart.match(/name="pdf_file"; filename="([^"]+)"/)?.[1];
    if (!filename || !multipart.includes("%PDF-")) return error("A PDF must be sent using pdf_file");
    world.uploadStarted = true;
    if (world.uploadGate) await world.uploadGate;
    if (world.uploadFailure) return json(response, { status: "failed", message: "Synthetic extraction found no readable text." });
    world.files = [{ id: 11, chatbot_id: BOT_ID, file_name: filename, display_name: filename,
      original_file_name: filename, file_type: "pdf", role: "primary", is_active: true,
      is_enabled: true, processing_status: "completed", chunk_count: 1, file_size: raw.length }];
    world.bot.draft_pdf_file_name = filename;
    world.bot.draft_pdf_path = `synthetic/${filename}`;
    return json(response, { status: "completed", message: "Synthetic PDF processing completed. No extraction service was called." });
  }
  if (endpoint === "/api/profiles") {
    if (method === "POST") {
      if (!["name", "bot_name", "company_name", "business_description", "tone"].every(key => body[key]?.trim())) return error("Required profile field missing");
      world.profiles = world.profiles.filter(profile => profile.name !== body.name).concat(body);
      world.storedMatch = null;
      return ok(body);
    }
    return ok(world.profiles);
  }
  if (endpoint === "/api/settings") return ok({ active_profile: world.deployedProfile || "None", active_pdf: world.deployedPdf || "None" });
  if (endpoint === "/api/settings/active-profile" && method === "PUT") {
    if (!world.profiles.some(profile => profile.name === body.active_profile)) return error("Profile not found");
    world.bot.draft_profile_name = body.active_profile;
    world.storedMatch = null;
    return ok({ active_profile: body.active_profile });
  }
  if (endpoint === "/api/match/check" && method === "POST") {
    if (!world.files.length || !world.profiles.some(profile => profile.name === body.profile_name)) return error("Select real fixture instructions and a PDF before checking");
    world.matchStarted = true;
    if (world.matchGate) await world.matchGate;
    world.storedMatch = world.validationMatch;
    return ok({ match: world.validationMatch, validation_status: "completed",
      reason: world.validationMatch ? "Synthetic instructions and PDF describe Acme." : "Synthetic mismatch: instructions describe a different business." });
  }
  if (endpoint === "/api/settings/apply-profile" && method === "PUT") {
    // Strict mock ordering makes a removed frontend readiness gate fail loudly.
    if (!world.storedMatch || body.profile_name !== world.bot.draft_profile_name) return error("Synthetic readiness check has not passed", 409);
    world.deployedProfile = body.profile_name;
    world.deployedPdf = world.bot.draft_pdf_file_name;
    world.bot.deployed_profile_name = body.profile_name;
    return ok({ active_profile: body.profile_name, deployed_pdf_file_name: world.deployedPdf });
  }
  if (endpoint === "/api/testbot/context") return ok({ bot_name: world.bot.bot_name,
    active_profile: world.deployedProfile || "No active profile", active_pdf: world.deployedPdf || "No active PDF" });
  if (endpoint === "/api/testbot/scenarios") return ok({ matched: true, source_document: world.deployedPdf,
    scenarios: [{ key: "fact", name: "Opening hours", goal: "Answer from the document", message: "What are your opening hours?" }] });
  if (endpoint === "/api/testbot/chat" && method === "POST") {
    if (!world.deployedProfile) return error("Apply the fixture instructions before testing", 409);
    world.messages.push(body.message);
    return ok({ reply: "We are open Monday to Friday, 9am to 5pm." });
  }
  world.unexpected.push(`${method} ${url.pathname}${url.search}`);
  return error("Unexpected synthetic endpoint", 501);
}

// Dist-first, like the Playwright static server: a page Astro builds lives in web/dist, the rest in frontend/.
// `relative` is already decoded by the caller; each root keeps the original containment check.
function resolveFile(relative, roots) {
  for (const root of roots) {
    const target = path.resolve(root, relative);
    if (target.startsWith(root + path.sep) && fs.existsSync(target) && fs.statSync(target).isFile()) return target;
  }
  return null;
}

async function startJourneyServer({ port = 0, world = createWorld() } = {}) {
  await prepareAssets();
  const server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url, "http://127.0.0.1");
      if (url.pathname === "/__fixtures/state") return json(response, { synthetic: true, world });
      if (url.pathname.startsWith("/api/") || url.pathname === "/upload-pdf") {
        return await mockApi(request, response, url, world);
      }
      if (request.method !== "GET" && request.method !== "HEAD") return json(response, { error: "Static fixture is read-only" }, 405);
      const vendor = url.pathname.startsWith("/__fixtures/vendor/");
      const relative = vendor ? url.pathname.slice("/__fixtures/vendor/".length) : decodeURIComponent(url.pathname === "/" ? "bots.html" : url.pathname.slice(1));
      const target = resolveFile(relative, vendor ? [path.join(ARTIFACTS, "vendor")] : defaultRoots);
      if (!target) {
        response.writeHead(404); response.end("Fixture file not found"); return;
      }
      const ext = path.extname(target);
      let data = fs.readFileSync(target);
      // The sidebar also loads Lucide dynamically from its JavaScript module.
      // Resolve the same pinned local assets in both HTML and script sources.
      if (ext === ".html" || (ext === ".js" && !vendor)) {
        let source = data.toString();
        for (const [name, _url, remote] of ASSETS) source = source.replaceAll(remote, `/__fixtures/vendor/${name}`);
        data = Buffer.from(source);
      }
      if (ext === ".html") {
        let html = data.toString();
        html = html.replace(/<link\b[^>]*href="https:\/\/fonts\.[^"]*"[^>]*>/g, "");
        const session = `<script>sessionStorage.setItem('token','${TOKEN}');sessionStorage.setItem('isLoggedIn','true');sessionStorage.setItem('user',JSON.stringify({id:1,role:'owner',full_name:'Demo owner',email:'owner@example.test',company_id:7}));</script>`;
        html = html.replace("<head>", `<head>${session}`);
        html = html.replace("</body>", '<div style="position:fixed;right:12px;bottom:8px;z-index:99999;padding:6px 10px;background:#fff4cf;color:#332600;font:12px Arial;border-radius:4px;pointer-events:none">Synthetic review · no live services</div></body>');
        data = Buffer.from(html);
      }
      response.writeHead(200, { "Content-Type": ({ ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml" })[ext] || "application/octet-stream",
        "Cache-Control": "no-store", "X-Fixture-Mode": "synthetic",
        "Content-Security-Policy": "connect-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob:" });
      response.end(data);
    } catch (error) {
      json(response, { status: "error", message: `Synthetic fixture: ${error.message}` }, 500);
    }
  });
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(port, "127.0.0.1", resolve); });
  return { server, world, url: `http://127.0.0.1:${server.address().port}` };
}

if (require.main === module) {
  startJourneyServer({ port: Number(process.env.CLIENT_JOURNEY_PORT || 4187) }).then(({ url, server }) => {
    console.log(`Synthetic journey review: ${url}/bots.html`);
    for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(signal, () => server.close(() => process.exit(0)));
  }).catch(error => { console.error(error.message); process.exitCode = 1; });
}

module.exports = { ARTIFACTS, BOT_ID, PUBLIC_KEY, createWorld, startJourneyServer };
