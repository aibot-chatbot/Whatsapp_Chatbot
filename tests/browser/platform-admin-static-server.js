"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const { setPageCsp } = require("./csp-header");

// Dist first: a page migrated to Astro (web/dist) wins over its legacy frontend/ copy.
const defaultRoots = [
  path.resolve(__dirname, "..", "..", "web", "dist"),
  path.resolve(__dirname, "..", "..", "frontend")
];
const defaultPort = Number(process.env.PLATFORM_ADMIN_TEST_PORT || 4173);

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8"
};

function safePath(urlPath, root) {
  const normalized = path.normalize(decodeURIComponent(urlPath.split("?")[0]));
  const relative = normalized === path.sep ? "platform-admin.html" : normalized.replace(/^[/\\]+/, "");
  const absolute = path.resolve(root, relative);
  return absolute.startsWith(root + path.sep) || absolute === root ? absolute : null;
}

function resolveFile(urlPath, roots) {
  for (const root of roots) {
    const filePath = safePath(urlPath, root);
    if (filePath && fs.existsSync(filePath) && fs.statSync(filePath).isFile()) return filePath;
  }
  return null;
}

function pageRequestPath(request, response, pathname, roots) {
  if (request.method !== "GET" && request.method !== "HEAD") return pathname;
  const redirects = process.env.E2E_CLEAN_URLS === "1";
  if (redirects && pathname === "/") return "/landing.html";
  const page = /^\/([^./\\]+)(\.html)?$/.exec(decodeURIComponent(pathname));
  if (!page || page[1].toLowerCase() === "widget-chat" || (page[2] && !redirects)) return pathname;

  const clean = "/" + encodeURIComponent(page[1]);
  const html = clean + ".html";
  if (!resolveFile(html, roots)) return pathname;
  if (!page[2]) return html;

  const queryStart = request.url.indexOf("?");
  const query = queryStart < 0 ? "" : request.url.slice(queryStart);
  response.writeHead(301, { Location: (clean === "/landing" ? "/" : clean) + query, "Cache-Control": "public, max-age=3600" });
  response.end();
  return null;
}

// The file a URL path is served from (web/dist first, then frontend/), or null.
function servedFile(urlPath) {
  return resolveFile(urlPath, defaultRoots);
}

function createServer(roots = defaultRoots) {
  return http.createServer((request, response) => {
    if (request.url.startsWith("/api/")) {
      response.writeHead(503, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ status: "error", code: "unexpected_unmocked_api" }));
      return;
    }

    const pathname = pageRequestPath(request, response, request.url.split("?", 1)[0], roots);
    if (pathname === null) return;
    const filePath = resolveFile(pathname, roots);
    if (!filePath) {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Not found");
      return;
    }

    const ext = path.extname(filePath);
    if (ext === ".html") setPageCsp(response, filePath);
    response.writeHead(200, {
      "Content-Type": contentTypes[ext] || "application/octet-stream",
      "Cache-Control": "no-store"
    });
    fs.createReadStream(filePath).pipe(response);
  });
}

function startServer(port = defaultPort, roots = defaultRoots) {
  const server = createServer(roots);
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

if (require.main === module) {
  startServer().then(server => {
    function shutdown() {
      server.close(() => process.exit(0));
      setTimeout(() => process.exit(0), 1000).unref();
    }

    process.on("SIGINT", shutdown);
    process.on("SIGTERM", shutdown);
    process.on("SIGHUP", shutdown);
  }).catch(error => {
    console.error(error);
    process.exit(1);
  });
}

module.exports = { servedFile, startServer, safePath, pageRequestPath };
