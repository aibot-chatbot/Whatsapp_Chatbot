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
const freshHealth = {
    ready: false, profile: { active: false }, knowledge: { active: false, match_result: null },
    channels: { connected_count: 0, items: [] }, warnings: []
};
const json = data => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'success', data }) });

async function prepare(page, role = 'owner', health = freshHealth) {
    await page.addInitScript(value => {
        sessionStorage.setItem('token', 'fake-test-token');
        sessionStorage.setItem('isLoggedIn', 'true');
        sessionStorage.setItem('user', JSON.stringify({ id: 1, company_id: 12, role: value }));
    }, role);
    await page.route('https://**', route => route.abort());
    await page.route('**/api/**', route => {
        const path = new URL(route.request().url()).pathname;
        if (path === '/api/billing/usage') return route.fulfill(json({ usage: { chatbots: { used: 1, limit: 3 } } }));
        if (path === '/api/bots') return route.fulfill(json([bot]));
        if (path === '/api/bots/42') return route.fulfill(json(bot));
        if (path === '/api/dashboard/health') return route.fulfill(json(health));
        if (path === '/api/analytics') return route.fulfill(json({ total_users: 0, total_messages: 0, chart: { labels: [], data: [] }, recent_history: [] }));
        if (path === '/api/platform-admin/me') return route.fulfill({ status: 403, contentType: 'application/json', body: '{}' });
        return route.fulfill(json({}));
    });
}

test('create form focuses missing name and preserves details after a failed request', async ({ page }) => {
    await prepare(page);
    let submissions = 0;
    let release;
    await page.route('**/api/bots', async route => {
        if (route.request().method() !== 'POST') return route.fallback();
        submissions += 1;
        await new Promise(resolve => { release = resolve; });
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ status: 'error', message: 'Try again when the connection returns.' }) });
    });
    await page.goto(`${origin}/bots.html`, { waitUntil: 'domcontentloaded' });
    await page.locator('.header [data-create-bot-trigger]').click();
    await page.locator('#submit-create-btn').click();
    await expect(page.locator('#bot-name')).toBeFocused();
    await expect(page.locator('#bot-name')).toHaveAttribute('aria-invalid', 'true');
    expect(submissions).toBe(0);
    await page.locator('#bot-name').fill('Bakery helper');
    await page.locator('#bot-description').fill('Answers menu questions');
    await page.locator('#bot-name').press('Enter');
    await expect(page.locator('#bot-details-form')).toHaveAttribute('aria-busy', 'true');
    await expect(page.locator('#submit-create-btn')).toBeDisabled();
    await page.evaluate(() => createBot());
    await expect.poll(() => submissions).toBe(1);
    release();
    await expect(page.locator('#bot-form-error')).toHaveText('Try again when the connection returns.');
    await expect(page.locator('#bot-name')).toHaveValue('Bakery helper');
    await expect(page.locator('#bot-description')).toHaveValue('Answers menu questions');
    await expect(page.locator('#submit-create-btn')).toBeEnabled();
});

test('existing bots have a keyboard link and account belongs to the workspace footer', async ({ page }) => {
    await prepare(page);
    await page.goto(`${origin}/bots.html`);
    const link = page.getByRole('link', { name: 'Open bot: Bakery support' });
    await expect(link).toHaveAttribute('href', 'index.html?bot_id=42');
    await expect(page.locator('.side-rail nav tenant-account-menu')).toHaveCount(0);
    await expect(page.locator('.rail-footer tenant-account-menu')).toHaveCount(1);
    await link.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/index\.html\?bot_id=42$/);
});

test('new-bot overview chooses knowledge first and keeps reports available on demand', async ({ page }) => {
    await prepare(page);
    await page.goto(`${origin}/index.html?bot_id=42&setup=1`);
    await expect(page.locator('#dash-next-cta')).toHaveText(/Add knowledge/);
    await expect(page.locator('#dash-next-cta')).toHaveAttribute('href', 'new_linkdocs.html?bot_id=42&setup=1');
    await expect(page.locator('#dashboard-setup-journey [aria-current="step"]')).toHaveText('1Add knowledge');
    await expect(page.locator('#dash-monitoring')).not.toHaveAttribute('open');
    await page.locator('#dash-monitoring > summary').click();
    await expect(page.locator('#stat-total-users')).toBeVisible();
    await expect(page.locator('#stat-total-users')).toHaveText('0');
});

test('validated instructions lead to testing before publishing without claiming a test passed', async ({ page }) => {
    await prepare(page, 'owner', {
        ...freshHealth, profile: { active: true, name: 'Support' },
        knowledge: { active: true, file_name: 'Menu.pdf', match_result: true }
    });
    await page.goto(`${origin}/index.html?bot_id=42&setup=1`);
    await expect(page.locator('#dash-next-cta')).toHaveAttribute('href', 'testbot.html?bot_id=42&setup=1');
    await expect(page.locator('#dashboard-setup-journey [aria-current="step"]')).toHaveText('3Test replies');
    await expect(page.locator('#dashboard-setup-journey .is-done')).toHaveCount(0);
});

test('selected-bot navigation preserves setup scope and keeps account in a short viewport', async ({ page }) => {
    await page.setViewportSize({ width: 1692, height: 748 });
    await prepare(page);
    await page.goto(`${origin}/index.html?bot_id=42&setup=1`);
    const sidebar = page.locator('chatbot-sidebar');
    await expect(sidebar.locator('.sidebar-context-name')).toHaveText('Bakery support');
    await expect(sidebar.getByRole('link', { name: 'Bot instructions', exact: true })).toHaveAttribute('href', 'new_prompt.html?bot_id=42&setup=1');
    await expect(sidebar.getByRole('link', { name: 'Overview', exact: true })).toHaveAttribute('aria-current', 'page');
    await sidebar.locator('summary').click();
    await expect(sidebar.locator('summary')).toHaveAttribute('aria-expanded', 'true');
    const box = await sidebar.locator('.sidebar-account').boundingBox();
    expect(box.y + box.height).toBeLessThanOrEqual(748);
    expect(box.y).toBeGreaterThan(0);
    await page.setViewportSize({ width: 1440, height: 900 });
    const taller = await sidebar.locator('.sidebar-account').boundingBox();
    expect(taller.y + taller.height).toBeLessThanOrEqual(900);
});

test('mobile bot navigation stays operable and keeps owner controls out of member navigation', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await prepare(page, 'member');
    await page.goto(`${origin}/index.html?bot_id=42`);
    const sidebar = page.locator('chatbot-sidebar');
    await expect(sidebar.locator('.nav-list')).toBeHidden();
    await sidebar.getByRole('button', { name: 'Open menu' }).click();
    await expect(sidebar.locator('.sidebar-account')).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Bot instructions', exact: true })).toHaveCount(0);
    await expect(sidebar.getByRole('link', { name: 'Publish', exact: true })).toHaveCount(0);
    await sidebar.locator('summary').click();
    await expect(sidebar.getByRole('link', { name: 'Campaigns', exact: true })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBe(0);
});
