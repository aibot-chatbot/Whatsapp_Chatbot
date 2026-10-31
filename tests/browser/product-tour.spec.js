const { expect, test } = require('@playwright/test');
const { startServer } = require('./platform-admin-static-server');
test.setTimeout(30000);

let server;
let origin;
test.beforeAll(async () => {
    server = await startServer(0);
    origin = `http://127.0.0.1:${server.address().port}`;
});
test.afterAll(async () => { if (server) await new Promise(resolve => server.close(resolve)); });

const bot = { id: 42, bot_name: 'Bakery support', language: 'English', is_active: true };
const json = data => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'success', data }) });

async function prepare(page, { role = 'owner', bots = [], language = null } = {}) {
    await page.addInitScript(({ role, language }) => {
        sessionStorage.setItem('token', 'fake-test-token');
        sessionStorage.setItem('isLoggedIn', 'true');
        sessionStorage.setItem('user', JSON.stringify({ id: 1, company_id: 12, role }));
        if (language) localStorage.setItem('omnexa-language', language);
    }, { role, language });
    await page.route('https://**', route => route.abort());
    await page.route('**/api/**', route => {
        const path = new URL(route.request().url()).pathname;
        if (path === '/api/billing/usage') return route.fulfill(json({ usage: { chatbots: { used: bots.length, limit: 3 } } }));
        if (path === '/api/bots' && route.request().method() === 'POST') return route.fulfill(json(bot));
        if (path === '/api/bots') return route.fulfill(json(bots));
        if (path === '/api/bots/42') return route.fulfill(json(bot));
        if (path === '/api/dashboard/health') return route.fulfill(json({
            ready: false, profile: { active: false }, knowledge: { active: false, match_result: null },
            channels: { connected_count: 0, items: [] }, warnings: []
        }));
        if (path === '/api/platform-admin/me') return route.fulfill({ status: 403, contentType: 'application/json', body: '{}' });
        return route.fulfill(json({}));
    });
}

const tourStep = (page, title) => page.getByRole('dialog', { name: title });

test('a new owner is greeted on My bots and taught one step at a time', async ({ page }) => {
    await prepare(page);
    await page.goto(`${origin}/bots.html`);

    const welcome = tourStep(page, 'Welcome to Omnexa');
    await expect(welcome).toBeVisible();
    await expect(welcome.locator('.product-tour-count')).toHaveText('1 / 10');
    await expect(welcome.getByRole('button', { name: 'Back' })).toHaveCount(0);
    await welcome.getByRole('button', { name: 'Start tour' }).click();

    const create = tourStep(page, 'Create your first bot');
    await expect(create).toBeVisible();
    await expect(welcome).toHaveCount(0);
    await expect(create.locator('.product-tour-count')).toHaveText('2 / 10');
    // Every page after this one needs a bot, so this step waits for the user instead of offering Next.
    await expect(create.getByRole('button', { name: 'Next' })).toHaveCount(0);
    await expect(create.getByText('Do this step to continue.')).toBeVisible();

    const ring = await page.locator('.product-tour-ring').boundingBox();
    const button = await page.locator('.empty-state [data-create-bot-trigger]').boundingBox();
    expect(ring.x).toBeLessThanOrEqual(button.x);
    expect(ring.y).toBeLessThanOrEqual(button.y);
    expect(ring.x + ring.width).toBeGreaterThanOrEqual(button.x + button.width);
    expect(ring.y + ring.height).toBeGreaterThanOrEqual(button.y + button.height);
});

test('the tour steps aside while the bot is created, then carries on page by page', async ({ page }) => {
    await prepare(page);
    await page.goto(`${origin}/bots.html`);
    await tourStep(page, 'Welcome to Omnexa').getByRole('button', { name: 'Start tour' }).click();
    await expect(tourStep(page, 'Create your first bot')).toBeVisible();

    await page.locator('.empty-state [data-create-bot-trigger]').click();
    await expect(page.getByRole('dialog', { name: 'Name your bot' })).toBeVisible();
    // Nothing stays on screen to cover the form.
    await expect(page.locator('.product-tour, .product-tour-ring')).toHaveCount(0);
    await page.locator('#bot-name').fill('Bakery support');
    await page.locator('#submit-create-btn').click();

    // The app sends a new bot to Add knowledge. The CDN React that page needs is blocked
    // here, so this also proves a step whose target never renders still appears, centered.
    await expect(page).toHaveURL(/new_linkdocs\.html\?bot_id=42&setup=1$/);
    const knowledge = tourStep(page, 'Add knowledge');
    await expect(knowledge).toBeVisible({ timeout: 8000 });
    await expect(knowledge.locator('.product-tour-count')).toHaveText('3 / 10');
    await knowledge.getByRole('button', { name: 'Next' }).click();

    await expect(page).toHaveURL(/new_prompt\.html\?setup=1&bot_id=42$/);
    await expect(tourStep(page, 'Review the instructions').locator('.product-tour-count')).toHaveText('4 / 10');
    await tourStep(page, 'Review the instructions').getByRole('button', { name: 'Next' }).click();

    await expect(page).toHaveURL(/behaviour\.html\?tab=test&setup=1&bot_id=42$/);
    const testReply = tourStep(page, 'Test a reply');
    await expect(testReply).toBeVisible();
    await expect(testReply).toBeFocused();
    await testReply.getByRole('button', { name: 'Back' }).click();
    await expect(page).toHaveURL(/new_prompt\.html\?setup=1&bot_id=42$/);
    await expect(tourStep(page, 'Review the instructions')).toBeVisible();
});

test('skipping the tour ends it for good', async ({ page }) => {
    await prepare(page);
    await page.goto(`${origin}/bots.html`);
    await tourStep(page, 'Welcome to Omnexa').getByRole('button', { name: 'Skip tour' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    await page.reload();
    await expect(page.locator('#visible-bot-count')).toHaveText('0');
    await expect(page.locator('.empty-state [data-create-bot-trigger]')).toBeVisible();
    await expect(page.locator('.product-tour, .product-tour-ring')).toHaveCount(0);
});

async function openBotFromHelp(page) {
    await page.goto(`${origin}/bots.html`);
    await expect(page.locator('#visible-bot-count')).toHaveText('1');
    await expect(page.locator('.product-tour, .product-tour-ring')).toHaveCount(0);
    await page.getByRole('button', { name: 'Help: take the product tour' }).click();
    await tourStep(page, 'Welcome to Omnexa').getByRole('button', { name: 'Start tour' }).click();
    await expect(tourStep(page, 'Open a bot')).toBeVisible();
    await page.getByRole('link', { name: 'Open bot: Bakery support' }).click();
    await expect(page).toHaveURL(/index\.html\?bot_id=42$/);
}

test('owners who already have bots start the tour from Help and it follows them into the bot', async ({ page }) => {
    await prepare(page, { bots: [bot] });
    await openBotFromHelp(page);

    // Opening a bot lands on the Overview, so the Overview is taught next.
    const nextStep = tourStep(page, 'Your next step');
    await expect(nextStep.locator('.product-tour-count')).toHaveText('3 / 10');
    await nextStep.getByRole('button', { name: 'Next' }).click();
    await expect(tourStep(page, 'Check your setup').locator('.product-tour-count')).toHaveText('4 / 10');
});

test('clicking the page puts the card away, and the next page opened teaches its own step', async ({ page }) => {
    await prepare(page, { bots: [bot] });
    await page.goto(`${origin}/bots.html`);
    await expect(page.locator('#visible-bot-count')).toHaveText('1');
    await page.getByRole('button', { name: 'Help: take the product tour' }).click();
    await expect(tourStep(page, 'Welcome to Omnexa')).toBeVisible();

    // Opening a bot without pressing Start still counts the bot step as done.
    await page.getByRole('link', { name: 'Open bot: Bakery support' }).click();
    await expect(page).toHaveURL(/index\.html\?bot_id=42$/);
    await expect(tourStep(page, 'Your next step').locator('.product-tour-count')).toHaveText('3 / 10');

    await page.locator('#dashboard-title').click();
    await expect(page.locator('.product-tour, .product-tour-ring')).toHaveCount(0);

    // A put-away card is not shown again; the page's next unseen step is.
    await page.reload();
    await expect(tourStep(page, 'Check your setup').locator('.product-tour-count')).toHaveText('4 / 10');
    await page.locator('#dashboard-title').click();
    await expect(page.locator('.product-tour, .product-tour-ring')).toHaveCount(0);

    // The user moves on by themselves, as guided setup's own buttons do.
    await page.goto(`${origin}/behaviour.html?tab=test&bot_id=42`);
    await expect(tourStep(page, 'Test a reply').locator('.product-tour-count')).toHaveText('5 / 10');
});

test('the tour speaks the language chosen for the dashboard', async ({ page }) => {
    await prepare(page, { language: 'ms' });
    await page.goto(`${origin}/bots.html`);
    const welcome = tourStep(page, 'Selamat datang ke Omnexa');
    await expect(welcome).toBeVisible();
    await welcome.getByRole('button', { name: 'Mulakan lawatan' }).click();
    const create = tourStep(page, 'Cipta bot pertama anda');
    await expect(create.getByText('Lakukan langkah ini untuk meneruskan.')).toBeVisible();
    await expect(create.getByRole('button', { name: 'Langkau lawatan' })).toBeVisible();
});

test('members are only shown the steps they can use', async ({ page }) => {
    await prepare(page, { role: 'member', bots: [bot] });
    await page.goto(`${origin}/bots.html`);
    await expect(page.locator('#visible-bot-count')).toHaveText('1');
    await page.getByRole('button', { name: 'Help: take the product tour' }).click();
    await expect(tourStep(page, 'Welcome to Omnexa').locator('.product-tour-count')).toHaveText('1 / 7');
});
