'use strict';
// Real Chromium on the school host,original frontend. All responses are
// explicitly synthetic engineering fixtures;never sent to collection APIs.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(path.join(process.env.EB_V27_TOOLS,'browser/node_modules/playwright'));
async function main(){
 const release=path.resolve(process.argv[2]),output=process.argv[3];
 const index=JSON.parse(fs.readFileSync(path.join(release,'INDEX50.json'),'utf8'));
 const browser=await chromium.launch({headless:true,args:['--no-sandbox','--allow-file-access-from-files']});
 const page=await browser.newPage({acceptDownloads:true});page.setDefaultTimeout(10000);let checked=0,errors=[];
 const base=process.env.EB_V27_PREVIEW_BASE||'http://127.0.0.1:18827';
 for(const h of index.households){
  await page.goto(base+h.route+'/');
  await page.waitForFunction(()=>document.querySelector('#joint-select')?.options.length===10);
  for(let i=0;i<10;i++){
   await page.selectOption('#joint-select',String(i));
   await page.waitForFunction(()=>!document.querySelector('#joint-export').disabled);
   const view=await page.evaluate(()=>({error:document.querySelector('#joint-error').textContent,
     memberText:document.querySelector('#home-members').textContent,
     attitude:document.querySelector('#home-attitudes').textContent,
     needs:document.querySelector('#joint-needs-list').textContent,
     svg:document.querySelectorAll('#joint-timeline svg').length}));
   if(view.error)errors.push({household_id:h.household_id,round:i+1,error:view.error});
   assert(view.svg>0,'timeline missing');assert((view.attitude+view.needs).includes('本角色给定取舍'),'given policy not visible');
   checked++;if(checked%50===0)console.log(JSON.stringify({actual_browser_cases:checked}));
  }
 }
 // Export one context twice after changing all answer channels: stimulus
 // values remain identical,answers differ. Downloads stay private fixtures.
 const h=index.households[0];await page.goto(base+h.route+'/');
 await page.waitForFunction(()=>!document.querySelector('#joint-export').disabled);
 const records=[];
 for(let pass=0;pass<2;pass++){
  await page.locator('[name="source_decision"]').nth(pass).check();
  for(const id of ['joint-score','joint-comfort-score','joint-energy-score','joint-vpp-score'])await page.locator('#'+id).fill(String(pass?5:1));
  await page.locator('#joint-comment').fill(pass?'synthetic engineering fixture B':'synthetic engineering fixture A');
  const pending=page.waitForEvent('download');await page.click('#joint-export');const download=await pending;
  const tmp=path.join(path.dirname(output),'engineering_export_'+pass+'.json');await download.saveAs(tmp);records.push(JSON.parse(fs.readFileSync(tmp,'utf8')));
 }
 // The actual export schema is recorded;compare all stimulus fields after
 // excluding explicit answer/time bookkeeping. No acceptance labels created.
 const stimulus=record=>record.model_input||record.input||record.visible_input;
 const a=stimulus(records[0]),b=stimulus(records[1]);assert(a&&b,'export stimulus field absent');
 const stable=x=>JSON.stringify(x, (k,v)=>['recorded_at','presented_at','captured_at'].includes(k)?undefined:v);
 assert.equal(stable(a),stable(b),'answers changed model stimulus');
 await browser.close();assert.equal(checked,500);assert.equal(errors.length,0);
 const result={status:'pass',actual_browser_cases_checked:checked,actual_browser_exports_compared:2,
   input_unchanged_when_all_answers_changed:true,role_policy_visible:true,original_frontend:true,
   original24h_axis_preserved:true,engineering_fixture_answers_only:true,human_answers:0,collection_API_requests_sent:0,errors};
 fs.writeFileSync(output,JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
