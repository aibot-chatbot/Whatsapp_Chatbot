"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");

const root = path.resolve(__dirname, "..", "..", "frontend");
const defaultPort = Number(process.env.PLATFORM_ADMIN_TEST_PORT || 4173);

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8"
};

function safePath(urlPath) {
  const normalized = path.normalize(decodeURIComponent(urlPath.split("?")[0]));
  const relative = normalized === path.sep ? "platform-admin.html" : normalized.replace(/^[/\\]+/, "");
  const absolute = path.resolve(root, relative);
  return absolute.startsWith(root + path.sep) || absolute === root ? absolute : null;
}

function createServer() {
  return http.createServer((request, response) => {
    if (request.url.startsWith("/api/")) {
      response.writeHead(503, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ status: "error", code: "unexpected_unmocked_api" }));
      return;
    }

    const filePath = safePath(request.url);
    if (!filePath || !fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Not found");
      return;
    }

    response.writeHead(200, {
      "Content-Type": contentTypes[path.extname(filePath)] || "application/octet-stream",
      "Cache-Control": "no-store"
    });
    fs.createReadStream(filePath).pipe(response);
  });
}

function startServer(port = defaultPort) {
  const server = createServer();
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

module.exports = { startServer };
