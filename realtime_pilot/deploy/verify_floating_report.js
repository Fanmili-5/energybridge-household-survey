// Empty isolated test server, with planning disabled. No survey/model submission.
const {chromium}=require('playwright'),assert=require('assert');
(async()=>{
 const base=process.env.REPORT_TEST_URL;
 if(!base||new URL(base).hostname!=='127.0.0.1')throw Error('Use an isolated loopback server');
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
 try{
  for(const width of [390,1280]){
   const context=await browser.newContext({viewport:{width,height:844}}),page=await context.newPage(),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/api/paired',()=>{throw Error('Unexpected model request');});
   await page.route('**/api/households',()=>{throw Error('Unsubmitted answers must not be uploaded');});
   await page.goto(base);await page.locator('#p_B02').waitFor({state:'attached'});
   const button=page.locator('#report-problem');assert(await button.isVisible());
   const first=await button.boundingBox();
   await page.evaluate(()=>scrollTo(0,document.body.scrollHeight));
   const last=await button.boundingBox();assert(Math.abs(first.y-last.y)<1);assert(Math.abs(first.x-last.x)<1);
   assert.equal(await button.evaluate(e=>getComputedStyle(e).position),'fixed');
   const bounds=await button.boundingBox(),label=await button.locator('span').boundingBox();
   assert(label.x+label.width<=bounds.x+bounds.width);assert(bounds.height<60);
   for(let step=0;step<7;step++){
    await page.evaluate(step=>showWizard(step,{save:false}),step);
    assert(await button.isVisible());
   }
   await page.screenshot({path:'/tmp/eb-floating-'+width+'.png'});
   await button.click();await page.locator('#report-category').selectOption('display');await page.locator('#report-description').fill('首次填写页面反馈测试');
   await page.locator('#report-submit').click();await page.waitForFunction(()=>!document.getElementById('report-dialog').open);
   assert(await page.locator('#report-toast').isVisible());
   const state=await page.evaluate(()=>api('/api/session'));assert.equal(state.households.length,0);assert.equal(state.jobs.length,0);
   await button.click();assert((await page.locator('#report-status').innerText()).includes('报告编号'));
   await page.screenshot({path:'/tmp/eb-floating-dialog-'+width+'.png'});assert.deepEqual(errors,[]);
   await context.close();
  }
  const context=await browser.newContext({extraHTTPHeaders:{'X-EB-Authenticated-User':'testadmin'}}),page=await context.newPage();
  await page.goto(base+'/admin/');await page.waitForFunction(()=>document.querySelectorAll('.report-card').length===2);
  assert((await page.locator('#reports-list').innerText()).includes('填写中页面：'));
  const [download]=await Promise.all([page.waitForEvent('download'),page.locator('.report-card').first().getByText('下载诊断记录',{exact:true}).click()]);
  assert((await download.suggestedFilename()).startsWith('diagnostic-'));
  console.log(JSON.stringify({ok:true,widths:[390,1280],fixed_during_scroll:true,steps:7,page_reports:2,no_intake_or_generation:true}));
 }finally{await browser.close();}
})();
