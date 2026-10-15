'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const c=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const {chromium}=require(path.join(c.tools,'browser/node_modules/playwright'));
async function main(){
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});let checked=0,errors=[];const samples=[];
 async function until(page,fn,arg){const end=Date.now()+20000;while(Date.now()<end){if(await page.evaluate(fn,arg))return;await new Promise(r=>setTimeout(r,50));}throw Error('browser state timeout: '+fn);}
 async function claim(page,credential){
  await page.goto(c.origin+c.prefix);await page.locator('#credential').fill(credential);await page.locator('#claim-form button').click();
  await page.locator('#recovery-panel').waitFor({state:'visible'});const code=await page.locator('#recovery-code').inputValue();await page.locator('#assigned-link').click();
  await until(page,()=>document.querySelector('#joint-select')?.options.length===10);
  if(await page.locator('#formal-consent-controls').isVisible()){await page.locator('#formal-consent-accept').check();await page.locator('#formal-consent-submit').click();}
  await until(page,()=>!document.querySelector('#joint-export').disabled);return code;
 }
 try{
  async function inspect(hi,h){
   const context=await browser.newContext({ignoreHTTPSErrors:true});const page=await context.newPage();page.setDefaultTimeout(20000);page.on('pageerror',e=>errors.push(String(e)));
   const recovery=await claim(page,h.credential);
   for(let i=0;i<10;i++){
    await page.selectOption('#joint-select',String(i));const expected=h.cases[i];
    await until(page,date=>document.querySelector('#joint-date').textContent.includes(date)&&!document.querySelector('#joint-export').disabled,expected.identity.date);
    assert(await page.locator('#joint-results').isVisible(),'modeled consequences not visible to actor');
    const view=await page.evaluate(()=>({error:document.querySelector('#joint-error').textContent,changes:document.querySelector('#joint-changes').textContent,results:document.querySelector('#joint-results').textContent,policy:document.querySelector('#home-attitudes').textContent,svg:document.querySelectorAll('#joint-timeline svg').length}));
    assert.equal(view.error,'');assert(view.svg>0);assert(view.policy.includes('本角色给定取舍'));
    for(const cmd of expected.commands)assert(view.changes.includes(cmd.display_change_text),'actual visible command differs from source');
    for(const result of expected.impacts)if(result.status!=='unknown'&&result.description)assert(view.results.includes(result.description),'actual consequence differs from source');
    for(const result of expected.quantities){
     const fmt=x=>x.value==null?'未计算':`${Math.round(x.value*1000)/1000} ${x.unit}`;
     assert(view.results.includes(`${result.label}：A ${fmt(result.A)}；B ${fmt(result.B)}`),'actual A/B quantity not shown');
    }
    assert.equal(expected.plans.A.window_end_abs_min-expected.plans.A.window_start_abs_min,1440);checked++;
   }
   if(hi===0){
    await page.selectOption('#joint-select','0');await until(page,date=>document.querySelector('#joint-date').textContent.includes(date),h.cases[0].identity.date);
    const records=[];
    for(let pass=0;pass<2;pass++){
     await page.locator('[name="source_decision"]').nth(pass).check();
     for(const id of ['joint-score','joint-comfort-score','joint-energy-score','joint-vpp-score'])await page.locator('#'+id).fill(String(pass?4:2));
     await page.locator('#joint-comment').fill('invented engineering fixture '+pass+'; no human answer');
     await page.locator('#respondent-age').fill(String(pass?46:22));await page.selectOption('#respondent-gender',pass?'female':'male');
     const waiting=page.waitForResponse(r=>r.url().endsWith('/api/answers')&&r.request().method()==='POST');await page.locator('#joint-export').click();const response=await waiting;
     assert.equal(response.status(),201,await response.text());records.push(response.request().postDataJSON().record);
     await until(page,()=>document.querySelector('#joint-status').textContent.startsWith('答卷已提交')||document.querySelector('#joint-status').textContent.includes('此日期已有答卷'));
    }
    assert.deepEqual(records[0].input.fields,records[1].input.fields);assert.deepEqual(records[0].audit.source_case,records[1].audit.source_case);assert.notDeepEqual(records[0].respondent,records[1].respondent);assert.notDeepEqual(records[0].response,records[1].response);
    await page.locator('#formal-logout').evaluate(el=>el.closest('details').open=true);await page.locator('#formal-logout').click();await page.waitForURL(c.origin+c.prefix);
    const resumed=await browser.newContext({ignoreHTTPSErrors:true});const p2=await resumed.newPage();await claim(p2,recovery);
    await until(p2,()=>document.querySelector('#respondent-age').value==='46');assert.equal(await p2.locator('#respondent-gender').inputValue(),'female');assert((await p2.locator('#joint-comment').inputValue()).includes('fixture 1'));
    await p2.locator('#formal-withdraw').evaluate(el=>el.closest('details').open=true);await p2.locator('#formal-withdraw').click();await p2.locator('#formal-withdraw').click();await until(p2,()=>document.querySelector('#formal-progress').textContent.startsWith('已撤回全部答卷'));
    samples.push({household_id:h.household_id,actual_submit_revision_recovery_withdrawal:true});await resumed.close();
   }
   await context.close();if(checked%100===0)console.log(JSON.stringify({actual_browser_cases_checked:checked}));
  }
  let next=0;await Promise.all(Array.from({length:4},async()=>{while(next<c.fixtures.length){const i=next++;await inspect(i,c.fixtures[i]);}}));
  assert.equal(errors.length,0);assert.equal(checked,c.fixtures.length*10);
  const result={passed:true,validation_concurrency:4,release_signature:c.release_signature,source_case_count:c.source_case_count,actual_browser_cases_checked:checked,visible_change_text_matches_source:true,current_answer_and_respondent_outside_model_input:true,actual_submit_recovery_revision_withdrawal_passed:samples.length===1,all_cases_24_hours:true,given_role_policy_visible:true,browser:'school Chromium / actual shipped formal release',household_sampling:c.fixtures.length*10===c.source_case_count?'complete census':'deterministic evenly spaced complete households',errors,samples};
  result.visible_modeled_consequences_match_source=true;result.consequence_cases_checked=checked;
  fs.writeFileSync(c.output,JSON.stringify(result,null,2));
 }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
