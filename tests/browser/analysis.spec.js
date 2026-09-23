const {test, expect} = require("@playwright/test");
const {startServer} = require("./platform-admin-static-server");
let server;
test.beforeAll(async () => { server = await startServer(); });
test.afterAll(async () => { await new Promise(resolve => server.close(resolve)); });
const id = "00000000-0000-4000-8000-000000000001";
async function setup(page, {role = "owner", disabled = false, automation = true, denyFeature = false, denyReads = false, distributions = [], active = false} = {}) {
    const posts = [];
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
        if (disabled) return respond({message:"Analysis is not enabled yet."}, 503);
        if (route.request().method() === "GET" && denyReads && (path.endsWith("/schedules") || path.endsWith("/recording"))) return respond({code:"feature_not_available", message:"The feature \"automation_workflows\" is not available on your current subscription plan."}, 403);
        if (route.request().method() === "POST" && denyFeature && path.endsWith("/schedules")) return respond({code:"feature_not_available", message:"The feature \"automation_workflows\" is not available on your current subscription plan."}, 403);
        if (route.request().method() === "POST") {
            posts.push({path, body:route.request().postDataJSON()});
            return respond({data:path.endsWith("/messages") ? {id, status:"queued", request_text:posts.at(-1).body.text, created_at:"2026-09-22T10:00:00Z"} : {}},202);
        }
        if (path.endsWith("/messages")) return respond({data:[{id, status:"partial", request_text:"Analyze my restaurant requests", created_at:"2026-09-22T09:00:00Z"}], next_cursor:null});
        if (path.endsWith("/records")) return respond({data:[{id:1, action_type:"booking", status:"requested", conversation_id:9, created_at:"2026-09-22T09:00:00Z"}], next_cursor:null});
        if (path.endsWith("/schedules")) return respond({data:active ? [{frequency:"weekly", enabled:true}] : []});
        if (path.endsWith("/recording")) return respond({data:{enabled:active}});
        if (path.includes("/reports/")) return respond({data:{id, status:"partial", request_text:"Analyze my restaurant requests", formats:[], snapshot:{metrics:[{label:"Revenue",status:"unavailable",value:null}], limitations:["Bookings system not connected."],distributions,customer_questions:{excerpts:[{message_id:901,conversation_id:9,text:"<img src=x>Can I book a table?"}]}},result:{narrative:"<img src=x onerror=alert(1)>Only an application was recorded."}}});
        return respond({data:{bot:{id:7,bot_name:"Laksa assistant"},industry:{template_id:"restaurant",confirmed_at:"2026-09-22T09:00:00Z"},role:{business_description:"Restaurant customer service"}}});
    });
    await page.goto("/analysis.html?bot_id=7");
    return posts;
}
test("industry context, request state, safe report rendering and schedule opt-in", async ({page}) => {
    const posts = await setup(page);
    await expect(page.locator("#send-report")).toBeEnabled();
    await expect(page.locator("#industry-label")).toHaveText("restaurant");
    await expect(page.locator("#business-records")).toContainText("requested");
    await expect(page.locator('[data-frequency="weekly"]')).not.toBeChecked();
    await page.getByRole("button", {name:"View details"}).click();
    await expect(page.locator("#report-content")).toContainText("Not connected / unavailable");
    await expect(page.locator("#report-content img")).toHaveCount(0);
    await expect(page.locator("#report-content")).toContainText("Only an application");
    await page.getByText("Customer question samples", {exact:true}).click();
    await expect(page.locator("#report-content")).toContainText("Message 901 · Conversation 9:");
    await expect(page.locator("#report-content img")).toHaveCount(0);
    await page.getByRole("button", {name:"Close report"}).click();
    await page.locator("#report-command").fill("生成餐厅上个月的预约申请报告");
    await page.getByRole("button", {name:"Generate report"}).click();
    await expect(page.locator("#report-thread")).toContainText("Queued");
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
    await expect(page.locator("#report-content")).toContainText("Limited coverage");
    await expect(page.locator("#report-content")).toContainText("unknown, not zero");
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
    await expect(notes.first().getByRole("link")).toHaveAttribute("href", "billing.html");
});
test("server plan denial shows an upgrade prompt instead of the raw message", async ({page}) => {
    await setup(page, {denyFeature:true});
    await expect(page.locator('[data-frequency="weekly"]')).toBeEnabled();
    await page.locator('[data-frequency="weekly"]').check();
    await expect(page.locator("#analysis-status")).toContainText("Pro plan");
    await expect(page.locator("#analysis-status")).not.toContainText("automation_workflows");
    await expect(page.locator("#analysis-status a")).toHaveAttribute("href", "billing.html");
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
    await expect(page.locator("#business-records")).toContainText("requested");
    await expect(page.locator('[data-frequency="weekly"]')).toBeDisabled();
    await expect(page.locator("#recording-enabled")).toBeDisabled();
    await expect(page.locator("[data-plan-lock]").first()).toBeVisible();
});
