const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');
const { startServer } = require('./platform-admin-static-server');

let server;
let origin;
test.beforeAll(async () => {
  server = await startServer(0);
  origin = `http://127.0.0.1:${server.address().port}`;
});
test.afterAll(async () => {
  if (server) await new Promise(resolve => server.close(resolve));
});

test('a website visitor receives the inbox staff reply and can continue while AI stays paused', async ({ browser }) => {
  test.setTimeout(30000);
  const session = 'web_abcdefghijklmnopqrstuvwx';
  const world = { waiting: false, customerMessages: [], staffMessages: [], sessions: 0, resolves: 0 };
  const visitorContext = await browser.newContext();
  const staffContext = await browser.newContext();
  const visitor = await visitorContext.newPage();
  const staff = await staffContext.newPage();
  const html = fs.readFileSync(path.resolve(__dirname, '../../frontend/widget-chat.html'), 'utf8');
  const conversation = {
    id: 10, chatbot_id: 7, bot_name: 'Support bot', customer_name: 'Website visitor',
    source_channel: 'web', source_channel_id: null, platform_user_id: session,
    customer_phone: session, updated_at: '2026-09-22T08:00:00Z', message_count: 1,
  };

  async function mockService(route) {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === '/chat/roundtrip-widget') {
      return route.fulfill({ contentType: 'text/html', body: html });
    }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    let data = [];
    if (url.pathname === '/api/widget/roundtrip-widget/config') {
      data = { display_name: 'Support bot', welcome_message: 'How can we help?',
        suggested_questions: [], collect_lead: false, primary_color: '#4F46E5' };
    } else if (url.pathname === '/api/widget/roundtrip-widget/session') {
      world.sessions += 1;
      data = { session_id: session, welcome_message: 'How can we help?', suggested_questions: [] };
    } else if (url.pathname === '/api/widget/roundtrip-widget/message') {
      const body = request.postDataJSON();
      expect(body.session_id).toBe(session);
      world.customerMessages.push(body.message);
      world.waiting = true;
      data = { reply: world.customerMessages.length === 1 ? 'Our team will reply here.' : '',
        handled_by: 'human', messages_remaining: 49 };
    } else if (url.pathname === '/api/widget/roundtrip-widget/messages') {
      const body = request.postDataJSON();
      expect(body.session_id).toBe(session);
      const messages = world.staffMessages.filter(message => message.id > (body.after_id || 0));
      data = { messages, last_message_id: messages.at(-1)?.id || body.after_id || 0,
        has_more: false, awaiting_human: world.waiting };
    } else if (url.pathname === '/api/conversations') {
      data = world.waiting ? [conversation] : [];
    } else if (url.pathname === '/api/crm/leads') {
      data = { leads: [] };
    } else if (url.pathname === '/api/agent/escalations') {
      data = world.waiting ? [{ id: 100, chatbot_id: 7, conversation_id: 10,
        intent: 'handoff_request', status: 'detected' }] : [];
    } else if (url.pathname === '/api/conversations/10/messages') {
      data = world.customerMessages.map((message, index) => ({ id: index + 1,
        sender_type: 'customer', message_text: message, created_at: '2026-09-22T08:00:00Z' }))
        .concat(world.staffMessages);
    } else if (url.pathname === '/api/conversations/10/agent-reply') {
      const body = request.postDataJSON();
      expect(body.chatbot_id).toBe(7);
      expect(world.waiting).toBe(true);
      const message = { id: 501, sender_type: 'human', message_text: body.text,
        created_at: '2026-09-22T08:01:00Z' };
      world.staffMessages.push(message);
      data = { delivery_status: 'accepted', message_id: message.id };
    } else if (url.pathname.endsWith('/resolve')) {
      world.resolves += 1;
      world.waiting = false;
      data = { ai_resumed: true };
    }
    return route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ status: 'success', data }) });
  }

  await visitorContext.route('**/*', mockService);
  await staffContext.route('**/*', mockService);
  await staff.addInitScript(() => {
    sessionStorage.setItem('token', 'synthetic-staff-token');
    sessionStorage.setItem('isLoggedIn', 'true');
    sessionStorage.setItem('user', JSON.stringify({ id: 11, company_id: 42, role: 'owner' }));
  });

  try {
    await visitor.goto(`${origin}/chat/roundtrip-widget`);
    await expect(visitor.locator('#input')).toBeEnabled();
    await visitor.locator('#input').fill('Please connect me to a person');
    await visitor.locator('#send').click();
    await expect(visitor.locator('#log')).toContainText('Our team will reply here.');

    await staff.goto(`${origin}/conversations.html?conversation_id=10`);
    await expect(staff.locator('#conv-escalated-pill')).toBeVisible();
    await expect(staff.locator('#conv-reply-text')).toBeVisible();
    await staff.locator('#conv-reply-text').fill('I can help with your order.');
    await staff.locator('#conv-reply-send').click();
    await expect(staff.locator('#conv-compose-status')).toContainText('saved');
    await expect(staff.locator('#conv-escalated-pill')).toBeVisible();

    await visitor.bringToFront();
    await expect(visitor.locator('#log')).toContainText('I can help with your order.', { timeout: 10000 });
    await expect(visitor.locator('#log .msg.human').filter({ hasText: 'I can help with your order.' })).toHaveCount(1);
    await visitor.locator('#input').fill('My order number is 42');
    await visitor.locator('#send').click();
    await expect.poll(() => world.customerMessages).toEqual([
      'Please connect me to a person', 'My order number is 42',
    ]);
    expect(world.waiting).toBe(true);
    expect(world.resolves).toBe(0);
    expect(world.sessions).toBe(1);
    await visitor.screenshot({ path: test.info().outputPath('visitor-received-staff-reply.png'), fullPage: true });
    await staff.screenshot({ path: test.info().outputPath('staff-web-reply-accepted.png'), fullPage: true });
  } finally {
    await visitorContext.close();
    await staffContext.close();
  }
});
