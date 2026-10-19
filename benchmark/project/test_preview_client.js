/* Pending-result cases must not elicit invented scores, even after input events
 * or direct submit() calls. No network/storage capabilities are supplied. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const fields=Object.fromEntries(['score','comfort_score','energy_score','vpp_score','reason','submit-answer','response-status'].map(k=>[k,{value:'',disabled:false,textContent:''}]));
const radios=[{value:'accept',checked:false,disabled:false},{value:'reject',checked:false,disabled:false}];
const controls=[...Object.entries(fields).filter(([k])=>k!=='response-status').map(([,v])=>v),...radios];
const handlers={};
fields['response-form']={
  reset(){for(const el of controls){el.value=el===radios[0]?'accept':el===radios[1]?'reject':'';el.checked=false;}},
  querySelectorAll(){return controls;},
  addEventListener(name,fn){handlers[name]=fn;}
};
let validated=0;
const window={EBSimple50:{answer(raw){validated++;return raw;}}};
const document={getElementById:id=>fields[id],querySelectorAll:()=>radios,querySelector:()=>radios.find(r=>r.checked),addEventListener(name,fn){assert.equal(name,'DOMContentLoaded');fn();}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'preview-client.js'),'utf8'),{window,document});
window.EBCollection.onCaseShown({case_id:'pending',outcome_status:'not_computed'});
assert.ok(controls.every(el=>el.disabled));
for(const id of ['score','comfort_score','energy_score','vpp_score'])fields[id].value='4';
radios[0].checked=true;fields.reason.value='not an evidence-based response';handlers.input();handlers.change();
assert.equal(fields['submit-answer'].disabled,true);
assert.throws(()=>window.EBCollection.submit(),/OUTCOMES_NOT_COMPUTED/);
assert.equal(validated,0);assert.match(fields['response-status'].textContent,/请不要猜测评分/);
window.EBCollection.revert();assert.ok(controls.every(el=>el.disabled));
window.EBCollection.onCaseShown({case_id:'computed',outcome_status:'computed'});
assert.ok(controls.every(el=>!el.disabled));
assert.equal(window.EBCollection.submit().formal_response_saved,false);
window.EBCollection.onCaseShown({case_id:'pending-again',outcome_status:'not_computed'});
assert.ok(controls.every(el=>el.disabled));
console.log('pending case controls, input events, direct-submit guard and case switching passed; no network/storage');
