const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "tests/browser",
  workers: 1,
  timeout: 15000,
  expect: {
    timeout: 5000
  },
  use: {
    baseURL: "http://127.0.0.1:4173",
    channel: "chrome",
    trace: "retain-on-failure"
  }
});
