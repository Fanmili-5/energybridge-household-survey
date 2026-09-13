process.chdir(require('path').resolve(__dirname,'..'));
// Full frontend lifecycle audit. All routes mocked; no live storage/API/EP access.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
(async()=>{
 const out='ui_audit_20260911/collection_lifecycle';fs.mkdirSync(out,{recursive:true});
 const baseSchema=JSON.parse(fs.readFileSync('ui_audit_20260911/options_audit/schema.json'));
 const baseAnswers=JSON.parse(fs.readFileSync('ui_audit_20260911/members/answers.json'));
 const fixture=JSON.parse(fs.readFileSync('ui_audit_20260911/fixture.json'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined}),reports=[];
 const id=n=>n.toString(16).padStart(32,'0');
 const profile=a=>Object.fromEntries(Object.entries(a).map(([k,value])=>[k,{value,response_status:value==null?'skipped':'answered'}]));
 async function setup({paused=true,seed=true,history=false,intakeLost=false,queueFail=false,holdDecision=false}={}){
  const schema=structuredClone(baseSchema),answers=structuredClone(baseAnswers);schema.planning_enabled=!paused;schema.jobs=[];schema.households=[];
  const households=new Map(),intakeKeys=new Map(),jobs=new Map(),intakes=[],plans=[],decisions=[],errors=[];
  if(history)for(const n of [2,1])jobs.set(id(n),{...structuredClone(fixture),id:id(n),profile:profile(answers),questionnaire_snapshot:schema.paired_questions,questionnaire_version:schema.paired_questionnaire_version,decision_saved:false});
  let releaseDecision;let resolvePost;const decisionPosted=new Promise(r=>resolvePost=r);
  const ctx=await browser.newContext({viewport:{width:390,height:844}}),page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));
  if(seed)await page.addInitScript(({version,answers})=>{if(!localStorage.getItem('lifecycle-seeded')){localStorage.setItem('eb:questionnaire-draft:'+version,JSON.stringify({answers,wizard_step:5}));localStorage.setItem('eb:active-view',JSON.stringify({mode:'draft',questionnaire_version:version}));localStorage.setItem('lifecycle-seeded','1');}},{version:schema.paired_questionnaire_version,answers});
  await page.route('**/*',async r=>{
   const req=r.request(),path=new URL(req.url()).pathname;
   if(path==='/api/session')return r.fulfill({json:{...schema,jobs:[...jobs.values()],households:[...households.values()].map(h=>({id:h.id,created_at:h.created_at,questionnaire_version:h.questionnaire_version,questionnaire_hash:h.questionnaire_hash,household_record_hash:h.household_record_hash,case_ids:[...jobs.values()].filter(j=>j.submission_id===h.id).map(j=>j.id)}))}});
   if(path==='/api/households'&&req.method()==='POST'){
    const p=req.postDataJSON();intakes.push(p);let hid=intakeKeys.get(p.request_id);
    if(!hid){hid=id(100+households.size);intakeKeys.set(p.request_id,hid);households.set(hid,{id:hid,saved:true,created_at:Date.now()/1000,household_record_hash:'record-'+hid,questionnaire_version:p.questionnaire_version,questionnaire_hash:p.questionnaire_hash,raw_answers:p.answers,profile:profile(p.answers),questionnaire_snapshot:schema.paired_questions});}
    if(intakeLost&&intakes.length===1)return r.abort();return r.fulfill({json:households.get(hid)});
   }
   if(path.startsWith('/api/households/'))return r.fulfill({json:households.get(path.split('/')[3])});
   if(path==='/api/paired'){
    const p=req.postDataJSON();plans.push(p);if(queueFail&&plans.length===1)return r.fulfill({status:429,json:{error:'排队人数较多，请稍后重试'}});
    const h=households.get(p.submission_id);assert(h);const j={...structuredClone(fixture),id:id(200),submission_id:h.id,profile:h.profile,questionnaire_snapshot:h.questionnaire_snapshot,questionnaire_version:h.questionnaire_version,decision_saved:false};jobs.set(j.id,j);return r.fulfill({json:j});
   }
   if(path.endsWith('/decision')){
    const p=req.postDataJSON(),jid=path.split('/')[3];decisions.push({jid,p});resolvePost();if(holdDecision)await new Promise(done=>releaseDecision=done);
    jobs.get(jid).decision_saved=true;jobs.get(jid).decision=p;return r.fulfill({json:{saved:true}});
   }
   if(path.startsWith('/api/jobs/'))return r.fulfill({json:jobs.get(path.split('/')[3])});
   if(path.startsWith('/api/'))throw Error('Unexpected API '+path);
   const file=path==='/'?'index.html':path.slice(1);if(!['index.html','app.js','plan-view.js','time-input.js','style.css'].includes(file))return r.abort();
   return r.fulfill({body:fs.readFileSync('static/'+file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto('http://127.0.0.1:8766/');await page.locator('#p_B02').waitFor({state:'attached'});
  return{ctx,page,schema,households,jobs,intakes,plans,decisions,errors,decisionPosted,release:()=>releaseDecision()};
 }
 async function confirmResearch(page){
  await page.locator('#research-consent').check();
  await page.locator('#scenario-understood').check();
 }
 try{
  let x=await setup(),p=x.page;
  assert(await p.locator('#generate').isEnabled());assert.strictEqual(await p.locator('#generate').innerText(),'保存家庭资料');
  await confirmResearch(p);
  await p.locator('#generate').click();await p.locator('#household-receipt').waitFor({state:'visible'});
  assert.strictEqual(x.intakes.length,1);assert.strictEqual(x.plans.length,0);assert.strictEqual(x.intakes[0].research_consent,true);assert.strictEqual(x.intakes[0].scenario_understood,true);assert.strictEqual(x.intakes[0].research_notice_version,'eb.research_notice.v2');
  assert(await p.locator('#plan-saved').isDisabled());assert(await p.locator('#p_B02').isEnabled());
  const first=id(100);assert.strictEqual(await p.locator('#receipt-id').innerText(),first);
  await p.reload();await p.locator('#household-receipt').waitFor({state:'visible'});assert.strictEqual(await p.locator('#receipt-id').innerText(),first);assert.strictEqual(x.intakes.length,1);
  await p.evaluate(()=>localStorage.clear());await p.reload();await p.locator('#household-receipt').waitFor({state:'visible'});assert(await p.evaluate(()=>receiptMatches()));assert.strictEqual(x.intakes.length,1);
  await p.locator('[data-wizard-step="4"]').click();await p.locator('#p_X_CITY').fill('资料保存后修改');await p.locator('#wizard-next').click();await confirmResearch(p);await p.locator('#generate').click();await p.waitForFunction(first=>document.getElementById('receipt-id').textContent!==first,first);
  assert.strictEqual(x.households.size,2);assert.notStrictEqual(x.households.get(first).raw_answers.X_CITY,'资料保存后修改');assert.deepStrictEqual(x.errors,[]);
  assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await p.screenshot({path:out+'/saved-mobile.png'});
  reports.push({case:'paused_intake_receipt_refresh_new_revision',passed:true,intakes:x.intakes.length,plans:x.plans.length});await x.ctx.close();
  x=await setup({paused:false,queueFail:true});p=x.page;await confirmResearch(p);await p.locator('#generate').click();await p.waitForFunction(()=>document.getElementById('error').textContent.includes('排队人数'));
  assert.strictEqual(x.intakes.length,1);assert(await p.locator('#household-receipt').isVisible());await p.locator('#plan-saved').click();await p.locator('#decision-form').waitFor({state:'visible'});
  assert.strictEqual(x.intakes.length,1);assert.strictEqual(x.plans.length,2);assert.strictEqual(x.plans[0].request_id,x.plans[1].request_id);assert.strictEqual(x.plans[0].submission_id,x.plans[1].submission_id);assert(!('answers' in x.plans[1]));assert.deepStrictEqual(x.errors,[]);
  reports.push({case:'queue_failure_preserves_receipt_retry_same_plan_request',passed:true});await x.ctx.close();
  x=await setup({intakeLost:true});p=x.page;await confirmResearch(p);await p.locator('#generate').click();await p.waitForFunction(()=>!document.getElementById('error').hidden);
  assert.strictEqual(x.households.size,1);await confirmResearch(p);await p.locator('#generate').click();await p.locator('#household-receipt').waitFor({state:'visible'});assert.strictEqual(x.intakes.length,2);assert.strictEqual(x.intakes[0].request_id,x.intakes[1].request_id);assert.strictEqual(x.households.size,1);assert.deepStrictEqual(x.errors,[]);
  reports.push({case:'intake_response_lost_idempotent_retry',passed:true});await x.ctx.close();
  x=await setup({seed:false,history:true});p=x.page;await p.locator('#decision-form').waitFor({state:'visible'});await p.locator('#new-case').click();
  const changed=await p.evaluate(()=>{let s=document.getElementById('p_B04');s.value=[...s.options].find(o=>o.value&&o.value!==s.value).value;s.dispatchEvent(new Event('change',{bubbles:true}));return s.value;});
  await p.reload();await p.locator('#p_B04').waitFor({state:'attached'});assert.strictEqual(await p.locator('#p_B04').inputValue(),changed);assert(await p.locator('#decision-form').isHidden());await p.locator('#new-case').click();assert.strictEqual(await p.locator('#p_B04').inputValue(),changed);assert.deepStrictEqual(x.errors,[]);
  reports.push({case:'new_draft_not_overwritten_by_history_on_refresh',passed:true});await x.ctx.close();
  x=await setup({seed:false,history:true,holdDecision:true});p=x.page;await p.locator('#decision-form').waitFor({state:'visible'});
  const bid=id(2),hash=fixture.result.display_hash;
  await p.evaluate(({bid,hash})=>localStorage.setItem('eb:decision-draft:'+bid+':'+hash,JSON.stringify({choice:'reject',scores:{score:'4.4',comfort_score:'2',energy_score:'3',vpp_score:'4'},comment:'B 未提交理由'})),{bid,hash});
  await p.locator('[name=decision][value=accept]').check();for(const k of ['score','comfort_score','energy_score','vpp_score'])await p.locator('[name=feedback_'+k+']').fill('3');await p.locator('#save-decision').click();await x.decisionPosted;
  await p.evaluate(id=>loadJob(id),bid);x.release();await p.waitForTimeout(100);
  assert(await p.evaluate(({bid,hash})=>!!localStorage.getItem('eb:decision-draft:'+bid+':'+hash),{bid,hash}));assert.strictEqual(x.decisions.length,1);assert.strictEqual(x.jobs.get(bid).decision_saved,false);
  await p.reload();await p.locator('#decision-form').waitFor({state:'visible'});assert.strictEqual(await p.locator('#decision-reason').inputValue(),'B 未提交理由');assert.strictEqual(await p.locator('[name=feedback_score]').inputValue(),'4.4');assert.deepStrictEqual(x.errors,[]);
  reports.push({case:'decision_inflight_navigation_preserves_other_draft',passed:true});await x.ctx.close();
  fs.writeFileSync(out+'/report.json',JSON.stringify({passed:true,real_api_calls:0,reports},null,2));console.log(JSON.stringify(reports));
 }finally{await browser.close();}
})();
