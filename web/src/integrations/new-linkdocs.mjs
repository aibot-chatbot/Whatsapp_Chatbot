import { mkdir, readFile, writeFile } from "node:fs/promises";
import { transformWithOxc } from "vite";

/** @param {string} source */
export async function compileKnowledgeScript(source) {
  // Babel's script-tag transform enabled strict mode for the whole page script.
  const { code } = await transformWithOxc('"use strict";\n' + source, "new_linkdocs.jsx", {
    sourceType: "script",
    jsx: { runtime: "classic" },
    tsconfig: false,
    sourcemap: false,
  });
  return code;
}

/** @returns {import("astro").AstroIntegration} */
export default function knowledgeScript() {
  return {
    name: "knowledge-script",
    hooks: {
      // shortcut: astro dev has no generated script, use the Flask-served build for this page.
      "astro:build:done": async ({ dir }) => {
        const source = await readFile(new URL("../legacy/new_linkdocs.jsx", import.meta.url), "utf8");
        const script = await compileKnowledgeScript(source);
        const assets = new URL("assets/js/", dir);
        await mkdir(assets, { recursive: true });
        await writeFile(new URL("new_linkdocs.js", assets), script);
      },
    },
  };
}
