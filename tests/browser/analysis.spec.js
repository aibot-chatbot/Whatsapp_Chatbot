const {test, expect} = require("@playwright/test");
const {startServer} = require("./platform-admin-static-server");
let server;
test.beforeAll(async () => { server = await startServer(); });
test.afterAll(async () => { await new Promise(resolve => server.close(resolve)); });
const id = "00000000-0000-4000-8000-000000000001";
const OLDER_ID = "00000000-0000-4000-8000-000000000003";
async function setup(page, {role = "owner", disabled = false, disabledCode = false, locked = false, pollAdds = false, moreReports = false, formats = [], downloadFails = false, automation = true, denyFeature = false, denyReads = false, distributions = [], active = false, legacyActive = false, holdEnables = false, industry = {template_id:"restaurant", confirmed_at:"2026-09-22T09:00:00Z"}, scheduleRejects = ""} = {}) {
    const posts = [];
    let reportLists = 0;
    // Schedules follow the API contract: stored choices survive a switch-off, and the next run is computed from them.
    const blank = frequency => ({frequency, enabled:false, run_weekday:null, run_day:null, run_time:null, next_due_at:null});
    const store = {weekly:active ? {frequency:"weekly", enabled:true, run_weekday:3, run_day:null, run_time:"18:15", next_due_at:"2026-10-01T10:15:00Z"}
        : legacyActive ? {...blank("weekly"), enabled:true, next_due_at:"2026-10-01T01:00:00Z"} : blank("weekly"), monthly:blank("monthly")};
    // holdEnables: saves that switch a schedule on wait until the test calls posts.release(), to hold a save "in flight".
    let releaseEnables = () => {};
    const enablesHeld = new Promise(resolve => { releaseEnables = resolve; });
    const nextDue = row => {
        const [hour, minute] = row.run_time.split(":").map(Number);
        const day = row.frequency === "weekly" ? 1 : row.run_day === "last" ? 0 : row.run_day;
        return new Date(Date.UTC(2026, 9, day, hour - 8, minute)).toISOString();  // Malaysia is UTC+8
    };
    const saveSchedule = body => {
        const row = {...store[body.frequency], enabled:body.enabled};
        for (const key of ["run_weekday", "run_day", "run_time"]) if (key in body) row[key] = body[key];
        row.next_due_at = row.enabled ? nextDue(row) : null;
        return store[body.frequency] = row;
    };
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
            if (path.endsWith("/schedules")) {
                const body = posts.at(-1).body;
                if (scheduleRejects) return respond({message:scheduleRejects}, 400);
                if (holdEnables && body.enabled) await enablesHeld;
                return respond({data:saveSchedule(body)});
            }
            return respond({data:path.endsWith("/messages") ? {id, status:"queued", request_text:posts.at(-1).body.text, created_at:"2026-09-22T10:00:00Z"} : {}},202);
        }
        if (path.endsWith("/messages")) {
            if (new URL(route.request().url()).searchParams.get("before_id")) return respond({data:[{id:OLDER_ID, status:"complete", request_text:"Last month's summary", created_at:"2026-08-01T09:00:00Z"}], next_cursor:null});
            const newer = pollAdds && reportLists++ > 0 ? [{id:"00000000-0000-4000-8000-000000000002", status:"complete", request_text:"Weekly summary for the team", created_at:"2026-09-22T11:00:00Z"}] : [];
            return respond({data:[...newer, {id, status:"partial", request_text:"Analyze my restaurant requests", created_at:"2026-09-22T09:00:00Z"}], next_cursor:moreReports ? id : null});
        }
        if (path.endsWith("/download")) return downloadFails ? respond({message:"Download is unavailable right now."}, 500) : route.fulfill({status:200, contentType:"application/pdf", body:"%PDF-1.4"});
        if (path.endsWith("/records")) return respond({data:[{id:1, action_type:"booking", status:"requested", conversation_id:9, created_at:"2026-09-22T09:00:00Z"}], next_cursor:null});
        if (path.endsWith("/schedules")) return respond({data:Object.values(store)});
        if (path.endsWith("/recording")) return respond({data:{enabled:active}});
        if (path.includes("/reports/")) return respond({data:{id, status:"partial", request_text:"Analyze my restaurant requests", formats, snapshot:{metrics:[{label:"Revenue",status:"unavailable",value:null}], limitations:["Bookings system not connected."],distributions,customer_questions:{excerpts:[{message_id:901,conversation_id:9,text:"<img src=x>Can I book a table?"}]}},result:{narrative:"<img src=x onerror=alert(1)>Only an application was recorded."}}});
        return respond({data:{bot:{id:7,bot_name:"Laksa assistant"},industry,role:{business_description:"Restaurant customer service"}}});
    });
    await page.goto("/analysis.html?bot_id=7");
    posts.release = () => releaseEnables();
    return posts;
}
async function chooseWeekly(page, day = "3", time = "18:15") {
    await page.getByLabel("Weekly report day").selectOption(day);
    await page.getByLabel("Weekly report time").selectOption(time);
}
const schedulePosts = posts => posts.filter(post => post.path.endsWith("/schedules")).map(post => post.body);
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
    await chooseWeekly(page);
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
    await chooseWeekly(page);
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
    await chooseWeekly(page);
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
test("schedule pickers start empty and offer every quarter hour in 12-hour time", async ({page}) => {
    await setup(page);
    await expect(page.locator("#send-report")).toBeEnabled();
    for (const name of ["Weekly report day", "Weekly report time", "Monthly report day", "Monthly report time"]) await expect(page.getByLabel(name)).toHaveValue("");
    await expect(page.getByLabel("Weekly report day").locator("option")).toHaveText(["Choose a day", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]);
    const monthlyDays = page.getByLabel("Monthly report day").locator("option");
    await expect(monthlyDays).toHaveCount(30);
    await expect(monthlyDays.nth(1)).toHaveText("1st");
    await expect(monthlyDays.nth(22)).toHaveText("22nd");
    await expect(monthlyDays.nth(29)).toHaveText("Last day of the month");
    const times = page.getByLabel("Weekly report time").locator("option");
    await expect(times).toHaveCount(97);
    await expect(times.nth(0)).toHaveText("Choose a time");
    await expect(times.nth(1)).toHaveText("12:00 am");
    await expect(page.getByLabel("Weekly report time").locator('option[value="18:15"]')).toHaveText("6:15 pm");
    await expect(page.locator("#schedule-weekly-help")).toHaveText("Off — covers the 7 days before each report");
    await expect(page.locator("#schedule-monthly-help")).toHaveText("Off — covers the month before each report");
});
test("a schedule cannot switch on until a day and time are chosen", async ({page}) => {
    const posts = await setup(page);
    const weekly = page.locator('[data-frequency="weekly"]');
    await expect(weekly).toBeEnabled();
    await weekly.click();
    await expect(weekly).not.toBeChecked();
    await expect(page.locator("#schedule-weekly-help")).toHaveText("Choose a day and time first.");
    await expect(page.getByLabel("Weekly report day")).toBeFocused();
    await page.getByLabel("Weekly report day").selectOption("3");
    await weekly.click();
    await expect(page.getByLabel("Weekly report time")).toBeFocused();
    expect(schedulePosts(posts)).toEqual([]);
});
test("choosing a day and time then switching on saves them and shows the next report", async ({page}) => {
    const posts = await setup(page);
    await chooseWeekly(page);
    await page.locator('[data-frequency="weekly"]').check();
    await expect(page.locator("#analysis-status")).toHaveText("Schedule enabled.");
    await expect(page.locator("#schedule-weekly-help")).toHaveText("On — next report Thursday 1 Oct, 6:15 pm");
    await page.getByLabel("Monthly report day").selectOption("last");
    await page.getByLabel("Monthly report time").selectOption("09:00");
    await page.locator('[data-frequency="monthly"]').check();
    await expect(page.locator("#schedule-monthly-help")).toHaveText("On — next report Wednesday 30 Sep, 9:00 am");
    expect(schedulePosts(posts)).toEqual([
        {frequency:"weekly", enabled:true, run_weekday:3, run_time:"18:15"},
        {frequency:"monthly", enabled:true, run_day:"last", run_time:"09:00"},
    ]);
    await page.getByLabel("Monthly report day").selectOption("15");
    await expect.poll(() => schedulePosts(posts).at(-1)).toEqual({frequency:"monthly", enabled:true, run_day:15, run_time:"09:00"});
});
test("changing the time of an active schedule saves it and shows the new next report", async ({page}) => {
    const posts = await setup(page, {active:true});
    await expect(page.getByLabel("Weekly report day")).toHaveValue("3");
    await expect(page.getByLabel("Weekly report time")).toHaveValue("18:15");
    await expect(page.locator("#schedule-weekly-help")).toHaveText("On — next report Thursday 1 Oct, 6:15 pm");
    await page.getByLabel("Weekly report time").selectOption("07:30");
    await expect(page.locator("#schedule-weekly-help")).toHaveText("On — next report Thursday 1 Oct, 7:30 am");
    await expect(page.locator("#analysis-status")).toHaveText("Schedule updated. Next report Thursday 1 Oct, 7:30 am.");
    expect(schedulePosts(posts)).toEqual([{frequency:"weekly", enabled:true, run_weekday:3, run_time:"07:30"}]);
    await page.locator('[data-frequency="weekly"]').uncheck();
    await expect(page.locator("#schedule-weekly-help")).toHaveText("Off — covers the 7 days before each report");
    await expect(page.getByLabel("Weekly report time")).toHaveValue("07:30");
    expect(schedulePosts(posts).at(-1)).toEqual({frequency:"weekly", enabled:false});
});
test("a schedule the server refuses shows its message in the row", async ({page}) => {
    await setup(page, {scheduleRejects:"Choose a day and time first."});
    await chooseWeekly(page);
    await page.locator('[data-frequency="weekly"]').click();
    await expect(page.locator("#schedule-weekly-help")).toHaveText("Choose a day and time first.");
    await expect(page.locator('[data-frequency="weekly"]')).not.toBeChecked();
});
test("a plan without automation locks the schedule pickers too", async ({page}) => {
    await setup(page, {automation:false});
    await expect(page.locator("#send-report")).toBeEnabled();
    for (const name of ["Weekly report day", "Weekly report time", "Monthly report day", "Monthly report time"]) await expect(page.getByLabel(name)).toBeDisabled();
    const downgraded = await page.context().newPage();
    await setup(downgraded, {automation:false, active:true});
    await expect(downgraded.locator('[data-frequency="weekly"]')).toBeEnabled();
    await expect(downgraded.getByLabel("Weekly report day")).toBeDisabled();
    await expect(downgraded.getByLabel("Weekly report time")).toBeDisabled();
    await expect(downgraded.getByLabel("Weekly report time")).toHaveAttribute("aria-describedby", "schedule-weekly-help schedule-plan-lock");
});
test("switching off within the save delay of a time change keeps the schedule off", async ({page}) => {
    await page.clock.install();
    const posts = await setup(page, {active:true});
    const weekly = page.locator('[data-frequency="weekly"]');
    await expect(weekly).toBeChecked();
    await page.getByLabel("Weekly report time").selectOption("07:30");
    await weekly.uncheck();
    await page.clock.fastForward(1000);
    await expect.poll(() => schedulePosts(posts).length).toBeGreaterThan(0);
    await page.clock.fastForward(1000);
    expect(schedulePosts(posts).at(-1)).toEqual({frequency:"weekly", enabled:false});
    expect(schedulePosts(posts).some(body => body.enabled)).toBe(false);
    await expect(weekly).not.toBeChecked();
    await expect(page.locator("#schedule-weekly-help")).toHaveText("Off — covers the 7 days before each report");
});
test("switching off while a time change is still saving keeps the schedule off", async ({page}) => {
    await page.clock.install();
    const posts = await setup(page, {active:true, holdEnables:true});
    const weekly = page.locator('[data-frequency="weekly"]');
    await page.getByLabel("Weekly report time").selectOption("07:30");
    await page.clock.fastForward(1000);
    await expect.poll(() => schedulePosts(posts)).toEqual([{frequency:"weekly", enabled:true, run_weekday:3, run_time:"07:30"}]);
    await weekly.uncheck();
    // The switch-off waits for the in-flight save, so the server sees on-then-off, never off-then-on.
    expect(schedulePosts(posts)).toHaveLength(1);
    posts.release();
    await expect.poll(() => schedulePosts(posts).at(-1)).toEqual({frequency:"weekly", enabled:false});
    await expect(page.locator("#analysis-status")).toHaveText("Schedule paused.");
    await expect(weekly).not.toBeChecked();
    await expect(page.locator("#schedule-weekly-help")).toHaveText("Off — covers the 7 days before each report");
});
test("an active schedule with no stored day never saves a guessed Monday", async ({page}) => {
    await page.clock.install();
    const posts = await setup(page, {legacyActive:true});
    await expect(page.locator('[data-frequency="weekly"]')).toBeChecked();
    await page.getByLabel("Weekly report time").selectOption("07:30");
    await page.clock.fastForward(1000);
    await expect(page.locator("#schedule-weekly-help")).toHaveText("Choose a day and time first.");
    expect(schedulePosts(posts)).toEqual([]);
    await page.getByLabel("Weekly report day").selectOption("3");
    await page.clock.fastForward(1000);
    await expect.poll(() => schedulePosts(posts)).toEqual([{frequency:"weekly", enabled:true, run_weekday:3, run_time:"07:30"}]);
});
test("changing a time and changing it back does not re-save the schedule", async ({page}) => {
    await page.clock.install();
    const posts = await setup(page, {active:true});
    await page.getByLabel("Weekly report time").selectOption("07:30");
    await page.getByLabel("Weekly report time").selectOption("18:15");
    await page.clock.fastForward(1000);
    await expect(page.locator("#schedule-weekly-help")).toHaveText("On — next report Thursday 1 Oct, 6:15 pm");
    await page.clock.fastForward(1000);
    expect(schedulePosts(posts)).toEqual([]);
});
test("a day or time change shows Saving until the save returns", async ({page}) => {
    await page.clock.install();
    const posts = await setup(page, {active:true, holdEnables:true});
    const help = page.locator("#schedule-weekly-help");
    await page.getByLabel("Weekly report time").selectOption("07:30");
    await expect(help).toHaveText("Saving…");
    await expect(help).not.toHaveClass(/analysis-hint-error/);
    await page.clock.fastForward(1000);
    await expect.poll(() => schedulePosts(posts).length).toBe(1);
    await expect(help).toHaveText("Saving…");
    posts.release();
    await expect(help).toHaveText("On — next report Thursday 1 Oct, 7:30 am");
});
test("industry label uses the catalog name from the API", async ({page}) => {
    await setup(page, {industry:{template_id:"beauty_salon", name:"Beauty salon & spa", confirmed_at:"2026-09-26T09:00:00Z"}});
    await expect(page.locator("#industry-label")).toHaveText("Beauty salon & spa");
});
