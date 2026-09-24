const {test, expect} = require("@playwright/test");
const {startServer} = require("./platform-admin-static-server");
let server;
test.beforeAll(async () => { server = await startServer(); });
test.afterAll(async () => { await new Promise(resolve => server.close(resolve)); });
const id = "00000000-0000-4000-8000-000000000001";
const OLDER_ID = "00000000-0000-4000-8000-000000000003";
async function setup(page, {role = "owner", disabled = false, disabledCode = false, locked = false, pollAdds = false, moreReports = false, formats = [], downloadFails = false, automation = true, denyFeature = false, denyReads = false, distributions = [], active = false} = {}) {
    const posts = [];
    let reportLists = 0;
    await page.addInitScript(role => {
        sessionStorage.setItem("token", "test-token");
        sessionStorage.setItem("user", JSON.stringify({id: 31, company_id: 42, role, status: "active"}));
        sessionStorage.setItem("selectedBotId", "7");
    }, role);
    await page.route("https://fonts.googleapis.com/**", route => route.abort());
    await page.route("https://fonts.gstatic.com/**", route => route.abort());
    await page.route("**/api/**", async route => {
        const path = new URL(route.request().url()).pathname;
        const respond = (data, status = 200) => route.fulfill({status, contentType:"application/json", body:JSON.stringify(data)});
        if (path.includes("/api/bots/")) return respond({status:"success", data:{id:7, bot_name:"Laksa assistant"}});
        if (path.endsWith("/api/billing/subscription")) return respond({status:"success", data:{plan:{feature_flags:{ai_generated_reports:true, automation_workflows:automation}}}});
        if (!path.includes("/analysis")) return respond({status:"success", data:{}});
        if (disabled) return respond({message:"Analysis is not enabled yet.", ...(disabledCode ? {code:"analysis_disabled"} : {})}, 503);
        if (locked) return respond({code:"feature_not_available", message:"The feature \"ai_generated_reports\" is not available on your current subscription plan."}, 403);
        if (route.request().method() === "GET" && denyReads && (path.endsWith("/schedules") || path.endsWith("/recording"))) return respond({code:"feature_not_available", message:"The feature \"automation_workflows\" is not available on your current subscription plan."}, 403);
        if (route.request().method() === "POST" && denyFeature && path.endsWith("/schedules")) return respond({code:"feature_not_available", message:"The feature \"automation_workflows\" is not available on your current subscription plan."}, 403);
        if (route.request().method() === "POST") {
            posts.push({path, body:route.request().postDataJSON()});
            return respond({data:path.endsWith("/messages") ? {id, status:"queued", request_text:posts.at(-1).body.text, created_at:"2026-09-22T10:00:00Z"} : {}},202);
        }
        if (path.endsWith("/messages")) {
            if (new URL(route.request().url()).searchParams.get("before_id")) return respond({data:[{id:OLDER_ID, status:"complete", request_text:"Last month's summary", created_at:"2026-08-01T09:00:00Z"}], next_cursor:null});
            const newer = pollAdds && reportLists++ > 0 ? [{id:"00000000-0000-4000-8000-000000000002", status:"complete", request_text:"Weekly summary for the team", created_at:"2026-09-22T11:00:00Z"}] : [];
            return respond({data:[...newer, {id, status:"partial", request_text:"Analyze my restaurant requests", created_at:"2026-09-22T09:00:00Z"}], next_cursor:moreReports ? id : null});
        }
        if (path.endsWith("/download")) return downloadFails ? respond({message:"Download is unavailable right now."}, 500) : route.fulfill({status:200, contentType:"application/pdf", body:"%PDF-1.4"});
        if (path.endsWith("/records")) return respond({data:[{id:1, action_type:"booking", status:"requested", conversation_id:9, created_at:"2026-09-22T09:00:00Z"}], next_cursor:null});
        if (path.endsWith("/schedules")) return respond({data:active ? [{frequency:"weekly", enabled:true}] : []});
        if (path.endsWith("/recording")) return respond({data:{enabled:active}});
        if (path.includes("/reports/")) return respond({data:{id, status:"partial", request_text:"Analyze my restaurant requests", formats, snapshot:{metrics:[{label:"Revenue",status:"unavailable",value:null}], limitations:["Bookings system not connected."],distributions,customer_questions:{excerpts:[{message_id:901,conversation_id:9,text:"<img src=x>Can I book a table?"}]}},result:{narrative:"<img src=x onerror=alert(1)>Only an application was recorded."}}});
        return respond({data:{bot:{id:7,bot_name:"Laksa assistant"},industry:{template_id:"restaurant",confirmed_at:"2026-09-22T09:00:00Z"},role:{business_description:"Restaurant customer service"}}});
    });
    await page.goto("/analysis.html?bot_id=7");
    return posts;
}
test("industry context, request state, safe report rendering and schedule opt-in", async ({page}) => {
    const posts = await setup(page);
    await expect(page.locator("#send-report")).toBeEnabled();
    await expect(page.locator("#industry-label")).toHaveText("Restaurant");
    await expect(page.locator("#business-records")).toContainText("Requested");
    await expect(page.locator('[data-frequency="weekly"]')).not.toBeChecked();
    await page.getByRole("button", {name:"View details"}).click();
    await expect(page.locator("#report-content")).toContainText("Not available yet");
    await expect(page.locator("#report-content img")).toHaveCount(0);
    await expect(page.locator("#report-content")).toContainText("Only an application");
    await page.getByText("Customer question samples", {exact:true}).click();
    await expect(page.locator("#report-content")).toContainText("<img src=x>Can I book a table?");
    await expect(page.locator("#report-content").getByRole("link", {name:/Open chat/})).toHaveAttribute("href", "conversations.html?bot_id=7&conversation_id=9");
    await expect(page.locator("#report-content")).not.toContainText("Message 901");
    await expect(page.locator("#report-content img")).toHaveCount(0);
    await page.getByRole("button", {name:"Close report"}).click();
    await page.locator("#report-command").fill("生成餐厅上个月的预约申请报告");
    await page.getByRole("button", {name:"Generate report"}).click();
    await expect(page.locator("#report-thread")).toContainText("Waiting to start");
    expect(posts[0].body.company_id).toBeUndefined();
    expect(posts[0].body.client_message_id).toMatch(/^[a-f0-9-]{36}$/);
    await page.locator('[data-frequency="weekly"]').check();
    await expect(page.locator("#analysis-status")).toHaveText("Schedule enabled.");
    await expect(page.locator("#recording-enabled")).not.toBeChecked();
    await page.locator("#recording-enabled").check();
    await expect(page.locator("#analysis-status")).toContainText("AI credit usage applies");
    const labels = await page.locator("chatbot-sidebar").evaluate(node => [...node.querySelectorAll(".nav-link span")].map(n => n.textContent));
    expect(labels.indexOf("Analysis")).toBe(labels.indexOf("Conversations") + 1);
    await page.evaluate(() => window.scrollTo(0,0));
    await page.screenshot({path:"test-results/analysis-desktop.png",fullPage:true});
});
test("mobile has no horizontal overflow and unavailable records are not zero", async ({page}) => {
    await page.setViewportSize({width:390,height:844});
    await setup(page, {disabled:true});
    await expect(page.locator("#analysis-status")).toContainText("not enabled");
    await expect(page.locator("#business-records")).toContainText("does not mean there are no requests");
    await expect(page.locator("#send-report")).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path:"test-results/analysis-mobile.png",fullPage:true});
});
test("members are redirected", async ({page}) => {
    await setup(page,{role:"member"});
    await expect(page).toHaveURL(/bots.html/);
});
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const grids = [
    {key:"customer_inquiry_hours", label:"Customer inquiry times <img src=x>", timezone:"Asia/Kuala_Lumpur", days:DAYS,
     status:"partial", unreadable_count:1, total:4, note:"Timestamps only.",
     matrix:DAYS.map((_, day) => Array.from({length:24}, (_, hour) => day === 1 && hour === 9 ? 3 : day === 6 && hour === 0 ? 1 : 0))},
    {key:"trial_booked_slots", label:"When booked trial sessions take place", timezone:"Asia/Kuala_Lumpur", days:DAYS,
     status:"unavailable", matrix:null, total:null, unreadable_count:null, note:"Session start times."},
];
test("report heatmaps render as accessible day-by-hour tables", async ({page}) => {
    await setup(page, {distributions:grids});
    await page.getByRole("button", {name:"View details"}).click();
    const table = page.getByRole("table", {name:/Customer inquiry times/});
    await expect(table).toBeVisible();
    await expect(table.locator('th[scope="col"]')).toHaveCount(25);
    const tuesday = table.locator("tbody tr").nth(1);
    await expect(tuesday.locator('th[scope="row"]')).toHaveText("Tue");
    await expect(tuesday.locator("td").nth(9)).toHaveText("3");
    await expect(tuesday.locator("td").nth(9)).toHaveAttribute("data-level", "4");
    await expect(tuesday.locator("td").nth(8)).toHaveAttribute("data-level", "0");
    await expect(page.locator("#report-content")).toContainText("Some activity could not be counted (1), so real numbers may be higher.");
    await expect(page.locator("#report-content")).toContainText("It doesn't mean there were none.");
    await expect(page.locator("#report-content")).toContainText("Total 4");
    await expect(table.locator("caption")).toHaveClass(/kw-visually-hidden/);
    await expect(page.locator("#report-content img")).toHaveCount(0);
    await page.screenshot({path:"test-results/analysis-heatmap-desktop.png"});
});
test("heatmap scrolls inside the report on mobile without page overflow", async ({page}) => {
    await page.setViewportSize({width:390,height:844});
    await setup(page, {distributions:grids});
    await page.getByRole("button", {name:"View details"}).click();
    const region = page.getByRole("region", {name:/Customer inquiry times/});
    await expect(region).toBeVisible();
    await expect(region).toHaveAttribute("tabindex", "0");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path:"test-results/analysis-heatmap-mobile.png"});
});
test("automation controls are locked with a Pro plan note when the plan lacks automation", async ({page}) => {
    await setup(page, {automation:false});
    await expect(page.locator("#send-report")).toBeEnabled();
    await expect(page.locator('[data-frequency="weekly"]')).toBeDisabled();
    await expect(page.locator('[data-frequency="monthly"]')).toBeDisabled();
    await expect(page.locator("#recording-enabled")).toBeDisabled();
    const notes = page.locator("[data-plan-lock]");
    await expect(notes).toHaveCount(2);
    await expect(notes.first()).toBeVisible();
    await expect(notes.first()).toContainText("Pro plan");
    await expect(notes.first().getByRole("link", {name:"See plans"})).toHaveAttribute("href", "pricing.html");
});
test("server plan denial shows an upgrade prompt instead of the raw message", async ({page}) => {
    await setup(page, {denyFeature:true});
    await expect(page.locator('[data-frequency="weekly"]')).toBeEnabled();
    // click, not check: the page reverts the box after the server refuses, so check()'s own "is checked" wait races it.
    await page.locator('[data-frequency="weekly"]').click();
    await expect(page.locator("#analysis-status")).toContainText("Pro plan");
    await expect(page.locator("#analysis-status")).not.toContainText("automation_workflows");
    await expect(page.locator("#analysis-status a")).toHaveAttribute("href", "pricing.html");
    await expect(page.locator("#analysis-status a")).toHaveText("See plans");
    await expect(page.locator('[data-frequency="weekly"]')).not.toBeChecked();
});
test("a downgraded plan can still switch active automation off but not back on", async ({page}) => {
    const posts = await setup(page, {automation:false, active:true});
    const weekly = page.locator('[data-frequency="weekly"]');
    await expect(weekly).toBeChecked();
    await expect(weekly).toBeEnabled();
    await expect(page.locator("#recording-enabled")).toBeEnabled();
    await expect(page.locator('[data-frequency="monthly"]')).toBeDisabled();
    await weekly.uncheck();
    await expect.poll(() => posts.find(post => post.path.endsWith("/schedules"))?.body).toEqual({frequency:"weekly", enabled:false});
    await expect(weekly).toBeDisabled();
});
test("a non-Pro plan whose server denies automation reads still loads reports", async ({page}) => {
    await setup(page, {automation:false, denyReads:true});
    await expect(page.locator("#send-report")).toBeEnabled();
    await expect(page.locator("#analysis-status")).toHaveText("Connected to this bot's business records.");
    await expect(page.locator("#business-records")).toContainText("Requested");
    await expect(page.locator('[data-frequency="weekly"]')).toBeDisabled();
    await expect(page.locator("#recording-enabled")).toBeDisabled();
    await expect(page.locator("[data-plan-lock]").first()).toBeVisible();
});
const TOGGLES = ['[data-frequency="weekly"]', '[data-frequency="monthly"]', "#recording-enabled"];
test("a plan without reports shows one locked landing instead of the page", async ({page}) => {
    await page.setViewportSize({width:390,height:844});
    await setup(page, {locked:true});
    const landing = page.locator("#analysis-locked");
    await expect(landing).toBeVisible();
    await expect(landing.getByRole("heading", {name:"Business reports are part of the Pro plan"})).toBeVisible();
    await expect(landing.getByRole("link", {name:"See plans"})).toHaveAttribute("href", "pricing.html");
    // One upgrade call to action: the status banner is not shown on top of the landing.
    await expect(page.locator("#analysis-statusline")).toBeHidden();
    await expect(page.getByRole("link", {name:"See plans"})).toHaveCount(1);
    await expect(page.locator("main")).not.toContainText("ai_generated_reports");
    for (const selector of ["#report-command", "#report-thread", "#business-records", ...TOGGLES]) await expect(page.locator(selector)).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path:"test-results/analysis-locked-mobile.png", fullPage:true});
});
test("keyboard focus on View details survives a poll", async ({page}) => {
    await page.clock.install();
    await setup(page, {pollAdds:true});
    const details = page.getByRole("button", {name:"View details"});
    await details.focus();
    await details.evaluate(node => { node.dataset.probe = "kept"; });
    await page.clock.fastForward(11000);
    await expect(page.locator("#report-thread")).toContainText("Weekly summary for the team");
    await expect(page.locator('[data-probe="kept"]')).toBeFocused();
    await expect(page.locator("#report-thread")).not.toHaveAttribute("aria-live");
    await expect(page.locator("#analysis-status")).toHaveText("New report ready: Weekly summary for the team");
});
test("plan-lock notes describe the toggles only while they are locked", async ({page}) => {
    await setup(page);
    await expect(page.locator("#send-report")).toBeEnabled();
    for (const selector of TOGGLES) {
        const toggle = page.locator(selector);
        await expect(toggle).toHaveAttribute("aria-describedby", `${await toggle.getAttribute("id")}-help`);
    }
    const locked = await page.context().newPage();
    await setup(locked, {automation:false});
    await expect(locked.locator("#send-report")).toBeEnabled();
    for (const selector of TOGGLES) {
        const toggle = locked.locator(selector);
        const [help, note] = (await toggle.getAttribute("aria-describedby")).split(" ");
        expect(help).toBe(`${await toggle.getAttribute("id")}-help`);
        await expect(locked.locator(`#${note}`)).toBeVisible();
        await expect(locked.locator(`#${note}`)).toContainText("Pro plan");
    }
});
test("page styles never reach the sidebar toggle", async ({page}) => {
    await setup(page);
    await expect(page.locator("#send-report")).toBeEnabled();
    await page.addStyleTag({content:"chatbot-sidebar .sidebar-toggle{transition:none!important}"});
    const read = () => page.locator("chatbot-sidebar .sidebar-toggle").evaluate(node => {
        const style = getComputedStyle(node);
        return [style.backgroundColor, style.borderTopColor, style.borderRadius, style.padding, style.fontSize, style.color, style.width].join("|");
    });
    const withPageStyles = await read();
    await page.locator('link[href$="analysis.css"]').evaluate(link => { link.disabled = true; });
    expect(await read()).toBe(withPageStyles);
});
test("analysis switched off explains that the bot keeps answering", async ({page}) => {
    await setup(page, {disabled:true, disabledCode:true});
    await expect(page.locator("#analysis-status")).toHaveText("Analysis is not enabled yet.");
    await expect(page.getByRole("heading", {name:"Reports aren't switched on yet", exact:true})).toBeVisible();
    await expect(page.locator("#analysis-off")).toContainText("Contact Omnexa support");
    await expect(page.locator("#send-report")).toBeDisabled();
    await expect(page.locator("#business-records")).toContainText("does not mean there are no requests");
});
test("desktop keeps the side rail beside reports and 320px has no overflow", async ({page}) => {
    await page.setViewportSize({width:1440, height:900});
    await setup(page, {distributions:grids});
    await expect(page.locator("#send-report")).toBeEnabled();
    const main = await page.locator("#report-thread").boundingBox();
    const rail = await page.locator("#business-records").boundingBox();
    expect(rail.x).toBeGreaterThan(main.x + main.width);
    await page.screenshot({path:"test-results/analysis-desktop-1440.png", fullPage:true});
    await page.getByRole("button", {name:"View details"}).click();
    await expect(page.locator("#report-downloads").getByRole("button")).toHaveCount(0);
    await page.screenshot({path:"test-results/analysis-report-1440.png"});
    await page.getByRole("button", {name:"Close report"}).click();
    await page.setViewportSize({width:390, height:844});
    await page.evaluate(() => window.scrollTo(0, 0));
    expect(await page.locator("#send-report").evaluate(node => node.getBoundingClientRect().bottom <= innerHeight)).toBe(true);
    await page.screenshot({path:"test-results/analysis-mobile-390.png", fullPage:true});
    await page.getByRole("button", {name:"View details"}).click();
    await page.screenshot({path:"test-results/analysis-report-390.png"});
    await page.getByRole("button", {name:"Close report"}).click();
    await page.setViewportSize({width:320, height:700});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path:"test-results/analysis-mobile-320.png", fullPage:true});
});
test("report downloads offer PDF and Excel only", async ({page}) => {
    await setup(page);
    await page.route("**/reports/*", route => route.fulfill({status:200, contentType:"application/json", body:JSON.stringify({data:{id, status:"complete", request_text:"Analyze my restaurant requests", created_at:"2026-09-22T09:00:00Z", formats:["pdf", "xlsx", "json"], snapshot:{}, result:{narrative:"Done."}}})}));
    await page.getByRole("button", {name:"View details"}).click();
    await expect(page.locator("#report-downloads").getByRole("button")).toHaveText(["Download PDF", "Download Excel"]);
});
test("a failed download is announced inside the open report", async ({page}) => {
    await setup(page, {formats:["pdf", "xlsx"], downloadFails:true});
    await page.getByRole("button", {name:"View details"}).click();
    const dialogStatus = page.locator("#report-dialog #report-downloads > #report-dialog-status");
    await expect(dialogStatus).toHaveAttribute("role", "status");
    await expect(dialogStatus).toHaveText("");
    await page.getByRole("button", {name:"Download PDF"}).click();
    await expect(dialogStatus).toHaveText("Download is unavailable right now.");
    await expect(dialogStatus).toBeVisible();
    await expect(page.locator("#report-dialog")).toHaveJSProperty("open", true);
    await page.getByRole("button", {name:"Close report"}).click();
    await page.getByRole("button", {name:"View details"}).click();
    await expect(dialogStatus).toHaveText("");
});
test("every keyboard stop in the report stays visible at 320 by 256", async ({page}) => {
    await page.setViewportSize({width:320, height:256});
    await setup(page, {distributions:grids, formats:["pdf", "xlsx"]});
    await page.getByRole("button", {name:"View details"}).click();
    const stops = [];
    for (let step = 0; step < 30; step++) {
        const stop = await page.evaluate(() => {
            const node = document.activeElement, dialog = document.getElementById("report-dialog");
            if (!dialog.contains(node) || node.dataset.visited) return null;
            node.dataset.visited = "1";
            const box = node.getBoundingClientRect();
            const left = Math.max(box.left, 0), right = Math.min(box.right, innerWidth);
            const top = Math.max(box.top, 0), bottom = Math.min(box.bottom, innerHeight);
            const hit = right > left && bottom > top ? document.elementFromPoint((left + right) / 2, (top + bottom) / 2) : null;
            return {name: node.getAttribute("aria-label") || node.textContent.trim().slice(0, 40), visible: Boolean(hit && (hit === node || node.contains(hit)))};
        });
        if (!stop) break;
        stops.push(stop);
        await page.keyboard.press("Tab");
    }
    expect(stops.length).toBeGreaterThanOrEqual(5);
    expect(stops.filter(stop => !stop.visible)).toEqual([]);
});
test("keyboard focus stays put when a control pauses while saving", async ({page}) => {
    await setup(page);
    const weekly = page.locator('[data-frequency="weekly"]');
    await weekly.focus();
    await page.keyboard.press("Space");
    await expect(page.locator("#analysis-status")).toHaveText("Schedule enabled.");
    await expect(weekly).toBeFocused();
    await page.locator("#report-command").fill("Bookings last week");
    await page.locator("#send-report").focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#report-thread")).toContainText("Waiting to start");
    await expect(page.locator("#send-report")).toBeFocused();
});
test("switching off automation on a downgraded plan moves focus to the upgrade link", async ({page}) => {
    await setup(page, {automation:false, active:true});
    const weekly = page.locator('[data-frequency="weekly"]');
    await weekly.focus();
    await page.keyboard.press("Space");
    await expect(weekly).toBeDisabled();
    await expect(page.locator("#schedule-plan-lock").getByRole("link", {name:"See plans"})).toBeFocused();
});
test("loading earlier reports moves focus to the first one loaded", async ({page}) => {
    await setup(page, {moreReports:true});
    await page.getByRole("button", {name:"Show earlier reports"}).click();
    await expect(page.locator("#more-reports")).toBeHidden();
    await expect(page.locator(`[data-report-id="${OLDER_ID}"]`).getByRole("button", {name:"View details"})).toBeFocused();
});
test("Try again keeps keyboard focus in the status line", async ({page}) => {
    await setup(page, {disabled:true});
    const retry = page.getByRole("button", {name:"Try again"});
    await retry.focus();
    await page.keyboard.press("Enter");
    await expect(retry).toBeVisible();
    await expect(retry).toBeFocused();
    expect(await page.evaluate(() => document.activeElement !== document.body)).toBe(true);
});
test("a blank request explains what to type", async ({page}) => {
    await setup(page);
    await page.locator("#report-command").fill("   ");
    await page.getByRole("button", {name:"Generate report"}).click();
    await expect(page.locator("#report-hint")).toHaveText("Type what you want to know first.");
    await expect(page.locator("#report-command")).toHaveAttribute("aria-invalid", "true");
    await expect(page.locator("#report-command")).toBeFocused();
});
