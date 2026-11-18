// @ts-check
import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import knowledgeScript from "./src/integrations/new-linkdocs.mjs";

// Static output only: Flask serves dist/ and keeps every URL (src/pages/x.astro -> dist/x.html).
export default defineConfig({
  output: "static",
  outDir: "dist",
  trailingSlash: "ignore",
  build: { format: "file" },
  integrations: [react(), knowledgeScript()],
  // Astro inlines processed scripts (and styles) under this size; 0 keeps every one a file, for CSP.
  vite: { build: { assetsInlineLimit: 0 } },
});
