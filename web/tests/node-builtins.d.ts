// The node built-ins the contract tests use, typed by hand: @types/node is not installed (no new
// dependency) and astro check type-checks tests/ too. Extend only when a test needs another function.
declare module "node:fs" {
  export function readFileSync(path: URL | string, encoding: "utf8"): string;
}

declare module "node:vm" {
  export function createContext(sandbox: object): object;
  export function runInContext(code: string, context: object, options?: { filename?: string }): unknown;
}
