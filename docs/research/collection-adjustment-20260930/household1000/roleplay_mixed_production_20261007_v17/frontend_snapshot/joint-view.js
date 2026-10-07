"use strict";
(function(root){
 const clone=x=>JSON.parse(JSON.stringify(x));
 const canonical=x=>JSON.stringify(sort(x));
 function sort(x){if(Array.isArray(x))return x.map(sort);if(x&&typeof x==='object')return Object.fromEntries(Object.keys(x).sort().map(k=>[k,sort(x[k])]));return x;}
 async function hash(x){const raw=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(x)));return [...new Uint8Array(raw)].map(x=>x.toString(16).padStart(2,'0')).join('');}
 const q=id=>document.getElementById(id),el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=String(text);if(cls)e.className=cls;return e;};
 const location=(zone,labels={})=>{const z=labels[zone]||zone;const name=({bathroom:'卫浴',kitchen:'厨房',living_hall:'起居厅',corridor:'过道'}[z])||String(z||'').replace(/^natural_(\d+)$/,'自然间 $1');return name==='位置未提供'?'':name;};
 const named=(asset,labels)=>[asset.device,location(asset.zone,labels)].filter(Boolean).join(' · ');
 const time=(value,base)=>{const m=value-base,d=Math.floor(m/1440),v=((m%1440)+1440)%1440;return `${d===0?'当天':d===1?'次日':d<0?(d===-1?'前日':`前${-d}日`):`第${d+1}天`} ${String(Math.floor(v/60)).padStart(2,'0')}:${String(v%60).padStart(2,'0')}`;};
 const label=e=>e.operation_kind==='heater_availability'?'允许加热时段':e.setpoint_C!=null?`设定温度 ${e.setpoint_C} ℃`:'安排时段';
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
 function displayedRows(c){const b=new Map(c.plans.B.rows.map(r=>[r.asset_id,r]));
  return c.plans.A.rows.filter(a=>b.has(a.asset_id));}
 function chart(c){const base=dayBase(c),assets=Object.fromEntries(c.profile.profile.devices.map(a=>[a.asset_id,a])),selected=new Set(c.commands.map(x=>x.asset_id)),b=new Map(c.plans.B.rows.map(r=>[r.asset_id,r]));
  const [start,end]=focusWindow(c);
  return {schedule_chart:{start_h:(start-base)/60,end_h:(end-base)/60,event_start_h:(eventList(c)[0].start_abs_min-base)/60,event_end_h:(eventList(c)[0].end_abs_min-base)/60,event_windows:eventList(c).map(e=>({start_h:(e.start_abs_min-base)/60,end_h:(e.end_abs_min-base)/60})),notification_h:(c.vpp.notice_abs_min-base)/60,statistics_window:null,
   rows:displayedRows(c).map(a=>({device_id:a.asset_id,icon_device_id:a.device_class,device:named(assets[a.asset_id],c.profile.geometry?.zone_labels),active:selected.has(a.asset_id),schedule_complete:a.schedule_complete&&b.get(a.asset_id).schedule_complete,
    original:a.events.map(e=>({...e,start_h:(e.start_abs_min-base)/60,end_h:(e.end_abs_min-base)/60,label:label(e)})),proposal:b.get(a.asset_id).events.map(e=>({...e,start_h:(e.start_abs_min-base)/60,end_h:(e.end_abs_min-base)/60,label:label(e)}))}))},
   options:{sideLabels:{original:'原安排 A',proposal:'调整后 B'},eventLabel:'调整目标时段',axisLabel:'设备安排时间轴',deviceHint:(row,id)=>id==='ac'?' · 温度设定':'',emptyText:{original:r=>r.schedule_complete?'此侧未安排':'未提供安排',proposal:r=>r.schedule_complete?'此侧未安排':'未提供安排'},legendText:'上行为原安排，下行为调整后。浅色区域为调整目标时段。',barText:s=>s.label}};
 }
 async function verify(c,expected){if(c.schema!=='eb.joint_b.consumer.v2')throw Error('不支持的统一页面来源版本');if(await hash(c)!==expected)throw Error('来源内容与绑定不一致');if(!Array.isArray(c.commands)||!c.commands.length)throw Error('缺少完整命令列表');if(c.profile.role_id!==c.identity.role_id)throw Error('家庭来源不一致');
  for(const [key,value]of [['profile_sha256',c.profile],['commands_sha256',c.commands],['A_plan_sha256',c.plans.A],['B_plan_sha256',c.plans.B],['vpp_sha256',c.vpp]])if(await hash(value)!==c.bindings[key])throw Error('来源字段绑定不一致');
  if(c.physical&&await hash(c.physical)!==c.bindings.physical_sha256)throw Error('物理状态绑定不一致');
  if(new Set(c.commands.map(x=>x.command_id)).size!==c.commands.length)throw Error('命令编号重复');return true;
 }
 const hourText=h=>{const n=Math.round(h*60),day=n>=1440?'次日 ':'';return `${day}${String(Math.floor(n%1440/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;};
 function referenceText(e,ref){if(!ref||ref.source!=='synthetic_questionnaire_profile')return null;
  const h=ref.usual_start_hour,d=ref.usual_finish_hour,usual=[],difference=[],clock=((e.start_abs_min%1440)+1440)%1440;
  const overnight=Number.isFinite(h)&&h>=18&&clock<720;
  const referenceDay=Math.floor(e.start_abs_min/1440)*1440-(overnight?1440:0);
  if(Number.isFinite(h)){
   const minute=Math.round(h*60),delta=clock+(overnight?1440:0)-minute;
   usual.push(`${hourText(h)} 开始`);difference.push(delta===0?'B 按通常时间开始':`B ${delta>0?'晚':'早'} ${Math.abs(delta)} 分钟开始`);
  }
  if(Number.isFinite(d)){
   const finishLabel=ref.finish_meaning==='usual_end'?'通常结束':'通常最晚完成';
   const nextDay=Number.isFinite(h)&&d<h;
   const deadline=referenceDay+Math.round(d*60)+(nextDay?1440:0);
   const over=e.end_abs_min-deadline;
   usual.push(`${finishLabel} ${nextDay?'次日 ':''}${hourText(d)}`);difference.push(over>0?`B 晚于通常完成 ${over} 分钟`:'B 在通常完成时间内');
  }
  return usual.length?{usual:usual.join(' · '),difference:difference.join(' · ')}:null;
 }
 function renderPlans(c){const base=dayBase(c),[start,end]=focusWindow(c),assets=Object.fromEntries(c.profile.profile.devices.map(a=>[a.asset_id,a])),shown=new Set(displayedRows(c).map(r=>r.asset_id));
  for(const side of ['A','B']){const box=q('joint-plan-'+side);box.replaceChildren();for(const row of c.plans[side].rows.filter(r=>shown.has(r.asset_id))){const section=el('section',null,'joint-device-plan'),a=assets[row.asset_id],events=row.events.filter(e=>inWindow(e,start,end));section.append(el('strong',named(a,c.profile.geometry?.zone_labels)));
   if(!events.length)section.append(el('p',row.schedule_complete?'此侧未安排':'未提供安排'));
   for(const e of events)section.append(el('p',`${time(e.start_abs_min,base)}—${time(e.end_abs_min,base)} · ${label(e)}`));
   if(side==='B'&&events.length&&c.commands.some(command=>command.asset_id===row.asset_id)){const note=referenceText(events[0],c.profile.profile.operating_reference?.[row.device_class]);if(note){const context=el('div',null,'usual-compare');context.append(el('small',`家庭通常：${note.usual}`),el('small',note.difference));section.append(context);}}
   box.append(section);}}
  const changes=q('joint-changes');changes.replaceChildren();const grouped=new Map();for(const command of c.commands){const a=assets[command.asset_id],name=named(a,c.profile.geometry?.zone_labels);let difference;
   if(command.kind==='ac_setpoint')difference=`设定温度 ${command.from_setpoint_C}→${command.to_setpoint_C} ℃`;
   else{const minutes=command.start_abs_min-command.A_start_abs_min;difference=minutes===0?'时间不变':`${minutes>0?'延后':'提前'} ${Math.abs(minutes)} 分钟`;}
   const key=`${name}：${difference}`;grouped.set(key,(grouped.get(key)||0)+1);}
  for(const [text,count]of grouped)changes.append(el('span',text+(count>1?`（${count} 段）`:''),'joint-change'));
 }
 function renderResults(c){const box=q('joint-results');box.replaceChildren();for(const r of c.quantities){if(r.A.value==null&&r.B.value==null)continue;const fmt=x=>x.value==null?'未计算':`${Math.round(x.value*1000)/1000} ${x.unit}`;box.append(el('p',`${r.label}：A ${fmt(r.A)}；B ${fmt(r.B)}`));}for(const r of c.impacts||[])if(r.status!=='unknown'&&r.description)box.append(el('p',r.description));
  const tail=c.after_horizon;if(tail?.status==='computed_design_proxy'){const rows=tail.EV_new_target_shortfall_days||[];if(rows.length)box.append(el('p',`电动车充电目标：B 有 ${rows.length} 天未达到（${rows.join('、')}），A 均达到；这不代表无法出行。`));}
  const unified=c.physical;if(unified?.status==='failed')box.append(el('p','物理读回失败；本轮结果未知。'));else if(unified?.status==='partial'||unified?.status==='complete'){const rows=unified.channels.filter(ch=>ch.A.status==='computed'||ch.B.status==='computed');if(rows.length)box.append(el('h4','目标时段内的模型结果'));const fmt=(x,unit)=>x.status==='computed'?`${Math.round(x.value*1000)/1000} ${unit}`:'未计算';for(const ch of rows)box.append(el('p',`${ch.label}：A ${fmt(ch.A,ch.unit)}；B ${fmt(ch.B,ch.unit)}`));}
  if(!box.children.length)box.append(el('p','用电量、费用和舒适结果尚未计算。'));}
 const snapshotIds=['role-instructions','home-intro','home-visual','home-caption','home-summary','home-device-inventory','home-targets','home-members','home-attitudes','joint-date','joint-source-note','vpp-summary','joint-weather','joint-state','joint-needs-list','selected-assets','joint-timeline','joint-plan-A','joint-plan-B','joint-changes','joint-results','joint-history','answer-instructions','decision-question','score-question'];
 const modelFieldIds=snapshotIds.filter(id=>id!=='joint-date'&&id!=='joint-history');
 function snapshot(){return Object.fromEntries(snapshotIds.map(id=>{const e=q(id);if(id==='joint-needs-list'&&q('joint-needs').tagName==='DETAILS'&&!q('joint-needs').open)return [id,''];if((id==='joint-plan-A'||id==='joint-plan-B')&&!q('joint-plan-details').open)return [id,''];return [id,typeof e.innerText==='string'?e.innerText:e.textContent];}));}
 function modelInputFromSnapshot(rendered,assignment,history=[]){const fields={};for(const id of modelFieldIds){if(typeof rendered?.[id]!=='string')throw Error('可见字段缺失：'+id);fields[id]=rendered[id];}if(typeof rendered?.['joint-date']!=='string'||!/^\d{4}-\d{2}-\d{2}(?: · |$)/.test(rendered['joint-date']))throw Error('可见日期缺失');if(!assignment||assignment.left===assignment.right||!['A','B'].includes(assignment.left)||!['A','B'].includes(assignment.right))throw Error('左右安排无效');return {schema:'eb.joint_b.displayed_input.v1',date:rendered['joint-date'].slice(0,10),fields,display_assignment:clone(assignment),history:clone(history)};}
 async function exportRecord(c,input,expected,answer,rendered,presentedAt){await verify(c,expected);const clean=root.EBSourceDraft.buildAnswer(answer),auditInput=clone(input),modelInput=modelInputFromSnapshot(rendered,auditInput.display_assignment),link=c.collection_linkage||{household_id:c.identity.role_id,round_id:c.identity.round_index??null,source_scenario_id:c.identity.case_id,scenario_family_id:c.scenario_family_id??null,near_duplicate_or_derivative_relation:'pending_review',source_version_sha256:c.bindings?.A_manifest_sha256??null,participant_id:null,formal_split:null};return {schema:'eb.joint_b.local_test_export.v5',status:'engineering_click_not_human_feedback',input:modelInput,test_feedback:clean,
  audit:{collection_linkage:clone(link),semantic_input:auditInput,source_case:clone(c),source_binding:{source_package_sha256:expected,...c.bindings},presentation:{display_assignment:auditInput.display_assignment,presented_at:presentedAt,exported_at:new Date().toISOString(),joint_needs_expanded_at_export:q('joint-needs').tagName==='DETAILS'?Boolean(q('joint-needs').open):true,semantic_input_sha256:await hash(auditInput),rendered_snapshot:rendered,rendered_snapshot_sha256:await hash(rendered),model_input_sha256:await hash(modelInput)}},human_label_count:0,training_release:false,formal_export_eligible:false,history_status:'not_loaded_local_preview'};}
 function issueRecord(c,expected,issue,uiError=''){return {schema:'eb.joint_b.local_issue.v1',status:'local_download_not_submitted',issue:root.EBSourceDraft.buildIssue(issue),context:{household_id:c?.identity?.role_id??null,case_id:c?.identity?.case_id??null,round_index:c?.identity?.round_index??null,date:c?.identity?.date??null,source_package_sha256:expected??null,ui_error:String(uiError||'')},created_at:new Date().toISOString()};}
 const api={chart,hash,canonical,verify,snapshot,modelInputFromSnapshot,exportRecord,issueRecord,renderPlans,renderResults};root.EBJoint=api;
 if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;
 const live=root.EBLiveConfig||null,experienceOnly=root.EBExperienceOnly===true;
 if(experienceOnly){
  q('preview-mode-notice').textContent='请代入这户家庭，查看生活需求与 A/B 安排。您的选择只在当前页面显示，离开后不会保存。';
  q('answer-instructions').textContent='先判断 B 能否照此实行，再比较 A/B；四项分数均评价原样 B，不确定的分数可以留空。';
  q('joint-export').hidden=true;q('report-problem').hidden=true;
  q('joint-reason-label').firstChild.textContent='可以写下主要原因（不会保存）';
  const choice=(name,value,title)=>{const label=el('label',null,'check'),input=el('input');input.type='radio';input.name=name;input.value=value;label.append(input,document.createTextNode(title));return label;};
  const decision=q('decision-question'),decisionRows=el('div',null,'inline-choices');
  decisionRows.append(choice('experience_decision','accept','可以照此接受 B'),choice('experience_decision','modify','修改后才接受 B'),choice('experience_decision','reject','不能接受 B'));
  decision.replaceChildren(el('legend','调整后 B 能否照此实行？'),decisionRows);
  const preference=el('fieldset',null,'decision-choices'),preferenceRows=el('div',null,'inline-choices');
  preferenceRows.append(choice('experience_preference','A','原安排 A'),choice('experience_preference','B','调整后 B'),choice('experience_preference','equal','两者同样可接受'),choice('experience_preference','neither','两者都不合适'));
  preference.append(el('legend','原样 A 与原样 B 相比，您更偏好哪一个？'),preferenceRows);
  q('score-question').before(preference);
 }else if(live){q('preview-mode-notice').textContent='合成家庭工程体验 · 请代入这户家庭，依据生活需求和 A/B 安排判断是否采用 B。回答和问题报告会在线保存。';q('report-mode-notice').textContent='提交后会显示报告编号。';q('report-submit').textContent='提交问题';q('joint-export').textContent='保存工程试填';}
 const cases=JSON.parse(q('joint-cases-data').textContent),inputs=JSON.parse(q('visible-inputs-data').textContent),hashes=JSON.parse(q('source-hashes-data').textContent);let current=0,currentInput=null,presentedAt=null;
 const scoreKeys=['score','comfort-score','energy-score','vpp-score'];
 function syncScore(key){const number=q('joint-'+key),range=q('joint-'+key+'-range'),meaning=q('joint-'+key+'-meaning'),raw=number.value,n=Number(raw),anchors=['很不合适','较不合适','一般','较合适','很合适'];
  range.parentElement?.classList.toggle('unanswered',raw==='');
  if(raw===''){meaning.textContent='尚未评分';return;}
  if(!Number.isFinite(n)||n<1||n>5){meaning.textContent='请填写 1–5 分';return;}
  range.value=raw;meaning.textContent=Number.isInteger(n)?`${n} 分 · ${anchors[n-1]}`:`${raw} 分 · ${anchors[Math.floor(n)-1]}与${anchors[Math.ceil(n)-1]}之间`;
 }
 for(const key of scoreKeys){q('joint-'+key).addEventListener('input',()=>syncScore(key));q('joint-'+key+'-range').addEventListener('input',()=>{q('joint-'+key).value=q('joint-'+key+'-range').value;syncScore(key);});syncScore(key);}
 async function show(i){q('joint-error').textContent='';q('joint-export').disabled=true;try{const c=cases[i];await verify(c,hashes[i]);current=i;currentInput=clone(inputs[i]);currentInput.history=[];currentInput.display_assignment=experienceOnly?clone(c.display_assignment):{left:'A',right:'B'};presentedAt=new Date().toISOString();q('joint-feedback').reset();q('joint-status').textContent='';
   if(experienceOnly){const cards={A:q('joint-plan-A').closest('.plan-card'),B:q('joint-plan-B').closest('.plan-card')};q('joint-comparison').replaceChildren(cards[c.display_assignment.left],cards[c.display_assignment.right]);}
   for(const key of scoreKeys)syncScore(key);
   renderHome(c.identity.role_id);q('joint-date').textContent=c.identity.date;const base=dayBase(c),v=q('vpp-summary');v.replaceChildren();for(const [n,event]of eventList(c).entries()){const request=el('p',null,'request-item'),goal=event.household_request.text.replace(/^本事件内[，,]?\s*/,'').replace(/^希望家庭从电网购入的电量比原安排少/,'家庭向电网购电比原安排少');request.append(el('strong',eventList(c).length>1?`调整目标 ${n+1}：`:'调整目标：'),el('span',`${time(event.start_abs_min,base)}—${time(event.end_abs_min,base)}，${goal}`));v.append(request);if(event.incentive?.text)v.append(el('p',event.incentive.text,'request-extra'));}v.append(el('p',`通知时间：${time(c.vpp.notice_abs_min,base)}`,'request-notice'));
   const weather=c.context.weather_days?.[0];q('joint-weather').textContent=weather?`气温 ${weather.min_drybulb_C_derived}–${weather.max_drybulb_C_derived}℃`:'';const state=c.context.pre_event_state?.display_text||'';q('joint-state').textContent=/未提供|未单独核算/.test(state)?'':state;q('joint-more-context').hidden=!q('joint-weather').textContent&&!q('joint-state').textContent;
   const needs=q('joint-needs-list');needs.replaceChildren();const dailyNeeds=c.context.daily_need_texts||[];for(const raw of dailyNeeds){const text=raw.replace(/（合成情境需求）/g,'').replace(/约 跨日时段，(\d+)\s*%/g,'跨日时段，目标 $1%'),match=text.match(/^(当天|次日)：(.*)$/),row=el('p',null,'need-item');if(match)row.append(el('span',match[1],'need-day'),el('span',match[2],'need-content'));else row.textContent=text;needs.append(row);}if(dailyNeeds.some(x=>x.includes('洗衣'))&&!c.profile.profile.devices.some(x=>x.device_class==='washer'&&x.installed!==false&&x.owned!==false))needs.append(el('p','设备清单中没有洗衣机；洗衣方式未提供。','need-note'));if(!needs.children.length)needs.append(el('p','本轮没有额外生活需求。'));q('selected-assets').textContent='';
   const view=chart(c);root.EBView.render(q('joint-timeline'),view,view.options);renderPlans(c);renderResults(c);q('joint-history').textContent='';q('joint-export').disabled=false;
  }catch(e){q('joint-error').textContent='无法展示：'+e.message;}}
 cases.forEach((c,i)=>{const option=el('option',`情境 ${i+1} · ${c.identity.date} · ${c.profile.profile.household.city||'城市未知'}`);option.value=String(i);q('joint-select').append(option);});q('joint-select').addEventListener('change',()=>show(Number(q('joint-select').value)));
 function downloadJson(record,name){const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),500);}
 async function postLive(path,payload){if(experienceOnly)throw Error('此页面仅供体验，回答不会保存。');const response=await fetch(live.base+'/api/'+path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-EB-CSRF':live.csrf},body:JSON.stringify(payload)}),data=await response.json();if(!response.ok||!data.saved)throw Error(data.error||'服务器未确认保存，请重试。');return data;}
 let pendingAnswer=null,pendingIssue=null;
 q('joint-feedback').addEventListener('submit',e=>e.preventDefault());q('joint-export').addEventListener('click',async()=>{if(experienceOnly)return;try{const answer={choice:document.querySelector('[name="source_decision"]:checked')?.value,score:q('joint-score').value,comfort_score:q('joint-comfort-score').value,energy_score:q('joint-energy-score').value,vpp_score:q('joint-vpp-score').value,comment:q('joint-comment').value};
  const serialized=JSON.stringify({case_index:current,answer});if(live){if(!pendingAnswer||pendingAnswer.serialized!==serialized)pendingAnswer={serialized,key:crypto.randomUUID(),record:await exportRecord(cases[current],currentInput,hashes[current],answer,snapshot(),presentedAt)};const saved=await postLive('answers',{case_index:current,record:pendingAnswer.record,request_id:pendingAnswer.key});pendingAnswer=null;q('joint-status').textContent='工程试填已保存；回执编号：'+saved.receipt_id+'。不计作正式人类反馈。';}else{const record=await exportRecord(cases[current],currentInput,hashes[current],answer,snapshot(),presentedAt);downloadJson(record,'joint-b-local-test.json');q('joint-status').textContent='已下载本地测试记录；未提交，不计作人类反馈。';}}catch(e){q('joint-status').textContent=e.message;}});
 q('report-problem').addEventListener('click',()=>{if(experienceOnly)return;const index=Number(q('joint-select').value)||0,c=cases[index];q('report-form').reset();q('report-reference').textContent=`当前情境：${c.identity.role_id} · ${c.identity.date} · 第 ${index+1} 轮`;q('report-status').textContent='';q('report-dialog').showModal();q('report-category').focus();});
 q('report-close').addEventListener('click',()=>q('report-dialog').close());
 q('report-form').addEventListener('submit',async e=>{e.preventDefault();if(experienceOnly)return;try{const index=Number(q('joint-select').value)||0,issue={category:q('report-category').value,description:q('report-description').value},serialized=JSON.stringify({case_index:index,issue});if(live){if(!pendingIssue||pendingIssue.serialized!==serialized)pendingIssue={serialized,key:crypto.randomUUID(),record:{...issueRecord(cases[index],hashes[index],issue,q('joint-error').textContent),status:'engineering_issue_submission'}};const saved=await postLive('issues',{case_index:index,record:pendingIssue.record,request_id:pendingIssue.key});pendingIssue=null;q('report-status').textContent='问题已保存；报告编号：'+saved.receipt_id+'。';}else{const record=issueRecord(cases[index],hashes[index],issue,q('joint-error').textContent);downloadJson(record,'joint-b-local-issue.json');q('report-status').textContent='已下载问题记录；尚未提交给研究团队。';}}catch(error){q('report-status').textContent=error.message;}});
 api.show=show;api.current=()=>({case:cases[current],input:currentInput});show(0);
})(typeof window!=='undefined'?window:globalThis);
