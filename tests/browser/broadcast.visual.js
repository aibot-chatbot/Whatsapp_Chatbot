/* Visual + computed-style verification for frontend/broadcast.html.
 *
 * Run:  npm i playwright && npx playwright install chromium
 *       node tests/browser/broadcast.visual.js output/playwright
 *
 * Not wired into pytest: it needs Node and a browser, which the Python suite
 * does not. tests/test_broadcast_templates_frontend.py covers what can be
 * asserted from source text; this covers what can only be seen once the
 * cascade has actually run.
 *
 * It exists because six real defects shipped past the source-text tests --
 * an <ol> rendering list markers, a segmented control whose selected state
 * was never styled, a back link inheriting the user-agent button face, a
 * primary action sitting under a fixed overlay, a 5-column grid holding 4
 * cards, and three places where a non-.kw-field sibling broke the design
 * system's spacing rules. Every one of them is invisible to a grep and
 * obvious to getComputedStyle.
 *
 * Serves web/dist first, then frontend/ over http (sessionStorage and route interception both
 * misbehave on file://), seeds an admin session so the login guard does not
 * redirect, stubs every /api/ call, then walks all three wizard steps.
 */

const path = require("path");
const { chromium } = require("playwright");
const { startServer } = require("./platform-admin-static-server");

const OUT = process.argv[2] || ".";
const PORT = 8899;

const STUBS = {
    "/api/broadcast/campaigns": { status: "success", campaigns: [] },
    "/api/media-attachments": { status: "success", data: [] },
    "/api/meta-templates": { status: "success", data: [] },
    "/api/conversations": { status: "success", data: [] }
};

const problems = [];
const notes = [];

function check(label, ok, detail) {
    (ok ? notes : problems).push((ok ? "PASS  " : "FAIL  ") + label + (detail ? "  -- " + detail : ""));
}

(async () => {
    const server = await startServer(PORT);
    const browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

    const consoleErrors = [];
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
    page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));

    await page.addInitScript(() => {
        sessionStorage.setItem("token", "test-token");
        sessionStorage.setItem("isLoggedIn", "true");
        sessionStorage.setItem("user", JSON.stringify({ id: 1, role: "admin", full_name: "Test", email: "t@e.com" }));
    });

    await page.route("**/api/**", (route) => {
        const url = new URL(route.request().url());
        let body = { status: "success", data: [] };
        for (const key of Object.keys(STUBS)) {
            if (url.pathname === key) body = STUBS[key];
        }
        if (url.pathname.endsWith("/progress")) {
            body = { status: "success", campaign_status: "draft", total: 0, done: 0, sent: 0, failed: 0, pending: 0, cancelled: 0 };
        }
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });

    await page.goto(`http://127.0.0.1:${PORT}/broadcast.html?bot_id=1`, { waitUntil: "networkidle" });

    check("page did not redirect to login", page.url().includes("broadcast.html"), page.url());
    await page.screenshot({ path: path.join(OUT, "01-list.png"), fullPage: true });

    // -- Into the wizard ----------------------------------------------
    await page.click("#bc-new");
    await page.waitForSelector("#bc-step-1:not([hidden])");
    await page.screenshot({ path: path.join(OUT, "02-step1.png"), fullPage: true });

    // Defect 1: the <ol> stepper was rendering "1." / "2." list markers.
    const stepper = await page.evaluate(() => {
        const ol = document.getElementById("bc-wizard-steps");
        const cs = getComputedStyle(ol);
        const sep = document.querySelector(".kw-step-sep");
        return {
            listStyleType: cs.listStyleType,
            paddingLeft: cs.paddingLeft,
            sepDisplay: sep ? getComputedStyle(sep).display : "none",
            text: ol.innerText.replace(/\s+/g, " ").trim()
        };
    });
    check("stepper has no list markers", stepper.listStyleType === "none", "list-style-type=" + stepper.listStyleType);
    // 16px here is the stepper card's own padding from broadcast.css.
    // The bug was the browser's 40px <ol> indent.
    check("stepper has no browser list indent", stepper.paddingLeft !== "40px", "padding-left=" + stepper.paddingLeft);
    check("separators are not list items", stepper.sepDisplay === "block", "display=" + stepper.sepDisplay);
    check("no stray numbering in stepper text", !/(^|\s)[12]\.(\s|$)/.test(stepper.text), JSON.stringify(stepper.text));

    // Defect 2: the back link is a <button>, and was inheriting the UA grey
    // button face because .dashboard-back-link was written for an <a>.
    const back = await page.evaluate(() => {
        const cs = getComputedStyle(document.getElementById("bc-wizard-back"));
        return { bg: cs.backgroundColor, border: cs.borderTopWidth, padding: cs.paddingTop };
    });
    const backTransparent = back.bg === "rgba(0, 0, 0, 0)" || back.bg === "transparent";
    check("back link has no button chrome", backTransparent && back.border === "0px", JSON.stringify(back));

    // Defect 3: .kw-segment styled only [aria-selected], but a radiogroup
    // uses aria-checked, so no option ever looked selected.
    const seg = await page.evaluate(() => {
        const buttons = Array.from(document.querySelectorAll("#bc-source button"));
        return buttons.map((b) => ({
            label: b.textContent.trim(),
            checked: b.getAttribute("aria-checked"),
            bg: getComputedStyle(b).backgroundColor
        }));
    });
    const on = seg.find((s) => s.checked === "true");
    const off = seg.find((s) => s.checked === "false");
    check("selected segment looks different from unselected",
        !!on && !!off && on.bg !== off.bg, JSON.stringify(seg));

    // -- Keyboard: arrow keys must move between segment options -------
    await page.focus('#bc-source button[aria-checked="true"]');
    await page.keyboard.press("ArrowRight");
    const movedTo = await page.evaluate(() => document.activeElement.textContent.trim());
    check("arrow key moves focus within the segment", movedTo === "From my contacts", "focus=" + movedTo);

    // -- Walk to step 2 and 3 -----------------------------------------
    await page.click('#bc-source button[data-source="manual"]');
    await page.fill("#bc-manual-phone", "+60123456789");
    await page.fill("#bc-manual-name", "Ali Hassan");
    await page.click("#bc-manual-add");
    await page.waitForSelector("#bc-recipients-field:not([hidden])");
    await page.screenshot({ path: path.join(OUT, "03-step1-recipient.png"), fullPage: true });

    check("Next is enabled once a recipient exists", await page.isEnabled("#bc-next"), "");

    await page.click("#bc-next");
    await page.waitForSelector("#bc-step-2:not([hidden])");
    await page.fill("#bc-name", "July promotion");
    await page.fill("#bc-body", "Hi! We are running a promotion this week - 20% off everything until Sunday.\n[BUTTON: Shop now]");
    await page.waitForTimeout(150);
    await page.screenshot({ path: path.join(OUT, "04-step2.png"), fullPage: true });

    const preview = await page.evaluate(() => {
        const el = document.getElementById("bc-preview");
        return { text: el.innerText.replace(/\s+/g, " ").trim(), buttons: el.querySelectorAll(".wa-btn").length };
    });
    check("preview renders the typed message", preview.text.includes("20% off"), preview.text.slice(0, 80));
    check("preview extracts [BUTTON:] into a real button", preview.buttons === 1, "count=" + preview.buttons);

    // The counter used to sit inside the help sentence, lengthening it enough
    // to wrap and crowd the next field's label.
    const counter = await page.evaluate(() => {
        const el = document.getElementById("bc-body-count");
        const help = el.closest(".kw-field").querySelector("p.kw-help");
        return {
            parent: el.parentElement.className,
            text: el.textContent,
            helpHasCounter: /\d+ \/ 1024/.test(help.textContent)
        };
    });
    check("character counter sits in the label row, not the help text",
        counter.parent.includes("kw-field-head") && !counter.helpHasCounter, JSON.stringify(counter));

    // Nothing may render flush against its neighbour on the review step.
    await page.click("#bc-next");
    await page.waitForSelector("#bc-step-3:not([hidden])");
    const gaps = await page.evaluate(() => {
        const note = document.getElementById("bc-review-count-note").getBoundingClientRect();
        const dl = document.getElementById("bc-review-summary").getBoundingClientRect();
        const arm = document.getElementById("bc-arm-field").getBoundingClientRect();
        return { aboveSummary: Math.round(dl.top - note.bottom), belowSummary: Math.round(arm.top - dl.bottom) };
    });
    check("review summary is not flush against its neighbours",
        gaps.aboveSummary >= 10 && gaps.belowSummary >= 10, JSON.stringify(gaps));
    await page.screenshot({ path: path.join(OUT, "05-step3.png"), fullPage: true });

    const armed = await page.isDisabled("#bc-send");
    check("send stays disabled before the name is typed", armed === true, "disabled=" + armed);
    await page.fill("#bc-arm", "July promotion");
    await page.waitForTimeout(80);
    const armedAfter = await page.isDisabled("#bc-send");
    check("send unlocks once the name matches", armedAfter === false, "disabled=" + armedAfter);
    await page.screenshot({ path: path.join(OUT, "06-step3-armed.png"), fullPage: true });

    // -- Responsive: no horizontal overflow ---------------------------
    for (const w of [1440, 1024, 768, 375]) {
        await page.setViewportSize({ width: w, height: 900 });
        await page.waitForTimeout(150);
        const overflow = await page.evaluate(() => ({
            scroll: document.documentElement.scrollWidth,
            inner: window.innerWidth
        }));
        check(`no horizontal overflow at ${w}px`, overflow.scroll <= overflow.inner + 1,
            `scrollWidth=${overflow.scroll} innerWidth=${overflow.inner}`);
        await page.screenshot({ path: path.join(OUT, `07-step3-${w}.png`), fullPage: true });
    }

    check("no console errors on broadcast", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));

    // ── Message Templates: same shared components, same fixes ────────
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`http://127.0.0.1:${PORT}/meta_templates.html?bot_id=1`, { waitUntil: "networkidle" });
    check("templates page did not redirect", page.url().includes("meta_templates.html"), page.url());
    await page.screenshot({ path: path.join(OUT, "10-templates-library.png"), fullPage: true });

    // The library must be the landing screen, not the builder.
    const landing = await page.evaluate(() => ({
        library: !document.getElementById("mt-library").hidden,
        builder: !document.getElementById("mt-builder").hidden,
        libraryFirst: !!(document.getElementById("mt-library").compareDocumentPosition(
            document.getElementById("mt-builder")) & Node.DOCUMENT_POSITION_FOLLOWING)
    }));
    check("library lands first, builder is hidden", landing.library && !landing.builder && landing.libraryFirst, JSON.stringify(landing));

    await page.click("#mt-new");
    await page.waitForSelector("#mt-step-1:not([hidden])");
    await page.screenshot({ path: path.join(OUT, "11-templates-step1.png"), fullPage: true });

    // The language/category pair must actually sit side by side.
    const pair = await page.evaluate(() => {
        const fields = document.querySelectorAll("#mt-step-1 .kw-fieldpair > .kw-field");
        if (fields.length < 2) return { count: fields.length };
        const a = fields[0].getBoundingClientRect();
        const b = fields[1].getBoundingClientRect();
        return { count: fields.length, sameRow: Math.abs(a.top - b.top) < 4, aRight: Math.round(a.right), bLeft: Math.round(b.left) };
    });
    check("field pair renders as two columns", pair.count === 2 && pair.sameRow, JSON.stringify(pair));

    await page.fill("#mt-name", "Promo Offer V1");
    const sanitised = await page.inputValue("#mt-name");
    check("template name is sanitised to Meta's rules", sanitised === "promo_offer_v1", "value=" + sanitised);

    await page.click("#mt-next");
    await page.waitForSelector("#mt-step-2:not([hidden])");
    await page.fill("#mt-body", "Hi {{1}}, use code {{2}} for 20% off.");
    await page.fill("#mt-footer", "Reply STOP to unsubscribe");
    await page.click('#mt-header-type button[data-header="TEXT"]');
    await page.fill("#mt-header-text", "Special offer");
    await page.click("#mt-add-button");
    await page.fill('.mt-button-row [data-part="text"]', "Shop now");
    await page.waitForTimeout(150);
    await page.screenshot({ path: path.join(OUT, "12-templates-step2.png"), fullPage: true });

    const tplPreview = await page.evaluate(() => {
        const el = document.getElementById("mt-preview");
        return {
            head: el.querySelector(".wa-head") ? el.querySelector(".wa-head").textContent : "",
            foot: el.querySelector(".wa-foot") ? el.querySelector(".wa-foot").textContent : "",
            buttons: el.querySelectorAll(".wa-btn").length,
            keepsPlaceholders: el.innerText.includes("{{1}}")
        };
    });
    check("template preview shows header, footer and button",
        tplPreview.head === "Special offer" && tplPreview.foot.includes("STOP") && tplPreview.buttons === 1,
        JSON.stringify(tplPreview));
    check("preview keeps placeholders verbatim (that is what Meta reviews)",
        tplPreview.keepsPlaceholders, JSON.stringify(tplPreview));

    const tplSeg = await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll("#mt-header-type button"));
        const on = b.find((x) => x.getAttribute("aria-checked") === "true");
        const off = b.find((x) => x.getAttribute("aria-checked") === "false");
        return { on: on && getComputedStyle(on).backgroundColor, off: off && getComputedStyle(off).backgroundColor };
    });
    check("templates segment shows its selected state", tplSeg.on !== tplSeg.off, JSON.stringify(tplSeg));

    await page.click("#mt-next");
    await page.waitForSelector("#mt-step-3:not([hidden])");
    await page.screenshot({ path: path.join(OUT, "13-templates-step3.png"), fullPage: true });

    for (const w of [1024, 768, 375]) {
        await page.setViewportSize({ width: w, height: 900 });
        await page.waitForTimeout(150);
        const o = await page.evaluate(() => ({ s: document.documentElement.scrollWidth, i: window.innerWidth }));
        check(`templates: no horizontal overflow at ${w}px`, o.s <= o.i + 1, `scrollWidth=${o.s} innerWidth=${o.i}`);
    }

    await browser.close();
    server.close();

    console.log("\n" + notes.join("\n"));
    if (problems.length) {
        console.log("\n=== PROBLEMS ===\n" + problems.join("\n"));
        process.exitCode = 1;
    } else {
        console.log("\n=== ALL CHECKS PASSED ===");
    }
})();
