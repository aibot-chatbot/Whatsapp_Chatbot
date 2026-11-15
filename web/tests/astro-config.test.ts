import { describe, expect, it } from "vitest";
import config from "../astro.config.mjs";

// Flask serves web/dist/<page>.html at the legacy /<page>.html URL, so these values are a contract.
describe("astro.config", () => {
  it("builds static files named like the legacy pages", () => {
    expect(config.output).toBe("static");
    expect(config.outDir).toBe("dist");
    expect(config.build?.format).toBe("file");
    expect(config.trailingSlash).toBe("ignore");
    expect(config.adapter).toBeUndefined();
  });

  it("never inlines a processed script, so built pages stay free of inline script (CSP)", () => {
    // Astro inlines scripts smaller than this limit; 0 makes every one an external file.
    expect(config.vite?.build?.assetsInlineLimit).toBe(0);
  });

  it("enables React (TSX) components", () => {
    const names = (config.integrations ?? []).flat().map((integration) => integration && integration.name);
    expect(names).toContain("@astrojs/react");
  });
});
