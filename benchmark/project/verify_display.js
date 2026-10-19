/* Execute the v69 renderer itself: the displayed text is the data contract. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const folder=path.resolve(process.argv[2]),pub=path.join(folder,'public');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
require(path.join(pub,'required-response.js'));
require(path.join(pub,'view.js'));
const index=read(path.join(pub,'index.json')),models={};
for(const row of index.cases){
  const c=read(path.join(pub,row.path)),p=read(path.join(pub,'households',row.household_id+'.json'));
  assert.equal(c.household_id,p.household_id);
  const shown=globalThis.EBSimple50.displayed(c,p);
  for(const key of ['family','request','changes','impacts','schedule']){
    assert.equal(typeof shown[key],'string');assert.ok(shown[key].length>0);
    assert.ok(!/undefined|NaN|Infinity|· null/.test(shown[key]));
  }
  assert.equal((shown.impacts.match(/未计算/g)||[]).length,8);
  assert.ok(!/已列任务均完成|0\/0|已达标|达到目标|无有人时记录/.test(shown.impacts));
  assert.match(shown.request,/这是请求目标，实际响应未计算/);
  assert.match(shown.schedule,/允许充电不表示全程充电/);
  assert.match(shown.schedule,/不是实际室温或出水温度/);
  assert.deepEqual(c.impact,null);assert.deepEqual(c.VPP_results,null);assert.deepEqual(c.response,null);
  models[c.case_id]=shown;
}
const target=path.join(folder,'DISPLAY_MODELS.json');
if(fs.existsSync(target)) assert.deepEqual(read(target),models);
else fs.writeFileSync(target,JSON.stringify(models)+'\n');
console.log(JSON.stringify({passed:true,cases:index.cases.length,renderer:'v69_with_pending_data_adapter',answers_written:0}));
