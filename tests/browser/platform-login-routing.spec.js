const { test, expect } = require('@playwright/test');
const { startServer } = require('./platform-admin-static-server');
let server, base;
test.beforeAll(async () => { server = await startServer(0); base = 'http://127.0.0.1:' + server.address().port; });
test.afterAll(async () => { if (server) await new Promise(resolve => server.close(resolve)); });

for (const [role, landing, expected] of [
  ['admin', 'admin.html', '#customers/42'],
  ['super_admin', 'superadmin.html', '#customers?company=42'],
]) {
  test(`legacy company link retains record for ${role}`, async ({ page }) => {
    await page.addInitScript(() => sessionStorage.setItem('token', 'synthetic-routing-token'));
    await page.route('**/api/**', route => route.fulfill({
      contentType: 'application/json', status: 200,
      body: JSON.stringify({ status: 'success', data: {
        platform_role: role, landing_page: landing, modules: { billing: false, support: false, customers: true },
        user: { id: 1, email: 'routing@example.test' }, platform_admin: { id: 1, is_active: true },
      } }),
    }));
    await page.goto(base + '/platform-admin-company.html?company_id=42');
    await expect(page).toHaveURL(base + '/' + landing + expected);
  });
}

test('legacy link rejects invalid company IDs', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('token', 'synthetic-routing-token'));
  await page.route('**/api/**', route => route.fulfill({
    contentType: 'application/json', status: 200,
    body: JSON.stringify({ status: 'success', data: {
      platform_role: 'admin', landing_page: 'admin.html', modules: {}, user: { id: 1 }, platform_admin: { id: 1 },
    } }),
  }));
  await page.goto(base + '/platform-admin-company.html?company_id=42%2F..%2F%2Fevil.example');
  await expect(page).toHaveURL(base + '/admin.html#customers');
});
