const {test,expect}=require('@playwright/test');
const {startServer}=require('./platform-admin-static-server');
const fs=require('node:fs');
const path=require('node:path');

let server,base;
test.beforeAll(async()=>{server=await startServer(0);base='http://127.0.0.1:'+server.address().port;});
test.afterAll(async()=>{if(server)await new Promise(resolve=>server.close(resolve));});

function fixture(){
  const company={id:42,company_name:'Meridian <script>window.__xss=true</script>',business_type:'Healthcare',status:'active',contact_email:'contact@example.test',created_at:'2026-09-01T00:00:00Z'};
  return {
    company,
    identity:{user:{id:11,email:'operator@example.test',full_name:'Operator',status:'active'},platform_admin:{id:7,is_active:true},platform_role:'admin',modules:{billing:true,support:true,customers:true}},
    requests:[],events:[],replies:[],writes:[],calls:[],failApproval:false,failNote:false,failDirectory:false,recheckOutcome:'manual_review_required',
    order:{id:19,status:'pending',amount_sen:38900,new_plan:{name:'Growth'},activation_status:'pending',created_at:'2026-09-01T00:00:00Z'},
    ticket:{id:9,company_id:42,company:{id:42,company_name:company.company_name},title:'Review renewal issue',redacted_summary:'Customer requested assistance.',status:'open',priority:'high',assigned_platform_admin_user_id:7,updated_at:'2026-09-01T00:00:00Z'}
  };
}
const pagination=rows=>({limit:25,offset:0,returned:rows.length,total:rows.length,has_more:false});
async function mock(page,state){
  await page.addInitScript(()=>{sessionStorage.setItem('token','mock-token');sessionStorage.setItem('user',JSON.stringify({role:'owner'}));sessionStorage.setItem('aveon.prototype.permissions',JSON.stringify({billing:true,support:true,customers:true}));});
  await page.route('**/api/**',async route=>{
    const request=route.request(),url=new URL(request.url()),path=url.pathname,method=request.method();state.calls.push(path);
    const send=(data,status=200,code)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(status===200?{status:'success',data}:{status:'error',code:code||'platform_admin_data_unavailable'})});
    if(method!=='GET')state.writes.push({path,method,body:request.postDataJSON()});
    if(path==='/api/platform-admin/me')return send(state.identity);
    if(path==='/api/platform-admin/approval-requests'){
      if(method==='POST'){if(state.failApproval)return send(null,503);const row={id:31,...request.postDataJSON(),status:'pending',requester_platform_admin_user_id:7,created_at:'2026-09-07T00:00:00Z',execution_status:'not_executed'};state.requests.push(row);return send({request:row});}
      const rows=state.requests.filter(r=>!url.searchParams.get('status')||r.status===url.searchParams.get('status'));return send({requests:rows,pagination:pagination(rows)});
    }
    if(path==='/api/platform-admin/approval-requests/31')return send({request:state.requests[0]});
    if(path==='/api/platform-admin/billing/overview')return send({generated_at:'2026-09-07T00:00:00Z',subscriptions:{by_status:{active:3,past_due:1,expired:0},active_plan_catalogue:[]},subscription_orders:{pending_count:1,failed_count:2}});
    if(path==='/api/platform-admin/billing/companies')return send({companies:[{company_id:42,company_name:state.company.company_name,current_plan:{name:'Growth'},subscription_status:'active',subscription_order_attention:{pending_count:1,failed_count:0,reconciliation_required_count:0,activation_failed_count:0,activation_conflict_count:0}}],pagination:pagination([state.company])});
    if(path==='/api/platform-admin/companies'){if(state.failDirectory)return send(null,503);const rows=state.company.company_name.toLowerCase().includes((url.searchParams.get('search')||'').toLowerCase())?[state.company]:[];return send({companies:rows,pagination:pagination(rows)});}
    if(path==='/api/platform-admin/companies/42')return send(state.company);
    if(path==='/api/platform-admin/companies/42/subscription')return send({company:state.company,subscription:{status:'active',plan:{name:'Growth',billing_interval:'monthly'},current_period_end:'2026-10-01T00:00:00Z'}});
    if(path==='/api/platform-admin/companies/42/ai-credit-usage')return send({company:state.company,credit_balance:{initialized:true,total_balance_micro_myr:23000000},usage:{request_count:42},period:{start:'2026-09-01T00:00:00Z',end:'2026-10-01T00:00:00Z'}});
    if(path==='/api/platform-admin/companies/42/billing-orders')return send({billing_orders:[state.order],pagination:pagination([state.order])});
    if(path==='/api/platform-admin/companies/42/billing-orders/19/recheck')return state.recheckConflict?send(null,409,'gateway_recheck_unavailable'):send({order:state.order,outcome:state.recheckOutcome,source:'existing_reconciliation'});
    if(path==='/api/platform-admin/support-cases')return send({cases:[state.ticket],pagination:pagination([state.ticket])});
    if(path==='/api/platform-admin/support-case-assignees')return send({assignees:[{id:7,user_full_name:'Operator',is_active:true},{id:8,user_full_name:'Second operator',is_active:true}]});
    if(path==='/api/platform-admin/support-cases/9')return send({case:state.ticket,events:state.events,events_pagination:pagination(state.events),source_tenant_request:{request_id:12},status_transitions:state.ticket.status==='resolved'?['in_progress']:['in_progress','resolved']});
    if(path==='/api/platform-admin/support-cases/10')return send({case:{...state.ticket,id:10,title:'Second support ticket'},events:[],events_pagination:pagination([]),source_tenant_request:{request_id:13},status_transitions:['in_progress','resolved']});
    if(path==='/api/platform-admin/support-cases/10/replies')return send({replies:[],pagination:pagination([])});
    if(path==='/api/platform-admin/support-cases/9/replies'){
      if(method==='POST'){state.replies.push({reply_id:21,redacted_body:request.postDataJSON().redacted_body,author_type:'platform_admin',created_at:'2026-09-07T00:00:00Z'});return send({reply:state.replies.at(-1)});}
      return send({replies:state.replies,pagination:pagination(state.replies)});
    }
    if(path==='/api/platform-admin/support-cases/9/notes'){if(state.failNote)return send(null,503);state.events.push({id:22,event_type:'note_added',actor_platform_admin_user_id:7,redacted_note:request.postDataJSON().redacted_note,created_at:'2026-09-07T00:00:00Z'});return send({case:state.ticket});}
    if(path==='/api/platform-admin/support-cases/9/assignment'){state.ticket.assigned_platform_admin_user_id=request.postDataJSON().assigned_platform_admin_user_id;return send({case:state.ticket});}
    if(path==='/api/platform-admin/support-cases/9/status'){state.ticket.status=request.postDataJSON().status;return send({case:state.ticket});}
    return send(null,503,'unexpected_unmocked_api');
  });
}

test('fails closed on missing role and rejects a forged local tenant owner',async({page})=>{
  const state=fixture();delete state.identity.platform_role;await mock(page,state);await page.goto(base+'/admin.html#billing');
  await expect(page.getByRole('heading',{name:'Access not assigned'})).toBeVisible();
  await expect(page.locator('#admin-app')).toBeHidden();
  expect(state.calls.every(path=>path.endsWith('/me'))).toBe(true);
});

for(const view of ['dashboard','customers/42'])test(`permission refresh removes revoked cross-module data from ${view}`,async({page})=>{
  const state=fixture();await mock(page,state);await page.goto(base+'/admin.html#'+view);
  const billingHeading=view==='dashboard'?'Payments to follow up':'Usage and credit';
  await expect(page.getByRole('heading',{name:billingHeading,exact:true})).toBeVisible();
  const priorReads=state.calls.filter(path=>path.includes('/billing')||path.endsWith('/subscription')||path.endsWith('/ai-credit-usage')).length;
  state.identity.modules.billing=false;
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await expect(page.getByRole('heading',{name:billingHeading,exact:true})).toHaveCount(0);
  await expect(page.locator('#main')).toHaveAttribute('aria-busy','false');
  await expect(page.getByText('Review renewal issue',{exact:true})).toBeVisible();
  await expect(page.locator('#navigation').getByRole('link',{name:'Billing',exact:true})).toHaveCount(0);
  expect(state.calls.filter(path=>path.includes('/billing')||path.endsWith('/subscription')||path.endsWith('/ai-credit-usage')).length).toBe(priorReads);
});

test('revoked Support access discards ticket drafts before access is restored',async({page})=>{
  const state=fixture();await mock(page,state);await page.goto(base+'/admin.html#helpdesk/9');
  await page.locator('#reply-text').fill('Discard this private draft after revocation.');
  state.identity.modules.support=false;
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await expect(page.getByRole('heading',{name:'Access not assigned',exact:true})).toBeVisible();
  await expect(page.locator('#reply-text')).toHaveCount(0);
  state.identity.modules.support=true;
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await expect(page.getByRole('heading',{name:'Review renewal issue',exact:true})).toBeVisible();
  await expect(page.locator('#reply-text')).toHaveValue('');
  expect(state.writes).toHaveLength(0);
});

for(const kind of ['public','internal'])test(`late ${kind} ticket A completion preserves ticket B draft and dialog`,async({page})=>{
  const state=fixture();await mock(page,state);let release,started=false;
  const gate=new Promise(resolve=>{release=resolve;});
  const endpoint='/api/platform-admin/support-cases/9/'+(kind==='public'?'replies':'notes');
  await page.route('**'+endpoint,async route=>{if(route.request().method()!=='POST')return route.fallback();started=true;await gate;return route.fallback();});
  await page.goto(base+'/admin.html#helpdesk/9');
  if(kind==='internal')await page.getByRole('button',{name:'Internal note',exact:true}).click();
  await page.locator('#reply-text').fill('Ticket A submitted text.');
  await page.getByRole('button',{name:kind==='public'?'Review reply':'Add internal note',exact:true}).click();
  if(kind==='public')await page.getByRole('button',{name:'Send public reply',exact:true}).click();
  await expect.poll(()=>started).toBe(true);
  // Browser history navigation can change the resource while a write is pending.
  await page.evaluate(()=>{location.hash='helpdesk/10';});
  await expect(page.getByRole('heading',{name:'Second support ticket',exact:true})).toBeVisible();
  await page.locator('#reply-text').fill('Ticket B unsent draft.');
  await page.keyboard.press('Control+k');
  await expect(page.getByRole('dialog')).toContainText('Search workspace');
  const completed=page.waitForResponse(response=>response.url().endsWith(endpoint)&&response.request().method()==='POST');
  release();await completed;
  await expect.poll(()=>state.writes.some(write=>write.path===endpoint)).toBe(true);
  await expect(page.getByRole('dialog')).toContainText('Search workspace');
  await expect(page.locator('#reply-text')).toHaveValue('Ticket B unsent draft.');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
  await page.locator('#main .detail-top a').click();
  await expect(page.getByRole('heading',{name:'Help Desk',exact:true})).toBeVisible();
  await page.evaluate(()=>{location.hash='helpdesk/10';});
  await expect(page.locator('#reply-text')).toHaveValue('Ticket B unsent draft.');
});

test('company search stays in memory and strips legacy query text from browser URLs',async({page})=>{
  const state=fixture();await mock(page,state);await page.goto(base+'/admin.html#customers?q=Private%20legacy%20name&status=active');
  await expect(page.getByLabel('Search companies…')).toHaveValue('');
  expect(new URL(page.url()).hash).toBe('#customers?status=active');
  await page.getByLabel('Search companies…').fill('Private customer name');
  await expect(page.getByText('No records match this view.')).toBeVisible();
  expect(page.url()).not.toContain('Private');expect(page.url()).not.toContain('q=');
  await page.locator('#navigation').getByRole('link',{name:'Profile',exact:true}).click();
  await page.locator('#navigation').getByRole('link',{name:'Customers',exact:true}).click();
  await expect(page.getByLabel('Search companies…')).toHaveValue('Private customer name');
  await page.reload();await expect(page.getByLabel('Search companies…')).toHaveValue('');
  await page.keyboard.press('Control+k');await page.getByRole('searchbox',{name:'Search workspace',exact:true}).fill('Another private name');
  await page.locator('[data-customer-search]').click();
  await expect(page.getByLabel('Search companies…')).toHaveValue('Another private name');
  expect(page.url()).not.toContain('private');expect(page.url()).not.toContain('q=');
});

test('module denial prevents reads and unavailable data remains an error',async({page})=>{
  const state=fixture();state.identity.modules.billing=false;await mock(page,state);await page.goto(base+'/admin.html#billing/42');
  await expect(page.getByRole('heading',{name:'Access not assigned'})).toBeVisible();
  await expect(page.locator('#navigation').getByRole('link',{name:'Billing',exact:true})).toHaveCount(0);
  expect(state.calls.some(path=>path.includes('/billing'))).toBe(false);
  state.failDirectory=true;await page.locator('#navigation').getByRole('link',{name:'Customers',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Could not load Customers'})).toBeVisible();
  await expect(page.getByText('No records match this view.')).toHaveCount(0);
  state.failDirectory=false;await page.getByRole('button',{name:'Try again'}).click();
  await expect(page.getByRole('heading',{name:'Customers',exact:true})).toBeVisible();
});

test('creates server approval requests, retains failed input, and renders decisions safely',async({page})=>{
  const state=fixture();await mock(page,state);await page.goto(base+'/admin.html#customers/42');
  await page.getByRole('button',{name:'Request account edit',exact:true}).first().click();
  await expect(page.getByLabel('Requested change')).toBeFocused();
  await page.getByRole('button',{name:'Create request'}).click();
  await expect(page.getByText('Enter the requested change.')).toBeVisible();
  const summary='Change billing name <img src=x onerror=window.__xss=true>';
  await page.getByLabel('Requested change').fill(summary);await page.getByLabel('Reason',{exact:true}).fill('The customer requested their updated legal billing name.');
  state.failApproval=true;await page.getByRole('button',{name:'Create request'}).click();
  await expect(page.locator('#approval-error')).toContainText('could not confirm');
  await expect(page.getByLabel('Requested change')).toHaveValue(summary);
  state.failApproval=false;await page.getByRole('button',{name:'Create request'}).click();
  await expect(page.getByRole('heading',{name:'My requests'})).toBeVisible();
  await expect(page.getByText(summary,{exact:true})).toBeVisible();
  const body=state.writes.filter(w=>w.path.endsWith('/approval-requests')).at(-1).body;
  expect(body).toEqual({type:'account_change',company_id:42,summary,reason:'The customer requested their updated legal billing name.'});
  expect(await page.evaluate(()=>window.__xss)).toBeUndefined();
  state.requests[0].status='approved';state.requests[0].decision_reason='Reviewed and recorded.';
  await page.locator('#main').getByRole('button',{name:'View',exact:false}).click();
  await expect(page.getByRole('dialog')).toContainText('Approved');
  await expect(page.getByRole('dialog')).toContainText('No operational change was executed.');
});

test('private notes and confirmed public replies use distinct APIs and clear only successful drafts',async({page})=>{
  const state=fixture();state.ticket.assigned_platform_admin_user_id=99;await mock(page,state);await page.goto(base+'/admin.html#helpdesk/9');
  await expect(page.getByLabel('Assigned to')).toHaveValue('99');await expect(page.getByRole('button',{name:'Update assignee'})).toBeDisabled();
  await page.getByRole('button',{name:'Internal note',exact:true}).click();await page.locator('#reply-text').fill('Private follow-up context.');
  state.failNote=true;await page.getByRole('button',{name:'Add internal note'}).click();await expect(page.locator('#reply-error')).toContainText('could not confirm');await expect(page.locator('#reply-text')).toHaveValue('Private follow-up context.');
  state.failNote=false;await page.getByRole('button',{name:'Add internal note'}).click();
  await expect(page.locator('.message.internal')).toContainText('Private follow-up context.');await expect(page.locator('#reply-text')).toHaveValue('');
  expect(state.replies).toHaveLength(0);
  await page.getByRole('button',{name:'Public reply',exact:true}).click();await page.locator('#reply-text').fill('Your request has been reviewed.');await page.getByRole('button',{name:'Review reply'}).click();
  await expect(page.getByRole('dialog')).toContainText('visible to the customer');expect(state.replies).toHaveLength(0);
  await page.getByRole('button',{name:'Send public reply',exact:true}).click();
  await expect(page.locator('#main').getByText('Your request has been reviewed.',{exact:true})).toBeVisible();await expect(page.locator('#reply-text')).toHaveValue('');
  expect(state.replies).toHaveLength(1);
  await page.getByLabel('Assigned to').selectOption('8');await page.getByRole('button',{name:'Update assignee'}).click();await expect(page.getByLabel('Assigned to')).toHaveValue('8');
  await page.getByRole('button',{name:'Resolve ticket'}).click();await expect(page.getByRole('button',{name:'Reopen ticket'})).toBeFocused();
  await page.getByRole('button',{name:'Reopen ticket'}).click();await expect(page.getByRole('button',{name:'Resolve ticket'})).toBeFocused();
});

test('provider recheck makes an explicit authenticated POST and preserves unresolved outcomes',async({page})=>{
  const state=fixture();await mock(page,state);await page.goto(base+'/admin.html#billing/42');
  await expect(page.getByText('38,900 sen',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'View',exact:false}).click();await page.getByRole('button',{name:'Recheck payment'}).click();
  await expect(page.locator('#payment-result')).toContainText('Manual review required');
  await expect(page.locator('#payment-result')).toContainText('No successful completion is confirmed');
  expect(state.writes.filter(w=>w.path.endsWith('/recheck'))).toEqual([{path:'/api/platform-admin/companies/42/billing-orders/19/recheck',method:'POST',body:{}}]);
  state.recheckConflict=true;await page.getByRole('button',{name:'Recheck payment'}).click();await expect(page.locator('#payment-result')).toContainText('Wait for the payment callback');await expect(page.getByRole('dialog')).toBeVisible();await expect(page.locator('#admin-app')).toBeVisible();
  await page.getByRole('button',{name:'Request manual approval'}).click();await expect(page.getByLabel('Reason',{exact:true})).toBeFocused();
  await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toBeHidden();
});

test('narrow shell, search clearing, skip navigation, and escaped text remain operable',async({page})=>{
  const state=fixture();state.company.company_name='Meridian Dental';state.ticket.company.company_name='Meridian Dental';await mock(page,state);await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/admin.html#dashboard');
  await expect(page.getByRole('heading',{name:'Your work, at a glance'})).toBeVisible();
  if(process.env.ADMIN_PORTAL_SCREENSHOT_DIR){fs.mkdirSync(process.env.ADMIN_PORTAL_SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.ADMIN_PORTAL_SCREENSHOT_DIR,'admin-desktop.png'),fullPage:true});}
  await page.setViewportSize({width:390,height:844});
  if(process.env.ADMIN_PORTAL_SCREENSHOT_DIR)await page.screenshot({path:path.join(process.env.ADMIN_PORTAL_SCREENSHOT_DIR,'admin-mobile.png'),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('button',{name:'Toggle navigation'}).click();await page.locator('#navigation').getByRole('link',{name:'Customers',exact:true}).click();await page.getByLabel('Search companies…').fill('No result');
  await expect(page.getByText('No records match this view.')).toBeVisible();await page.getByRole('button',{name:'Clear search',exact:true}).click();await expect(page.locator('tbody')).toContainText('Meridian');
  await page.keyboard.press('Control+k');await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('searchbox',{name:'Search workspace',exact:true}).fill('Profile');await page.locator('#search-results').getByRole('link').filter({hasText:'Workspace page'}).click();
  await expect(page.getByRole('heading',{name:'Profile',exact:true})).toBeVisible();await page.keyboard.press('Tab');
  await page.locator('.skip-link').focus();await page.keyboard.press('Enter');expect(new URL(page.url()).hash).toBe('#profile');await expect(page.locator('#main')).toBeFocused();
  expect(await page.evaluate(()=>window.__xss)).toBeUndefined();
});
