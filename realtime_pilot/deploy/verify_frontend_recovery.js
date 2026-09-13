process.chdir(require('path').resolve(__dirname,'..'));
// Isolated UI regression: every API response is a fixture; no live writes or LLM calls.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
(async()=>{
 const root=process.cwd(),out=root+'/ui_audit_20260911/fixes';fs.mkdirSync(out,{recursive:true});
 const schema=JSON.parse(fs.readFileSync(root+'/ui_audit_20260911/session.json')),fixture=JSON.parse(fs.readFileSync(root+'/ui_audit_20260911/fixture.json'));
 schema.questionnaire_context={context_hash:'offline-browser-fixture',label:'9月12日 · 秋季',instruction:'兼容旧记录的显示测试。'};
 const origin='http://127.0.0.1:8766';
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined});
 const reports=[];
 async function setup(mode){
  const ctx=await browser.newContext({viewport:{width:390,height:844}}),page=await ctx.newPage();let reads=0,sessionReads=0,posts=0,saved=false,payload,alternate=false;const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{const req=route.request(),path=new URL(req.url()).pathname;
   if(!path.startsWith('/api/')){const name=path==='/'?'index.html':path.slice(1);if(!['index.html','app.js','plan-view.js','time-input.js','style.css'].includes(name))return route.abort();return route.fulfill({contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync('static/'+name)});}
   let job=structuredClone(fixture);if(alternate)job.id='b'.repeat(32);if(saved){job.decision_saved=true;job.decision=payload;}
   let body,status=200;
   if(req.method()!=='GET'){posts++;assert(path.endsWith('/decision'),'Unexpected mutation');payload=req.postDataJSON();saved=true;body={saved:true};}
   else if(path==='/api/session'){sessionReads++;if(mode==='session'&&sessionReads===1){status=503;body={error:'temporary session failure'};}else body={...schema,planning_enabled:false,jobs:['paused','session'].includes(mode)?[]:[job]};}
   else if(path.endsWith('/status'))body={id:job.id,status:'complete',created_at:job.created_at};
   else{reads++;if((mode==='initial'&&reads===1)||(mode==='terminal'&&reads===2)){status=503;body={error:'temporary fixture failure'};}else body=mode==='terminal'&&reads===1?{...job,status:'running',result:undefined}:job;}
   return route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  });await page.goto(origin);return {page,ctx,errors,state:()=>({reads,sessionReads,posts,payload}),alternate:v=>{alternate=v;}};
 }
 try{
  let x=await setup('paused'),p=x.page;await p.locator('[data-question-id]').first().waitFor();assert(await p.locator('#generate').isEnabled());assert.strictEqual(await p.locator('#generate').innerText(),'保存家庭资料');assert(await p.locator('#planning-status').isVisible());assert(await p.locator('.history-panel').isHidden());await p.locator('#new-case').evaluate(button=>button.click());assert(await p.locator('#generate').isEnabled());reports.push({case:'paused',passed:true,...x.state()});await p.screenshot({path:out+'/paused-mobile.png'});assert.deepStrictEqual(x.errors,[]);await x.ctx.close();
  x=await setup('feedback');p=x.page;await p.locator('#decision-form').waitFor({state:'visible'});
  await p.locator('[name=decision][value=reject]').check();for(const [k,v] of Object.entries({score:'3.75',comfort_score:'2.5',energy_score:'4.1',vpp_score:'2.25'}))await p.locator(`[name=feedback_${k}]`).fill(v);await p.locator('#decision-reason').fill('工程测试草稿');
  await p.reload();await p.locator('#decision-form').waitFor({state:'visible'});assert.strictEqual(await p.locator('[name=feedback_score]').inputValue(),'3.75');assert.strictEqual(await p.locator('#decision-reason').inputValue(),'工程测试草稿');assert(await p.locator('[name=decision][value=reject]').isChecked());
  // Same browser, different result ID must not borrow this draft.
  x.alternate(true);await p.reload();await p.locator('#decision-form').waitFor({state:'visible'});assert.strictEqual(await p.locator('[name=feedback_score]').inputValue(),'');x.alternate(false);await p.reload();await p.locator('#decision-form').waitFor({state:'visible'});
  await p.waitForTimeout(100);const pan=await p.evaluate(()=>{let s=document.querySelector('.schedule-scroll'),e=s.querySelector('.event-shade').getBoundingClientRect(),r=s.getBoundingClientRect(),label=s.querySelector('.schedule-device').getBoundingClientRect();const heading=s.querySelector('.schedule-group h3 strong').getBoundingClientRect();return {headingLeft:heading.left,headingRight:heading.right,scroll:s.scrollLeft,eventLeft:e.left,eventRight:e.right,labelRight:label.right,viewportRight:r.right,overflow:document.documentElement.scrollWidth>innerWidth};});assert(pan.headingLeft>=0&&pan.headingRight<=390);assert(pan.scroll>0&&pan.eventLeft>=pan.labelRight-1&&pan.eventRight<=pan.viewportRight+1&&!pan.overflow);await p.locator('#result-panel').evaluate(e=>e.scrollIntoView({block:'start'}));await p.screenshot({path:out+'/timeline-mobile.png'});
  await p.locator('#save-decision').click();await p.waitForFunction(()=>document.getElementById('decision-status').textContent.includes('选择、四项评分和原因已保存'));assert.strictEqual(x.state().payload.score,3.75);assert.strictEqual(await p.evaluate(()=>Object.keys(localStorage).filter(k=>k.startsWith('eb:decision-draft:')).length),0);reports.push({case:'draft_roundtrip_isolation_submit',passed:true,...x.state(),pan});assert.deepStrictEqual(x.errors,[]);await x.ctx.close();
  x=await setup('session');p=x.page;await p.locator('[data-question-id]').first().waitFor({timeout:10000});assert(x.state().sessionReads>=2);assert(await p.locator('#generate').isEnabled());reports.push({case:'session_failure_recovery',passed:true,...x.state()});assert.deepStrictEqual(x.errors,[]);await x.ctx.close();
  for(const mode of ['initial','terminal']){x=await setup(mode);p=x.page;await p.locator('#decision-form').waitFor({state:'visible',timeout:15000});assert(x.state().reads>=(mode==='initial'?2:3));assert(await p.locator('#error').isHidden());reports.push({case:mode+'_failure_recovery',passed:true,...x.state()});assert.deepStrictEqual(x.errors,[]);await x.ctx.close();}
  fs.writeFileSync(out+'/report.json',JSON.stringify(reports,null,2));console.log(JSON.stringify(reports));
 }finally{await browser.close();}
})();
