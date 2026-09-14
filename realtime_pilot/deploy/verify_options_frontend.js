process.chdir(require('path').resolve(__dirname,'..'));
// Isolated option audit: every request is mocked; no records or real model API calls.
const { chromium }=require('playwright'),fs=require('fs'),assert=require('assert');
(async()=>{
 const out='ui_audit_20260911/options_audit';fs.mkdirSync(out,{recursive:true});
 const schema=JSON.parse(fs.readFileSync(out+'/schema.json'));schema.planning_enabled=true;schema.jobs=[];
 const answers=JSON.parse(fs.readFileSync('ui_audit_20260911/members/answers.json'));
 answers.B02='6_plus';answers.M_MEMBERS=Array.from({length:6},(_,i)=>({routine:'home_regular',comfort:'temp_sensitive',task:'flexible',participation:i===0?'important':'shared',age_band:'adult',life_roles:['home_work','caregiver'],grid_importance:'4'}));
 for(const q of schema.paired_questions.filter(q=>q.id.startsWith('X_FREQ_')))answers[q.id]='daily';
 answers.X_RESTORE='keep';answers.X_AREA='90_119';
 const seeded=JSON.stringify({answers,wizard_step:1});
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];let posts=0,payload;
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>{const path=new URL(r.request().url()).pathname;
   if(path==='/api/session')return r.fulfill({json:schema});
   if(path==='/api/households'){payload=r.request().postDataJSON();assert.strictEqual(payload.research_consent,true);return r.fulfill({json:{saved:true,id:'c'.repeat(32),household_record_hash:'mock-record-hash',questionnaire_version:schema.paired_questionnaire_version,questionnaire_hash:schema.paired_questionnaire_hash}});}
 if(path==='/api/paired'){posts++;assert.strictEqual(r.request().postDataJSON().submission_id,'c'.repeat(32));assert(!('answers' in r.request().postDataJSON()));return r.fulfill({status:422,json:{error:'隔离测试已捕获，不创建任务'}});}
   if(path.startsWith('/api/'))return r.abort();
   const file=path==='/'?'index.html':path.slice(1);if(!['index.html','app.js','style.css','plan-view.js','time-input.js'].includes(file))return r.abort();
   return r.fulfill({contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync('static/'+file)});
  });
  await page.addInitScript(seed=>{if(!localStorage.getItem('eb:options-test-seed')){localStorage.setItem('eb:questionnaire-draft:eb.persona_questionnaire.v3.7',seed);localStorage.setItem('eb:options-test-seed','1');}},seeded);
  await page.goto('http://127.0.0.1:8766/');await page.locator('#p_member_0_routine').waitFor({state:'attached'});
  async function choose(id,value){const s=page.locator('#'+id);if(await s.isVisible())return s.selectOption(value);const inputs=page.locator('#'+id+' + .inline-choices input');for(let i=0;i<await inputs.count();i++)if(await inputs.nth(i).getAttribute('value')===value)return inputs.nth(i).check();throw Error('Missing option '+id+'='+value);}
  assert.strictEqual(await page.locator('#p_member_0_participation').inputValue(),'');
  assert.strictEqual(await page.locator('#p_member_1_participation').inputValue(),'');
  assert.strictEqual(await page.locator('#p_member_0_grid_importance').inputValue(),'');
  assert.strictEqual(await page.locator('#p_X_RESTORE').inputValue(),'');
  assert.strictEqual(await page.locator('#p_X_AREA').inputValue(),'');
  assert.strictEqual(await page.locator('#p_member_0_comfort').inputValue(),'temp_sensitive');
  for(const q of schema.paired_questions.filter(q=>q.id.startsWith('X_FREQ_')))assert.strictEqual(await page.locator('#p_'+q.id).inputValue(),'');
  assert.strictEqual(await page.evaluate(()=>localStorage.getItem('eb:questionnaire-draft:eb.persona_questionnaire.v3.7')),seeded);
  // Unfilled removed member must not leave hidden required inputs enabled.
  await page.locator('[data-member-add]').click();assert.strictEqual(await page.locator('.member-card:not([hidden])').count(),7);
  await page.locator('[data-member-remove]').click();assert.strictEqual(await page.locator('.member-card:not([hidden])').count(),6);
  assert.strictEqual(await page.locator('.member-card[hidden] input:required:enabled').count(),0);
  await page.locator('#wizard-next').click();assert((await page.locator('#wizard-progress').innerText()).includes('电器安排'));
  // Flexible tasks collect the window first; the usual-start slider is derived from it.
  assert.deepStrictEqual(await page.locator('[data-device-card="washer"] .device-fields>.field').evaluateAll(rows=>rows.slice(0,4).map(r=>r.dataset.questionId)),['E_washer','D_washer','T_washer','H_washer']);
  await choose('p_E_washer',JSON.stringify('8'));await choose('p_D_washer',JSON.stringify('22'));await choose('p_T_washer',JSON.stringify('1.5'));
  let legalStarts=await page.locator('#p_H_washer').evaluate(s=>[...s.options].map(o=>o.value));assert(!legalStarts.includes(JSON.stringify('21')));assert(legalStarts.includes(JSON.stringify('20.5')));
  await choose('p_H_washer',JSON.stringify('20.5'));await choose('p_D_washer',JSON.stringify('21'));
  assert.strictEqual(await page.locator('#p_H_washer').inputValue(),'');
  legalStarts=await page.locator('#p_H_washer').evaluate(s=>[...s.options].map(o=>o.value));assert(legalStarts.includes(JSON.stringify('19.5')));
  await choose('p_H_washer',JSON.stringify('19.5'));
  // Explicit custom AC window crosses midnight, and newly added start times render literally.
  await choose('p_H_ac',JSON.stringify('custom'));
  assert(await page.locator('[data-question-id="H_ac_start"]').isVisible());
  await choose('p_H_ac_start',JSON.stringify('22'));await choose('p_H_ac_end',JSON.stringify('8'));
  assert((await page.locator('#habit_ac').innerText()).includes('22:00'));
  assert((await page.locator('#habit_ac').innerText()).includes('次日'));
  await choose('p_H_home_ev',JSON.stringify('19'));
  assert((await page.locator('#habit_home_ev').innerText()).includes('19:00'));
  await page.locator('[data-wizard-step="5"]').click();
  for(const id of ['X_EXTRA_DEVICES','X_PROTECTED']){
   const opts=page.locator('[name=p_'+id+']');let none,first;
   for(let i=0;i<await opts.count();i++){const item=opts.nth(i),value=JSON.parse(await item.getAttribute('value'));if(value==='none')none=item;else if(!first)first=item;}
   assert(none&&first);await first.check();await none.check();assert.strictEqual(await page.locator('[name=p_'+id+']:checked').count(),1);
   await first.check();assert(!(await none.isChecked()));await none.check();await none.uncheck();assert.strictEqual(await page.locator('[name=p_'+id+']:checked').count(),0);
  }
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:out+'/options-mobile.png'});
  await page.reload();await page.locator('#p_H_ac').waitFor({state:'attached'});
  assert.strictEqual(await page.locator('#p_H_ac').inputValue(),JSON.stringify('custom'));
  assert.strictEqual(await page.locator('#p_H_ac_start').inputValue(),JSON.stringify('22'));
  await page.locator('#research-consent').check();await page.locator('#scenario-understood').check();
  await page.locator('#generate').click();await page.waitForFunction(()=>document.getElementById('error').textContent.includes('隔离测试已捕获'));
  assert.strictEqual(posts,1);assert.strictEqual(payload.answers.M_MEMBERS.length,6);assert.strictEqual(payload.answers.M_MEMBERS[0].participation,null);
  assert.strictEqual(payload.answers.H_ac_start,'22');assert.strictEqual(payload.answers.H_ac_end,'8');assert.strictEqual(payload.answers.H_home_ev,'19');
  assert.deepStrictEqual(payload.answers.X_EXTRA_DEVICES,[]);assert.deepStrictEqual(payload.answers.X_PROTECTED,[]);
  assert.deepStrictEqual(errors,[]);
  const result={passed:true,real_api_calls:0,cases:['v37_migration_preserves_source','semantic_fields_not_reinterpreted','six_plus_removed_required_disabled','optional_none_exclusive_and_clear','task_window_first','derived_legal_usual_start','invalidated_start_cleared','custom_ac_overnight','new_ev_time_preview','reload_and_final_payload'],questionnaire_version:schema.paired_questionnaire_version};
  fs.writeFileSync(out+'/frontend_options_report.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})();
