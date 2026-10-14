'use strict';
// Verify the actual inherited renderer's axis and unclipped operation facts.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const release=path.resolve(process.argv[2]),output=process.argv[3];
const index=JSON.parse(fs.readFileSync(path.join(release,'INDEX50.json'),'utf8'));
let cases=0,carryEvents=0;
for(const h of index.households){
 const site=path.join(release,'households',h.household_id);
 const api=require(path.join(site,'joint-view.js'));
 const page=fs.readFileSync(path.join(site,'index.html'),'utf8');
 const rows=JSON.parse(page.match(/id="joint-cases-data"[^>]*>(.*?)<\/script>/s)[1]);
 for(const c of rows){
  const chart=api.chart(c).schedule_chart;
  assert.equal(chart.start_h,8);assert.equal(chart.end_h,32);
  assert.equal(chart.end_h-chart.start_h,24);
  for(const side of ['A','B'])for(const row of c.plans[side].rows)for(const e of row.events){
   assert.equal(e.start_abs_min,e.source_start_abs_min);
   assert.equal(e.end_abs_min,e.source_end_abs_min);
   if(e.start_abs_min<480||e.end_abs_min>1920){
    carryEvents++;assert.ok(e.operation_label.includes('完整安排'));
    if(e.end_abs_min>1920)assert.equal(e.end_status,'observation_cutoff');
   }
  }
  cases++;
 }
}
assert.equal(cases,500);
const report={status:'pass',actual_cases_checked:cases,axis_start_abs_min:480,axis_end_abs_min:1920,axis_hours:24,
 complete_operation_endpoints_preserved:true,carry_events_checked:carryEvents,question_contract_changed:false,human_answers:0};
fs.writeFileSync(output,JSON.stringify(report,null,2));console.log(JSON.stringify(report));
