"use strict";

const policy = require("../../app/csp_policy.json");

const PAGE_CSP = Object.entries(policy)
  .map(([name, sources]) => [name, ...sources].join(" "))
  .join("; ");

module.exports = { PAGE_CSP };
