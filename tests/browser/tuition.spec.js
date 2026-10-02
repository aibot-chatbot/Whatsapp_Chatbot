const {test, expect} = require("@playwright/test");
const path = require("path");
const os = require("os");
const {startServer} = require("./platform-admin-static-server");
let server, origin;
const uid = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const sessionToken = "web_0123456789abcdefghijklmn";
const participant = {id:uid(1), label:"Amy", version:1};
const session = {id:uid(2), class_id:uid(3), course_name:"Mathematics", class_name:"Year 5", starts_at:"2099-09-26T02:00:00Z", ends_at:"2099-09-26T03:00:00Z", total_capacity:10, enrolled_seats:8, trial_limit:2, available_trial_seats:2, version:3};
const booking = {id:uid(4), participant_id:participant.id, participant_label:"Amy", session_id:session.id, conversation_id:9, status:"confirmed", version:1};
const reply = (route, data, status = 200) => route.fulfill({status, contentType:"application/json", body:JSON.stringify(status === 200 || status === 201 ? {status:"success",data} : data)});
test.beforeAll(async () => { server = await startServer(0); origin = `http://127.0.0.1:${server.address().port}`; });
test.afterAll(async () => { await new Promise(resolve => server.close(resolve)); });

async function admin(page, industry = "tuition_center") {
    const posts = [], errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(() => {
        sessionStorage.setItem("token", "test-token");
        sessionStorage.setItem("user", JSON.stringify({id:31,company_id:42,role:"owner",status:"active"}));
        sessionStorage.setItem("selectedBotId", "7");
    });
    await page.route("https://fonts.googleapis.com/**", route => route.abort());
    await page.route("https://fonts.gstatic.com/**", route => route.abort());
    await page.route("**/api/**", route => {
        const pathname = new URL(route.request().url()).pathname;
        if (pathname.includes("/api/bots/")) return reply(route, {id:7,bot_name:"Learning assistant"});
        if (pathname.includes("/tuition/")) {
            if (route.request().method() === "POST") { posts.push({path:pathname,body:route.request().postDataJSON()}); return reply(route, {}); }
            return reply(route, {courses:[{id:uid(5),name:"Mathematics"}],classes:[{id:uid(3),name:"Year 5"}],sessions:[session],bookings:[booking]});
        }
        if (pathname.endsWith("/analysis")) return reply(route, {bot:{id:7,bot_name:"Learning assistant"},industry:{template_id:industry,confirmed_at:"2026-09-22T09:00:00Z"},role:{business_description:"Customer service"}});
        if (pathname.endsWith("/recording")) return reply(route, {enabled:false});
        return reply(route, []);
    });
    await page.goto(origin + "/analysis.html?bot_id=7");
    await expect(page.locator("#send-report")).toBeEnabled();
    return {posts,errors};
}

async function guest(page, {disabled = false, existing = false} = {}) {
    const world = {calls:[],bookings:existing ? [{...booking}] : [],participants:[{...participant}],errors:[],conflict:false,handoff:false,loseParticipantResponse:false};
    page.on("pageerror", error => world.errors.push(error.message));
    await page.route("**/chat/*", route => route.fulfill({path:path.resolve(__dirname,"../../frontend/widget-chat.html"),contentType:"text/html"}));
    await page.route("**/api/widget/**", async route => {
        const endpoint = new URL(route.request().url()).pathname.split("/").at(-1);
        if (endpoint === "config") return reply(route,{display_name:"Learning assistant",welcome_message:"Welcome",suggested_questions:[]});
        if (endpoint === "session") return reply(route,{session_id:sessionToken});
        if (endpoint === "messages") return reply(route,{messages:[],last_message_id:0,has_more:false,awaiting_human:false});
        if (endpoint !== "tuition") throw new Error("Unexpected endpoint " + endpoint);
        const body = route.request().postDataJSON(); world.calls.push(body);
        expect(body.session_id_token).toBe(sessionToken);
        expect(body.company_id).toBeUndefined(); expect(body.chatbot_id).toBeUndefined(); expect(body.confirmed).toBeUndefined();
        if (disabled) return reply(route,{code:"tuition_disabled",message:"Not enabled"},503);
        if (body.action === "list") return reply(route,{sessions:[session,{...session,id:uid(6),class_name:"Year 6"}],participants:world.participants,bookings:world.bookings,reminders_supported:false});
        if (world.handoff) return reply(route,{code:"tuition_human_controlled",message:"A staff member must handle this conversation."},409);
        if (body.action === "participant") {
            if (world.loseParticipantResponse) { world.loseParticipantResponse = false; return route.abort("failed"); }
            const row = {id:uid(7),label:body.label,version:1}; world.participants.push(row); return reply(route,row);
        }
        if (body.action === "prepare") return reply(route,{confirmation_token:"one-time-server-token",expires_at:"2099-09-25T00:00:00Z",participant:world.participants.find(row => row.id === body.participant_id),session:{...session,id:body.session_id},reserved:false});
        if (body.action === "confirm") {
            expect(Object.keys(body).sort()).toEqual(["action","confirmation_token","session_id_token"]);
            if (world.conflict) return reply(route,{code:"tuition_conflict",message:"No available places"},409);
            world.bookings = [{...booking}]; return reply(route,{booking:world.bookings[0],session});
        }
        if (body.action === "cancel") {
            if (body.expected_version !== world.bookings[0].version) return reply(route,{code:"tuition_conflict",message:"Booking changed"},409);
            world.bookings = [{...booking,status:"cancelled"}]; return reply(route,world.bookings[0]);
        }
        throw new Error("Unexpected action " + body.action);
    });
    await page.goto(origin + "/chat/wgt_tuition_test");
    await expect(page.locator("#input")).toBeEnabled();
    await expect.poll(() => world.calls.length).toBeGreaterThan(0);
    return world;
}

test("administrator creates catalogue and sessions in Kuala Lumpur time and updates versioned capacity", async ({page}) => {
    const world = await admin(page);
    await page.getByRole("button",{name:"Manage trial lessons"}).click();
    await expect(page.locator("#tuition-bookings")).toContainText(booking.id);
    await page.locator("#tuition-course-form input").fill("Science");
    await page.locator("#tuition-course-form button").click();
    await expect(page.locator("#tuition-status")).toHaveText("Course added.");
    await expect(page.locator("#tuition-course-form button")).toBeFocused();
    await page.locator("#tuition-class-form select").selectOption(uid(5));
    await page.locator("#tuition-class-form input").fill("Year 6");
    await page.locator("#tuition-class-form button").click();
    await expect(page.locator("#tuition-status")).toHaveText("Class added.");
    const form = page.locator("#tuition-session-form");
    await form.locator("select").selectOption(uid(3));
    await form.locator('[name="starts_at"]').fill("2099-09-26T10:00");
    await form.locator('[name="ends_at"]').fill("2099-09-26T11:00");
    await form.locator('[name="total_capacity"]').fill("10");
    await form.locator('[name="enrolled_seats"]').fill("8");
    await form.locator('[name="trial_limit"]').fill("2");
    await form.getByRole("button").click();
    await expect(page.locator("#tuition-status")).toHaveText("Session added.");
    expect(world.posts[2].body).toEqual({kind:"session",class_id:uid(3),starts_at:"2099-09-26T10:00:00+08:00",ends_at:"2099-09-26T11:00:00+08:00",total_capacity:10,enrolled_seats:8,trial_limit:2});
    await page.locator('#tuition-sessions [name="trial_limit"]').fill("1");
    await page.getByRole("button",{name:"Save capacity"}).click();
    await expect(page.locator("#tuition-status")).toHaveText("Capacity updated.");
    await expect(page.getByRole("button",{name:"Save capacity"})).toBeFocused();
    expect(world.posts[3].body).toEqual({expected_version:3,total_capacity:10,enrolled_seats:8,trial_limit:1});
    expect(world.posts.every(row => row.body.company_id === undefined)).toBe(true);
    expect(world.errors).toEqual([]);
    await page.locator("#tuition-dialog").evaluate(node => { node.scrollTop = 0; });
    await page.screenshot({path:path.join(os.tmpdir(),"tuition-admin-desktop.png")});
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator("#tuition-dialog").evaluate(node => { node.scrollTop = 0; });
    await page.screenshot({path:path.join(os.tmpdir(),"tuition-admin-mobile.png")});
});

test("non-tuition industry does not get trial management", async ({page}) => {
    await admin(page,"restaurant");
    await expect(page.locator("#manage-trials")).toBeHidden();
});

test("guest listing is read-only; explicit review and confirm reserve a place; cancellation requires confirmation", async ({page}) => {
    const world = await guest(page);
    await page.getByRole("button",{name:"Book a trial lesson"}).click();
    await expect(page.locator("#trial-status")).toContainText("Choose a participant");
    expect(world.calls.every(row => row.action === "list")).toBe(true);
    await page.getByLabel("Participant",{exact:true}).selectOption(participant.id);
    await page.getByLabel("Trial session",{exact:true}).selectOption(session.id);
    await page.getByRole("button",{name:"Review booking"}).click();
    await expect(page.locator("#trial-review")).toContainText("No place reserved yet");
    await expect(page.locator("#trial-confirm")).toBeFocused();
    expect(world.calls.some(row => row.action === "confirm")).toBe(false);
    await page.getByRole("button",{name:"Confirm booking",exact:true}).click();
    await expect(page.locator("#trial-status")).toContainText("Booking confirmed. Reference: " + booking.id);
    await expect(page.locator("#trial-bookings")).toContainText("confirmed");
    await page.getByRole("button",{name:"Cancel booking",exact:true}).click();
    expect(world.calls.some(row => row.action === "cancel")).toBe(false);
    await page.getByRole("button",{name:"Confirm cancellation"}).click();
    await expect(page.locator("#trial-status")).toContainText("Booking cancelled");
    expect(world.calls.find(row => row.action === "cancel").client_message_id).toMatch(/^[a-f0-9-]{36}$/);
    expect(world.calls.find(row => row.action === "cancel").expected_version).toBe(booking.version);
    expect(world.errors).toEqual([]);
});

test("full reschedule preserves original booking and human control blocks confirmation", async ({page}) => {
    const world = await guest(page,{existing:true});
    await page.getByRole("button",{name:"Book a trial lesson"}).click();
    await page.getByRole("button",{name:"Change session"}).click();
    await page.getByLabel("Trial session",{exact:true}).selectOption(uid(6));
    await page.getByRole("button",{name:"Review booking"}).click();
    await expect(page.locator("#trial-review")).toBeVisible();
    world.conflict = true;
    await page.getByRole("button",{name:"Confirm new session"}).click();
    await expect(page.locator("#trial-status")).toContainText("Your original booking is unchanged");
    await expect(page.locator("#trial-bookings")).toContainText(booking.id);
    expect(world.calls.some(row => row.action === "cancel")).toBe(false);
    expect(world.calls.find(row => row.action === "prepare").booking_id).toBe(booking.id);
    world.handoff = true;
    await page.getByRole("button",{name:"Review booking"}).click();
    await expect(page.locator("#trial-status")).toContainText("A staff member is handling");
    await expect(page.locator("#trial-prepare")).toBeDisabled();
});

test("participant retries use the same key, labels render safely and mobile has no overflow", async ({page}) => {
    await page.setViewportSize({width:390,height:844});
    const world = await guest(page); world.loseParticipantResponse = true;
    await page.getByRole("button",{name:"Book a trial lesson"}).click();
    await page.getByLabel("New participant name").fill('<img src=x onerror="alert(1)">');
    await page.getByRole("button",{name:"Add participant"}).click();
    await expect(page.locator("#trial-status")).toContainText("Failed to fetch");
    await page.getByRole("button",{name:"Add participant"}).click();
    await expect(page.locator("#trial-status")).toContainText("Participant added");
    expect(world.calls.filter(row => row.action === "participant").map(row => row.client_key)[0]).toBe(world.calls.filter(row => row.action === "participant")[1].client_key);
    await page.getByLabel("Trial session",{exact:true}).selectOption(session.id);
    await page.getByRole("button",{name:"Review booking"}).click();
    await expect(page.locator("#trial-review-details")).toContainText('<img src=x onerror="alert(1)">');
    await expect(page.locator("#trial-review-details img")).toHaveCount(0);
    await expect(page.locator("#trial-dialog")).toContainText("reminders are not available");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.getElementById("trial-dialog").scrollWidth <= document.getElementById("trial-dialog").clientWidth)).toBe(true);
    expect(world.errors).toEqual([]);
    await page.screenshot({path:path.join(os.tmpdir(),"tuition-guest-mobile.png"),fullPage:true});
});

test("disabled capability has no customer entry", async ({page}) => {
    await guest(page,{disabled:true});
    await expect(page.locator("#trial-entry")).toBeHidden();
    await expect(page.locator("#input")).toBeEnabled();
});

test("stale cancellation confirmation leaves the changed booking intact", async ({page}) => {
    const world = await guest(page,{existing:true});
    await page.getByRole("button",{name:"Book a trial lesson"}).click();
    await page.getByRole("button",{name:"Cancel booking",exact:true}).click();
    world.bookings[0] = {...world.bookings[0],version:2,session_id:uid(6)};
    await page.getByRole("button",{name:"Confirm cancellation"}).click();
    await expect(page.locator("#trial-status")).toContainText("Review the latest sessions");
    expect(world.calls.find(row => row.action === "cancel").expected_version).toBe(1);
    expect(world.bookings[0]).toMatchObject({status:"confirmed",version:2,session_id:uid(6)});
});
