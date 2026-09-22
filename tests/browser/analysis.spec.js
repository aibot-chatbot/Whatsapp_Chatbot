const {test, expect} = require("@playwright/test");
const {startServer} = require("./platform-admin-static-server");
let server;
test.beforeAll(async () => { server = await startServer(); });
test.afterAll(async () => { await new Promise(resolve => server.close(resolve)); });
const id = "00000000-0000-4000-8000-000000000001";
async function setup(page, {role = "owner", disabled = false} = {}) {
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
        if (!path.includes("/analysis")) return respond({status:"success", data:{}});
        if (disabled) return respond({message:"Analysis is not enabled yet."}, 503);
        if (route.request().method() === "POST") {
            posts.push({path, body:route.request().postDataJSON()});
            return respond({data:path.endsWith("/messages") ? {id, status:"queued", request_text:posts.at(-1).body.text, created_at:"2026-09-22T10:00:00Z"} : {}},202);
        }
        if (path.endsWith("/messages")) return respond({data:[{id, status:"partial", request_text:"Analyze my restaurant requests", created_at:"2026-09-22T09:00:00Z"}], next_cursor:null});
        if (path.endsWith("/records")) return respond({data:[{id:1, action_type:"booking", status:"requested", conversation_id:9, created_at:"2026-09-22T09:00:00Z"}], next_cursor:null});
        if (path.endsWith("/schedules")) return respond({data:[]});
        if (path.endsWith("/recording")) return respond({data:{enabled:false}});
        if (path.includes("/reports/")) return respond({data:{id, status:"partial", request_text:"Analyze my restaurant requests", formats:[], snapshot:{metrics:[{label:"Revenue",status:"unavailable",value:null}], limitations:["Bookings system not connected."],customer_questions:{excerpts:[{message_id:901,conversation_id:9,text:"<img src=x>Can I book a table?"}]}},result:{narrative:"<img src=x onerror=alert(1)>Only an application was recorded."}}});
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
