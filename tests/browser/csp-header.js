"use strict";

const { createHash } = require("node:crypto");
const path = require("node:path");
const policy = require("../../app/csp_policy.json");
const handlers = require("../../app/csp_inline_handlers.json");

const PAGE_CSP = Object.entries(policy)
  .map(([name, sources]) => [name, ...sources].join(" "))
  .join("; ");

function hashSource(script) {
  return `'sha256-${createHash("sha256").update(script, "utf8").digest("base64")}'`;
}

const PAGE_CSP_REPORT_ONLY = [
  "script-src", ...policy["script-src"].filter(source => source !== "'unsafe-inline'"),
  "'unsafe-hashes'", ...handlers.map(hashSource)
].join(" ");

function setPageCsp(response, filePath, fixtureScript) {
  if (path.basename(filePath).toLowerCase() === "widget-chat.html") return;
  if (process.env.E2E_CSP === "strict") {
    const scriptSrc = fixtureScript ? `${PAGE_CSP_REPORT_ONLY} ${hashSource(fixtureScript)}` : PAGE_CSP_REPORT_ONLY;
    response.setHeader("Content-Security-Policy", PAGE_CSP.replace(/script-src [^;]+/, scriptSrc));
  } else {
    response.setHeader("Content-Security-Policy", PAGE_CSP);
    response.setHeader("Content-Security-Policy-Report-Only", PAGE_CSP_REPORT_ONLY);
  }
}

module.exports = { PAGE_CSP, PAGE_CSP_REPORT_ONLY, setPageCsp };
