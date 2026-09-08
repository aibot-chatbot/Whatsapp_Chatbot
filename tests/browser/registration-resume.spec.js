const { test, expect } = require('@playwright/test');
const { startServer } = require('./platform-admin-static-server');

let server, base;
test.beforeAll(async () => {
  server = await startServer(0);
  base = `http://127.0.0.1:${server.address().port}`;
});
test.afterAll(async () => {
  if (server) await new Promise(resolve => server.close(resolve));
});

const email = 'signup-resume@example.test';
const originalPassword = 'OriginalSynthetic1!';

for (const matches of [true, false]) {
  test(`fresh-browser pending signup ${matches ? 'resumes with original password' : 'rejects a different password'}`, async ({ page }) => {
    const submissions = [], unexpected = [];
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      // Only the loopback static server is reachable. Google/fonts stay offline.
      if (url.origin !== base) return route.abort();
      if (url.pathname === '/api/auth/google-config') {
        return route.fulfill({ status: 200, json: { enabled: false } });
      }
      if (url.pathname === '/api/auth/register' && request.method() === 'POST') {
        const payload = request.postDataJSON();
        submissions.push(payload);
        const accepted = payload.password === originalPassword;
        return route.fulfill({ status: accepted ? 200 : 409, json: accepted ? {
          status: 'success', code: 'registration_pending',
          message: 'Continue verification. Request a new code if the previous code expired.',
          data: { email },
        } : {
          status: 'error',
          message: 'A registration is already pending. Use the original registration password to continue.',
        } });
      }
      if (url.pathname.startsWith('/api/')) {
        unexpected.push(url.pathname);
        return route.fulfill({ status: 503, json: { status: 'error' } });
      }
      return route.continue();
    });

    await page.goto(`${base}/register.html`);
    expect(await page.evaluate(() => sessionStorage.getItem('pending_verification_email'))).toBeNull();
    await page.locator('#first_name').fill('Original');
    await page.locator('#last_name').fill('User');
    await page.locator('#company_name').fill('Synthetic Company');
    await page.locator('#email').fill(email);
    const password = matches ? originalPassword : 'DifferentSynthetic1!';
    await page.locator('#password').fill(password);
    await page.locator('#confirm_password').fill(password);
    await page.locator('#submit-btn').click();

    if (matches) {
      await expect(page).toHaveURL(`${base}/verify-email.html`);
      expect(await page.evaluate(() => sessionStorage.getItem('pending_verification_email'))).toBe(email);
      await expect(page.locator('#user-email')).toHaveText(email);
      await expect(page.locator('#resend-link')).toBeVisible();
    } else {
      await expect(page.locator('#general-error')).toContainText('original registration password');
      await expect(page).toHaveURL(`${base}/register.html`);
      expect(await page.evaluate(() => sessionStorage.getItem('pending_verification_email'))).toBeNull();
    }
    expect(submissions).toHaveLength(1);
    expect(submissions[0]).toMatchObject({ email, password, confirm_password: password });
    expect(unexpected).toEqual([]);
  });
}
