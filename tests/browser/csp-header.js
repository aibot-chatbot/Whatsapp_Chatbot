"use strict";

const { createHash } = require("node:crypto");
const path = require("node:path");
const policy = require("../../app/csp_policy.json");
const handlers = require("../../app/csp_inline_handlers.json");

function hashSource(script) {
  return `'sha256-${createHash("sha256").update(script, "utf8").digest("base64")}'`;
}

const scriptSrc = [
  "script-src", ...policy["script-src"],
  "'unsafe-hashes'", ...handlers.map(hashSource)
].join(" ");
const PAGE_CSP = Object.entries(policy)
  .map(([name, sources]) => name === "script-src" ? scriptSrc : [name, ...sources].join(" "))
  .join("; ");

function setPageCsp(response, filePath, fixtureScript) {
  if (path.basename(filePath).toLowerCase() === "widget-chat.html") return;
  const header = fixtureScript ? PAGE_CSP.replace(scriptSrc, `${scriptSrc} ${hashSource(fixtureScript)}`) : PAGE_CSP;
  response.setHeader("Content-Security-Policy", header);
}

module.exports = { PAGE_CSP, setPageCsp };
