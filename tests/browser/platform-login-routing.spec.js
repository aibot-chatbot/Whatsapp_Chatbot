const { test, expect } = require('@playwright/test');
const { startServer } = require('./platform-admin-static-server');
let server, base;
test.beforeAll(async () => { server = await startServer(0); base = 'http://127.0.0.1:' + server.address().port; });
test.afterAll(async () => { if (server) await new Promise(resolve => server.close(resolve)); });

async function submitLogin(page, destination, returnTo) {
  const user = { id: 1, email: 'routing@example.test' };
  const role = destination === 'superadmin.html' ? 'super_admin' : 'admin';
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin !== base) return route.abort();
    if (url.pathname === '/api/auth/login') return route.fulfill({ json: {
      user, token: 'synthetic-routing-token', redirect_url: destination
    } });
    if (url.pathname.startsWith('/api/')) return route.fulfill({ json: { status: 'success', data:
      url.pathname.endsWith('/me') ? { user, platform_role: role, landing_page: destination,
        platform_admin: { id: 1, is_active: true }, modules: {} } : {}
    } });
    return route.continue();
  });
  await page.goto(base + '/login.html?returnTo=' + encodeURIComponent(returnTo));
  await page.locator('#login-form input[type=email]').fill(user.email);
  await page.locator('#login-password').fill('synthetic-password');
  await page.locator('#login-btn').click();
}

for (const landing of ['admin.html', 'superadmin.html']) {
  test(`login uses the authorized ${landing} despite a foreign returnTo`, async ({ page }) => {
    await submitLogin(page, landing, '//outside.invalid/ignore');
    await expect.poll(() => new URL(page.url()).pathname.replace(/\.html$/, ''))
      .toBe('/' + landing.replace('.html', ''));
    expect(new URL(page.url()).origin).toBe(base);
  });
}

test('login rejects a foreign server destination even with a local returnTo', async ({ page }) => {
  await submitLogin(page, '//outside.invalid/ignore', 'superadmin.html#customers?company=42');
  await expect(page.locator('#login-error')).toHaveText('Login could not be completed. Please try again.');
  expect(new URL(page.url()).origin).toBe(base);
  expect(await page.evaluate(() => sessionStorage.getItem('token'))).toBeNull();
});
