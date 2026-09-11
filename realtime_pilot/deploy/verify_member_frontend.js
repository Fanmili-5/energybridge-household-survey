process.chdir(require('path').resolve(__dirname,'..'));
// All network requests intercepted; fake submit only, no live jobs/API calls.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
(async()=>{
 const out='ui_audit_20260911/members',schema=JSON.parse(fs.readFileSync(out+'/schema.json')),answers=JSON.parse(fs.readFileSync(out+'/answers.json'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined});
 try{const context=await browser.newContext({viewport:{width:390,height:844}}),page=await context.newPage(),errors=[];let payload;
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{const r=route.request(),path=new URL(r.url()).pathname;
 if(path==='/api/session')return route.fulfill({json:schema});
 if(path==='/api/households'){payload=r.postDataJSON();assert.strictEqual(payload.research_consent,true);return route.fulfill({json:{saved:true,id:'c'.repeat(32),household_record_hash:'mock-record-hash',questionnaire_version:schema.paired_questionnaire_version,questionnaire_hash:schema.paired_questionnaire_hash}});}
 if(path==='/api/paired'){assert.strictEqual(r.postDataJSON().submission_id,'c'.repeat(32));assert(!('answers' in r.postDataJSON()));return route.fulfill({status:422,json:{error:'模拟提交已捕获，未创建真实任务'}});}
 if(path.startsWith('/api/'))throw Error('Unexpected request '+path);
 const name=path==='/'?'index.html':path.slice(1);if(!['index.html','app.js','style.css','time-input.js','plan-view.js'].includes(name))return route.abort();
 return route.fulfill({contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync('static/'+name)});
 });
 async function choose(id,value){await page.locator('#'+id).evaluate(e=>showWizard(Number(e.closest('[data-form-page]').dataset.formPage),{save:false}));const select=page.locator('#'+id);if(await select.isVisible())return select.selectOption(value);const radios=page.locator('#'+id+' + .inline-choices input');for(let i=0;i<await radios.count();i++)if(await radios.nth(i).getAttribute('value')===value)return radios.nth(i).check();throw Error('Missing visible option '+id);}
 await page.goto('http://127.0.0.1:8766/');await page.locator('#p_B02').waitFor({state:'attached'});assert(await page.locator('.hero-art svg').isVisible());assert.strictEqual(await page.locator('header svg,header .brand-mark').count(),0);assert.strictEqual(await page.locator('.survey-hero h1').innerText(),'用电安排变一点，\n您家的生活会怎样？');
 await choose('p_B02',JSON.stringify('3'));await page.evaluate(()=>showWizard(1));assert.strictEqual(await page.locator('.member-card:visible').count(),3);
 assert.strictEqual(await page.locator('#p_member_0_routine').inputValue(),'');
 await choose('p_member_0_routine','out_regular');await choose('p_member_0_comfort','temp_sensitive');
 await choose('p_B02',JSON.stringify('2'));await choose('p_B02',JSON.stringify('3'));
 assert.strictEqual(await page.locator('#p_member_0_comfort').inputValue(),'temp_sensitive');
 await page.reload();await page.locator('#p_member_0_routine').waitFor({state:'attached'});assert.strictEqual(await page.locator('#p_member_0_comfort').inputValue(),'temp_sensitive');
 assert.strictEqual(await page.locator('#p_member_1_comfort').inputValue(),'');
 await choose('p_B02',JSON.stringify('6_plus'));await page.evaluate(()=>showWizard(1));await page.locator('[data-member-add]').click();assert.strictEqual(await page.locator('.member-card:visible').count(),7);
 await choose('p_member_6_routine','irregular');await page.reload();await page.locator('#p_member_6_routine').waitFor({state:'attached'});assert.strictEqual(await page.locator('#p_member_6_routine').inputValue(),'irregular');
 await page.evaluate(a=>{restore(Object.fromEntries(Object.entries(a).map(([k,value])=>[k,{value,response_status:'answered'}])));conditional();saveDraft();},answers);
 await choose('p_member_1_comfort','temp_sensitive');
 assert.strictEqual(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.evaluate(()=>{showWizard(0,{save:false});scrollTo(0,0);});await page.screenshot({path:out+'/direct-choices-top.png',fullPage:false});await page.evaluate(()=>showWizard(1,{save:false}));await page.locator('#p_M_MEMBERS').evaluate(e=>e.scrollIntoView({block:'start'}));await page.screenshot({path:out+'/mobile.png'});
 await page.evaluate(()=>showWizard(3,{save:false}));await page.locator('#attitudes-heading').evaluate(e=>e.scrollIntoView({block:'start'}));await page.screenshot({path:out+'/attitudes-mobile.png'});
 await page.setViewportSize({width:1280,height:1000});await page.evaluate(()=>{showWizard(0,{save:false});scrollTo(0,0);});await page.screenshot({path:out+'/direct-choices-desktop-top.png'});await page.evaluate(()=>showWizard(1,{save:false}));await page.locator('#p_M_MEMBERS').evaluate(e=>e.scrollIntoView({block:'start'}));await page.screenshot({path:out+'/desktop.png'});
 await page.evaluate(()=>showWizard(3,{save:false}));await page.locator('#generate').click();await page.waitForFunction(()=>document.getElementById('error').textContent.includes('模拟提交已捕获'));
 assert.strictEqual(payload.answers.P_GRID,'3');assert.strictEqual(payload.answers.P_EV_TARGET,'0.8');assert.strictEqual(payload.answers.P_AC_RANGE,'24_26');assert(!('A_EB_PRICE' in payload.answers));assert.strictEqual(payload.answers.M_MEMBERS.length,3);assert.strictEqual(payload.answers.M_MEMBERS[1].comfort,'temp_sensitive');assert.strictEqual(payload.answers.M_MEMBERS[0].participation,null);
 assert.deepStrictEqual(errors,[]);fs.writeFileSync(out+'/report.json',JSON.stringify({passed:true,tests:['empty_defaults','count_changes_preserve_answers','draft_reload','seven_members_reload','mobile_no_overflow','fake_submission_nested_fields'],actual_api_calls:0},null,2));console.log('Member UI checks passed; all requests mocked.');
 }finally{await browser.close();}
})();
