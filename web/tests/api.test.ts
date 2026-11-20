// web/src/lib/api.ts against stubbed shell globals (window.authenticatedFetch, window.resilientLoad).
// The real globals are contract-tested in legacy-shell-contract.test.ts.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getJson, requestRaw, sendJson, type ApiPath } from "../src/lib/api";

type Plan = { code: string };
const isPlan = (data: unknown): data is Plan =>
  typeof data === "object" && data !== null && typeof (data as { code?: unknown }).code === "string";
const isAnything = (_data: unknown): _data is unknown => true;

const UNEXPECTED = "The server sent an unexpected response.";
const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const authenticatedFetch = vi.fn<Window["authenticatedFetch"]>();
const loadJson = vi.fn<Window["resilientLoad"]["loadJson"]>();
// The real classification from resilient-load.js:33-35, so `terminal` means the same thing everywhere.
const isRetryableStatus = (status: number) => [408, 425, 429].includes(status) || (status >= 500 && status < 600);

beforeEach(() => {
  vi.stubGlobal("window", { authenticatedFetch, resilientLoad: { loadJson, isRetryableStatus } });
  // The client must never touch the session: auth.js owns it.
  vi.stubGlobal("sessionStorage", new Proxy({}, { get: () => { throw new Error("api.ts read sessionStorage"); } }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

describe("getJson", () => {
  it("returns the data of a success envelope that passes the guard", async () => {
    loadJson.mockResolvedValue({ ok: true, data: { code: "pro" }, status: 200, message: "", terminal: false });
    await expect(getJson("/api/billing/plans/pro", isPlan)).resolves.toEqual({ ok: true, data: { code: "pro" }, status: 200 });
    expect(loadJson).toHaveBeenCalledWith("/api/billing/plans/pro");
  });

  it("passes on a 200 carrying status:\"error\" as a terminal failure with the server's sentence", async () => {
    loadJson.mockResolvedValue({ ok: false, data: null, status: 200, message: "That plan is retired.", terminal: true, attempts: 1 });
    await expect(getJson("/api/billing/plans/old", isPlan))
      .resolves.toEqual({ ok: false, status: 200, message: "That plan is retired.", terminal: true });
  });

  it("retries only through resilientLoad: one loadJson call, its verdict passed on, no fetch of its own", async () => {
    // loadJson already retried the 503s itself (resilient-load.js:78-108) before giving this verdict.
    loadJson.mockResolvedValue({ ok: false, data: null, status: 503, message: "The server is restarting.", terminal: false, attempts: 4 });
    await expect(getJson("/api/bots", isAnything))
      .resolves.toEqual({ ok: false, status: 503, message: "The server is restarting.", terminal: false });
    expect(loadJson).toHaveBeenCalledTimes(1);
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });

  it("turns data that fails the guard into a terminal failure with the fixed sentence", async () => {
    loadJson.mockResolvedValue({ ok: true, data: { code: 42 }, status: 200, message: "", terminal: false });
    await expect(getJson("/api/billing/plans/pro", isPlan)).resolves.toEqual({ ok: false, status: 200, message: UNEXPECTED, terminal: true });
  });
});

describe("sendJson", () => {
  it("sends a mutation once as JSON through authenticatedFetch and returns the guarded data", async () => {
    authenticatedFetch.mockResolvedValue(json(201, { status: "success", data: { code: "team" } }));
    await expect(sendJson("/api/plans", "POST", { code: "team" }, isPlan)).resolves.toEqual({ ok: true, data: { code: "team" }, status: 201 });
    expect(authenticatedFetch).toHaveBeenCalledTimes(1);
    expect(authenticatedFetch).toHaveBeenCalledWith("/api/plans", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: '{"code":"team"}'
    });
    expect(loadJson).not.toHaveBeenCalled();
  });

  it("never retries a mutation, even on a retryable 503", async () => {
    authenticatedFetch.mockResolvedValue(json(503, { status: "error", message: "The server is restarting." }));
    await expect(sendJson("/api/plans", "PUT", {}, isPlan))
      .resolves.toEqual({ ok: false, status: 503, message: "The server is restarting.", terminal: false });
    expect(authenticatedFetch).toHaveBeenCalledTimes(1);
  });

  it("reports a 4xx as terminal with the server's sentence", async () => {
    authenticatedFetch.mockResolvedValue(json(422, { status: "error", message: "A plan code is required." }));
    await expect(sendJson("/api/plans", "POST", {}, isPlan))
      .resolves.toEqual({ ok: false, status: 422, message: "A plan code is required.", terminal: true });
  });

  it("reports a 200 carrying status:\"error\" as terminal with the server's sentence", async () => {
    authenticatedFetch.mockResolvedValue(json(200, { status: "error", message: "That plan already exists." }));
    await expect(sendJson("/api/plans", "POST", {}, isPlan))
      .resolves.toEqual({ ok: false, status: 200, message: "That plan already exists.", terminal: true });
  });

  it("turns a success envelope whose data fails the guard into a terminal failure", async () => {
    authenticatedFetch.mockResolvedValue(json(200, { status: "success", data: ["not", "a", "plan"] }));
    await expect(sendJson("/api/plans", "PATCH", {}, isPlan)).resolves.toEqual({ ok: false, status: 200, message: UNEXPECTED, terminal: true });
  });

  it("turns a non-JSON body into a failure instead of throwing", async () => {
    authenticatedFetch.mockResolvedValueOnce(new Response("<html>gateway</html>", { status: 200 }));
    await expect(sendJson("/api/plans", "POST", {}, isPlan)).resolves.toEqual({ ok: false, status: 200, message: UNEXPECTED, terminal: true });
    authenticatedFetch.mockResolvedValueOnce(new Response("<html>bad gateway</html>", { status: 502 }));
    await expect(sendJson("/api/plans", "POST", {}, isPlan))
      .resolves.toEqual({ ok: false, status: 502, message: "The server responded with status 502.", terminal: false });
  });

  it("turns a network failure into a retryable failure instead of throwing", async () => {
    authenticatedFetch.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(sendJson("/api/plans", "DELETE", {}, isAnything))
      .resolves.toEqual({ ok: false, status: 0, message: "We could not reach the server.", terminal: false });
  });
});

describe("requestRaw", () => {
  it("guards a non-envelope body whole, through one authenticatedFetch call", async () => {
    const isCampaigns = (data: unknown): data is { campaigns: unknown[] } =>
      typeof data === "object" && data !== null && Array.isArray((data as { campaigns?: unknown }).campaigns);
    authenticatedFetch.mockResolvedValue(json(200, { status: "ok", campaigns: [] }));
    await expect(requestRaw("/api/broadcast/campaigns", isCampaigns))
      .resolves.toEqual({ ok: true, data: { status: "ok", campaigns: [] }, status: 200 });
    expect(authenticatedFetch).toHaveBeenCalledTimes(1);
  });

  it("never lets the token land in the caller's own headers object", async () => {
    // auth.js writes the token into options.headers (auth.js:86-93); the caller's object must not get it.
    authenticatedFetch.mockImplementation(async (_url, options) => {
      if (options?.headers) options.headers["Authorization"] = "Bearer secret";
      return json(200, {});
    });
    const headers = { Accept: "text/csv" };
    await requestRaw("/api/reports/export", isAnything, { headers });
    expect(headers).toEqual({ Accept: "text/csv" });
  });
});

describe("the path guard: authenticatedFetch attaches the Bearer token to any URL (auth.js:91-95)", () => {
  // Each must throw TypeError before anything is fetched: the token must never leave for another origin.
  const rejected: [string, string][] = [
    ["another origin", "https://evil.example/api/x"],
    ["a protocol-relative URL", "//evil.example/api/x"],
    ["a path that only starts with /api", "/apix"],
    ["a relative path", "api/x"],
    ["the wrong case", "/API/x"],
    ["a backslash, which browsers read as a slash", "/\\evil.example"],
    ["a backslash inside an /api/ path", "/api/\\evil.example"],
    ["a tab, which URL parsing strips", "/api/\tx"],
    ["a line break", "/api/x\n"],
    ["a NUL control character", "/api/x\u0000"],
    ["just /api", "/api"]
  ];
  const calls: [string, (path: ApiPath) => Promise<unknown>][] = [
    ["getJson", path => getJson(path, isAnything)],
    ["sendJson", path => sendJson(path, "POST", {}, isAnything)],
    ["requestRaw", path => requestRaw(path, isAnything)]
  ];

  for (const [name, call] of calls) {
    it.each(rejected)(`${name} refuses %s (%j) before any fetch`, (_why, path) => {
      expect(() => call(path as ApiPath)).toThrow(TypeError);
      expect(authenticatedFetch).not.toHaveBeenCalled();
      expect(loadJson).not.toHaveBeenCalled();
    });
  }

  it("accepts a same-origin /api/ path with a query string", async () => {
    loadJson.mockResolvedValue({ ok: true, data: {}, status: 200, message: "", terminal: false });
    await expect(getJson("/api/geo/analyses?limit=5", isAnything)).resolves.toMatchObject({ ok: true });
  });
});
