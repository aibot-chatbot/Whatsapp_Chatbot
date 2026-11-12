const { expect, test } = require('@playwright/test');
const path = require('path');
const { startServer } = require('./platform-admin-static-server');

let server;
let origin;
const SESSION = 'web_0123456789abcdefghijklmn';
const human = (id, text = `Staff reply ${id}`) => ({ id, message_text: text, sender_type: 'human', created_at: '2026-09-22T08:00:00Z' });
const pageOf = (messages = [], extra = {}) => ({ messages, last_message_id: messages.at(-1)?.id || 0, has_more: false, awaiting_human: true, ...extra });
const ok = data => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'success', data }) });

test.beforeAll(async () => {
  server = await startServer(0);
  origin = `http://127.0.0.1:${server.address().port}`;
});
test.afterAll(async () => { if (server) await new Promise(resolve => server.close(resolve)); });

async function openWidget(page, world = {}) {
  world.polls = [];
  world.sessions = 0;
  world.sent = [];
  await page.clock.install();
  await page.route('**/chat/*', route => route.fulfill({ path: path.resolve(__dirname, '../../frontend/widget-chat.html'), contentType: 'text/html' }));
  await page.route('**/api/widget/**', async route => {
    const url = new URL(route.request().url());
    const endpoint = url.pathname.split('/').at(-1);
    if (endpoint === 'config') return route.fulfill(ok({ display_name: 'Example shop', subtitle: 'Our custom subtitle', welcome_message: 'Welcome', suggested_questions: [] }));
    if (endpoint === 'session') {
      world.sessions += 1;
      return route.fulfill(ok({ session_id: SESSION }));
    }
    if (endpoint === 'tuition') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 'tuition_disabled' }) });
    const body = route.request().postDataJSON();
    expect(route.request().method()).toBe('POST');
    expect(url.search).toBe('');
    expect(body.session_id).toBe(SESSION);
    if (endpoint === 'messages') {
      world.polls.push(body);
      if (world.poll) return world.poll(route, body, world.polls.length);
      return route.fulfill(ok(pageOf([], { last_message_id: body.after_id })));
    }
    if (endpoint === 'message') {
      world.sent.push(body);
      if (world.send) return world.send(route, body);
      return route.fulfill(ok({ reply: 'An AI reply' }));
    }
    throw new Error(`Unmocked widget endpoint: ${endpoint}`);
  });
  await page.goto(`${origin}/chat/wgt_staff_test`);
  await expect(page.locator('#input')).toBeEnabled();
  return world;
}

test('visitor receives paginated staff replies once as safe text with a team label', async ({ page }) => {
  const unsafe = '<img src=x onerror="window.staffXss=true"> Hello';
  const world = await openWidget(page, {
    poll: (route, body) => route.fulfill(ok(body.after_id === 0
      ? pageOf([human(1, unsafe)], { has_more: true })
      : pageOf([human(1, unsafe), human(2)])))
  });
  await expect(page.locator('#log .msg.human')).toHaveCount(2);
  await expect(page.locator('#log .msg.human').first()).toContainText('Support team');
  await expect(page.locator('#log .msg.human').first()).toContainText(unsafe);
  await expect(page.locator('#log img')).toHaveCount(0);
  expect(await page.evaluate(() => window.staffXss)).toBeUndefined();
  await expect(page.locator('#subtitle')).toHaveText('Our custom subtitle');
  await expect(page.locator('#handoff-status')).toContainText('support team');
  expect(world.polls.slice(0, 2).map(body => body.after_id)).toEqual([0, 1]);
});

test('refresh restores the same session, chat history and staff cursor', async ({ page }) => {
  const world = await openWidget(page, { poll: (route, body) => route.fulfill(ok(pageOf(body.after_id ? [] : [human(7)], { last_message_id: 7 }))) });
  await expect(page.locator('#log .msg.human')).toHaveCount(1);
  await page.locator('#input').fill('Can someone help?');
  await page.locator('#send').click();
  await expect(page.locator('#log')).toContainText('An AI reply');
  await page.reload();
  await expect(page.locator('#input')).toBeEnabled();
  await expect.poll(() => world.polls.at(-1)?.after_id).toBe(7);
  expect(world.sessions).toBe(1);
  await expect(page.locator('#log .msg.human')).toHaveCount(1);
  await expect(page.locator('#log .msg.user')).toHaveText('Can someone help?');
  await expect(page.locator('#log')).toContainText('An AI reply');
  await expect(page.locator('#log .msg.bot').filter({ hasText: 'Welcome' })).toHaveCount(1);
});

test('poll failure preserves messages and cursor and recovers without error bubbles', async ({ page }) => {
  const world = await openWidget(page, { poll: (route, body, call) => call === 2
    ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ status: 'error', message: 'Temporary failure' }) })
    : route.fulfill(ok(pageOf([human(call === 1 ? 7 : 8)]))) });
  await expect(page.locator('#log .msg.human')).toHaveCount(1);
  await page.clock.runFor(3000);
  await expect(page.locator('#connection-status')).toContainText('Reconnecting');
  await expect(page.locator('#log .msg.human')).toHaveCount(1);
  await expect(page.locator('#log .msg.error')).toHaveCount(0);
  await page.clock.runFor(3000);
  await expect(page.locator('#log .msg.human')).toHaveCount(2);
  await expect(page.locator('#connection-status')).toBeEmpty();
  expect(world.polls.map(body => body.after_id)).toEqual([0, 7, 7]);
});

test('polling stays singleflight while a customer send and focus events overlap', async ({ page }) => {
  let finishPoll;
  let finishSend;
  const world = await openWidget(page, {
    poll: async (route, body, call) => {
      if (call === 1) await new Promise(resolve => { finishPoll = resolve; });
      return route.fulfill(ok(pageOf([human(1)])));
    },
    send: async route => {
      await new Promise(resolve => { finishSend = resolve; });
      return route.fulfill(ok({ reply: '', handled_by: 'human' }));
    }
  });
  await expect.poll(() => world.polls.length).toBe(1);
  await page.locator('#input').fill('I need help');
  await page.locator('#send').click();
  await expect.poll(() => world.sent.length).toBe(1);
  await page.evaluate(() => { for (let i = 0; i < 4; i++) window.dispatchEvent(new Event('focus')); });
  await page.clock.runFor(9000);
  expect(world.polls).toHaveLength(1);
  finishPoll();
  await expect(page.locator('#log .msg.human')).toHaveCount(1);
  await page.clock.runFor(3000);
  await expect.poll(() => world.polls.length).toBeGreaterThan(1);
  finishSend();
  await expect(page.locator('#input')).toBeEnabled();
  await expect(page.locator('#log .msg.human')).toHaveCount(1);
  await expect(page.locator('#log .msg.user')).toHaveCount(1);
});

test('hidden pages poll every 15 seconds and pagehide stops until pageshow', async ({ page }) => {
  const world = await openWidget(page);
  await expect.poll(() => world.polls.length).toBe(1);
  await expect(page.locator('#handoff-status')).toContainText('support team');
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(14000);
  expect(world.polls).toHaveLength(1);
  await page.clock.runFor(1000);
  await expect.poll(() => world.polls.length).toBe(2);
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect.poll(() => world.polls.length).toBe(3);
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
  await page.clock.runFor(45000);
  expect(world.polls).toHaveLength(3);
  await page.evaluate(() => window.dispatchEvent(new Event('pageshow')));
  await expect.poll(() => world.polls.length).toBe(4);
});

for (const code of ['invalid_session', 'widget_disabled']) {
  test(`${code} stops polling and retains the session instead of opening a new chat`, async ({ page }) => {
    const world = await openWidget(page, { poll: (route, body, call) => call === 1
      ? route.fulfill(ok(pageOf([human(1)])))
      : route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ status: 'error', code, message: 'This chat is unavailable.' }) }) });
    await expect(page.locator('#log .msg.human')).toHaveCount(1);
    await page.clock.runFor(3000);
    await expect(page.locator('#connection-status')).toContainText('unavailable');
    await expect(page.locator('#input')).toBeDisabled();
    const polls = world.polls.length;
    await page.clock.runFor(30000);
    expect(world.polls).toHaveLength(polls);
    await expect(page.locator('#log .msg.human')).toHaveCount(1);
    await page.reload();
    await expect(page.locator('#connection-status')).toContainText('unavailable');
    expect(world.sessions).toBe(1);
  });
}

async function openInbox(page, world) {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  world.messages = [{ id: 1, sender_type: 'customer', message_text: 'I need help', created_at: '2026-09-22T08:00:00Z' }];
  await page.addInitScript(() => {
    sessionStorage.setItem('token', 'fake-tenant-token');
    sessionStorage.setItem('isLoggedIn', 'true');
    sessionStorage.setItem('user', JSON.stringify({ id: 1, company_id: 42, role: 'owner', email: 'owner@example.test' }));
  });
  await page.route('https://fonts.googleapis.com/**', route => route.abort());
  await page.route('https://fonts.gstatic.com/**', route => route.abort());
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    let data = [];
    if (url.pathname === '/api/conversations') data = [{ id: 10, chatbot_id: 7, bot_name: 'Support bot', customer_name: 'Website visitor', source_channel: 'web', platform_user_id: SESSION, updated_at: '2026-09-22T08:00:00Z' }];
    if (url.pathname === '/api/crm/leads') data = { leads: [] };
    if (url.pathname.endsWith('/messages')) data = world.messages;
    if (url.pathname.endsWith('/agent-reply')) return world.reply(route);
    return route.fulfill(ok(data));
  });
  await page.goto(`${origin}/conversations.html?bot_id=7&conversation_id=10`);
  await expect(page.locator('#conv-reply-text')).toBeVisible();
}

test('staff network failure keeps the draft and unlocks retry', async ({ page }) => {
  const world = { reply: route => route.abort('failed') };
  await openInbox(page, world);
  await page.locator('#conv-reply-text').fill('Keep this draft');
  await page.locator('#conv-reply-text').press('Control+Enter');
  await expect(page.locator('#conv-reply-send')).toBeEnabled();
  await expect(page.locator('#conv-reply-text')).toHaveValue('Keep this draft');
  await expect(page.locator('#conv-compose-status')).toContainText('Could not send');
  world.reply = route => route.fulfill(ok({}));
  await page.locator('#conv-reply-send').click();
  await expect(page.locator('#conv-compose-status')).toHaveText('Reply saved. The visitor will receive it in this chat.');
  await expect(page.locator('#conv-reply-text')).toBeEmpty();
});

test('successful staff send keeps a new draft typed while saving', async ({ page }) => {
  let release;
  let requested = false;
  await openInbox(page, { reply: async route => {
    requested = true;
    await new Promise(resolve => { release = resolve; });
    return route.fulfill(ok({}));
  } });
  await page.locator('#conv-reply-text').fill('First reply');
  await page.locator('#conv-reply-send').click();
  await expect.poll(() => requested).toBe(true);
  await page.locator('#conv-reply-text').fill('Next reply still being written');
  release();
  await expect(page.locator('#conv-reply-send')).toBeEnabled();
  await expect(page.locator('#conv-reply-text')).toHaveValue('Next reply still being written');
});

test('staff inbox refreshes new customer messages without replacing a draft', async ({ page }) => {
  await page.clock.install();
  const world = { reply: route => route.fulfill(ok({})) };
  await openInbox(page, world);
  await expect(page.locator('#conv-transcript')).toContainText('I need help');
  await page.locator('#conv-reply-text').fill('Unsent staff reply');
  world.messages.push({ ...human(2, 'Saved staff reply'), delivery_status: 'sent' });
  world.messages.push({ id: 3, sender_type: 'customer', message_text: 'Are you still there?', created_at: '2026-09-22T08:01:00Z' });
  await page.clock.runFor(10000);
  await expect(page.locator('#conv-transcript')).toContainText('Are you still there?');
  await expect(page.locator('#conv-transcript [data-message-id="2"]')).toContainText('Support team');
  await expect(page.locator('#conv-transcript [data-message-id="2"] [data-part="delivery"]')).toHaveText('Saved');
  await expect(page.locator('#conv-reply-text')).toHaveValue('Unsent staff reply');
});
