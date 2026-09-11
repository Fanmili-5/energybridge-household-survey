// All requests intercepted: exercise the four-page form without real jobs/APIs.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
(async()=>{
 const source='ui_audit_20260911/members',out='ui_audit_20260911/wizard';fs.mkdirSync(out,{recursive:true});
 const schema=JSON.parse(fs.readFileSync(source+'/schema.json')),answers=JSON.parse(fs.readFileSync(source+'/answers.json'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined});
 try{const ctx=await browser.newContext({viewport:{width:390,height:844}}),page=await ctx.newPage(),errors=[];let submits=0,payload;
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{const r=route.request(),path=new URL(r.url()).pathname;
  if(path==='/api/session')return route.fulfill({json:schema});
  if(path==='/api/households'){payload=r.postDataJSON();assert.strictEqual(payload.research_consent,true);return route.fulfill({json:{saved:true,id:'c'.repeat(32),household_record_hash:'mock-record-hash',questionnaire_version:schema.paired_questionnaire_version,questionnaire_hash:schema.paired_questionnaire_hash}});}
 if(path==='/api/paired'){submits++;assert.strictEqual(r.postDataJSON().submission_id,'c'.repeat(32));assert(!('answers' in r.postDataJSON()));return route.fulfill({status:422,json:{error:'测试捕获提交，未创建真实任务'}});}
  if(path.startsWith('/api/'))throw Error('Unexpected API '+path);
  const name=path==='/'?'index.html':path.slice(1);if(!['index.html','app.js','style.css','time-input.js','plan-view.js'].includes(name))return route.abort();
  return route.fulfill({contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync('static/'+name)});
 });
 async function choose(id,value){const select=page.locator('#'+id);if(await select.isVisible())return select.selectOption(value);const radios=page.locator('#'+id+' + .inline-choices input');for(let i=0;i<await radios.count();i++)if(await radios.nth(i).getAttribute('value')===value)return radios.nth(i).check();throw Error('Missing choice '+id);}
 const progress=()=>page.locator('#wizard-progress').innerText();
 await page.goto('http://127.0.0.1:8766/');await page.locator('#p_B02').waitFor({state:'attached'});
 assert((await progress()).includes('第 1 / 4'));assert(await page.locator('[data-form-page="1"]').isHidden());
 await page.locator('#wizard-next').click();assert((await progress()).includes('第 1 / 4'));assert.strictEqual(submits,0);
 for(const id of ['B02','B04','F_EVENING','F_REGULARITY','F_LATE_USE'])await choose('p_'+id,JSON.stringify(answers[id]));
 await page.locator('#wizard-next').click();assert((await progress()).includes('第 2 / 4'));assert(await page.locator('.survey-hero').isHidden());assert.strictEqual(await page.locator('.member-card:visible').count(),3);
 await page.locator('#wizard-next').click();assert((await progress()).includes('第 2 / 4'));
 for(let i=0;i<3;i++)await choose('p_member_'+i+'_routine','out_regular');
 await choose('p_member_0_comfort','temp_sensitive');await page.reload();await page.locator('#p_member_0_routine').waitFor({state:'attached'});assert((await progress()).includes('第 2 / 4'));assert.strictEqual(await page.locator('#p_member_0_comfort').inputValue(),'temp_sensitive');
 await page.locator('#wizard-prev').click();assert((await progress()).includes('第 1 / 4'));await page.locator('#wizard-next').click();assert.strictEqual(await page.locator('#p_member_0_comfort').inputValue(),'temp_sensitive');
 await page.locator('#wizard-next').click();assert((await progress()).includes('第 3 / 4'));
 await page.locator('#wizard-next').click();assert((await progress()).includes('第 3 / 4'));assert.strictEqual(submits,0);
 // A household with only AC: other equipment's required inputs must stay inapplicable.
 await page.locator('[name=p_B05]').filter({visible:true}).first().check();
 const acValue=await page.locator('[name=p_B05]').first().getAttribute('value');assert.strictEqual(acValue,JSON.stringify('ac'));
 for(const id of ['H_ac','H_ac_temp','P_AC_RANGE','P_AC_CHANGE'])await choose('p_'+id,JSON.stringify(answers[id]));
 await page.locator('#wizard-next').click();assert((await progress()).includes('第 4 / 4'));assert(await page.locator('#generate').isVisible());
 // Browser Back should restore the preceding page, without resubmitting.
 await page.goBack();assert((await progress()).includes('第 3 / 4'));await page.goForward();assert((await progress()).includes('第 4 / 4'));
 await page.locator('#generate').click();assert.strictEqual(submits,0);
 for(const id of ['P_COMFORT','P_COST','P_GRID','P_NOTICE','A_EB_CONTROL']){const radios=page.locator('[name="p_'+id+'"]');for(let i=0;i<await radios.count();i++)if(await radios.nth(i).getAttribute('value')===JSON.stringify(answers[id]))await radios.nth(i).check();}
 await page.locator('#wizard-nav').evaluate(e=>e.scrollIntoView({block:'start'}));await page.screenshot({path:out+'/last-step-mobile.png'});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.locator('#generate').click();await page.waitForFunction(()=>document.getElementById('error').textContent.includes('测试捕获提交'));
 assert.strictEqual(submits,1);assert.deepStrictEqual(payload.answers.B05,['ac']);assert.strictEqual(payload.answers.M_MEMBERS.length,3);assert.strictEqual(payload.answers.M_MEMBERS[0].comfort,'temp_sensitive');assert.strictEqual(payload.answers.P_EV_TARGET,null);assert.strictEqual(payload.answers.P_GRID,'3');
 await page.locator('[data-wizard-step="0"]').click();await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:out+'/first-step-mobile.png'});
 await page.setViewportSize({width:1280,height:1000});await page.screenshot({path:out+'/first-step-desktop.png'});
 assert.deepStrictEqual(errors,[]);fs.writeFileSync(out+'/report.json',JSON.stringify({passed:true,actual_api_calls:0,cases:['required_per_page','forward_back_preserves_answers','refresh_page_and_draft','browser_back_forward','unselected_equipment_skipped','single_final_complete_payload','mobile_no_overflow']},null,2));console.log('Four-page wizard checks passed; no real API calls.');
 }finally{await browser.close();}
})();
