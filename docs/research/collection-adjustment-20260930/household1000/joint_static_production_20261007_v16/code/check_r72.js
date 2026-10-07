"use strict";
// Load the original adapter. No new frontend or DOM renderer is authored here.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const out=path.resolve(__dirname,'..');
const adapter=require(path.join(out,'inputs','r72-view-adapter.js'));
const registry=JSON.parse(fs.readFileSync(path.join(out,'COLLECTION_INPUT_BINDINGS1000.json')));
let checked=0;const failures=[];
for(const h of registry.records)for(const row of h.scenes){
  const scene=JSON.parse(fs.readFileSync(path.join(out,row.path)));
  try{
    const v=adapter.fromCase(scene),c=v.schedule_chart;
    if(c.start_h!==0||c.end_h!==48||!Array.isArray(c.rows))throw Error('chart contract');
    for(const d of c.rows)for(const side of ['original','proposal'])for(const s of d[side]){
      if(!Number.isFinite(s.start_h)||!Number.isFinite(s.end_h)||s.start_h<0||s.end_h>48||s.end_h<=s.start_h)throw Error('timeline bound');
    }
    if(scene.answers.adoption!==null||scene.answers.relative_preference!==null)throw Error('human answer fabricated');
    checked++;
  }catch(e){failures.push({case:scene.artifact.date,role:h.household_id,error:String(e)});}
}
const result={existing_R72_adapter_sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(out,'inputs','r72-view-adapter.js'))).digest('hex'),
  checked,failures,new_frontend_designed:false,scope:'saved schedule data through actual original R72 timeline adapter;browser visual QA and physics effect display await EP',EP_started:0};
fs.writeFileSync(path.join(out,'R72_ADAPTER_REVIEW.json'),JSON.stringify(result,null,2)+'\n');
console.log({existing_adapter_cases:checked,failures:failures.length});
if(failures.length)process.exitCode=1;
