import { test, expect } from '@playwright/test';

// Local session regressions; API fixtures avoid any paid model calls.
test.use({ channel: process.env.CI ? undefined : 'chrome' });
const account = (name: string) => ({customer_id:name,full_name:name,phone:'0900000000',email:null,registered:true,registered_at:null});
const conversation = {conversation_id:'test-conversation',conversation_token:'test-token',customer_id:'B'};

async function fixtures(page: import('@playwright/test').Page) {
  await page.route('**/backend/api/**', async route => {
    const url = route.request().url();
    let data: unknown = {};
    if (url.endsWith('/customer/login')) data = {customer_token:'token-B',account:account('B')};
    else if (url.endsWith('/customer/me')) data = account('B');
    else if (url.endsWith('/customer/cart')) data = {items:[]};
    else if (url.endsWith('/conversations')) data = route.request().headers().authorization ? conversation : {...conversation,conversation_id:'guest-conversation',customer_id:null};
    else if (url.endsWith('/conversations/test-conversation')) data = {status:'open',customer_id:'B',messages:[{speaker:'customer',text:'Tin nhắn đã lưu'}]};
    else if (url.endsWith('/conversations/guest-conversation')) data = {status:'open',customer_id:null,messages:[]};
    else if (url.includes('/catalog')) data = [];
    await route.fulfill({json:data});
  });
}

test('a delayed unauthorized profile response cannot sign out the newly logged-in customer', async ({page}) => {
  await fixtures(page);
  let release!: () => void;
  let started!: () => void;
  const requestStarted = new Promise<void>(r=>started=r);
  const pending = new Promise<void>(r=>release=r);
  await page.route('**/backend/api/customer/me', async route => {
    started(); await pending;
    await route.fulfill({status:401,json:{detail:'expired old token'}});
  });
  await page.addInitScript(()=>localStorage.setItem('customer-token','old-token-A'));
  await page.goto('/dang-nhap?next=/');
  await requestStarted;
  await page.getByLabel('Số điện thoại',{exact:true}).fill('0900000000');
  await page.locator('input[autocomplete="current-password"]').fill('test-password');
  await page.getByRole('button',{name:'Đăng nhập',exact:true}).click();
  await expect(page).toHaveURL(/\/$/);
  const rejected = page.waitForResponse(r=>r.url().endsWith('/customer/me') && r.status()===401);
  release();
  await rejected;
  await page.evaluate(()=>new Promise(requestAnimationFrame));
  await expect.poll(()=>page.evaluate(()=>localStorage.getItem('customer-token'))).toBe('token-B');
  await expect(page.getByRole('link',{name:'Tài khoản của tôi'})).toBeVisible();
});

test('reload restores this customer conversation and switching token drops its transcript', async ({page}) => {
  await fixtures(page);
  await page.goto('/');
  await page.evaluate(()=>{
    localStorage.setItem('customer-token','token-B');
    sessionStorage.setItem('conversation',JSON.stringify({conversation_id:'test-conversation',conversation_token:'test-token',customer_id:'B'}));
    sessionStorage.setItem('conversation-customer','token-B');
  });
  await page.reload();
  await page.getByRole('button',{name:'Chat với trợ lý',exact:true}).click();
  await expect(page.locator('.s-msg')).toContainText('Tin nhắn đã lưu');
  await page.reload();
  await page.getByRole('button',{name:'Chat với trợ lý',exact:true}).click();
  await expect(page.locator('.s-msg')).toContainText('Tin nhắn đã lưu');
  await page.evaluate(()=>{
    localStorage.removeItem('customer-token');
    window.dispatchEvent(new StorageEvent('storage',{key:'customer-token',oldValue:'token-B',newValue:null}));
  });
  await expect(page.locator('.s-msg')).toHaveCount(0);
  await expect.poll(()=>page.evaluate(()=>JSON.parse(sessionStorage.getItem('conversation') || 'null')?.conversation_id)).not.toBe('test-conversation');
});

test('opening chat in Strict Mode creates one conversation even while the request is pending', async ({page}) => {
  await fixtures(page);
  let created=0;
  let release!: () => void;
  let started!: () => void;
  const pending=new Promise<void>(r=>release=r);
  const requestStarted=new Promise<void>(r=>started=r);
  await page.route('**/backend/api/conversations', async route=>{
    created++;
    started();
    await pending;
    await route.fulfill({json:{...conversation,conversation_id:'guest-conversation',customer_id:null}});
  });
  await page.goto('/');
  await page.route('**/backend/api/conversations/*/stream', route=>route.fulfill({contentType:'text/event-stream',body:'event: done\ndata: {"reply":"Dạ em đang kiểm tra ạ."}\n\n'}));
  await page.getByRole('button',{name:'Chat với trợ lý',exact:true}).click();
  await requestStarted;
  await page.getByRole('button',{name:'Giày chạy bộ nào đang giảm giá?',exact:true}).click();
  await page.evaluate(()=>new Promise(requestAnimationFrame));
  release();
  await expect.poll(()=>page.evaluate(()=>JSON.parse(sessionStorage.getItem('conversation') || 'null')?.conversation_id)).toBe('guest-conversation');
  expect(created).toBe(1);
});
