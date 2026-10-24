/* Exercise the actual UI91 renderer without writing an answer or a case. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const folder=path.resolve(process.argv[2]),pub=path.join(folder,'public');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
require(path.join(pub,'required-response.js'));require(path.join(pub,'view.js'));
const ui=globalThis.EBSimple50,index=read(path.join(pub,'index.json'));
const html=fs.readFileSync(path.join(pub,'index.html'),'utf8');
const rendererHash=require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(pub,'view.js'))).digest('hex');
assert.ok(html.includes(`src="view.js?offline_sha=${rendererHash}"`));
assert.ok(html.includes('src="preview-client.js"'));
assert.ok(!html.includes('src="collection-client.js"'));
assert.ok(!html.includes('草稿自动保存'));
assert.ok(html.includes('不保存正式答卷，也不生成回执'));
let nullTargets=0,numericTargets=0;
for(const row of index.cases){
  const c=read(path.join(pub,row.path)),p=read(path.join(pub,'households',row.household_id+'.json'));
  const shown=ui.displayed(c,p);
  assert.ok(!shown.request.includes('未提供kW'));
  if(c.VPP_requests.some(r=>r.target_kw===null)){
    assert.ok(shown.request.includes('本题未设定数值目标'));nullTargets++;
  }
  assert.match(shown.family,/房屋剖面示意/);
  assert.ok(shown.family.includes(c.offline_presentation_context.attitude_priority));
  const fullFamily=ui.familyLines(c,p).join('\n');
  assert.equal(c.offline_presentation_context.action_reason_lines.length,Object.keys(c.questionnaire_context.reasons).length);
  for(const line of [...c.offline_presentation_context.calendar_lines,...c.offline_presentation_context.action_reason_lines])assert.ok(fullFamily.includes(line));
  assert.equal(c.response,null);assert.equal(c.impact,null);assert.equal(c.VPP_results,null);
  // In-memory probes verify zero is not accidentally treated as missing.
  for(const target of [0,1.5])for(const direction of ['down','up']){
    const probe=structuredClone(c);probe.VPP_requests=probe.VPP_requests.map(r=>({...r,target_kw:target,direction}));
    const text=ui.displayed(probe,p).request;
    assert.ok(text.includes(`希望${direction==='down'?'降低':'增加'}${target}kW`));
    assert.ok(!text.includes('本题未设定数值目标'));numericTargets++;
  }
}
console.log(JSON.stringify({passed:true,cases:index.cases.length,null_target_cases:nullTargets,numeric_target_probes:numericTargets,answers_written:0,case_files_changed:0}));
