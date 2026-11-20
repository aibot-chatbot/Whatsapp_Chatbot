// Contract tests for the legacy shell that api.ts wraps. They run the REAL frontend/assets/js/auth.js
// and resilient-load.js in a node:vm context with stubbed sessionStorage, fetch and location; no code
// from those files is copied here. At F8 they replace the auth.js source-text pins in
// tests/test_platform_admin_frontend.py:457-458 and tests/test_cross_tenant_chatbot_access.py:177-178.
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";
import { describe, expect, it, vi } from "vitest";

type Respond = (url: string, init: RequestInit) => Response | Promise<Response>;

interface ShellGlobals {
  authenticatedFetch(url: string, options?: RequestInit): Promise<Response>;
  establishAuthenticatedSession(user: unknown, token: unknown): boolean;
  resilientLoad: {
    loadJson(url: string, options?: object): Promise<{ ok: boolean; data: unknown; status: number; message: string; terminal: boolean }>;
  };
}

const shellSource = (name: string): string =>
  readFileSync(new URL(`../../frontend/assets/js/${name}`, import.meta.url), "utf8");

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

// Loads both shell scripts the way a page does: classic scripts sharing one global (window).
function loadShell(session: Record<string, string> = {}, respond: Respond = () => json(200, { status: "success", data: {} })) {
  const items = new Map(Object.entries(session));
  const sessionStorage = {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => { items.set(key, String(value)); },
    removeItem: (key: string) => { items.delete(key); },
  };
  const fetch = vi.fn(async (url: string, init: RequestInit) => respond(url, init));
  const location = { href: "pricing.html", replace: vi.fn() };
  const sandbox: Record<string, unknown> = { sessionStorage, fetch, location, setTimeout, clearTimeout, AbortController, console };
  sandbox.window = sandbox;
  const context = createContext(sandbox);
  runInContext(shellSource("auth.js"), context, { filename: "frontend/assets/js/auth.js" });
  runInContext(shellSource("resilient-load.js"), context, { filename: "frontend/assets/js/resilient-load.js" });
  return { shell: sandbox as unknown as ShellGlobals, items, fetch, location };
}

const SIGNED_IN = { token: "session-token-1", user: '{"id":1}', isLoggedIn: "true", selectedBotId: "7" };
const NO_WAIT = { baseDelay: 0, maxDelay: 0 }; // real retry logic, without the real backoff delay

describe("auth.js (the real file)", () => {
  it("authenticatedFetch sends the session token as a Bearer Authorization header", async () => {
    const { shell, fetch } = loadShell(SIGNED_IN);
    await shell.authenticatedFetch("/api/bots");
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/api/bots");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer session-token-1");
  });

  it("a 401 logs the user out: token, user, isLoggedIn and the selected bot are cleared and the page goes to login.html", async () => {
    const { shell, items, location } = loadShell(SIGNED_IN, () => json(401, { status: "error", message: "Expired." }));
    const response = await shell.authenticatedFetch("/api/bots");
    expect(response.status).toBe(401);
    expect([...items.keys()]).toEqual([]);
    expect(location.href).toBe("login.html");
  });

  it("a 403 whose message says the account is deactivated keeps that message for sign-in and logs out", async () => {
    const message = "This account has been deactivated. Contact your workspace owner.";
    const { shell, items, location } = loadShell(SIGNED_IN, () => json(403, { status: "error", message }));
    await shell.authenticatedFetch("/api/bots");
    expect(Object.fromEntries(items)).toEqual({ deactivated_message: message });
    expect(location.href).toBe("login.html");
  });

  it("any other 403 keeps the session and the page", async () => {
    const { shell, items, location } = loadShell(SIGNED_IN, () => json(403, { status: "error", message: "Owners only." }));
    await shell.authenticatedFetch("/api/team");
    expect(Object.fromEntries(items)).toEqual(SIGNED_IN);
    expect(location.href).toBe("pricing.html");
  });

  it("establishAuthenticatedSession refuses an empty or blank token and leaves no session behind", () => {
    for (const token of ["", "   ", undefined]) {
      const { shell, items } = loadShell(SIGNED_IN);
      expect(shell.establishAuthenticatedSession({ id: 2 }, token)).toBe(false);
      expect([...items.keys()]).toEqual([]);
    }
  });

  it("establishAuthenticatedSession starts a clean session: the previous user's selected bot is cleared", () => {
    const { shell, items } = loadShell(SIGNED_IN);
    expect(shell.establishAuthenticatedSession({ id: 2 }, "session-token-2")).toBe(true);
    expect(Object.fromEntries(items)).toEqual({ isLoggedIn: "true", user: '{"id":2}', token: "session-token-2" });
  });
});

describe("resilient-load.js (the real file)", () => {
  it("loadJson retries a 503 and returns the data once the server answers", async () => {
    const answers = [json(503, { message: "Restarting." }), json(200, { status: "success", data: { plans: 4 } })];
    const { shell, fetch } = loadShell(SIGNED_IN, () => answers.shift()!);
    const result = await shell.resilientLoad.loadJson("/api/billing/plans", NO_WAIT);
    expect(result).toMatchObject({ ok: true, data: { plans: 4 }, status: 200 });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("loadJson does not retry a 404: one request, and a terminal failure with the server's sentence", async () => {
    const { shell, fetch } = loadShell(SIGNED_IN, () => json(404, { status: "error", message: "That plan does not exist." }));
    const result = await shell.resilientLoad.loadJson("/api/billing/plans/9", NO_WAIT);
    expect(result).toMatchObject({ ok: false, status: 404, terminal: true, message: "That plan does not exist." });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
