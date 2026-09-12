// Current source contract and actual disposable backend; EP uses the offline fixture only.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
(async()=>{
 const origin=process.env.EB_BROWSER_ORIGIN,answers=JSON.parse(fs.readFileSync(process.env.EB_BROWSER_ANSWERS));
 if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))throw Error('Only disposable loopback test server allowed');
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
 try{for(const width of [390,1365]){
  const ctx=await browser.newContext({viewport:{width,height:900}}),page=await ctx.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
  await page.goto(origin);await page.waitForFunction(()=>typeof schema!=='undefined'&&schema?.questionnaire_context&&document.getElementById('generate').disabled===false);
  await page.locator('#wizard-next').click();assert((await page.locator('#wizard-progress').innerText()).includes('第 1 /'));
  // Populate all synthetic answers through the same restore routine used by saved drafts.
  await page.evaluate(a=>{restore(answerProfile(a));conditional();saveDraft();showWizard(0,{save:true});},answers);
  const contextHash=await page.evaluate(()=>schema.questionnaire_context.context_hash);
  await page.reload();await page.waitForFunction(()=>typeof schema!=='undefined'&&schema?.questionnaire_context&&document.getElementById('generate').disabled===false);
  assert.strictEqual(await page.evaluate(()=>schema.questionnaire_context.context_hash),contextHash);
  assert.strictEqual(await page.evaluate(()=>collect(schema.profile_questions,'p_').H_ac_temp),answers.H_ac_temp);
  // Province changes clear a stale city, then the city list follows the selected province.
  await page.evaluate(()=>{showWizard(4);const el=document.getElementById('p_X_REGION');el.value=JSON.stringify('北京');el.dispatchEvent(new Event('change',{bubbles:true}));});
  assert.strictEqual(await page.locator('#p_X_CITY').inputValue(),'');
  await page.evaluate(a=>{restore(answerProfile(a));conditional();saveDraft();showWizard(0);},answers);
  const count=await page.evaluate(()=>wizardSteps().length);
  for(let i=1;i<count;i++){await page.locator('#wizard-next').click();assert((await page.locator('#wizard-progress').innerText()).includes(`第 ${i+1} /`));}
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#generate').click();
  await page.waitForFunction(()=>!document.getElementById('decision-form').hidden||!document.getElementById('error').hidden||['failed','timeout','interrupted'].includes(currentJob?.status),{},{timeout:120000});
  assert(await page.locator('#decision-form').isVisible(),await page.locator('body').innerText());
  assert(await page.locator('.schedule-board').count()>0);
  assert((await page.locator('#result-panel').innerText()).includes('制冷设定'));
  await page.locator('[name=decision][value=reject]').check();
  for(const [key,value] of Object.entries({score:'3.75',comfort_score:'2.5',energy_score:'4.1',vpp_score:'2.25'}))await page.locator(`[name=feedback_${key}]`).fill(value);
  await page.locator('#decision-reason').fill('Synthetic browser audit, not a human response.');
  await page.reload();await page.locator('#decision-form').waitFor({state:'visible'});
  assert.strictEqual(await page.locator('[name=feedback_score]').inputValue(),'3.75');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#save-decision').click();await page.waitForFunction(()=>document.getElementById('decision-status').textContent.includes('已保存'));
  await page.reload();await page.waitForFunction(()=>document.getElementById('decision-status').textContent.includes('已保存'));
  assert.deepStrictEqual(errors,[]);await ctx.close();console.log(`Current ${width}px: annual context, draft, cities, ${count} pages, native EP, timeline, decimal feedback and reload passed.`);
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
