'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root=__dirname;
class Element{
 constructor(){this._text='';this.children=[];this.dataset={};this.style={};this.attributes={};this.listeners={};this.value='';this.classList={toggle(){},add(){},remove(){}};}
 get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}set textContent(v){this._text=String(v);this.children=[];}
 append(...children){this.children.push(...children);}replaceChildren(...children){this._text='';this.children=children;}setAttribute(k,v){this.attributes[k]=v;}reset(){}scrollIntoView(){}addEventListener(k,v){this.listeners[k]=v;}
 querySelectorAll(selector){return this.children.flatMap(c=>[...((c.className||'').split(' ').includes(selector.slice(1))?[c]:[]),...c.querySelectorAll(selector)]);}querySelector(s){return this.querySelectorAll(s)[0]||null;}
 cloneNode(){const x=new Element();x._text=this._text;x.className=this.className;x.children=this.children.map(c=>c.cloneNode());return x;}
}
function open(dir){const html=fs.readFileSync(path.join(dir,'index.html'),'utf8'),elements=new Map();
 const document={body:{dataset:{}},getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement:()=>new Element(),createElementNS:()=>new Element(),createTextNode:v=>Object.assign(new Element(),{textContent:v}),querySelector:()=>null,querySelectorAll:()=>[]};
 document.getElementById('joint-needs').open=true;
 for(const id of ['profile-data','source-cases-data','source-selection-data','joint-cases-data','visible-inputs-data','source-hashes-data'])document.getElementById(id).textContent=html.match(new RegExp('id="'+id+'">(.*?)</script>','s'))[1];
 for(const id of ['role-instructions','joint-source-note','answer-instructions','decision-question','score-question']){const m=html.match(new RegExp('id="'+id+'"[^>]*>([\\s\\S]*?)</(?:p|fieldset)>'));assert.ok(m,id);document.getElementById(id).textContent=m[1].replace(/<[^>]+>/g,'').trim();}
 const window={},context={window,document,crypto:crypto.webcrypto,TextEncoder,Uint8Array,console,Date,Map,Set,WeakMap,setTimeout,clearTimeout,requestAnimationFrame(){},ResizeObserver:class{observe(){}disconnect(){}}};vm.createContext(context);
 for(const f of ['plan-view.js','source-draft.js','household-view.js','joint-view.js'])vm.runInContext(fs.readFileSync(path.join(dir,f),'utf8'),context,{filename:f});
 return {document,context,api:window.EBJoint,cases:JSON.parse(document.getElementById('joint-cases-data').textContent),hashes:JSON.parse(document.getElementById('source-hashes-data').textContent)};
}

(async()=>{const release=process.argv[2], out=process.argv[3], index=JSON.parse(fs.readFileSync(path.join(release,'INDEX50.json'),'utf8'));let rendered=0,saved=0;const all=[];
 for(const row of index.households){const dir=path.join(release,'households',row.household_id),{document,api,cases,hashes}=open(dir);assert.equal(cases.length,10);const records=[];
  for(let i=0;i<10;i++){await api.show(i);assert.equal(document.getElementById('joint-error').textContent,'',row.household_id+':'+i);assert.equal(cases[i].identity.role_id,row.household_id);assert.equal(document.getElementById('joint-date').textContent,cases[i].identity.date);assert.ok(document.getElementById('joint-results').textContent.includes('kWh'));assert.ok(document.getElementById('home-members').children.length===cases[i].profile.profile.household.family_size);const rec=await api.exportRecord(cases[i],api.current().input,hashes[i],{choice:i%2?'reject':'accept',score:'3.5',comfort_score:'4.0',energy_score:'',vpp_score:'2.5',comment:'合成工程测试：核验实际展示和保存链路'},api.snapshot(),'synthetic-test');assert.equal(rec.human_label_count,0);assert.ok(!/design_condition|constraint_challenge|service_risk_challenge|integrity_errors/.test(JSON.stringify(rec.input)),'design metadata leaked into model visible input');assert.equal(rec.test_feedback.energy_score,null);assert.equal(rec.test_feedback.score,3.5);assert.equal(rec.audit.source_binding.source_package_sha256,hashes[i]);records.push(rec);rendered++;}
  const dst=path.join(out,row.household_id);fs.mkdirSync(dst,{recursive:true});fs.writeFileSync(path.join(dst,'records.json'),JSON.stringify(records));saved+=records.length;all.push({household_id:row.household_id,cases:records.length});
 }
 const report={status:'pass',actual_cases_rendered:rendered,engineering_records_prepared:saved,source_bindings_checked:true,member_counts_checked:true,question_contract:'original live joint-b binary adoption,four scores,reason',browser_visual_qa:'separate',human_answers:0,records:all};fs.writeFileSync(path.join(out,'RENDER_REVIEW.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({...report,records:undefined}));
})().catch(e=>{console.error(e);process.exitCode=1;});
