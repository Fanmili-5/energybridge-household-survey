// Offline queue UX regression: every HTTP request is mocked, no planner/API execution.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
(async()=>{
 const out='ui_audit_20260911/queue_frontend';fs.mkdirSync(out,{recursive:true});
 const schema=JSON.parse(fs.readFileSync('ui_audit_20260911/options_audit/schema.json'));
 const answers=JSON.parse(fs.readFileSync('ui_audit_20260911/members/answers.json'));
 const fixture=JSON.parse(fs.readFileSync('ui_audit_20260911/fixture.json'));
 const originalId='a'.repeat(32),nextId='b'.repeat(32),submissionId='c'.repeat(32),now=Date.now()/1000;
 const record={id:submissionId,created_at:now-50,raw_answers:answers,household_record_hash:'frozen-household-hash',questionnaire_version:schema.paired_questionnaire_version,questionnaire_hash:schema.paired_questionnaire_hash};
 const profile=Object.fromEntries(Object.entries(answers).map(([k,value])=>[k,{value,response_status:value==null?'skipped':'answered'}]));
 const initial={...structuredClone(fixture),id:originalId,profile,questionnaire_snapshot:schema.paired_questions,questionnaire_version:schema.paired_questionnaire_version,household_submission_id:submissionId,status:'queued',message:'家庭资料已保存，前面还有 1 个等待任务。',created_at:now-40,started_at:null,finished_at:null,estimated_wait_seconds:30,estimate_basis:'configured_cold_start',queue_position:2,queue_wait_limit_seconds:300,poll_after_ms:1000};
 delete initial.result;const jobs=new Map([[originalId,initial]]);let posts=[],intakes=0,statusReads=0,errors=[];
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}});page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>{const req=r.request(),path=new URL(req.url()).pathname;
   if(path==='/api/session')return r.fulfill({json:{...schema,planning_enabled:true,jobs:[...jobs.values()],households:[{...record,raw_answers:undefined,case_ids:[...jobs.values()].filter(j=>j.household_submission_id===submissionId).map(j=>j.id)}]}});
   if(path==='/api/households/'+submissionId)return r.fulfill({json:record});
   if(path==='/api/households'){intakes++;throw Error('Existing saved household must not be resubmitted');}
   if(path==='/api/paired'){
    const body=req.postDataJSON();posts.push(body);
    if(posts.length===1)return r.fulfill({status:429,json:{error:'队列等待过长，请稍后手动重试。家庭资料已保存。'}});
    const job={...structuredClone(initial),id:nextId,status:'queued',created_at:Date.now()/1000,started_at:null,finished_at:null,queue_seconds:undefined,message:'家庭资料已保存，前面还有 0 个等待任务。',queue_position:1,estimated_wait_seconds:20,estimate_basis:'recent_runs'};jobs.set(nextId,job);return r.fulfill({json:job});
   }
   if(path.startsWith('/api/jobs/')){const jid=path.split('/')[3];if(path.endsWith('/status'))statusReads++;return r.fulfill({json:jobs.get(jid)});}
   if(path.startsWith('/api/'))throw Error('Unexpected API '+path);
   const file=path==='/'?'index.html':path.slice(1);if(!['index.html','app.js','style.css','time-input.js','plan-view.js'].includes(file))return r.abort();
   return r.fulfill({body:fs.readFileSync('static/'+file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  const poll=()=>page.evaluate(()=>{clearTimeout(timer);return pollJob(currentJob.id,generation);});
  await page.goto('http://127.0.0.1:8766/');await page.locator('#job-panel').waitFor({state:'visible'});
  let text=await page.locator('#job-timing').innerText();assert(text.includes('已排队'));assert(text.includes('30秒'));assert(text.includes('开始计算'));assert(text.includes('暂按初始估算'));assert(!text.includes('完成'));
  assert((await page.locator('#queue-policy').innerText()).includes('5分'));assert(await page.locator('#retry-generation').isHidden());assert.strictEqual(posts.length,0);
  await page.locator('#job-panel').evaluate(e=>e.scrollIntoView({block:'start'}));await page.screenshot({path:out+'/queued-mobile.png'});
  initial.estimated_wait_seconds=90;initial.estimate_basis='recent_runs';initial.queue_position=3;initial.message='家庭资料已保存，前面还有 2 个等待任务。';await poll();
  text=await page.locator('#job-timing').innerText();assert(text.includes('1分30秒'));assert(text.includes('根据近期任务估算'));assert((await page.locator('#job-status').innerText()).includes('2 个'));
  initial.estimated_wait_seconds=null;await poll();text=await page.locator('#job-timing').innerText();assert(text.includes('暂时无法估算'));assert(!text.includes('预计即将'));
  initial.status='running';initial.started_at=Date.now()/1000-10;initial.queue_seconds=30;initial.message='正在运行 EnergyPlus';await poll();text=await page.locator('#job-timing').innerText();assert(text.includes('先前排队 30秒'));assert(text.includes('计算用时'));assert(!text.includes('预计'));assert(await page.locator('#queue-policy').isHidden());
  initial.status='expired';initial.started_at=null;initial.finished_at=Date.now()/1000;initial.queue_seconds=40;initial.message='等待已超过上限，本次排队结束。家庭资料仍保留，可以稍后手动重试。';await poll();
  assert((await page.locator('#job-heading').innerText()).includes('排队已结束'));assert(await page.locator('#cancel').isHidden());assert(await page.locator('#retry-generation').isEnabled());assert.strictEqual(posts.length,0);assert(await page.locator('#p_B02').isDisabled());
  assert((await page.locator('#job-status').innerText()).includes('家庭资料仍保留'));assert((await page.locator('#job-timing').innerText()).includes('尚未开始计算'));
  await page.locator('#job-panel').evaluate(e=>e.scrollIntoView({block:'start'}));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:out+'/expired-mobile.png'});
  // Retrying a historical frozen submission must not delete a separate unfinished questionnaire.
  const newerId='d'.repeat(32);jobs.set(newerId,{...structuredClone(initial),id:newerId,status:'failed',created_at:now+1});record.case_ids=[originalId,newerId];
  await page.evaluate(({answers,version})=>localStorage.setItem('eb:questionnaire-draft:'+version,JSON.stringify({answers:{...answers,X_CITY:'另一份未提交草稿'},wizard_step:4})),{answers,version:schema.paired_questionnaire_version});
  await page.locator('#retry-generation').click();await page.waitForFunction(()=>!document.getElementById('error').hidden);assert.strictEqual(posts.length,1);assert.strictEqual(intakes,0);assert.strictEqual(posts[0].submission_id,submissionId);assert.strictEqual(posts[0].household_record_hash,record.household_record_hash);assert(!('answers' in posts[0]));
  const nonce=posts[0].request_id;await page.reload();await page.locator('#retry-generation').waitFor({state:'visible'});assert.strictEqual(posts.length,1);assert.strictEqual(await page.evaluate(()=>currentJob.id),originalId);
  assert.strictEqual(await page.evaluate(()=>JSON.parse(localStorage.getItem('eb:pending-plan')).request_id),nonce);
  await page.locator('#retry-generation').click();await page.waitForFunction(id=>currentJob?.id===id,nextId);
  assert.strictEqual(posts.length,2);assert.strictEqual(posts[1].request_id,nonce);assert.strictEqual(intakes,0);assert.strictEqual(jobs.get(originalId).status,'expired');
  assert.strictEqual(await page.evaluate(version=>JSON.parse(localStorage.getItem('eb:questionnaire-draft:'+version)).answers.X_CITY,schema.paired_questionnaire_version),'另一份未提交草稿');
  // Existing failed and timed-out jobs also expose explicit retry; older records without an intake open the review flow.
  for(const status of ['failed','timeout','interrupted','cancelled']){initial.status=status;initial.started_at=now-20;await page.evaluate(id=>loadJob(id),originalId);assert(await page.locator('#retry-generation').isEnabled());assert.strictEqual(posts.length,2);}
  delete initial.household_submission_id;initial.status='failed';await page.evaluate(id=>loadJob(id),originalId);assert.strictEqual(await page.locator('#retry-generation').innerText(),'核对资料后重试');await page.locator('#retry-generation').click();assert(await page.locator('#job-panel').isHidden());assert(await page.locator('#p_B02').isEnabled());assert.strictEqual(posts.length,2);
  assert.deepStrictEqual(errors,[]);
  const result={passed:true,real_api_calls:0,intakes,manual_plan_requests:posts.length,status_reads:statusReads,cases:['queued_start_eta_cold_start','eta_updates_recent_runs','eta_null_is_unknown','running_queue_and_compute_separated','expired_no_auto_generation','frozen_submission_manual_retry_429_refresh_same_nonce','unrelated_draft_preserved','failed_timeout_retry','legacy_review_before_retry','mobile_no_overflow']};
  fs.writeFileSync(out+'/report.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})();
