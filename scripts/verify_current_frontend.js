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
  // Fill through visible controls, not the application's restore/collect helpers.
  const questions=await page.evaluate(()=>schema.profile_questions);
  const count=await page.locator('[data-wizard-step]').count();
  for(let step=0;step<count;step++){
   for(const q of questions){
    const row=page.locator(`[data-question-id="${q.id}"]`),value=answers[q.id];
    if(value==null||!await row.isVisible())continue;
    if(q.type==='member_list'){
     assert.strictEqual(await row.locator('.member-card:visible').count(),value.length);
     for(let i=0;i<value.length;i++)for(const [field,v] of Object.entries(value[i])){
      if(v==null)continue;
      for(const option of Array.isArray(v)?v:[v])await row.locator(`input[name="p_member_${i}_${field}__choices"]`).filter({visible:true}).locator(`xpath=self::input[@value='${option}']`).check();
     }
    }else if(q.cities_by_region){await page.locator('#p_'+q.id+'_choices').selectOption(value);}
    else if(q.type==='text'){await page.locator('#p_'+q.id).fill(value);}
    else if(await row.locator('input[type=range]').count()){
     const slider=row.locator('input[type=range]'),index=q.options.findIndex(o=>o.value===value);
     assert(index>=0,`Missing option for ${q.id}`);
     await slider.focus();await slider.press('End');await slider.press('Home');
     for(let i=0;i<index;i++)await slider.press('ArrowRight');
     assert.strictEqual(await page.locator('#p_'+q.id).inputValue(),JSON.stringify(value));
    }else if(await row.locator('input[type=radio],input[type=checkbox]').count()){
     for(const option of Array.isArray(value)?value:[value])await row.locator('input').filter({visible:true}).locator(`xpath=self::input[@value='${JSON.stringify(option)}']`).check();
    }else{await page.locator('#p_'+q.id).selectOption(JSON.stringify(value));}
   }
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   if(step<count-1){await page.locator('#wizard-next').click();assert((await page.locator('#wizard-progress').innerText()).includes(`第 ${step+2} /`));}
  }
  const contextHash=await page.evaluate(()=>schema.questionnaire_context.context_hash);
  await page.reload();await page.waitForFunction(()=>typeof schema!=='undefined'&&schema?.questionnaire_context&&document.getElementById('generate').disabled===false);
  assert.strictEqual(await page.evaluate(()=>schema.questionnaire_context.context_hash),contextHash);
  assert.strictEqual(await page.evaluate(()=>collect(schema.profile_questions,'p_').H_ac_temp),answers.H_ac_temp);
  // Province changes clear a stale city, then the city list follows the selected province.
  await page.locator('[data-wizard-step="4"]').click();
  await page.locator('#p_X_REGION').selectOption(JSON.stringify('北京'));
  assert.strictEqual(await page.locator('#p_X_CITY').inputValue(),'');
  await page.locator('#p_X_REGION').selectOption(JSON.stringify(answers.X_REGION));
  await page.locator('#p_X_CITY_choices').selectOption(answers.X_CITY);
  await page.locator('#wizard-next').click();
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
