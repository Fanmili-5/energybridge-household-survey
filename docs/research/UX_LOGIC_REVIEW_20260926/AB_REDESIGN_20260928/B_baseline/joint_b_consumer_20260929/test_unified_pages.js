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
(async()=>{const batches=['legacy11','revision2_full','rich_fixture','rich_not_computed','rich_complete','rich_failed','direct_fixture'],staticNames=['candidate.css','household-view.js','joint-view.css','joint-view.js','plan-view.js','source-draft.js','style.css'],staticHashes={},counts={};
 for(const batch of batches){const base=path.join(root,'unified_preview',batch),index=JSON.parse(fs.readFileSync(path.join(base,'BUILD_INDEX.json')));let tested=0;
  for(const role of Object.keys(index.roles)){const dir=path.join(base,role),{document,api,cases,hashes}=open(dir);for(const name of staticNames){const hash=crypto.createHash('sha256').update(fs.readFileSync(path.join(dir,name))).digest('hex');if(staticHashes[name])assert.equal(hash,staticHashes[name],name+' differs across batches');else staticHashes[name]=hash;}
   for(let i=0;i<cases.length;i++){const c=cases[i],get=id=>document.getElementById(id);await api.show(i);assert.equal(get('joint-error').textContent,'',c.identity.case_id);assert.equal(c.schema,'eb.joint_b.consumer.v2');assert.ok(c.audit.source_binding);assert.equal(c.audit.consumer_version_policy.sha256,index.policy_sha256);assert.ok(!('policy_admission' in c));const shown=api.chart(c).schedule_chart.rows.length;assert.equal(get('joint-plan-A').children.length,shown);assert.equal(get('joint-plan-B').children.length,shown);assert.equal(get('joint-changes').children.length,c.commands.length);
    const out=await api.exportRecord(c,api.current().input,hashes[i],{choice:'reject',score:'3.5',comfort_score:'4.0',energy_score:'',vpp_score:'2.5',comment:'计划晚于通常时段'},api.snapshot(),'fixture-time');assert.equal(Object.keys(out.input.fields).length,23);assert.equal(out.schema,'eb.joint_b.local_test_export.v5');assert.equal(out.test_feedback.decision,'reject');assert.equal(out.test_feedback.decision_status,'answered');assert.equal(out.test_feedback.score,3.5);assert.equal(out.test_feedback.energy_score,null);assert.equal(out.test_feedback.comment,'计划晚于通常时段');assert.ok(!/cityrole-|engineering-rich|sha256/.test(JSON.stringify(out.input)));assert.equal(out.audit.source_case.audit.consumer_manifest_sha256||out.audit.source_case.audit.source_binding.manifest_sha256,index.manifest_sha256);assert.equal(out.human_label_count,0);assert.equal(out.formal_export_eligible,false);
    if(c.physical.status==='partial')assert.ok(get('joint-results').textContent.includes('限定通道读回'));if(c.physical.status==='failed')assert.ok(get('joint-results').textContent.includes('物理读回失败'));
    if(batch.startsWith('rich_')||batch==='direct_fixture'){assert.equal(c.profile.profile.devices.filter(d=>d.controllable).length,7);assert.ok(get('joint-timeline').textContent.includes('次日')||get('joint-plan-A').textContent.includes('次日'));}
    if(batch==='rich_fixture')assert.equal(c.physical.channels[0].B.status,'not_computed');
    if(batch==='rich_not_computed')assert.equal(c.physical.status,'not_computed');
    if(batch==='rich_complete')assert.equal(c.physical.channels[0].B.status,'computed');
    if(batch==='rich_failed')assert.equal(c.physical.status,'failed');
    if(batch==='direct_fixture')assert.equal(c.audit.backend_release.status,'held');
    tested++;
   }
  }
  counts[batch]=tested;
 }
 const historical=open(path.join(root,'unified_preview','revision2_full','cityrole-0012'));
 assert.equal(historical.api.chart(historical.cases[0]).schedule_chart.end_h,24);
 assert.equal(historical.api.chart(historical.cases[0]).schedule_chart.rows.length,2);
 await historical.api.show(8);
 const visible=id=>historical.document.getElementById(id).textContent;
 assert.ok(!visible('home-device-inventory').includes('位置未提供'));
 assert.ok(!visible('joint-timeline').includes('位置未提供'));
 assert.ok(!visible('home-attitudes').includes('/5'));
 assert.ok(!visible('joint-needs-list').includes('合成情境需求'));
 assert.ok(visible('joint-plan-A').includes('洗衣机')&&visible('joint-plan-B').includes('洗衣机'));
 const demo=open(path.join(root,'unified_preview','rich_fixture','engineering-rich-0001'));
 demo.context.renderInventory({devices:[
  {device_class:'washer',device:'不存在的洗衣机',owned:false,installed:false},
  {device_class:'dryer',device:'未安装的烘干机',owned:true,installed:false},
  {device_class:'dishwasher',device:'家中洗碗机',owned:true,installed:true,controllable:true}]});
 assert.equal(demo.document.getElementById('home-device-inventory').textContent.includes('家中洗碗机'),true);
 assert.equal(demo.document.getElementById('home-device-inventory').textContent.includes('不存在的洗衣机'),false);
 assert.equal(demo.document.getElementById('home-device-inventory').textContent.includes('未安装的烘干机'),false);
 assert.throws(()=>demo.context.window.EBSourceDraft.buildAnswer({choice:'accept',score:'5.5',comment:'测试'}),/1–5/);
 assert.throws(()=>demo.context.window.EBSourceDraft.buildAnswer({choice:'cannot_judge',comment:'测试'}),/同意或不同意/);
 assert.ok(!fs.readFileSync(path.join(root,'template.html'),'utf8').includes('value="cannot_judge"'));
 const issue=demo.api.issueRecord(demo.cases[0],demo.hashes[0],{category:'display',description:'时间轴标签重叠'});assert.equal(issue.status,'local_download_not_submitted');assert.equal(issue.issue.category,'display');assert.equal(issue.context.case_id,demo.cases[0].identity.case_id);
 assert.throws(()=>demo.context.window.EBSourceDraft.buildIssue({category:'other',description:''}),/描述/);
 assert.deepEqual(counts,{legacy11:11,revision2_full:2970,rich_fixture:1,rich_not_computed:1,rich_complete:1,rich_failed:1,direct_fixture:1});console.log(JSON.stringify({status:'PASS',cases:counts,identical_static_renderer:true,whitelisted_export:true,physical_statuses:['not_computed','partial','complete','failed'],cross_midnight_and_extra_AC:true,backend_status_passthrough:true,visual_qa:'DOM_only_not_browser_visual'}));
})().catch(e=>{console.error(e);process.exitCode=1;});
