import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";
import { expect, it, vi } from "vitest";

it("mounts Knowledge as a classic script using the page's global React", async () => {
  const { compileKnowledgeScript } = await import("../src/integrations/new-linkdocs.mjs");
  const source = readFileSync(new URL("../src/legacy/new_linkdocs.jsx", import.meta.url), "utf8");
  const script = await compileKnowledgeScript(source);
  expect(script).toMatch(/^["']use strict["'];/);
  expect(script).not.toMatch(/^\s*(?:import|export)\b/m);
  expect(script).toContain("ReactDOM.createRoot(");
  expect(script).toContain("React.Fragment");

  const rootElement = {};
  const render = vi.fn();
  const createRoot = vi.fn(() => ({ render }));
  runInContext(script, createContext({
    document: { getElementById: (id: string) => id === "root" ? rootElement : null },
    React: { createElement: (component: unknown) => component },
    ReactDOM: { createRoot },
  }));
  expect(createRoot).toHaveBeenCalledWith(rootElement);
  expect(render).toHaveBeenCalledWith(expect.any(Function));
});
