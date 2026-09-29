"use strict";
(function(root){
 const clone=x=>JSON.parse(JSON.stringify(x));
 const canonical=x=>JSON.stringify(sort(x));
 function sort(x){if(Array.isArray(x))return x.map(sort);if(x&&typeof x==='object')return Object.fromEntries(Object.keys(x).sort().map(k=>[k,sort(x[k])]));return x;}
 async function hash(x){const raw=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(x)));return [...new Uint8Array(raw)].map(x=>x.toString(16).padStart(2,'0')).join('');}
 const q=id=>document.getElementById(id),el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=String(text);if(cls)e.className=cls;return e;};
 const location=(zone,labels={})=>{const z=labels[zone]||zone;return ({bathroom:'卫浴',kitchen:'厨房',living_hall:'起居厅',corridor:'过道'}[z])||String(z||'').replace(/^natural_(\d+)$/,'自然间 $1')||'位置未提供';};
 const time=(value,base)=>{const m=value-base,d=Math.floor(m/1440),v=((m%1440)+1440)%1440;return `${d===0?'当天':d===1?'次日':d<0?(d===-1?'前日':`前${-d}日`):`第${d+1}天`} ${String(Math.floor(v/60)).padStart(2,'0')}:${String(v%60).padStart(2,'0')}`;};
 const label=e=>e.operation_kind==='heater_availability'?'允许加热时段':e.setpoint_C!=null?`设置${e.setpoint_C} ℃`:'安排时段';
 const eventList=c=>c.vpp.events||[c.vpp];
 const dayBase=c=>(c.identity.day_index??Math.floor(c.plans.A.window_start_abs_min/1440))*1440;
 function focusWindow(c){
  const start=dayBase(c),firstEnd=start+1440;
  const relevant=[...eventList(c),
   ...c.plans.A.rows.flatMap(r=>r.events),...c.plans.B.rows.flatMap(r=>r.events)]
   .filter(e=>e.start_abs_min<firstEnd&&e.end_abs_min>start);
  relevant.push(...c.commands.filter(e=>e.start_abs_min<c.plans.A.window_end_abs_min&&e.end_abs_min>start));
  const latest=Math.max(firstEnd,...relevant.map(e=>e.end_abs_min));
  return [start,Math.min(c.plans.A.window_end_abs_min,
    Math.max(firstEnd,Math.ceil((latest+(latest>firstEnd?60:0))/60)*60))];
 }
 const inWindow=(e,start,end)=>e.end_abs_min>start&&e.start_abs_min<end;
 function displayedRows(c,start,end){const b=new Map(c.plans.B.rows.map(r=>[r.asset_id,r]));
  return c.plans.A.rows.filter(a=>[...a.events,...(b.get(a.asset_id)?.events||[])].some(e=>inWindow(e,start,end)));}
 function chart(c){const base=dayBase(c),assets=Object.fromEntries(c.profile.profile.devices.map(a=>[a.asset_id,a])),selected=new Set(c.commands.map(x=>x.asset_id)),b=new Map(c.plans.B.rows.map(r=>[r.asset_id,r]));
  const [start,end]=focusWindow(c);
  return {schedule_chart:{start_h:(start-base)/60,end_h:(end-base)/60,event_start_h:(eventList(c)[0].start_abs_min-base)/60,event_end_h:(eventList(c)[0].end_abs_min-base)/60,event_windows:eventList(c).map(e=>({start_h:(e.start_abs_min-base)/60,end_h:(e.end_abs_min-base)/60})),notification_h:(c.vpp.notice_abs_min-base)/60,statistics_window:null,
   rows:displayedRows(c,start,end).map(a=>({device_id:a.asset_id,icon_device_id:a.device_class,device:`${assets[a.asset_id].device} · ${location(assets[a.asset_id].zone,c.profile.geometry?.zone_labels)}`,active:selected.has(a.asset_id),schedule_complete:a.schedule_complete&&b.get(a.asset_id).schedule_complete,
    original:a.events.map(e=>({...e,start_h:(e.start_abs_min-base)/60,end_h:(e.end_abs_min-base)/60,label:label(e)})),proposal:b.get(a.asset_id).events.map(e=>({...e,start_h:(e.start_abs_min-base)/60,end_h:(e.end_abs_min-base)/60,label:label(e)}))}))},
   options:{sideLabels:{original:'原安排 A',proposal:'调整后 B'},eventLabel:'VPP事件',axisLabel:'事件当天安排时间轴',deviceHint:(row,id)=>id==='ac'?' · 温度设定':'',emptyText:{original:r=>r.schedule_complete?'此侧未安排':'未提供安排',proposal:r=>r.schedule_complete?'此侧未安排':'未提供安排'},legendText:'上行为原安排，下行为调整后。浅色区域为本次事件时段。',barText:s=>s.label}};
 }
 async function verify(c,expected){if(c.schema!=='eb.joint_b.consumer.v2')throw Error('不支持的统一页面来源版本');if(await hash(c)!==expected)throw Error('来源内容与绑定不一致');if(!Array.isArray(c.commands)||!c.commands.length)throw Error('缺少完整命令列表');if(c.profile.role_id!==c.identity.role_id)throw Error('家庭来源不一致');
  for(const [key,value]of [['profile_sha256',c.profile],['commands_sha256',c.commands],['A_plan_sha256',c.plans.A],['B_plan_sha256',c.plans.B],['vpp_sha256',c.vpp]])if(await hash(value)!==c.bindings[key])throw Error('来源字段绑定不一致');
  if(c.physical&&await hash(c.physical)!==c.bindings.physical_sha256)throw Error('物理状态绑定不一致');
  if(new Set(c.commands.map(x=>x.command_id)).size!==c.commands.length)throw Error('命令编号重复');return true;
 }
 const hourText=h=>{const n=Math.round(h*60),day=n>=1440?'次日 ':'';return `${day}${String(Math.floor(n%1440/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;};
 function referenceText(e,ref){if(!ref||ref.source!=='synthetic_questionnaire_profile')return '家庭通常时段未提供，无法判定偏离。';
  const h=ref.usual_start_hour,d=ref.usual_finish_hour,parts=[],clock=((e.start_abs_min%1440)+1440)%1440;
  const overnight=Number.isFinite(h)&&h>=18&&clock<720;
  const referenceDay=Math.floor(e.start_abs_min/1440)*1440-(overnight?1440:0);
  if(Number.isFinite(h)){
   const minute=Math.round(h*60),delta=clock+(overnight?1440:0)-minute;
   parts.push(`通常开始 ${hourText(h)}；本次${delta===0?'与通常开始相同':`比通常${delta>0?'晚':'早'} ${Math.abs(delta)} 分钟`}`);
  }
  if(Number.isFinite(d)){
   const finishLabel=ref.finish_meaning==='usual_end'?'通常结束':'通常最晚完成';
   const nextDay=Number.isFinite(h)&&d<h;
   const deadline=referenceDay+Math.round(d*60)+(nextDay?1440:0);
   const over=e.end_abs_min-deadline;
   parts.push(`${finishLabel} ${nextDay?'次日 ':''}${hourText(d)}；本次${over>0?`晚于该时刻 ${over} 分钟`:'未晚于该时刻'}`);
  }
  return parts.length?parts.join('。')+'。合成画像对照，非可执行性裁定。':'家庭通常时段未提供，无法判定偏离。';
 }
 function renderPlans(c){const base=dayBase(c),[start,end]=focusWindow(c),assets=Object.fromEntries(c.profile.profile.devices.map(a=>[a.asset_id,a])),shown=new Set(displayedRows(c,start,end).map(r=>r.asset_id));
  for(const side of ['A','B']){const box=q('joint-plan-'+side);box.replaceChildren();for(const row of c.plans[side].rows.filter(r=>shown.has(r.asset_id))){const section=el('section',null,'joint-device-plan'),a=assets[row.asset_id],events=row.events.filter(e=>inWindow(e,start,end));section.append(el('strong',`${a.device} · ${location(a.zone,c.profile.geometry?.zone_labels)}`));
   if(!events.length)section.append(el('p',row.schedule_complete?'此侧未安排':'未提供安排'));
   for(const e of events)section.append(el('p',`${time(e.start_abs_min,base)}—${time(e.end_abs_min,base)} · ${label(e)}`));
   if(events.length&&c.commands.some(command=>command.asset_id===row.asset_id))section.append(el('small',referenceText(events[0],c.profile.profile.operating_reference?.[row.device_class])));
   box.append(section);}}
  const changes=q('joint-changes');changes.replaceChildren();for(const c0 of c.commands){const card=el('article',null,'joint-change'),a=assets[c0.asset_id];card.append(el('strong',`${a.device} · ${location(a.zone,c.profile.geometry?.zone_labels)}`));
   card.append(el('p',c0.kind==='ac_setpoint'?`${time(c0.start_abs_min,base)}—${time(c0.end_abs_min,base)}：${c0.from_setpoint_C} ℃ → ${c0.to_setpoint_C} ℃`:`原安排 ${time(c0.A_start_abs_min,base)}—${time(c0.A_end_abs_min,base)}；调整后 ${time(c0.start_abs_min,base)}—${time(c0.end_abs_min,base)}`));
   if(c0.reason_text)card.append(el('p',c0.reason_text));changes.append(card);}
 }
 function renderResults(c){const box=q('joint-results');box.replaceChildren();for(const r of c.quantities){if(r.A.value==null&&r.B.value==null)continue;const fmt=x=>x.value==null?'未提供':`${Math.round(x.value*1000)/1000} ${x.unit}`;box.append(el('p',`${r.label}：原安排 ${fmt(r.A)}；调整后 ${fmt(r.B)}`));}for(const r of c.impacts||[])if(r.status!=='unknown'&&r.description)box.append(el('p',r.description));
  const unified=c.physical;if(unified?.status==='failed')box.append(el('p','物理读回失败；本轮结果未知。'));else if(unified?.status==='partial'||unified?.status==='complete'){box.append(el('h4',unified.status==='partial'?'限定通道读回（部分）':'限定通道读回'));const fmt=(x,unit)=>x.status==='computed'?`${x.value} ${unit}`:x.status==='held'?'暂缓展示':'未计算';for(const ch of unified.channels)box.append(el('p',`${ch.label}（${ch.scope==='annual_A'?'年度 A':ch.scope==='48h'?'48小时':'事件时段'}）：原安排 ${fmt(ch.A,ch.unit)}；调整后 ${fmt(ch.B,ch.unit)}。`));if(unified.hold_reason)box.append(el('p',unified.hold_reason));box.append(el('p','所列通道不等于整屋电表；不得据此判断 VPP 达标。'));}
  const tail=c.after_horizon;if(tail?.status==='computed_design_proxy'){const rows=tail.EV_new_target_shortfall_days||[],later=rows.filter(x=>x.day_index>c.identity.day_index+1);box.append(el('p',`年度电动车目标估算：调整后 B 相比同户原安排 A 新增 ${rows.length} 个目标日未达到（其中本轮次日之后 ${later.length} 日）。这是设计代理回放，不是整屋电表结果。`));if(later.length){const details=el('details');details.open=true;details.append(el('summary','查看后续目标日'));for(const x of later)details.append(el('p',`${x.date}：原安排电量 ${Math.round(x.A_SOC_post_charge*1000)/10}%，调整后 ${Math.round(x.B_SOC_post_charge*1000)/10}%，同一目标 ${Math.round(x.same_original_target_SOC*1000)/10}%。`));box.append(details);}}
  else box.append(el('p','两日后的电动车目标后效尚未提供。'));
  box.append(el('p','两日外洗衣与餐具任务物料后效尚未计算。'));
  if(c.result_note)box.append(el('p',c.result_note));}
 const snapshotIds=['role-instructions','home-intro','home-visual','home-caption','home-summary','home-device-inventory','home-targets','home-members','home-attitudes','joint-date','joint-source-note','vpp-summary','joint-weather','joint-state','joint-needs-list','selected-assets','joint-timeline','joint-plan-A','joint-plan-B','joint-changes','joint-results','joint-history','answer-instructions','decision-question','score-question'];
 const modelFieldIds=snapshotIds.filter(id=>id!=='joint-date'&&id!=='joint-history');
 function snapshot(){return Object.fromEntries(snapshotIds.map(id=>{const e=q(id);if(id==='joint-needs-list'&&!q('joint-needs').open)return [id,''];return [id,typeof e.innerText==='string'?e.innerText:e.textContent];}));}
 function modelInputFromSnapshot(rendered,assignment,history=[]){const fields={};for(const id of modelFieldIds){if(typeof rendered?.[id]!=='string')throw Error('可见字段缺失：'+id);fields[id]=rendered[id];}if(typeof rendered?.['joint-date']!=='string'||!/^\d{4}-\d{2}-\d{2}(?: · |$)/.test(rendered['joint-date']))throw Error('可见日期缺失');if(!assignment||assignment.left===assignment.right||!['A','B'].includes(assignment.left)||!['A','B'].includes(assignment.right))throw Error('左右安排无效');return {schema:'eb.joint_b.displayed_input.v1',date:rendered['joint-date'].slice(0,10),fields,display_assignment:clone(assignment),history:clone(history)};}
 async function exportRecord(c,input,expected,answer,rendered,presentedAt){await verify(c,expected);const clean=root.EBSourceDraft.buildAnswer(answer),auditInput=clone(input),modelInput=modelInputFromSnapshot(rendered,auditInput.display_assignment),link=c.collection_linkage||{household_id:c.identity.role_id,round_id:c.identity.round_index??null,source_scenario_id:c.identity.case_id,scenario_family_id:c.scenario_family_id??null,near_duplicate_or_derivative_relation:'pending_review',source_version_sha256:c.bindings?.A_manifest_sha256??null,participant_id:null,formal_split:null};return {schema:'eb.joint_b.local_test_export.v5',status:'engineering_click_not_human_feedback',input:modelInput,test_feedback:clean,
  audit:{collection_linkage:clone(link),semantic_input:auditInput,source_case:clone(c),source_binding:{source_package_sha256:expected,...c.bindings},presentation:{display_assignment:auditInput.display_assignment,presented_at:presentedAt,exported_at:new Date().toISOString(),joint_needs_expanded_at_export:Boolean(q('joint-needs').open),semantic_input_sha256:await hash(auditInput),rendered_snapshot:rendered,rendered_snapshot_sha256:await hash(rendered),model_input_sha256:await hash(modelInput)}},human_label_count:0,training_release:false,formal_export_eligible:false,history_status:'not_loaded_local_preview'};}
 function issueRecord(c,expected,issue,uiError=''){return {schema:'eb.joint_b.local_issue.v1',status:'local_download_not_submitted',issue:root.EBSourceDraft.buildIssue(issue),context:{household_id:c?.identity?.role_id??null,case_id:c?.identity?.case_id??null,round_index:c?.identity?.round_index??null,date:c?.identity?.date??null,source_package_sha256:expected??null,ui_error:String(uiError||'')},created_at:new Date().toISOString()};}
 const api={chart,hash,canonical,verify,snapshot,modelInputFromSnapshot,exportRecord,issueRecord,renderPlans,renderResults};root.EBJoint=api;
 if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;
 const live=root.EBLiveConfig||null;
 if(live){q('preview-mode-notice').textContent='这是一份合成家庭的线上工程试填。答卷与问题报告会保存到独立服务；目前不计作正式人类反馈，也不进入训练。';q('report-mode-notice').textContent='问题报告会保存到独立工程服务，成功后显示报告编号；不会更改评分。';q('report-submit').textContent='提交问题';q('joint-export').textContent='保存工程试填';}
 const cases=JSON.parse(q('joint-cases-data').textContent),inputs=JSON.parse(q('visible-inputs-data').textContent),hashes=JSON.parse(q('source-hashes-data').textContent);let current=0,currentInput=null,presentedAt=null;
 const scoreKeys=['score','comfort-score','energy-score','vpp-score'];
 function syncScore(key){const number=q('joint-'+key),range=q('joint-'+key+'-range'),meaning=q('joint-'+key+'-meaning'),raw=number.value,n=Number(raw),anchors=['很不合适','较不合适','一般','较合适','很合适'];
  range.parentElement?.classList.toggle('unanswered',raw==='');
  if(raw===''){meaning.textContent='尚未评分';return;}
  if(!Number.isFinite(n)||n<1||n>5){meaning.textContent='请填写 1–5 分';return;}
  range.value=raw;meaning.textContent=Number.isInteger(n)?`${n} 分 · ${anchors[n-1]}`:`${raw} 分 · ${anchors[Math.floor(n)-1]}与${anchors[Math.ceil(n)-1]}之间`;
 }
 for(const key of scoreKeys){q('joint-'+key).addEventListener('input',()=>syncScore(key));q('joint-'+key+'-range').addEventListener('input',()=>{q('joint-'+key).value=q('joint-'+key+'-range').value;syncScore(key);});syncScore(key);}
 async function show(i){q('joint-error').textContent='';q('joint-export').disabled=true;try{const c=cases[i];await verify(c,hashes[i]);current=i;currentInput=clone(inputs[i]);currentInput.history=[];presentedAt=new Date().toISOString();q('joint-feedback').reset();q('joint-status').textContent='';
   for(const key of scoreKeys)syncScore(key);
   renderHome(c.identity.role_id);q('joint-date').textContent=c.identity.date;const base=dayBase(c),v=q('vpp-summary');v.replaceChildren(el('p',`通知时间：${time(c.vpp.notice_abs_min,base)}`));for(const [n,event]of eventList(c).entries())v.append(el('p',`事件 ${n+1}：${time(event.start_abs_min,base)}—${time(event.end_abs_min,base)}`),el('p',`家庭请求：${event.household_request.text}`),el('p',event.incentive?.text||'本次未设置激励。'));
   const weather=c.context.weather_days?.[0];q('joint-weather').textContent=weather?`情境气温：${weather.min_drybulb_C_derived}–${weather.max_drybulb_C_derived}℃`:'';q('joint-state').textContent=c.context.pre_event_state?.display_text||'当天设备初态：未提供。';
   const needs=q('joint-needs-list');needs.replaceChildren();for(const text of c.context.daily_need_texts||[])needs.append(el('p',text));if(!needs.children.length)needs.append(el('p','本测试夹具未额外加载需求明细。'));const assets=Object.fromEntries(c.profile.profile.devices.map(a=>[a.asset_id,a]));q('selected-assets').textContent='本次调整：'+[...new Set(c.commands.map(x=>x.asset_id))].map(id=>`${assets[id].device}（${location(assets[id].zone,c.profile.geometry?.zone_labels)}）`).join('、');
   const view=chart(c);root.EBView.render(q('joint-timeline'),view,view.options);renderPlans(c);renderResults(c);q('joint-comparison').classList.toggle('swapped',c.display_assignment.left==='B');q('joint-history').textContent='本情境未提供既往回答。';q('joint-export').disabled=false;
  }catch(e){q('joint-error').textContent='无法展示：'+e.message;}}
 cases.forEach((c,i)=>{const option=el('option',`情境 ${i+1} · ${c.identity.date} · ${c.profile.profile.household.city||'城市未知'}`);option.value=String(i);q('joint-select').append(option);});q('joint-select').addEventListener('change',()=>show(Number(q('joint-select').value)));
 function downloadJson(record,name){const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),500);}
 async function postLive(path,payload){const response=await fetch(live.base+'/api/'+path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-EB-CSRF':live.csrf},body:JSON.stringify(payload)}),data=await response.json();if(!response.ok||!data.saved)throw Error(data.error||'服务器未确认保存，请重试。');return data;}
 let pendingAnswer=null,pendingIssue=null;
 q('joint-feedback').addEventListener('submit',e=>e.preventDefault());q('joint-export').addEventListener('click',async()=>{try{const answer={choice:document.querySelector('[name="source_decision"]:checked')?.value,score:q('joint-score').value,comfort_score:q('joint-comfort-score').value,energy_score:q('joint-energy-score').value,vpp_score:q('joint-vpp-score').value,comment:q('joint-comment').value};
  const serialized=JSON.stringify({case_index:current,answer});if(live){if(!pendingAnswer||pendingAnswer.serialized!==serialized)pendingAnswer={serialized,key:crypto.randomUUID(),record:await exportRecord(cases[current],currentInput,hashes[current],answer,snapshot(),presentedAt)};const saved=await postLive('answers',{case_index:current,record:pendingAnswer.record,request_id:pendingAnswer.key});pendingAnswer=null;q('joint-status').textContent='工程试填已保存；回执编号：'+saved.receipt_id+'。不计作正式人类反馈。';}else{const record=await exportRecord(cases[current],currentInput,hashes[current],answer,snapshot(),presentedAt);downloadJson(record,'joint-b-local-test.json');q('joint-status').textContent='已下载本地测试记录；未提交，不计作人类反馈。';}}catch(e){q('joint-status').textContent=e.message;}});
 q('report-problem').addEventListener('click',()=>{const index=Number(q('joint-select').value)||0,c=cases[index];q('report-form').reset();q('report-reference').textContent=`当前情境：${c.identity.role_id} · ${c.identity.date} · 第 ${index+1} 轮`;q('report-status').textContent='';q('report-dialog').showModal();q('report-category').focus();});
 q('report-close').addEventListener('click',()=>q('report-dialog').close());
 q('report-form').addEventListener('submit',async e=>{e.preventDefault();try{const index=Number(q('joint-select').value)||0,issue={category:q('report-category').value,description:q('report-description').value},serialized=JSON.stringify({case_index:index,issue});if(live){if(!pendingIssue||pendingIssue.serialized!==serialized)pendingIssue={serialized,key:crypto.randomUUID(),record:{...issueRecord(cases[index],hashes[index],issue,q('joint-error').textContent),status:'engineering_issue_submission'}};const saved=await postLive('issues',{case_index:index,record:pendingIssue.record,request_id:pendingIssue.key});pendingIssue=null;q('report-status').textContent='问题已保存；报告编号：'+saved.receipt_id+'。';}else{const record=issueRecord(cases[index],hashes[index],issue,q('joint-error').textContent);downloadJson(record,'joint-b-local-issue.json');q('report-status').textContent='已下载问题记录；尚未提交给研究团队。';}}catch(error){q('report-status').textContent=error.message;}});
 api.show=show;api.current=()=>({case:cases[current],input:currentInput});show(0);
})(typeof window!=='undefined'?window:globalThis);
