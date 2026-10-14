const { expect, test } = require("@playwright/test");
const { startServer } = require("./platform-admin-static-server");

// Light mode swaps colour tokens; anything that hard-codes a dark-mode colour slips through.
// Platform admin is out of scope (owner decision), so its pages are not listed.
const PAGES = [
  "login.html", "register.html", "forgot.html", "accept-invite.html", "privacy.html", "terms.html",
  "bots.html", "index.html?bot_id=1", "billing.html", "bookings.html", "team.html", "profile.html",
  "pricing.html", "conversations.html", "integration.html", "broadcast.html", "meta_templates.html",
  "geo-analysis.html", "support.html", "media_attachments.html", "behaviour.html", "message_style.html"
];

let staticServer;
test.beforeAll(async () => { staticServer = await startServer(); });
test.afterAll(async () => { if (staticServer) await new Promise(resolve => staticServer.close(resolve)); });

async function openInLightMode(page, url) {
  await page.addInitScript(() => {
    localStorage.setItem("omnexa-theme", "light");
    localStorage.setItem("omnexa-language", "en");
    sessionStorage.setItem("token", "browser-test-token");
    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("selectedBotId", "1");
    sessionStorage.setItem("user", JSON.stringify({ id: 1, role: "owner", email: "owner@example.com" }));
  });
  await page.route(/^https:/, route => route.abort());
  await page.route("**/api/**", route => route.fulfill(/\/api\/bots\/1$/.test(route.request().url())
    ? { json: { status: "success", data: { id: 1, name: "Demo bot" } } }
    : { json: { status: "success", data: [] } }));
  await page.goto("/" + url);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.waitForTimeout(800);
}

// Lists visible text under 3:1 against what is painted behind it, and neutral dark panels.
function findLightModeProblems() {
  const parse = s => {
    const m = /rgba?\(([^)]+)\)/.exec(s || "");
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lin = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const lum = c => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
  const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
  // null when a strong gradient sits behind the element: its colour there is unknown
  const behind = el => {
    const layers = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      const stops = (cs.backgroundImage.match(/rgba?\([^)]+\)/g) || []).map(parse);
      if (stops.some(s => s.a >= 0.3)) return null;
      const c = parse(cs.backgroundColor);
      if (c && c.a > 0) layers.push(c);
      if (c && c.a >= 0.98) break;
    }
    return layers.reduceRight((under, top) => over(top, under), { r: 246, g: 245, b: 241, a: 1 });
  };
  const name = el => el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + [...el.classList].slice(0, 2).map(c => "." + c).join("");
  const problems = [];
  for (const el of document.body.querySelectorAll("*")) {
    if (el.closest("video,img,svg,canvas,iframe,.message-bubble,.wa-preview")) continue;
    const box = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (box.width < 4 || box.height < 4 || cs.visibility === "hidden" || Number(cs.opacity) < 0.05) continue;
    const fill = parse(cs.backgroundColor);
    const parentBg = behind(el.parentElement || el);
    if (fill && fill.a >= 0.45 && parentBg && box.width * box.height >= 300) {
      const shown = over(fill, parentBg);
      const chroma = (Math.max(shown.r, shown.g, shown.b) - Math.min(shown.r, shown.g, shown.b)) / 255;
      if (lum(shown) < 0.2 && chroma < 0.3) problems.push(`dark surface ${name(el)} ${cs.backgroundColor}`);
    }
    const text = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join("");
    const fg = parse(cs.color);
    const bg = text && fg && fg.a > 0.3 && Number(cs.opacity) > 0.5 && !el.closest(":disabled,[aria-disabled=true]") ? behind(el) : null;
    if (bg) {
      const [hi, lo] = [lum(over(fg, bg)), lum(bg)].sort((a, b) => b - a);
      const ratio = (hi + 0.05) / (lo + 0.05);
      if (ratio < 3) problems.push(`${ratio.toFixed(2)}:1 ${name(el)} "${text.slice(0, 40)}"`);
    }
  }
  return problems;
}

for (const url of PAGES) {
  test(`light mode keeps ${url} readable with no dark leftovers`, async ({ page }) => {
    await openInLightMode(page, url);
    expect(await page.evaluate(findLightModeProblems)).toEqual([]);
  });
}

test("light mode keeps checked switches on the accent and unchecked ones visible", async ({ page }) => {
  await openInLightMode(page, "message_style.html");
  const toggle = page.locator(".bh-switch").first();
  await expect(toggle).toBeVisible();
  const colours = await toggle.evaluate(input => {
    const read = () => getComputedStyle(input).backgroundColor;
    input.style.transition = "none"; // read the end colour, not the first frame of the fade
    const original = input.checked;
    input.checked = true;
    const on = read();
    input.checked = false;
    const off = read();
    input.checked = original;
    return { on, off };
  });
  expect(colours.on).toBe("rgb(14, 116, 144)");
  expect(colours.off).toBe("rgba(35, 36, 31, 0.09)");
});
