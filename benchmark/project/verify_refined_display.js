/* Read the new renderer's exact nodes, with no old prices or physical files. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const folder=path.resolve(process.argv[2]),pub=fs.existsSync(path.join(folder,'public'))?path.join(folder,'public'):folder;
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
require(path.join(pub,'required-response.js'));require(path.join(pub,'view.js'));
const ui=globalThis.EBSimple50,index=read(path.join(pub,'index.json')),models={};
const reviews=index.physical_review_index?read(path.join(pub,index.physical_review_index.path)).cases:null,counts={};
for(const row of index.cases){
  const c=read(path.join(pub,row.path)),p=read(path.join(pub,'households',row.household_id+'.json'));
  if(reviews){c.physical_review=reviews[c.case_id];assert.equal(c.physical_review.source_frozen_pair_sha256,c.bindings.source_pair_sha256);const s=c.physical_review.status;counts[s]=(counts[s]||0)+1;}
  assert.equal(c.outcome_status,'not_computed');assert.equal(c.impact,null);assert.equal(c.VPP_results,null);
  assert.ok(p.display_housing.rooms.length);const shown=ui.displayed(c,p);
  for(const key of ['family','request','changes','impacts','schedule']){
    assert.equal(typeof shown[key],'string');assert.ok(shown[key].length);
    assert.ok(!/undefined|NaN|Infinity|制冷40|已列任务均完成/.test(shown[key]),key);
  }
  assert.match(shown.family,/房屋剖面示意/);assert.match(shown.request,/18:00–19:00/);
  if(c.physical_review?.status==='computed'){assert.match(shown.impacts,/已完成/);assert.match(shown.impacts,/实际平均/);for(const e of c.physical_review.actual_outcomes.events)assert.ok(shown.impacts.includes(e.target_met?'达标':'未达标'));}
  else{assert.match(shown.impacts,/未计算/);assert.ok(!/实际平均[\d]|实际降低[\d]/.test(shown.impacts));}
  if(c.physical_review?.status==='unsupported_world')assert.match(shown.impacts,/模型兼容问题/);
  const nodes=ui.presentationNodes(c,p),flatten=n=>(n.text??'')+(n.children||[]).map(flatten).join('');
  for(const key of ['family','request','changes','impacts'])assert.equal(shown[key],nodes[key].map(flatten).join(''));
  assert.deepEqual(c.response,null);models[c.case_id]=shown;
}
fs.writeFileSync(path.join(folder,'DISPLAY_MODELS.json'),JSON.stringify(models)+'\n');
console.log(JSON.stringify({passed:true,cases:index.cases.length,presentation:ui.presentation_revision,review_statuses:counts,answers_written:0}));
