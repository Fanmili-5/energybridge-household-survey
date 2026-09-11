process.chdir(require('path').resolve(__dirname,'..'));
// Mock every request; no actual planner/API request or persistent participant record.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
(async()=>{
 const out='ui_audit_20260911/expanded',schema=JSON.parse(fs.readFileSync(out+'/schema.json')),answers=JSON.parse(fs.readFileSync('ui_audit_20260911/members/answers.json'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined});
 try{
 const context=await browser.newContext({viewport:{width:390,height:844}}),page=await context.newPage(),errors=[];let posts=0,payload;
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>{const path=new URL(r.request().url()).pathname;
  if(path==='/api/session')return r.fulfill({json:schema});
  if(path==='/api/households'){payload=r.request().postDataJSON();assert.strictEqual(payload.research_consent,true);return r.fulfill({json:{saved:true,id:'c'.repeat(32),household_record_hash:'mock-record-hash',questionnaire_version:schema.paired_questionnaire_version,questionnaire_hash:schema.paired_questionnaire_hash}});}
 if(path==='/api/paired'){posts++;assert.strictEqual(r.request().postDataJSON().submission_id,'c'.repeat(32));assert(!('answers' in r.request().postDataJSON()));return r.fulfill({status:422,json:{error:'测试已捕获，不创建任务'}});}
  if(path.startsWith('/api/'))throw Error('Unexpected request '+path);
  const file=path==='/'?'index.html':path.slice(1);if(!['index.html','app.js','style.css','plan-view.js','time-input.js'].includes(file))return r.abort();
  return r.fulfill({contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync('static/'+file)});
 });
 // An existing v3.6 draft is retained and imported without inventing new answers.
 await page.addInitScript(a=>{if(!localStorage.getItem('eb:test-seeded')){localStorage.setItem('eb:questionnaire-draft:eb.persona_questionnaire.v3.6',JSON.stringify({answers:a,wizard_step:1}));localStorage.setItem('eb:test-seeded','1');}},answers);
 await page.goto('http://127.0.0.1:8766/');await page.locator('#p_member_0_age_band').waitFor({state:'attached'});
 assert((await page.locator('#wizard-progress').innerText()).includes('第 2 / 6'));
 assert.strictEqual(await page.locator('#p_member_0_age_band').inputValue(),'');
 async function choose(id,value){const s=page.locator('#'+id);if(await s.isVisible())return s.selectOption(value);const radios=page.locator('#'+id+' + .inline-choices input');for(let i=0;i<await radios.count();i++)if(await radios.nth(i).getAttribute('value')===value)return radios.nth(i).check();throw Error('Missing '+id+' '+value);}
 await choose('p_member_0_age_band','older');await choose('p_member_0_life_roles','retired');await choose('p_member_0_life_roles','caregiver');await choose('p_member_0_cost_importance','2');
 await page.reload();await page.locator('#p_member_0_age_band').waitFor({state:'attached'});
 assert.strictEqual(await page.locator('#p_member_0_age_band').inputValue(),'older');
 assert.deepStrictEqual(await page.locator('#p_member_0_life_roles').evaluate(s=>[...s.selectedOptions].map(o=>o.value)),['retired','caregiver']);
 assert.strictEqual(await page.locator('#p_member_1_cost_importance').inputValue(),'');
 await page.screenshot({path:out+'/members-mobile.png'});
 // All older required answers came from the draft; optional context remains unfilled.
 await page.locator('[data-wizard-step="4"]').click();assert((await page.locator('#wizard-progress').innerText()).includes('第 5 / 6'));
 await choose('p_X_REGION',JSON.stringify('广东'));await page.locator('#p_X_CITY').fill('深圳');await choose('p_X_BUILDING',JSON.stringify('apartment'));
 await page.screenshot({path:out+'/housing-mobile.png'});
 await page.locator('#wizard-next').click();assert((await page.locator('#wizard-progress').innerText()).includes('第 6 / 6'));
 await page.locator('[name=p_X_EXTRA_DEVICES]').filter({hasNotText:'zz'}).first().check();
 const none=page.locator('[name=p_X_EXTRA_DEVICES]').last();await none.check();assert.strictEqual(await page.locator('[name=p_X_EXTRA_DEVICES]:checked').count(),1);
 await page.locator('[name=p_X_EXTRA_DEVICES]').first().check();assert(!(await none.isChecked()));
 await choose('p_X_INCOME',JSON.stringify('10000_19999'));await choose('p_X_COUNT_ac',JSON.stringify('2'));
 await page.reload();await page.locator('#p_X_CITY').waitFor({state:'attached'});assert((await page.locator('#wizard-progress').innerText()).includes('第 6 / 6'));
 assert.strictEqual(await page.locator('#p_X_CITY').inputValue(),'深圳');
 await page.locator('#generate').click();await page.waitForFunction(()=>document.getElementById('error').textContent.includes('测试已捕获'));
 assert.strictEqual(posts,1);assert.strictEqual(payload.answers.X_CITY,'深圳');assert.strictEqual(payload.answers.X_INCOME,'10000_19999');assert.deepStrictEqual(payload.answers.M_MEMBERS[0].life_roles,['retired','caregiver']);assert.strictEqual(payload.answers.X_BILL,null);
 assert.strictEqual(payload.questionnaire_version,'eb.persona_questionnaire.v3.7');
 // Optional unanswered items do not prevent submission; unselected devices drop conditional research answers.
 await page.locator('[data-wizard-step="2"]').click();await page.locator('[name=p_B05]').first().uncheck();
 assert.strictEqual(await page.evaluate(()=>collect(schema.profile_questions,'p_').X_COUNT_ac),null);
 await page.locator('[data-wizard-step="0"]').click();await page.evaluate(()=>scrollTo(0,0));
 assert(await page.locator('.hero-art svg').isVisible());assert.strictEqual(await page.locator('header svg').count(),0);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:out+'/first-mobile.png'});
 await page.setViewportSize({width:1280,height:1000});await page.screenshot({path:out+'/first-desktop.png'});
 assert.deepStrictEqual(errors,[]);fs.writeFileSync(out+'/browser_report.json',JSON.stringify({passed:true,real_api_calls:0,cases:['six_pages','old_draft_migration','member_multi_select_reload','optional_context_submission','extra_inventory_none_exclusive','conditional_inventory','mobile_layout'],payload},null,2));
 console.log('Expanded household UI passed; all requests mocked.');
 }finally{await browser.close();}
})();
