// Run against an isolated fixture server only; never invokes generation.
const {chromium}=require('playwright'),assert=require('assert'),fs=require('fs');
(async()=>{
 const base=process.env.REPORT_TEST_URL;
 if(!base||new URL(base).hostname!=='127.0.0.1')throw Error('REPORT_TEST_URL must be an isolated loopback fixture server');
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
 try{
  const context=await browser.newContext({viewport:{width:390,height:844}});
  await context.addCookies([{name:'pilot_session',value:'a'.repeat(64),url:base}]);
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/paired',()=>{throw Error('Test must never generate a plan');});
  await page.goto(base);await page.locator('#p_B02').waitFor({state:'attached'});
  assert(await page.locator('#participant-name').isVisible());assert(!(await page.locator('#participant-name').getAttribute('required')));
  await page.locator('#report-problem').click();await page.locator('#report-category').selectOption('generation_failed');await page.locator('#report-description').fill('生成前测试报告');await page.locator('#report-submit').click();
  await page.waitForFunction(()=>!document.getElementById('report-dialog').open);assert((await page.locator('#case-support-status').innerText()).includes('问题已收到'));
  const state=await page.evaluate(()=>api('/api/session')),jid=state.jobs[0].id;
  await page.evaluate(id=>loadJob(id),jid);assert.strictEqual(await page.locator('#case-reference-id').inputValue(),jid);
  await page.locator('#report-problem').click();await page.locator('#report-category').selectOption('display');await page.locator('#report-description').fill('手机上显示测试 <script>alert(1)</script>');
  let dropped=false;await page.route('**/api/reports',async route=>{if(!dropped){dropped=true;await route.fetch();await route.abort();}else await route.continue();});
  await page.locator('#report-submit').click();await page.waitForFunction(()=>document.getElementById('report-status').textContent.includes('重试'));
  await page.locator('#report-submit').click();await page.waitForFunction(()=>!document.getElementById('report-dialog').open);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'/tmp/eb-case-report-mobile.png',fullPage:true});
  const admin=await browser.newContext({extraHTTPHeaders:{'X-EB-Authenticated-User':'testadmin'}}),a=await admin.newPage();a.on('pageerror',e=>errors.push(e.message));
  await a.goto(base+'/admin/');await a.waitForFunction(()=>document.querySelectorAll('.report-card').length===2);
  assert((await a.locator('#reports-list').innerText()).includes('测试昵称'));assert((await a.locator('#reports-list').innerText()).includes('<script>alert(1)</script>'));
  await a.locator('.report-card').first().locator('select').selectOption('confirmed');await a.locator('.report-card').first().locator('textarea').fill('已复核测试');
  await a.locator('.report-card').first().getByText('保存核查结果',{exact:true}).click();await a.waitForFunction(()=>document.getElementById('reports-list').textContent.includes('核查结果已保存'));
  const [download]=await Promise.all([a.waitForEvent('download'),a.locator('.report-card').first().getByText('下载诊断记录',{exact:true}).click()]);
  await download.saveAs('/tmp/eb-case-diagnostic-test.json');const data=JSON.parse(fs.readFileSync('/tmp/eb-case-diagnostic-test.json'));
  assert.strictEqual(data.target_id,jid);assert(data.missing_documents.includes('outcome.json'));assert(!JSON.stringify(data).includes('测试昵称'));
  await a.locator('#report-filter').selectOption('open');await a.waitForFunction(()=>document.querySelectorAll('.report-card').length===1);
  await a.screenshot({path:'/tmp/eb-case-report-admin.png',fullPage:true});
  await page.reload();await page.locator('#p_B02').waitFor({state:'attached'});await page.evaluate(id=>loadJob(id),jid);
  assert((await page.locator('#case-support-status').innerText()).includes('问题已收到'));assert.deepStrictEqual(errors,[]);
  console.log(JSON.stringify({ok:true,reports:2,duplicate_retry:true,mobile_width:390,errors}));
 }finally{await browser.close();}
})();
