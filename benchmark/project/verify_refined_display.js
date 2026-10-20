/* Read the new renderer's exact nodes, with no old prices or physical files. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const folder=path.resolve(process.argv[2]),pub=path.join(folder,'public');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
require(path.join(pub,'required-response.js'));require(path.join(pub,'view.js'));
const ui=globalThis.EBSimple50,index=read(path.join(pub,'index.json')),models={};
for(const row of index.cases){
  const c=read(path.join(pub,row.path)),p=read(path.join(pub,'households',row.household_id+'.json'));
  assert.equal(c.outcome_status,'not_computed');assert.equal(c.impact,null);assert.equal(c.VPP_results,null);
  assert.ok(p.display_housing.rooms.length);const shown=ui.displayed(c,p);
  for(const key of ['family','request','changes','impacts','schedule']){
    assert.equal(typeof shown[key],'string');assert.ok(shown[key].length);
    assert.ok(!/undefined|NaN|Infinity|制冷40|¥[\d]|实际降低[\d]|已列任务均完成/.test(shown[key]),key);
  }
  assert.match(shown.family,/房屋剖面示意/);assert.match(shown.impacts,/未计算/);assert.match(shown.request,/18:00–19:00/);
  const nodes=ui.presentationNodes(c,p),flatten=n=>(n.text??'')+(n.children||[]).map(flatten).join('');
  for(const key of ['family','request','changes','impacts'])assert.equal(shown[key],nodes[key].map(flatten).join(''));
  assert.deepEqual(c.response,null);models[c.case_id]=shown;
}
fs.writeFileSync(path.join(folder,'DISPLAY_MODELS.json'),JSON.stringify(models)+'\n');
console.log(JSON.stringify({passed:true,cases:index.cases.length,presentation:ui.presentation_revision,answers_written:0}));
