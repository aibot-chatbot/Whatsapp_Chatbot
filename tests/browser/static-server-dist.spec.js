const fs = require("fs");
const os = require("os");
const path = require("path");
const { expect, test } = require("@playwright/test");
const { safePath, startServer } = require("./platform-admin-static-server");

// Temp roots stand in for web/dist and frontend/, so this never writes into the real web/ tree.
let tmp;
let server;
let origin;

test.beforeAll(async () => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "static-dist-"));
  const dist = path.join(tmp, "dist");
  const legacy = path.join(tmp, "frontend");
  fs.mkdirSync(dist);
  fs.mkdirSync(legacy);
  fs.writeFileSync(path.join(dist, "page.html"), "from dist");
  fs.writeFileSync(path.join(dist, "landing.html"), "landing");
  fs.writeFileSync(path.join(legacy, "page.html"), "from frontend");
  fs.writeFileSync(path.join(legacy, "legacy-only.html"), "legacy only");
  fs.writeFileSync(path.join(tmp, "secret.txt"), "outside both roots");
  server = await startServer(0, [dist, legacy]);
  origin = `http://127.0.0.1:${server.address().port}`;
});

test.afterAll(async () => {
  if (server) await new Promise(resolve => server.close(resolve));
  if (tmp) fs.rmSync(tmp, { recursive: true, force: true });
});

test("a page present in dist is served instead of its frontend copy", async ({ request }) => {
  const response = await request.get(`${origin}/page.html`);
  expect(response.status()).toBe(200);
  expect(await response.text()).toBe("from dist");
});

test("a page missing from dist falls back to frontend", async ({ request }) => {
  const response = await request.get(`${origin}/legacy-only.html`);
  expect(response.status()).toBe(200);
  expect(await response.text()).toBe("legacy only");
});

test("clean page URLs use the same dist-first lookup", async ({ request }) => {
  for (const [page, body] of [["page", "from dist"], ["legacy-only", "legacy only"]]) {
    const response = await request.get(`${origin}/${page}`);
    expect(response.status()).toBe(200);
    expect(await response.text()).toBe(body);
  }
});

test("legacy page redirects follow the selected URL mode", async ({ request }) => {
  const query = "?token=a%2Bb&section=one&section=two";
  for (const [page, clean] of [["page.html", "/page"], ["landing.html", "/"]]) {
    const response = await request.head(`${origin}/${page}${query}`, { maxRedirects: 0 });
    if (process.env.E2E_CLEAN_URLS === "1") {
      expect(response.status()).toBe(301);
      expect(response.headers().location).toBe(clean + query);
      expect(response.headers()["cache-control"]).toBe("public, max-age=3600");
    } else {
      expect(response.status()).toBe(200);
    }
  }
});

// "/..%2f" is clamped by path.normalize before the guard runs, so these cases hit the guard itself.
test("the path guard refuses a relative path that climbs out of the root", () => {
  const root = path.join(tmp, "frontend");
  expect(safePath("../secret.txt", root)).toBeNull();
  expect(safePath("/page.html", root)).toBe(path.join(root, "page.html"));
});

test("a drive path in the URL cannot reach a file outside the roots", async ({ request }) => {
  test.skip(process.platform !== "win32", "drive-letter paths exist only on Windows");
  const secret = path.join(tmp, "secret.txt").replace(/\\/g, "/");
  const response = await request.get(`${origin}/${secret}`);
  expect(response.status()).toBe(404);
});

test("a page in neither root is not found", async ({ request }) => {
  const response = await request.get(`${origin}/missing.html`);
  expect(response.status()).toBe(404);
});
