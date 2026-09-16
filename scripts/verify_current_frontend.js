// Current source contract and actual disposable backend; EP uses the offline fixture only.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
(async()=>{
 const origin=process.env.EB_BROWSER_ORIGIN,answers=JSON.parse(fs.readFileSync(process.env.EB_BROWSER_ANSWERS)),intakeOnly=process.env.EB_BROWSER_INTAKE_ONLY==='1',axePath=process.env.EB_AXE_PATH;
 if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))throw Error('Only disposable loopback test server allowed');
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
 try{for(const width of [390,1365]){
  const ctx=await browser.newContext({viewport:{width,height:900}});if(axePath)await ctx.addInitScript({path:axePath});const page=await ctx.newPage(),errors=[],accessibility=[];
  const audit=async label=>{if(!axePath)return;const violations=await page.evaluate(async()=>{const result=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}});return result.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)}));});if(violations.length)accessibility.push({label,violations});};
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
  // Hold full-record GETs: admission must show waiting directly from POST.
  let recordReads=0;
  await page.route('**/api/jobs/*',async r=>{if(r.request().method()==='GET'&&/\/api\/jobs\/[^/]+$/.test(new URL(r.request().url()).pathname)){recordReads++;await new Promise(resolve=>setTimeout(resolve,1800));}await r.continue();});
  await page.goto(origin);await page.waitForFunction(()=>typeof schema!=='undefined'&&schema?.questionnaire_context&&document.getElementById('generate').disabled===false);
  assert(await page.locator('.history-panel').isHidden());
  const migrated=await page.evaluate(()=>migrateAnswers({B02:'2',H_ac:'evening',A_EB_CONTROL:'suggestion_first',M_MEMBERS:[{age_band:'adult',routine:'out_regular',control:'suggest',comfort:'normal_comfort',task:'flexible'}]},'eb.persona_questionnaire.v4.4',schema.questionnaire_context.context_hash));
  assert.strictEqual(migrated.B02,'2');assert.strictEqual(migrated.H_ac,'evening');
  assert.strictEqual(migrated.A_EB_CONTROL,null);assert.strictEqual(migrated.M_MEMBERS[0].control,null);
  assert.strictEqual(migrated.M_MEMBERS[0].comfort,null);assert.strictEqual(migrated.M_MEMBERS[0].task,null);
  assert.strictEqual(migrated.M_MEMBERS[0].age_band,'adult');assert.strictEqual(migrated.M_MEMBERS[0].routine,'out_regular');

  // Empty pages can be browsed freely; only the final submit checks completeness.
  await page.locator('#participant-name').fill('自由跳转测试');
  await page.locator('#wizard-next').click();assert((await page.locator('#wizard-progress').innerText()).includes('第 2 /'));
  for(const step of [4,2,5,6]){
   await page.locator(`[data-wizard-step="${step}"]`).click();
   assert((await page.locator('#wizard-progress').innerText()).includes(`第 ${step+1} /`));
  }
  await page.locator('#generate').click();
  assert((await page.locator('#wizard-progress').innerText()).includes('第 1 /'));
  assert.strictEqual(await page.locator('#participant-name').inputValue(),'自由跳转测试');
  assert.strictEqual(await page.evaluate(()=>savedReceipt),null);
  // Fill through visible controls, not the application's restore/collect helpers.
  // Follow the rendered form: task windows and duration precede usual start.
  const questions=await page.evaluate(()=>[...document.querySelectorAll('[data-question-id]')].map(row=>schema.profile_questions.find(q=>q.id===row.dataset.questionId)).filter(Boolean));
  const count=await page.locator('[data-wizard-step]').count();
  for(let step=0;step<count;step++){
   for(const q of questions){
    const row=page.locator(`[data-question-id="${q.id}"]`),value=answers[q.id];
    if(value==null||!await row.isVisible())continue;
    if(q.type==='member_list'){
     assert.strictEqual(await row.locator('.member-card:visible').count(),1);
     // Browsing members/pages is free; final submit returns to the missing member.
     await page.locator('#wizard-next').click();
     assert.strictEqual(await row.getAttribute('data-active-member'),'1');
     await row.locator('.member-navigation button').last().click();
     await page.locator('[data-wizard-step="2"]').click();
     assert((await page.locator('#wizard-progress').innerText()).includes('第 3 /'));
     await page.locator('[data-wizard-step="6"]').click();await page.locator('#generate').click();
     assert((await page.locator('#wizard-progress').innerText()).includes('第 2 /'));
     assert.strictEqual(await page.locator('#p_M_MEMBERS').getAttribute('data-active-member'),'0');
     for(let i=0;i<value.length;i++){
      assert.strictEqual(await row.locator('.member-card:visible').count(),1);
      assert.strictEqual(await row.getAttribute('data-active-member'),String(i));
      for(const [field,v] of Object.entries(value[i])){
       if(v==null)continue;
       for(const option of Array.isArray(v)?v:[v])await row.locator(`input[name="p_member_${i}_${field}__choices"]`).filter({visible:true}).locator(`xpath=self::input[@value='${option}']`).check();
      }
      if(i<value.length-1)await page.locator('#wizard-next').click();
     }
     const members=await page.evaluate(()=>collect(schema.profile_questions,'p_').M_MEMBERS);
     assert.strictEqual(members.length,value.length);
     for(let i=0;i<value.length;i++)for(const [field,v] of Object.entries(value[i]))assert.deepStrictEqual(members[i][field],v);
     await page.reload();await page.waitForFunction(()=>typeof schema!=='undefined'&&schema?.questionnaire_context&&document.getElementById('generate').disabled===false);
     assert.strictEqual(await row.getAttribute('data-active-member'),String(value.length-1));
     assert.deepStrictEqual(await page.evaluate(()=>collect(schema.profile_questions,'p_').M_MEMBERS),members);
    }else if(q.type==='temperature_range'){const parts=value.split('_');await page.locator('#p_'+q.id+'_low').fill(parts[0]);await page.locator('#p_'+q.id+'_high').fill(parts[1]);
    }else if(q.cities_by_region){await page.locator('#p_'+q.id+'_choices').selectOption(value);}
    else if(q.type==='text'){await page.locator('#p_'+q.id).fill(value);}
    else if(await row.locator('input[type=range]').count()){
     const slider=row.locator('input[type=range]');
     const available=await page.locator('#p_'+q.id).evaluate(s=>[...s.options].filter(o=>o.value!=='').map(o=>JSON.parse(o.value)));
     const index=available.indexOf(value);
     assert(index>=0,`Missing option for ${q.id}`);
     await slider.focus();await slider.press('End');await slider.press('Home');
     for(let i=0;i<index;i++)await slider.press('ArrowRight');
     assert.strictEqual(await page.locator('#p_'+q.id).inputValue(),JSON.stringify(value));
    }else if(await row.locator('input[type=radio],input[type=checkbox]').count()){
     for(const option of Array.isArray(value)?value:[value])await row.locator('input').filter({visible:true}).locator(`xpath=self::input[@value='${JSON.stringify(option)}']`).check();
    }else{await page.locator('#p_'+q.id).selectOption(JSON.stringify(value));}
   }
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   if(step===1){
    await page.locator('.member-navigation button').first().click();
    const field=page.locator('.member-card').first().locator('[data-member-field="comfort"]').locator('..');
    const previous=await field.locator('select').inputValue();
    if(previous){await field.locator('.choice-clear').click();assert.strictEqual(await field.locator('select').inputValue(),'');assert(await field.locator('.choice-clear').isHidden());await field.locator(`input[value="${previous}"]`).check();}
   }
   if(process.env.EB_BROWSER_SCREENSHOTS&&[0,1,2,4,5].includes(step)){fs.mkdirSync(process.env.EB_BROWSER_SCREENSHOTS,{recursive:true});await page.screenshot({path:process.env.EB_BROWSER_SCREENSHOTS+'/answers-step-'+step+'-'+width+'.png',fullPage:true});}
   await audit(`wizard-${step}`);
   if(step===1)await page.locator('.member-navigation button').last().click();
   if(step<count-1){await page.locator('#wizard-next').click();assert((await page.locator('#wizard-progress').innerText()).includes(`第 ${step+2} /`));}
  }
  const contextHash=await page.evaluate(()=>schema.questionnaire_context.context_hash);
  await page.reload();await page.waitForFunction(()=>typeof schema!=='undefined'&&schema?.questionnaire_context&&document.getElementById('generate').disabled===false);
  assert.strictEqual(await page.evaluate(()=>schema.questionnaire_context.context_hash),contextHash);
  assert.strictEqual(await page.evaluate(()=>collect(schema.profile_questions,'p_').H_ac_temp),answers.H_ac_temp);
  assert.strictEqual(await page.evaluate(()=>collect(schema.profile_questions,'p_').P_AC_RANGE),answers.P_AC_RANGE);
  assert.strictEqual(await page.locator('#p_P_AC_RANGE_low').inputValue(),answers.P_AC_RANGE.split('_')[0]);
  assert.strictEqual(await page.evaluate(()=>collect(schema.profile_questions,'p_').H_washer),answers.H_washer);
  // Exercise the real version-key migration, preserving a valid old answer.
  const originalDraft=await page.evaluate(()=>{const key='eb:questionnaire-draft:'+schema.paired_questionnaire_version;const draft=localStorage.getItem(key);const old=JSON.parse(draft);old.answers.H_ac_temp='26.5';old.answers.P_AC_RANGE='24_26';old.answers.H_washer='evening';localStorage.setItem('eb:questionnaire-draft:eb.persona_questionnaire.v4.3',JSON.stringify(old));localStorage.removeItem(key);return draft;});
  await page.reload();await page.waitForFunction(()=>typeof schema!=='undefined'&&schema?.questionnaire_context&&document.getElementById('generate').disabled===false);
  assert.strictEqual(await page.evaluate(()=>collect(schema.profile_questions,'p_').H_washer),'evening');
  assert.strictEqual(await page.locator('#p_P_AC_RANGE_low').inputValue(),'24');
  await page.evaluate(draft=>{localStorage.setItem('eb:questionnaire-draft:'+schema.paired_questionnaire_version,draft);localStorage.removeItem('eb:questionnaire-draft:eb.persona_questionnaire.v4.3');},originalDraft);
  await page.reload();await page.waitForFunction(()=>typeof schema!=='undefined'&&schema?.questionnaire_context&&document.getElementById('generate').disabled===false);
  // Province changes clear a stale city, then the city list follows the selected province.
  await page.locator('[data-wizard-step="4"]').click();
  await page.locator('#p_X_REGION').selectOption(JSON.stringify('北京'));
  assert.strictEqual(await page.locator('#p_X_CITY').inputValue(),'');
  await page.locator('#p_X_REGION').selectOption(JSON.stringify(answers.X_REGION));
  await page.locator('#p_X_CITY_choices').selectOption(answers.X_CITY);
  await page.locator('#wizard-next').click();
  assert(await page.locator('.skip-optional').isVisible());
  assert(await page.locator('#submission-confirm').isHidden());
  await page.locator('#skip-optional').click();
  assert(await page.locator('#submission-confirm').isVisible());
  assert(await page.locator('[data-form-page="5"]').isHidden());
  assert(await page.locator('#questionnaire-context').isHidden());
  await page.locator('#wizard-prev').click();assert(await page.locator('#submission-confirm').isHidden());
  await page.locator('#wizard-next').click();
  if(process.env.EB_BROWSER_SCREENSHOTS)await page.screenshot({path:process.env.EB_BROWSER_SCREENSHOTS+'/submit-'+width+'.png',fullPage:true});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  // Consent is an active participant action and must never be inferred from
  // merely opening the final page.
  await page.locator('#generate').click();
  assert(await page.locator('#household-receipt').isHidden());
  assert.strictEqual(await page.locator('#research-consent').isChecked(),false);
  await page.locator('#research-consent').check();
  await page.locator('#scenario-understood').check();
  await page.locator('#generate').click();
  if(!intakeOnly&&process.env.EB_BROWSER_CAPTCHA==='1'){
   await page.locator('#captcha-dialog').waitFor({state:'visible'});
   await page.waitForFunction(()=>!document.getElementById('captcha-answer').disabled);
   assert(await page.evaluate(()=>!currentJob));
   await page.locator('#captcha-answer').fill('AAAAAA');await page.locator('#captcha-confirm').click();
   await page.waitForFunction(()=>document.getElementById('captcha-message').textContent.includes('不正确'));
   assert(await page.evaluate(()=>!currentJob));
   if(process.env.EB_BROWSER_SCREENSHOTS){fs.mkdirSync(process.env.EB_BROWSER_SCREENSHOTS,{recursive:true});await page.locator('#captcha-dialog').screenshot({path:process.env.EB_BROWSER_SCREENSHOTS+'/captcha-'+width+'.png'});}
   // Exhaust the old image. The user must receive a fresh image automatically.
   await page.locator('#captcha-answer').fill('AAAAAA');await page.locator('#captcha-confirm').click();
   await page.waitForFunction(()=>document.getElementById('captcha-message').textContent.includes('还可以尝试 1 次'));
   const nextImage=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/captcha'&&r.status()===200);
   await page.locator('#captcha-answer').fill('AAAAAA');await page.locator('#captcha-confirm').click();
   await nextImage;await page.waitForFunction(()=>document.getElementById('captcha-message').textContent.includes('已换好新图片')&&!document.getElementById('captcha-answer').disabled);
   assert.strictEqual(await page.locator('#captcha-answer').inputValue(),'');
   assert(await page.evaluate(()=>!currentJob));
   await page.locator('#captcha-answer').fill('ac2346');await page.locator('#captcha-confirm').click();
   await page.locator('#captcha-dialog').waitFor({state:'hidden'});
   await page.locator('#job-panel').waitFor({state:'visible'});
   assert(await page.locator('#profile-details').isHidden());
   assert(await page.locator('.survey-hero').isHidden());
   assert.strictEqual(recordReads,0,'Waiting view must not wait on a second full-record GET');
   assert(await page.locator('#waiting-guidance').isVisible());
   assert(await page.locator('#job-heading').evaluate(e=>e.getBoundingClientRect().top>=0&&e.getBoundingClientRect().top<innerHeight));
   if(process.env.EB_BROWSER_SCREENSHOTS)await page.screenshot({path:process.env.EB_BROWSER_SCREENSHOTS+'/waiting-'+width+'.png'});
  }
  if(intakeOnly){
   await page.locator('#household-receipt').waitFor({state:'visible'});
   assert((await page.locator('#receipt-status').innerText()).includes('已保存'));
   page.once('dialog',dialog=>dialog.accept());
   await page.locator('#clear-device-data').click();
   await page.waitForFunction(()=>document.getElementById('household-receipt').hidden&&localStorage.getItem('eb:household-receipt')===null);
   assert.deepStrictEqual(errors,[]);assert.deepStrictEqual(accessibility,[]);await ctx.close();console.log(`Current ${width}px: active consent, intake receipt, shared-device reset and responsive layout passed.`);continue;
  }
  await page.waitForFunction(()=>!document.getElementById('decision-form').hidden||!document.getElementById('error').hidden||['failed','timeout','interrupted'].includes(currentJob?.status),{},{timeout:120000});
  assert(await page.locator('#decision-form').isVisible(),await page.locator('body').innerText());
  assert(await page.locator('#job-panel').isHidden());
  assert(await page.locator('.survey-hero').isHidden());
  try{
   // Scrolling rounds the document offset to a CSS pixel; the title may be
   // less than one pixel above zero even when correctly aligned and visible.
   await page.waitForFunction(()=>{const y=document.getElementById('comparison-title').getBoundingClientRect().top;return y>=-1&&y<innerHeight;},null,{timeout:3000});
  }catch(e){
   await page.screenshot({path:'/tmp/eb-audit-result-navigation.png'});
   console.error('Result navigation geometry',await page.evaluate(()=>({scrollY,viewport:innerHeight,title:document.getElementById('comparison-title').getBoundingClientRect().toJSON(),panel:document.getElementById('result-panel').getBoundingClientRect().toJSON(),active:document.activeElement.id})));
   throw e;
  }
  assert((await page.locator('.feedback-reason').innerText()).includes('必填'));
  assert(await page.locator('.schedule-board').count()>0);
  const view=await page.evaluate(()=>currentJob.result.display.participant_view);
  assert.strictEqual(view.render_contract_version,'eb.participant_view.v2');
  assert(view.schedule_chart.end_h>24,'Actual comparison must include next-day simulation');
  assert.strictEqual(view.statistics_window.duration_h,24);
  assert.strictEqual(view.statistics_window.end_sim_h-view.statistics_window.start_sim_h,24);
  assert((await page.locator('#plan-visual').innerText()).includes('统计24小时'));
  const pairs=await page.locator('.device-pair').evaluateAll(nodes=>nodes.map(n=>({device:n.dataset.device,rows:[...n.querySelectorAll('.schedule-row')].map(r=>({device:r.dataset.device,side:r.dataset.side}))})));
  assert.strictEqual(pairs.length,view.schedule_chart.rows.length);
  for(const pair of pairs)assert.deepStrictEqual(pair.rows,[{device:pair.device,side:'original'},{device:pair.device,side:'proposal'}]);
  assert(view.metrics.some(m=>m.label==='24小时用电量'));
  assert(await page.locator('.schedule-scroll').evaluate(e=>e.scrollWidth<=e.clientWidth+1),'Full timeline including next day fits by default');
  await page.getByRole('button',{name:'放大查看',exact:true}).click();
  assert.strictEqual(await page.getByRole('button',{name:'放大查看',exact:true}).getAttribute('aria-pressed'),'true');
  await page.getByRole('button',{name:'完整时段',exact:true}).click();


  assert(await page.locator('#legacy-evidence').isHidden());
  assert.strictEqual(await page.locator('#result-panel details').count(),0);
  for(const metric of view.metrics){
   const row=page.locator('.outcome-metric').filter({hasText:metric.label});
   assert(await row.isVisible(),'Every metric must be visible: '+metric.label);
   assert((await row.textContent()).replace(/\s/g,'').includes(metric.original.replace(/\s/g,'')));assert((await row.textContent()).replace(/\s/g,'').includes(metric.proposal.replace(/\s/g,'')));
  }
  assert(!(await page.locator('#result-panel').innerText()).includes('同一个家庭 · 同一个情境'));
  assert(!(await page.locator('#result-panel').innerText()).includes('未验证'));
  const waterRow=page.locator('.outcome-service').filter({hasText:'电热水器'});
  assert((await waterRow.textContent()).includes('水箱温度'));
  assert(!(await waterRow.textContent()).includes('出水'));
  if(process.env.EB_BROWSER_SCREENSHOTS)await page.locator('#result-panel').screenshot({path:process.env.EB_BROWSER_SCREENSHOTS+'/comparison-'+width+'.png'});
  const recovery=await page.evaluate(async()=>{
   const savedApi=api,out=[];clearTimeout(timer);timer=null;
   try{
    for(const status of [503,404]){
     api=async()=>{throw Object.assign(new Error('fixture transport failure'),{status});};
     await pollJob(currentJob.id,generation);
     out.push({status,retry:timer!==null,message:$('connection-status').textContent});
     clearTimeout(timer);timer=null;
    }
    renderJobState({...currentJob,status:'failed'});
    out.push({failedGuidance:$('waiting-guidance').textContent,retryVisible:!$('retry-generation').hidden});
   }finally{api=savedApi;renderJobState(currentJob);}
   return out;
  });
  assert.strictEqual(recovery[0].retry,true);assert(recovery[0].message.includes('无需再次生成'));
  assert.strictEqual(recovery[1].retry,false);assert(recovery[1].message.includes('已停止查询'));
  assert(recovery[2].failedGuidance.includes('无需重新填写'));assert(recovery[2].retryVisible);
  await page.locator('[name=decision][value=reject]').check();
  for(const [key,value] of Object.entries({score:'3.75',comfort_score:'2.5',energy_score:'4.1',vpp_score:'2.25'}))await page.locator(`[name=feedback_${key}]`).fill(value);
  await page.locator('#decision-reason').fill('Synthetic browser audit, not a human response.');
  await page.reload();await page.locator('#resume-result').waitFor({state:'visible'});
  assert(await page.locator('#profile-details').isVisible());assert(await page.locator('#result-panel').isHidden());
  assert((await page.locator('#wizard-progress').innerText()).includes('第 1 /'));
  await page.locator('#resume-result').click();await page.locator('#decision-form').waitFor({state:'visible'});
  assert.strictEqual(await page.locator('[name=feedback_score]').inputValue(),'3.75');
  assert((await page.locator('#score-meaning-score').innerText()).includes('3.75 分 · 一般与较合适之间'));
  if(process.env.EB_BROWSER_SCREENSHOTS)await page.locator('#decision-form').screenshot({path:process.env.EB_BROWSER_SCREENSHOTS+'/score-'+width+'.png'});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await audit('result-and-feedback');
  // Failed feedback saves must keep the answers and must never show success.
  let rejectSave=true;
  await page.route('**/api/jobs/*/decision',async r=>{if(rejectSave){rejectSave=false;await r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Synthetic temporary save failure'})});}else await r.continue();});
  await page.locator('#save-decision').click();await page.waitForFunction(()=>!document.getElementById('save-decision').disabled);
  assert(await page.locator('#feedback-complete').isHidden());
  assert.strictEqual(await page.locator('[name=feedback_score]').inputValue(),'3.75');
  // After a successful POST, no result GET is needed for the completion screen.
  const readsBeforeSave=recordReads;
  await page.locator('#save-decision').click();await page.locator('#feedback-complete').waitFor({state:'visible'});
  assert.strictEqual(recordReads,readsBeforeSave);
  assert(await page.locator('#result-panel').isHidden());assert(await page.locator('#decision-form').isHidden());
  assert.strictEqual(await page.evaluate(()=>document.activeElement.id),'feedback-complete-heading');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await audit('feedback-complete');
  if(process.env.EB_BROWSER_SCREENSHOTS)await page.screenshot({path:process.env.EB_BROWSER_SCREENSHOTS+'/complete-'+width+'.png',fullPage:true});
  await page.locator('#view-saved-feedback').click();assert(await page.locator('#feedback-complete').isHidden());
  assert.strictEqual(await page.locator('[name=feedback_score]').inputValue(),'3.75');assert(await page.locator('#save-decision').isDisabled());
  await page.reload();await page.locator('#resume-result').waitFor({state:'visible'});
  assert(await page.locator('#result-panel').isHidden());
  assert.strictEqual(await page.locator('#resume-result').innerText(),'查看已保存的评价');
  await page.locator('#resume-result').click();await page.waitForFunction(()=>document.getElementById('decision-status').textContent.includes('已保存'));
  assert.deepStrictEqual(errors,[]);assert.deepStrictEqual(accessibility,[]);await ctx.close();console.log(`Current ${width}px: annual context, draft, cities, ${count} pages, native EP, timeline, decimal feedback and reload passed.`);
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
