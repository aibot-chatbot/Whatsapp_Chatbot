"use strict";

const { execSync } = require("child_process");
const path = require("path");

// The static server serves web/dist first, so every run rebuilds it; a failed build fails the run.
module.exports = () => {
  execSync("npm --prefix web run build", {
    cwd: path.resolve(__dirname, "..", ".."),
    stdio: "inherit",
    // Keep the build offline: no Astro telemetry, no npm update check.
    env: { ...process.env, ASTRO_TELEMETRY_DISABLED: "1", npm_config_update_notifier: "false" }
  });
};
