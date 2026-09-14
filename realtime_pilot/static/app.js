"use strict";
function feedbackCompatible(job){return (schema.feedback_compatible_versions||[schema.paired_version]).includes(job.result.schema_version);}
const $ = id => document.getElementById(id);
let schema, currentJob, timer;
const adminView=location.pathname==='/admin/survey';
const draftStorage=adminView?{getItem:key=>window.localStorage.getItem('eb:admin:'+key),setItem:(key,value)=>window.localStorage.setItem('eb:admin:'+key,value),removeItem:key=>window.localStorage.removeItem('eb:admin:'+key)}:window.localStorage;
const terminal = new Set(["complete","failed","timeout","cancelled","interrupted","expired"]);
const el = (tag, text, className) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
function error(message){const box=$("error");box.textContent=message;box.hidden=false;box.setAttribute('tabindex','-1');box.focus({preventScroll:true});box.scrollIntoView({block:'center',behavior:'smooth'});}
async function api(path,body){
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
 try{
  const response=await fetch((adminView&&path.startsWith('/api/')?'/admin':'')+path,{signal:controller.signal,credentials:"same-origin",...(body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})});
  let data;try{data=await response.json();}catch{}
  if(!response.ok){
   const messages={401:adminView?'管理员登录已失效，请刷新后重新登录。':'页面会话已失效，请刷新后重试。',429:'当前请求较多，请稍后再试。',502:'计算服务暂时不可用，请稍后再试。',503:'服务暂时不可用，请稍后再试。',504:'服务器响应超时，请稍后再试。'};
   const failure=new Error(data?.error||messages[response.status]||'请求失败，请稍后再试。');failure.code=data?.code;failure.refreshCaptcha=data?.refresh_captcha===true;failure.status=response.status;throw failure;
  }
  if(!data||typeof data!=='object')throw new Error('服务器返回异常，请稍后再试。');
  return data;
 }finally{clearTimeout(timeout);}
}
// Keep canonical select values for saved snapshots; present short option lists directly.
function inlineChoices(select,options,required=false){
 const group=el('div',undefined,'inline-choices');group.setAttribute('role','group');group.dataset.selectionMode=select.multiple?'multi':'single';
 const prompt=select.closest('.field,.member-field')?.querySelector('.question-label,span')?.textContent||'选择一项';group.setAttribute('aria-label',prompt);
 select.hidden=true;select.required=false;
 for(const o of options){const label=el('label',undefined,'inline-choice'),input=el('input');input.type=select.multiple?'checkbox':'radio';input.name=select.id+'__choices';input.value=o.value;input.required=required;
  input.onchange=()=>{if(select.multiple){for(const opt of select.options)if(opt.value===o.value)opt.selected=input.checked;}else if(input.checked)select.value=o.value;select.dispatchEvent(new Event('change',{bubbles:true}));};
  label.append(input,el('span',o.label));group.append(label);
 }
 select.after(group);
 let clear;if(!required){clear=el('button','清除此题选择','choice-clear');clear.type='button';clear.setAttribute('aria-label','清空：'+prompt);clear.onclick=()=>{if(select.multiple){for(const opt of select.options)opt.selected=false;}else select.value='';select.dispatchEvent(new Event('change',{bubbles:true}));};group.after(clear);}
 select._choiceSync=()=>{for(const input of group.querySelectorAll('input')){input.checked=select.multiple?[...select.selectedOptions].some(o=>o.value===input.value):input.value===select.value;input.disabled=select.disabled;}if(clear){clear.disabled=select.disabled||!select.value;clear.hidden=clear.disabled;}};select._choiceSync();
}

function memberFieldValue(select){return select.multiple?[...select.selectedOptions].map(o=>o.value):select.value||null;}
const memberSupplemental=new Set(['life_roles','needs_priority','cost_importance','grid_importance']);
// Page visibility is independent of membership: every current member is saved.
function memberValues(q){const root=$('p_'+q.id);return [...root.querySelectorAll('.member-card')].slice(0,Number(root.dataset.count)||0).map(card=>Object.fromEntries(q.fields.map(f=>[f.id,memberFieldValue(card.querySelector(`[data-member-field="${f.id}"]`))])));}
function memberRoot(){return document.querySelector('.member-section');}
function showMember(index,{scroll=false,save=true}={}){
 const root=memberRoot();if(!root)return;
 const count=Number(root.dataset.count)||0;
 root.dataset.activeMember=Math.max(0,Math.min(index,count-1));
 for(const [i,card] of [...root.querySelectorAll('.member-card')].entries())card.hidden=i!==Number(root.dataset.activeMember)||i>=count;
 const nav=root.querySelector('.member-navigation');nav.replaceChildren();nav.hidden=count<2;
 for(let i=0;i<count;i++){const b=el('button',`成员 ${i+1}`,'secondary');b.type='button';b.setAttribute('aria-current',i===Number(root.dataset.activeMember)?'step':'false');b.disabled=!!pendingSubmit;b.onclick=()=>showMember(i,{scroll:true});nav.append(b);}
 root.querySelector('.member-count').textContent=count?`正在填写第 ${Number(root.dataset.activeMember)+1} / ${count} 位成员`:'';
 syncMemberNavigation();
 if(save)saveDraft();
 if(scroll){root.scrollIntoView({block:'start'});root.querySelector('.member-count').focus({preventScroll:true});}
}
function syncMemberNavigation(){
 if(wizardStep!==1)return;const root=memberRoot();if(!root)return;
 const index=Number(root.dataset.activeMember)||0,count=Number(root.dataset.count)||0;
 $('wizard-prev').textContent=index?'上一位成员':'上一步';
 $('wizard-next').textContent=index<count-1?'下一位成员':'下一步：电器安排';
}
function syncMembers(){
 const q=schema.profile_questions.find(q=>q.type==='member_list');if(!q)return;
 const root=$('p_'+q.id),size=$('p_B02')?.value?JSON.parse($('p_B02').value):null;
 const count=size==='6_plus'?Math.max(6,Number(root.dataset.count)||6):Number(size)||0;
 root.dataset.count=count;
 const list=root.querySelector('.member-cards');
 while(list.children.length<count){const i=list.children.length,card=el('fieldset',undefined,'member-card'),core=el('div',undefined,'member-core'),extra=el('section',undefined,'member-extra'),extraBody=el('div',undefined,'member-extra-fields');card.append(el('legend',`成员 ${i+1}`),core);extra.append(el('h4','补充了解（均可选填）'),extraBody);
  for(const f of q.fields){const label=el('div',undefined,'member-field'),select=el('select');select.multiple=f.type==='multi_choice';select.dataset.memberField=f.id;select.id=`p_member_${i}_${f.id}`;
   const empty=el('option',f.required?'请选择':'选填');empty.value='';if(!select.multiple)select.append(empty);
   for(const o of f.options){const option=el('option',o.label);option.value=o.value;select.append(option);}select.required=!!f.required;
   label.append(el('span',f.prompt+(f.required||f.prompt.includes('选填')?'':'（选填）')),select);(memberSupplemental.has(f.id)?extraBody:core).append(label);inlineChoices(select,f.options,!!f.required);
  }card.append(extra);list.append(card);
 }
 [...list.children].forEach((card,i)=>{for(const s of card.querySelectorAll('select')){s.disabled=i>=count||!!currentJob;s._choiceSync?.();}});
 root.querySelector('.member-empty').hidden=!!count;
 root.querySelector('.member-actions').hidden=size!=='6_plus';
 root.querySelector('[data-member-add]').disabled=!!currentJob||count>=q.max_members;
 root.querySelector('[data-member-remove]').disabled=!!currentJob||count<=6;
 showMember(Number(root.dataset.activeMember)||0,{save:false});
}
// Display-only wording; frozen questionnaire definitions and answers stay intact.
function participantHelp(q){
 const hints={X_CITY:'找不到所在城市时，可以选择自行填写。',X_AREA_BASIS:'请按您知道的面积类型选择。建筑面积通常含公摊，套内使用面积不含公摊。'};
 return hints[q.id]??q.help;
}
function memberQuestion(q,container,prefix){
 const root=el('section',undefined,'member-section');root.id=prefix+q.id;root.dataset.questionId=q.id;
 root.append(el('h3',q.prompt),el('p',participantHelp(q),'hint'),el('p','先选择家庭人数，即可填写成员卡片。','member-empty'),el('p','','member-count'));
 root.querySelector('.member-count').tabIndex=-1;
 const nav=el('nav',undefined,'member-navigation');nav.setAttribute('aria-label','选择家庭成员');root.append(nav,el('div',undefined,'member-cards'));
 const actions=el('div',undefined,'member-actions');for(const [key,text,delta] of [['add','增加一位成员',1],['remove','减少一位成员',-1]]){const b=el('button',text,'secondary');b.type='button';b.dataset[key==='add'?'memberAdd':'memberRemove']='';b.onclick=()=>{root.dataset.count=Math.min(q.max_members,Math.max(6,Number(root.dataset.count)+delta));syncMembers();saveDraft();};actions.append(b);}root.append(actions);container.append(root);
}
function intakeRequired(q){
 if(Object.hasOwn(q,'required_for_intake'))return !!q.required_for_intake;
 // Frozen pre-v4.3 snapshots can still be reviewed.  This compatibility path
 // only controls their disabled/read-only form semantics; current submissions
 // always use the explicit server contract.
 return !!q.required||['B02','B04','B05','F_EVENING'].includes(q.id)||(!!q.device&&!q.show_when)||(['attitude','stated_preference'].includes(q.group)&&!q.device);
}

function question(q, container, prefix){
  if(q.type==="member_list"){memberQuestion(q,$("member-questions"),prefix);return;}
  const row=el("div",undefined,["attitude","stated_preference"].includes(q.group)&&!q.device?"attitude-row":"field");
  if(["P_COMFORT","P_COST","P_GRID"].includes(q.id))row.classList.add("importance-row");
  const required=intakeRequired(q),requirement=required?'（必填）':q.environment_input?'（需填写）':q.research_only&&!q.prompt.includes('选填')?'（选填）':'';
  const label=el("label",q.prompt+requirement,"question-label");label.htmlFor=prefix+q.id;row.append(label);
  if(q.type==="multi_choice"||(["attitude","stated_preference"].includes(q.group)&&!q.device)){
    const group=el("div",undefined,["attitude","stated_preference"].includes(q.group)?"attitude-options":"options");group.id=prefix+q.id;group.setAttribute("role","group");group.setAttribute("aria-label",q.prompt);
    for(const option of q.options){const l=el("label",undefined,"check"),input=el("input");input.type=["attitude","stated_preference"].includes(q.group)?"radio":"checkbox";input.name=prefix+q.id;if(required&&input.type==='radio')input.required=true;input.value=JSON.stringify(option.value);l.append(input);if(q.id==="B05"){l.dataset.deviceValue=option.value;l.append(EBTime.icon(option.value));}if(row.classList.contains("importance-row"))l.append(el("strong",option.value,"importance-number"));l.append(el("span",option.label));group.append(l);}row.append(group);
  }else if(q.type==="temperature_range"){
    EBTime.temperatureRange(q,row,prefix,required);
  }else if(q.type==="text"){
    const t=el(q.cities_by_region?'input':'textarea');t.id=prefix+q.id;t.maxLength=1000;t.placeholder=q.environment_input?'填写实际常住城市':'可以留空';row.append(t);
    if(q.cities_by_region){
     const cities=el('select');cities.id=prefix+q.id+'_choices';cities.setAttribute('aria-label','常住城市');row.insertBefore(cities,t);
     cities.onchange=()=>{t.hidden=cities.value!=='__other';t.value=cities.value==='__other'?'':cities.value;t.dispatchEvent(new Event('change',{bubbles:true}));if(!t.hidden)t.focus();};
     t._citiesSync=(provinceChanged=false)=>{
      const province=$('p_X_REGION')?.value?JSON.parse($('p_X_REGION').value):'';
      const manual=cities.value==='__other'&&!provinceChanged;
      if(provinceChanged)t.value='';
      const available=q.cities_by_region[province]||[];
      const placeholder=el('option',province?'请选择常住城市':'请先选择省级地区');placeholder.value='';cities.replaceChildren(placeholder);
      for(const city of available){const option=el('option',city);option.value=city;cities.append(option);}
      if(province){const other=el('option',available.length?'其他城市（自行填写）':'填写常住城市');other.value='__other';cities.append(other);}
      const actual=t.value.trim().replace(/市$/,'');cities.value=available.includes(actual)?actual:t.value||manual?'__other':'';
      if(province&&!available.length)cities.value='__other';
      t.hidden=cities.value!=='__other';cities.disabled=!province||!!currentJob;t.disabled=!province||!!currentJob;
     };
    }
  }else{const s=el("select");s.id=prefix+q.id;const empty=el("option","请选择");empty.value="";s.append(empty);for(const o of q.options){const option=el("option",o.label);option.value=JSON.stringify(o.value);s.append(option);}row.append(s);}
  row.dataset.questionId=q.id; if(q.device)row.dataset.device=q.device;
  container.append(row);
  const answerHint=EBTime.answerHint(q);
  if(answerHint)row.append(el('p',answerHint,'answer-hint'));
  if(q.type==='multi_choice')row.insertBefore(el('small','可多选','selection-guide'),row.children[1]);
  if(q.help)row.append(el('p',participantHelp(q),'hint'));
  const select=row.querySelector("select");if(select){
   if(q.id==="X_REGION"||q.cities_by_region){$(prefix+q.id)?._citiesSync?.();return;}
   if(q.research_only||q.environment_input||!q.device||q.id==='H_ac'||q.group==='stated_preference'&&!['P_HOT_WATER','P_AC_CHANGE'].includes(q.id))inlineChoices(select,q.options.map(o=>({value:JSON.stringify(o.value),label:o.label})),required);
   else{select.required=required;EBTime.mount(q,select,row);}
 }
}
function collect(questions,prefix){const answers={};for(const q of questions){if(q.type==="member_list"){answers[q.id]=memberValues(q);continue;}if(q.type==="multi_choice"||(["attitude","stated_preference"].includes(q.group)&&!q.device)){const values=[...document.getElementsByName(prefix+q.id)].filter(x=>x.checked).map(x=>JSON.parse(x.value));answers[q.id]=q.type==="multi_choice"?values:values[0]??null;}else{const value=$(prefix+q.id).value;answers[q.id]=q.type==="text"?value:value?JSON.parse(value):null;}}for(const q of questions){const row=document.querySelector(`[data-question-id="${q.id}"]`);if(row?.hidden)answers[q.id]=null;}return answers;}
function renderQuestions(questions){schema.profile_questions=questions;$("basic-questions").replaceChildren();$("attitude-questions").replaceChildren();$("device-questions").replaceChildren();$("member-questions").replaceChildren();$("housing-questions").replaceChildren();$("research-questions").replaceChildren();EBTime.group($("basic-questions"),questions.filter(q=>!q.research_only&&!q.environment_input),(q,c)=>question(q,c,"p_"),$("device-questions"));for(const q of questions.filter(q=>["attitude","stated_preference"].includes(q.group)&&!q.device))question(q,$("attitude-questions"),"p_");for(const q of questions.filter(q=>q.research_only||q.environment_input))question(q,$(q.research_section==="housing"?"housing-questions":"research-questions"),"p_");showWizard(0,{save:false});}
function restore(profile){for(const q of schema.profile_questions){if(q.type==="member_list")continue;const cell=profile[q.id];if(!cell)continue;let value=cell.response_status==="answered"?cell.value:cell.response_status;if(q.type==="multi_choice"||(["attitude","stated_preference"].includes(q.group)&&!q.device)){if(!Array.isArray(value))value=[value];for(const input of document.getElementsByName("p_"+q.id))input.checked=value.includes(JSON.parse(input.value));}else $("p_"+q.id).value=cell.response_status!=="answered"?"":q.type==="text"?value:JSON.stringify(value);}
 document.querySelectorAll('[data-temperature-answer]').forEach(input=>input._temperatureSync?.());
 const mq=schema.profile_questions.find(q=>q.type==='member_list');if(mq){const values=profile[mq.id]?.value||[];$('p_'+mq.id).dataset.count=values.length;syncMembers();values.forEach((member,i)=>{const card=$('p_'+mq.id).querySelectorAll('.member-card')[i];if(card)for(const f of mq.fields){const s=card.querySelector(`[data-member-field="${f.id}"]`);if(s.multiple){for(const o of s.options)o.selected=(member[f.id]||[]).includes(o.value);}else s.value=member[f.id]||'';}});}
}
const devices={ac:"空调",washer:"洗衣机",dishwasher:"洗碗机",dryer:"烘干机",electric_water_heater:"电热水器",home_ev:"家用电动汽车充电"};
const scoreFields={score:"整体：这份方案总体适合您家吗？",comfort_score:"舒适：室温和生活安排的变化合适吗？",energy_score:"用电与费用：模拟用电量和费用符合您家期望吗？",vpp_score:"响应安排：您对本次错峰用电的处理方式满意吗？请考虑安排调整和自主决定体验。"};
let generation=0,pendingSubmit=false;
const UI_VERSION="eb.survey_ui.v6.18";
const RESEARCH_NOTICE_VERSION="eb.research_notice.v2";
let savedReceipt=null,savedHouseholdRecord=null;
const pendingDecisions=new Set(),pendingRequests=new Map();
let loadFailures=0,loadingId=null;
function readBrowser(store,key){try{return JSON.parse(store.getItem(key)||'null');}catch{return null;}}
function writeBrowser(store,key,value){try{store.setItem(key,JSON.stringify(value));return true;}catch{return false;}}
function removeBrowser(store,key){try{store.removeItem(key);}catch{}}
function stableJson(value){return JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);}
function householdBody(){return {answers:collect(schema.profile_questions,'p_'),questionnaire_version:schema.paired_questionnaire_version,questionnaire_hash:schema.paired_questionnaire_hash,questionnaire_context_hash:schema.questionnaire_context.context_hash};}
function householdFingerprint(body=householdBody()){return stableJson({answers:body.answers,questionnaire_version:body.questionnaire_version,questionnaire_hash:body.questionnaire_hash,questionnaire_context_hash:body.questionnaire_context_hash});}
function receiptMatches(){try{return !!savedReceipt&&savedReceipt.fingerprint===householdFingerprint();}catch{return false;}}
function saveReceipt(receipt,body){savedReceipt={id:receipt.id||receipt.submission_id,household_record_hash:receipt.household_record_hash,questionnaire_version:receipt.questionnaire_version||body.questionnaire_version,questionnaire_hash:receipt.questionnaire_hash||body.questionnaire_hash,created_at:receipt.created_at,environment_readiness:receipt.environment_readiness,case_ids:receipt.case_ids||[],fingerprint:householdFingerprint(body)};writeBrowser(draftStorage,'eb:household-receipt',savedReceipt);renderReceipt();}
function renderReceipt(){
 const panel=$('household-receipt');if(!panel)return;panel.hidden=!savedReceipt;
 syncHistoryVisibility();
 if(!savedReceipt)return;
 $('receipt-id').textContent=savedReceipt.id;
 $('receipt-status').textContent=receiptMatches()?'这份家庭资料已保存。'+(savedReceipt.environment_readiness?.status==='ready'?'可以继续查看用电安排。':savedReceipt.environment_readiness?.issues?.join('；')||''):'当前回答有改动，请重新保存后再继续。';
 $('plan-saved').hidden=!!currentJob;
 $('plan-saved').disabled=pendingSubmit||schema?.planning_enabled===false||!receiptMatches();
}
function availability(){
 for(const button of document.querySelectorAll('[data-wizard-step],#wizard-prev,#wizard-next,#history button'))button.disabled=!!pendingSubmit;
 const paused=schema?.planning_enabled===false;
 $('planning-status').hidden=!paused;
 $('planning-status').textContent=paused?'暂未开放方案生成；您仍可以完成问卷并保存家庭资料。':'';
 $('generate').disabled=pendingSubmit||!!currentJob;
 $('generate').textContent=pendingSubmit?'正在保存或提交…':paused?'保存家庭资料':'保存并生成两份安排 →';
 renderReceipt();renderRetryControl(currentJob);
}
function decisionDraftKey(job){return 'eb:decision-draft:'+job.id+':'+job.result.display_hash;}
function saveDecisionDraft(){
 const j=currentJob;if(!j||j.status!=='complete'||j.decision_saved||!feedbackCompatible(j))return;
 const draft={choice:document.querySelector('input[name="decision"]:checked')?.value||null,scores:Object.fromEntries(Object.keys(scoreFields).map(k=>[k,scoreInputs(k)[0]?.value||''])),comment:$("decision-reason").value};
 try{draftStorage.setItem(decisionDraftKey(j),JSON.stringify(draft));$("decision-status").textContent="评价草稿已保存在此浏览器，尚未提交。";}catch{$("decision-status").textContent="此浏览器无法保存评价草稿，请保持页面打开并提交。";}
}
function restoreDecisionDraft(job){
 if(job.decision_saved){try{draftStorage.removeItem(decisionDraftKey(job));}catch{}return;}
 if(!feedbackCompatible(job))return;
 try{const d=JSON.parse(draftStorage.getItem(decisionDraftKey(job))||'null');if(!d)return;
 for(const x of document.getElementsByName('decision'))x.checked=x.value===d.choice;
 $("decision-reason").value=typeof d.comment==='string'?d.comment:'';
 for(const k of Object.keys(scoreFields))for(const x of scoreInputs(k)){x.value=d.scores?.[k]??'';x._scoreSync?.();}
 $("decision-status").textContent="已恢复未提交的评价草稿，请确认后提交。";
 }catch{}
}
function draftKey(){return "eb:questionnaire-draft:"+schema.paired_questionnaire_version;}
let environmentTimer,environmentPreviewVersion=0;
function scheduleEnvironmentPreview(){
 clearTimeout(environmentTimer);const version=++environmentPreviewVersion;
 environmentTimer=setTimeout(async()=>{
  const panel=$('environment-preview');if(!schema||!panel)return;
  const questions=schema.profile_questions.filter(q=>q.environment_input);
  const answers=collect(questions,'p_');
  try{const result=await api('/api/environment-preview',{answers});if(version!==environmentPreviewVersion)return;
   panel.textContent=result.status==='ready'?'住房信息已填好，可以继续。':result.issues.join('；')+'。';
  }catch(e){if(version===environmentPreviewVersion)panel.textContent='暂时无法检查住房信息，您的回答仍保留，请稍后再试。';}
 },350);
}
function saveDraft(){if(!schema||currentJob||pendingSubmit)return;
 scheduleEnvironmentPreview();
 const saved=writeBrowser(draftStorage,draftKey(),{answers:collect(schema.profile_questions,'p_'),wizard_step:wizardStep,member_index:Number(memberRoot()?.dataset.activeMember)||0,questionnaire_context_hash:schema.questionnaire_context.context_hash,saved_at:Date.now()});
 writeBrowser(draftStorage,'eb:active-view',{mode:'draft',questionnaire_version:schema.paired_questionnaire_version});
 $('draft-status').textContent=saved?'草稿已保存在此浏览器，最后一步再提交。':'此浏览器无法保存草稿，请保持页面打开并完成最后的保存。';
 renderReceipt();
}
function migrateAnswers(answers,sourceVersion,contextHash){
 const copy=JSON.parse(JSON.stringify(answers));
 const compatiblePrecisionUpgrade=(sourceVersion==='eb.persona_questionnaire.v4.3'&&schema.paired_questionnaire_version==='eb.persona_questionnaire.v4.4')||(['eb.persona_questionnaire.v4.3','eb.persona_questionnaire.v4.4'].includes(sourceVersion)&&schema.paired_questionnaire_version==='eb.persona_questionnaire.v4.5');
 if(sourceVersion!==schema.paired_questionnaire_version&&schema.paired_questionnaire_version==='eb.persona_questionnaire.v4.5'){copy.A_EB_CONTROL=null;for(const m of copy.M_MEMBERS||[])for(const k of ['control','comfort','task'])m[k]=null;}
 if((sourceVersion!==schema.paired_questionnaire_version&&!compatiblePrecisionUpgrade)||contextHash!==schema.questionnaire_context.context_hash){
  for(const k of Object.keys(copy))if(/^(H_|D_|E_|T_|P_|X_FREQ_)/.test(k)||['B04','F_EVENING','X_BILL'].includes(k))copy[k]=null;
  for(const m of copy.M_MEMBERS||[])for(const k of ['routine','comfort','task'])m[k]=null;
 }
 if(schema.paired_questionnaire_version==='eb.persona_questionnaire.v4.0'&&sourceVersion!==schema.paired_questionnaire_version){
  if(copy.X_BUILDING==='house')copy.X_BUILDING=null;
  copy.X_AREA_BASIS=null;copy.X_FLOOR=null;
 }
 if(['eb.persona_questionnaire.v3.8','eb.persona_questionnaire.v3.9','eb.persona_questionnaire.v4.0'].includes(schema.paired_questionnaire_version)&&['eb.persona_questionnaire.v3.6','eb.persona_questionnaire.v3.7'].includes(sourceVersion)){
  for(const k of Object.keys(copy))if(k.startsWith('X_FREQ_')||['X_RESTORE','X_AREA'].includes(k))copy[k]=null;
  for(const m of copy.M_MEMBERS||[]){m.participation=null;m.grid_importance=null;m.needs_priority=null;}
 }
 return copy;
}
function answerProfile(answers){return Object.fromEntries(Object.entries(answers).map(([k,value])=>[k,{value,response_status:value==null?'skipped':'answered'}]));}
function restoreDraft(){try{
 const version=schema.paired_questionnaire_version;
 const versions=[version,...(version==='eb.persona_questionnaire.v4.5'?['eb.persona_questionnaire.v4.4','eb.persona_questionnaire.v4.3','eb.persona_questionnaire.v4.2','eb.persona_questionnaire.v4.1','eb.persona_questionnaire.v4.0','eb.persona_questionnaire.v3.9','eb.persona_questionnaire.v3.8']:version==='eb.persona_questionnaire.v4.4'?['eb.persona_questionnaire.v4.3','eb.persona_questionnaire.v4.2','eb.persona_questionnaire.v4.1','eb.persona_questionnaire.v4.0','eb.persona_questionnaire.v3.9','eb.persona_questionnaire.v3.8']:version==='eb.persona_questionnaire.v4.3'?['eb.persona_questionnaire.v4.2','eb.persona_questionnaire.v4.1','eb.persona_questionnaire.v4.0','eb.persona_questionnaire.v3.9','eb.persona_questionnaire.v3.8']:version==='eb.persona_questionnaire.v4.2'?['eb.persona_questionnaire.v4.1','eb.persona_questionnaire.v4.0','eb.persona_questionnaire.v3.9','eb.persona_questionnaire.v3.8']:version==='eb.persona_questionnaire.v4.1'?['eb.persona_questionnaire.v4.0','eb.persona_questionnaire.v3.9','eb.persona_questionnaire.v3.8']:version==='eb.persona_questionnaire.v4.0'?['eb.persona_questionnaire.v3.9','eb.persona_questionnaire.v3.8','eb.persona_questionnaire.v3.7','eb.persona_questionnaire.v3.6']:version==='eb.persona_questionnaire.v3.9'?['eb.persona_questionnaire.v3.8','eb.persona_questionnaire.v3.7','eb.persona_questionnaire.v3.6']:version==='eb.persona_questionnaire.v3.8'?['eb.persona_questionnaire.v3.7','eb.persona_questionnaire.v3.6']:version==='eb.persona_questionnaire.v3.7'?['eb.persona_questionnaire.v3.6']:[])];
 for(const source of versions){const d=JSON.parse(draftStorage.getItem('eb:questionnaire-draft:'+source)||'null');if(!d?.answers)continue;
  wizardStep=Number.isInteger(d.wizard_step)?d.wizard_step:0;restore(answerProfile(migrateAnswers(d.answers,source,d.questionnaire_context_hash)));showMember(Number(d.member_index)||0,{save:false});
  if(version==='eb.persona_questionnaire.v4.5'&&source!==version&&d.questionnaire_context_hash===schema.questionnaire_context.context_hash){$('draft-status').textContent='已恢复家庭资料；系统调整、室温感受和时间调整的选项已更新，请重新选择这几项。';return true;}
  if(source==='eb.persona_questionnaire.v4.3'&&version==='eb.persona_questionnaire.v4.4'&&d.questionnaire_context_hash===schema.questionnaire_context.context_hash){$('draft-status').textContent='已恢复上次填写内容；时间和温度选项已细化，原答案保留。';return true;}
  $('draft-status').textContent=(source!==version||d.questionnaire_context_hash!==schema.questionnaire_context.context_hash)?'已恢复家庭基本资料；情境日期或问卷已更新，请按指定月份重新填写习惯和偏好。原记录保留。':['eb.persona_questionnaire.v3.6','eb.persona_questionnaire.v3.7'].includes(source)&&['eb.persona_questionnaire.v3.8','eb.persona_questionnaire.v3.9','eb.persona_questionnaire.v4.0'].includes(version)?'已恢复原草稿；使用频率、成员参与方式等选项已更新，请重新选择。原草稿保留。':'已恢复上次未提交的填写内容。';return true;
 }
}catch{}return false;}
function at(h){const total=Math.round(h*60),day=Math.floor(total/1440),m=total%1440;if(total===1440)return "24:00";return `${day===1?"次日":day>1?`第${day+1}日`:""}${String(Math.floor(m/60)).padStart(2,"0")}:${String(m%60).padStart(2,"0")}`;}
function selectedDevices(){return [...document.getElementsByName("p_B05")].filter(x=>x.checked).map(x=>JSON.parse(x.value));}
function conditional(){$("p_X_CITY")?._citiesSync?.();syncMembers();const selected=selectedDevices();for(const q of schema.profile_questions){if(!q.device&&!q.show_when)continue;const row=document.querySelector(`[data-question-id="${q.id}"]`);row.hidden=(q.device&&!selected.includes(q.device))||(q.show_when&&$('p_'+q.show_when.question_id)?.value!==JSON.stringify(q.show_when.value));for(const input of row.querySelectorAll("input,select,button"))input.disabled=row.hidden||!!currentJob;}EBTime.sync();document.querySelectorAll("#profile-form select").forEach(s=>s._choiceSync?.());}
function freeze(on){for(const x of $("profile-form").querySelectorAll("input,select,textarea,button"))x.disabled=on;if(!on)conditional();availability();}
const scoreInputs=key=>[...document.getElementsByName('feedback_'+key)];
const scoreValue=key=>{const value=scoreInputs(key)[0]?.value;return value===undefined||value===''?null:Number(value);};
function renderScores(legacy=false){
  $("decision-scores").replaceChildren();
  const labels={score:["整体","总体是否合适"],comfort_score:["舒适","室温与生活安排"],energy_score:[legacy?"费用":"用电与费用",legacy?"用电费用":"用电量与费用"],vpp_score:[legacy?"控制体验":"响应安排","调整方式与自主决定"]};
  const anchors=['很不合适','较不合适','一般','较合适','很合适'];
  for(const [key,description] of Object.entries(scoreFields)){
    const row=el('fieldset',undefined,'score-row');row.id=key;
    const legend=el('legend');legend.append(el('strong',labels[key][0]),el('small',labels[key][1]));row.append(legend);
    const choices=el('div',undefined,'score-continuous'),range=el('input'),number=el('input'),meaning=el('p','尚未评分','score-meaning');meaning.id='score-meaning-'+key;number.setAttribute('aria-describedby',meaning.id);
    range.type='range';range.min=1;range.max=5;range.step=0.1;range.value=3;range.setAttribute('aria-label',labels[key][0]+'评分滑块');
    number.type='number';number.min=1;number.max=5;number.step='any';number.inputMode='decimal';number.name='feedback_'+key;number.placeholder='未评分';number.setAttribute('aria-label',labels[key][0]+'评分，可填小数');
    const sync=()=>{const n=Number(number.value);meaning.textContent=number.value===''?'尚未评分':!number.validity.valid?'请填写 1—5 之间的分数':Number.isInteger(n)?`${n} 分 · ${anchors[n-1]}`:`${number.value} 分 · ${anchors[Math.floor(n)-1]}与${anchors[Math.ceil(n)-1]}之间`;choices.classList.toggle('unanswered',number.value==='');if(number.value!==''&&number.validity.valid)range.value=number.value;range.setAttribute('aria-valuetext',number.value===''?'尚未评分':number.value+' 分');};
    number.oninput=sync;number._scoreSync=sync;range.oninput=()=>{number.value=range.value;sync();};
    choices.append(range,number);row.append(choices,meaning);$("decision-scores").append(row);sync();

  }
}
function initialPlan(job){EBTime.initial($("initial-plan"),job.original_plan);}
function showPair(job){
 renderScores(!feedbackCompatible(job));
 const d=job.result.display,view=d.participant_view||d;
 EBView.render($("plan-visual"),view);
 $("outcome-cards").replaceChildren();EBView.outcomes($("outcome-cards"),view);
 $("comparison-title").textContent=view.title||"调整前后，用电安排有什么变化？";
 $("decision-question").textContent=view.question||"您同意采用调整后的安排吗？";
 $("result-panel").hidden=false;
 $("unchanged-notice").hidden=view.has_changes!==false;
 // Historical records retain their original evidence; new v2 views contain
 // only the timeline and outcome table that participants actually judge.
 const legacy=$("legacy-evidence");legacy.replaceChildren();legacy.hidden=view.render_contract_version==='eb.participant_view.v2';
 if(!legacy.hidden){
   for(const key of ['assumptions','selection_reason','execution_notice'])if(view[key])legacy.append(el('p',view[key],'hint'));
   for(const step of view.timeline||[])legacy.append(el('p',`${step.time} · ${step.trigger} · ${step.observed_temperature} ${step.explanation||''}`,'hint'));
   EBView.temperature(legacy,view);
 }
 const required=job.result.feedback_contract?.required_scores||[];for(const key of Object.keys(scoreFields))for(const input of scoreInputs(key))input.required=required.includes(key);$("decision-reason").required=!!job.result.feedback_contract?.required_comment;$("score-hint").textContent="1 很不合适 · 5 很合适，可填小数"+(required.length?"":"（旧记录可留空）");
 $("decision-form").hidden=false;const saved=job.decision_saved;for(const x of $("decision-form").querySelectorAll("input,select,textarea,button"))x.disabled=saved||pendingDecisions.has(job.id)||!feedbackCompatible(job);if(saved){for(const x of document.getElementsByName("decision"))x.checked=x.value===job.decision.choice;$("decision-reason").value=job.decision.comment??job.decision.reason??"";for(const key of Object.keys(scoreFields)){const value=job.decision[key]??job.decision[({score:"overall_score",energy_score:"price_score",vpp_score:"control_score"})[key]];for(const input of scoreInputs(key)){input.value=value??'';input._scoreSync?.();}}}$("decision-status").textContent=saved?"选择、四项评分和原因已保存。未控制真实电器。":"";restoreDecisionDraft(job);
}
function syncHistoryVisibility(){const panel=document.querySelector('.history-panel');if(panel)panel.hidden=!(savedReceipt||panel.dataset.hasRecords==='true');}
function renderHistory(jobs){const records=jobs.filter(j=>j.flow==="paired_ep_v1"),panel=document.querySelector('.history-panel');$("history").replaceChildren();if(panel)panel.dataset.hasRecords=String(!!records.length);syncHistoryVisibility();const names={queued:"排队中",running:"计算中",complete:"等待评价",failed:"计算失败",timeout:"超时",cancelled:"已取消",interrupted:"已中断",expired:"排队已结束"};for(const j of records.slice().reverse()){const b=el("button",`${new Date(j.created_at*1000).toLocaleString()} · ${j.decision_saved?"评价已保存":names[j.status]}`,"secondary");b.type="button";b.disabled=!!pendingSubmit;b.onclick=async()=>{if(!pendingSubmit){const loaded=await loadJob(j.id);if(loaded)$(currentJob?.status==='complete'?'result-panel':'job-panel').scrollIntoView({block:'start'});}};$("history").append(b);}}
const retryableJobStates=new Set(['expired','failed','timeout','cancelled','interrupted']);
function secondsText(value){const total=Math.max(0,Math.floor(value)),hours=Math.floor(total/3600),minutes=Math.floor(total%3600/60),seconds=total%60;return hours?`${hours}小时${minutes}分`:minutes?`${minutes}分${seconds}秒`:`${seconds}秒`;}
function finiteSeconds(value){return typeof value==='number'&&Number.isFinite(value)&&value>=0;}
function jobPollDelay(job){return Math.max(1000,Math.min(15000,Number(job?.poll_after_ms)||2000))+Math.random()*250;}
function renderRetryControl(job){
 const retry=$('retry-generation');if(!retry)return;
 retry.hidden=!job||!retryableJobStates.has(job.status);
 retry.textContent=job?.household_submission_id?'重新尝试生成':'核对资料后重试';
 retry.disabled=pendingSubmit||!!job?.household_submission_id&&schema?.planning_enabled===false;
}
function renderJobState(job){
 const now=Date.now()/1000,created=finiteSeconds(job.created_at)?job.created_at:now;
 const stopped=terminal.has(job.status),ended=finiteSeconds(job.finished_at)?job.finished_at:now;
 const start=finiteSeconds(job.started_at)?job.started_at:null;
 const queueSeconds=finiteSeconds(job.queue_seconds)?job.queue_seconds:Math.max(0,(start??(stopped?ended:now))-created);
 const headings={queued:'家庭资料已保存，正在排队',running:'正在计算两份方案',expired:'本次排队已结束',failed:'本次生成未完成',timeout:'本次计算已超时',cancelled:'本次生成已取消',interrupted:'本次计算已中断'};
 $('job-heading').textContent=headings[job.status]||'两份方案';
 const stages={baseline:'正在模拟您家的日常用电安排。',proposal:'正在生成调整安排，并模拟调整后的用电情况。',planning:'正在根据您家的资料规划调整安排，随后核算模拟结果。',queued:'计算位置暂时已满，正在等待空闲位置。'};
 $('job-status').textContent=stopped?job.message||'本次生成已结束。':stages[job.progress?.stage]||job.progress?.message||job.message||'正在查询任务状态。';
 const timing=$('job-timing');timing.replaceChildren();
 if(job.status==='queued'){
  timing.append(el('span',`已排队 ${secondsText(queueSeconds)}`));
  const estimate=job.estimated_wait_seconds;
  const basis=job.estimate_basis==='configured_cold_start'?'暂按初始估算':job.estimate_basis==='recent_runs'?'根据近期任务估算':'估算值会随队列变化';
  const wait=finiteSeconds(estimate)?estimate===0?'预计即将开始计算':`预计还需等待约 ${secondsText(Math.ceil(estimate))} 后开始计算`:'暂时无法估算何时开始计算';
  timing.append(el('span',finiteSeconds(estimate)?`${wait}（${basis}）`:wait));
 }else if(start!==null){timing.append(el('span',`先前排队 ${secondsText(queueSeconds)}`),el('span',`计算用时 ${secondsText(Math.max(0,(stopped?ended:now)-start))}`));}
 else{timing.append(el('span',`排队用时 ${secondsText(queueSeconds)} · 尚未开始计算`));}
 const policy=$('queue-policy');policy.hidden=job.status!=='queued'||!finiteSeconds(job.queue_wait_limit_seconds)||job.queue_wait_limit_seconds===0;
 policy.textContent=policy.hidden?'':`本次排队等待上限 ${secondsText(job.queue_wait_limit_seconds)}；超时仅结束排队，已保存的家庭资料仍会保留。`;
 $('cancel').hidden=stopped;renderRetryControl(job);
 $('job-panel').classList.toggle('is-generating',!stopped);
 $('waiting-guidance').hidden=false;
 $('connection-status').hidden=true;
 $('waiting-guidance').textContent=stopped?'家庭资料仍然保留，无需重新填写。可以点击下方按钮重试；重试成功后再评价。':'家庭资料已保存，无需再次提交。完成后会自动进入方案对比和评分；也可稍后用同一浏览器回来查看。';
}
async function loadJob(id,acceptedJob=null){
 clearTimeout(timer);const token=++generation;
 if(loadingId!==id){loadingId=id;loadFailures=0;}
 try{const j=acceptedJob||await api("/api/jobs/"+id);if(token!==generation||j.flow!=="paired_ep_v1")return false;
 loadFailures=0;$("error").hidden=true;
 const enterResult=j.status==="complete"&&$("result-panel").hidden;
 if(currentJob?.id!==id)$("decision-form").reset();
 currentJob=j;writeBrowser(draftStorage,"eb:active-view",{mode:"job",id:j.id});$("profile-details").hidden=true;$('resume-panel').hidden=true;
 for(const [i,step] of [...document.querySelectorAll(".journey li")].entries())step.classList.toggle("active",i===(j.status==="complete"?2:1));
 renderQuestions(j.questionnaire_snapshot);restore(j.profile);conditional();freeze(true);showWizard(0,{save:false});
 $("job-panel").hidden=j.status==="complete";renderJobState(j);
 initialPlan(j);$("cancel").hidden=terminal.has(j.status);$("result-panel").hidden=true;$("decision-form").hidden=true;
 if(j.status==="complete")showPair(j);
 if(acceptedJob||enterResult){const panel=$(j.status==="complete"?"result-panel":"job-panel");panel.scrollIntoView({block:"start"});panel.querySelector("h2").focus({preventScroll:true});}
 if(!terminal.has(j.status))timer=setTimeout(()=>pollJob(id,token),jobPollDelay(currentJob));
 else{try{const state=await api("/api/session");if(token===generation){schema.planning_enabled=state.planning_enabled;availability();renderHistory(state.jobs);}}catch{/* A history refresh must not erase the loaded result or draft. */}}
 return true;
 }catch(e){if(token!==generation)return false;
 if([401,403,404,410].includes(e.status)){error('无法读取这条记录，请刷新页面查看“我的记录”。'+e.message);$('connection-status').textContent='记录当前不可访问，已停止自动重试。';$('connection-status').hidden=false;return false;}
 loadFailures++;error("暂时无法读取记录，正在自动重试。"+(e.name==='AbortError'?"请求超时。":e.message));
 timer=setTimeout(()=>{if(token===generation)loadJob(id);},Math.min(8000,1000*2**Math.min(loadFailures,3)));
 return false;}
}
async function pollJob(id,token){
 if(token!==generation||currentJob?.id!==id)return;
 try{const state=await api(`/api/jobs/${id}/status`);if(token!==generation)return;
  Object.assign(currentJob,state);renderJobState(currentJob);
  if(terminal.has(state.status)){await loadJob(id);return;}
 }catch(e){if(token!==generation)return;$('connection-status').hidden=false;
  if([401,403,404,410].includes(e.status)){$('connection-status').textContent='记录当前不可访问，已停止查询。请刷新页面查看“我的记录”。';$('job-panel').classList.remove('is-generating');$('job-status').textContent='暂时无法确认计算状态。';$('waiting-guidance').textContent='请刷新后查看“我的记录”，无需重新填写或重复生成。';return;}
  $('connection-status').textContent='连接暂时中断，正在自动重新查询；无需再次生成。';}
 if(token===generation)timer=setTimeout(()=>pollJob(id,token),jobPollDelay(currentJob));
}
$("profile-form").addEventListener("change",e=>{if(e.target.id==="p_X_REGION")$("p_X_CITY")?._citiesSync?.(true);if(schema.profile_questions.some(q=>q.type==="multi_choice"&&e.target.name==="p_"+q.id)){const selected=JSON.parse(e.target.value);if(e.target.checked){for(const x of document.getElementsByName(e.target.name))if(x!==e.target&&(selected==="none"||JSON.parse(x.value)==="none"))x.checked=false;}}conditional();saveDraft();});
$("profile-form").addEventListener("input",saveDraft);
function submissionNonce(key,body){const fingerprint=stableJson(body);let pending=pendingRequests.get(key)||readBrowser(draftStorage,key);
 if(!pending||pending.fingerprint!==fingerprint)pending={fingerprint,request_id:typeof crypto.randomUUID==='function'?crypto.randomUUID():Array.from(crypto.getRandomValues(new Uint8Array(16)),x=>x.toString(16).padStart(2,'0')).join('')};
 pendingRequests.set(key,pending);writeBrowser(draftStorage,key,pending);return pending.request_id;
}
function clearPending(key){pendingRequests.delete(key);removeBrowser(draftStorage,key);}
async function saveHousehold(){
 const base=householdBody();if(receiptMatches())return savedReceipt;
 const body={...base,ui_version:UI_VERSION,scenario_understood:$('scenario-understood').checked,research_consent:$('research-consent').checked,research_notice_version:schema.research_notice_version||RESEARCH_NOTICE_VERSION};
 const receipt=await api('/api/households',{...body,request_id:submissionNonce('eb:pending-household',body)});
 saveReceipt(receipt,base);clearPending('eb:pending-household');
 $('draft-status').textContent='家庭资料已保存，您仍可以修改后重新提交。';return savedReceipt;
}
async function requestSavedPlan(receipt,retrySourceId=null){
 const environment=receipt.environment_readiness;
 if(environment?.status==='unavailable')throw new Error('家庭资料已保存。'+environment.issues.join('；'));
 if(environment?.status==='ready')$('draft-status').textContent='家庭资料已保存，正在准备两份用电安排。';
 const body={submission_id:receipt.id,household_record_hash:receipt.household_record_hash,scenario_id:schema.paired_context.id,scenario_understood:$('scenario-understood').checked,questionnaire_version:receipt.questionnaire_version||schema.paired_questionnaire_version,questionnaire_hash:receipt.questionnaire_hash||schema.paired_questionnaire_hash};
 // The local attempt context creates a fresh nonce for an explicit terminal-job retry.
 // Repeated 429/network retries of that same attempt keep the nonce unchanged.
 let identity={...body,known_case_ids:receipt.case_ids||[],...(retrySourceId?{retry_source_job_id:retrySourceId}:{})};
 const pending=pendingRequests.get('eb:pending-plan')||readBrowser(draftStorage,'eb:pending-plan');
 if(pending){try{const previous=JSON.parse(pending.fingerprint),{known_case_ids,retry_source_job_id,...priorBody}=previous;
  if((retry_source_job_id||null)===retrySourceId&&stableJson(priorBody)===stableJson(body))identity=previous;
 }catch{}}
 const j=await EBCaptcha.submit(api,{...body,request_id:submissionNonce('eb:pending-plan',identity)},schema.captcha_enabled&&!schema.is_admin);
 clearPending('eb:pending-plan');
 const draft=readBrowser(draftStorage,draftKey());
 if(draft?.answers&&householdFingerprint({answers:draft.answers,questionnaire_version:schema.paired_questionnaire_version,questionnaire_hash:schema.paired_questionnaire_hash,questionnaire_context_hash:draft.questionnaire_context_hash})===receipt.fingerprint)removeBrowser(draftStorage,draftKey());
 writeBrowser(draftStorage,'eb:active-view',{mode:'job',id:j.id});
 await loadJob(j.id,j);
}
async function planSavedHousehold(){
 if(!receiptMatches())throw new Error('回答已有改动，请先保存当前家庭资料。');
 if(schema?.planning_enabled===false)return;
 if(selectedDevices().includes('none'))throw new Error('家庭资料已保存。本次没有可纳入 EB 调整的设备，因此不生成两份方案。');
 if(savedReceipt.environment_readiness?.status==='unavailable'){
  showWizard(4,{scroll:true,push:true});
  throw new Error('家庭资料已经保存。若要生成两份方案，请补齐住房信息：'+savedReceipt.environment_readiness.issues.join('；'));
 }
 return requestSavedPlan(savedReceipt);
}
async function retryStoppedJob(){
 const job=currentJob;if(pendingSubmit||!job||!retryableJobStates.has(job.status))return;
 if(!job.household_submission_id){$('new-case').click();return;}
 if(schema?.planning_enabled===false){error('方案生成暂未开放，已保存的家庭资料仍然保留。');return;}
 pendingSubmit=true;availability();$('error').hidden=true;
 try{
  const record=await api('/api/households/'+job.household_submission_id);
  saveReceipt(record,{answers:record.raw_answers,questionnaire_version:record.questionnaire_version,questionnaire_hash:record.questionnaire_hash,questionnaire_context_hash:record.questionnaire_context?.context_hash});
  await requestSavedPlan(savedReceipt,job.id);
 }catch(ex){error('已保存的家庭资料仍然保留。'+(ex.name==='AbortError'?'连接超时，请稍后手动重试。':ex.message));}
 finally{pendingSubmit=false;availability();}
}
$('retry-generation').onclick=retryStoppedJob;
async function submitHousehold(generateOnly=false){
 if(pendingSubmit||currentJob)return;
 if(!validateWholeQuestionnaire())return;
 saveDraft();$('error').hidden=true;pendingSubmit=true;freeze(true);
 try{if(!generateOnly)await saveHousehold();await planSavedHousehold();}
 catch(ex){error((savedReceipt?'已保存的家庭资料仍然保留。':'')+(ex.name==='AbortError'?'连接超时，请重试；重复提交不会重复保存同一请求。':ex.message));}
 finally{pendingSubmit=false;freeze(!!currentJob);availability();}
}
$('profile-form').onsubmit=async e=>{e.preventDefault();if(pendingSubmit)return;if(wizardStep!==wizardSteps().at(-1)){nextWizard();return;}await submitHousehold();};
$('plan-saved').onclick=()=>submitHousehold(true);
$("decision-form").addEventListener('input',saveDecisionDraft);
$("decision-form").addEventListener('change',saveDecisionDraft);
$('decision-form').onsubmit=async e=>{
 e.preventDefault();const job=currentJob,selected=document.querySelector('input[name="decision"]:checked');
 if(!job||!selected||pendingDecisions.has(job.id))return;
 const id=job.id,draft=decisionDraftKey(job),r=job.result;
 const payload={choice:selected.value,comment:$('decision-reason').value,...Object.fromEntries(Object.keys(scoreFields).map(k=>[k,scoreValue(k)])),display_hash:r.display_hash,original_plan_hash:r.original_plan_hash,proposal_plan_hash:r.proposal_plan_hash};
 pendingDecisions.add(id);$('error').hidden=true;
 for(const input of $('decision-form').querySelectorAll('input,textarea,button'))input.disabled=true;
 try{await api(`/api/jobs/${id}/decision`,payload);job.decision_saved=true;removeBrowser(draftStorage,draft);
  if(currentJob?.id===id){$('decision-status').textContent='反馈已保存，正在更新显示。';await loadJob(id);}
 }catch(ex){if(currentJob?.id===id){error(ex.message);for(const input of $('decision-form').querySelectorAll('input,textarea,button'))input.disabled=false;}}
 finally{pendingDecisions.delete(id);}
};
$("cancel").onclick=async()=>{try{if(currentJob){await api(`/api/jobs/${currentJob.id}/cancel`,{});await loadJob(currentJob.id);}}catch(e){error(e.message);}};
$('new-case').onclick=()=>{
 if(pendingSubmit||currentJob&&!terminal.has(currentJob.status)){error('请先完成或取消当前计算。');return;}
 clearTimeout(timer);generation++;const previous=currentJob?.profile,sourceVersion=currentJob?.questionnaire_version,previousContext=currentJob?.scenario?.questionnaire_context?.context_hash;currentJob=null;
 for(const [i,step] of [...document.querySelectorAll('.journey li')].entries())step.classList.toggle('active',i===0);
 renderQuestions(schema.paired_questions);
 $('profile-details').hidden=false;$('research-consent').checked=false;$('scenario-understood').checked=false;
 const resumed=restoreDraft();
 if(!resumed&&previous)restore(answerProfile(migrateAnswers(Object.fromEntries(Object.entries(previous).map(([k,c])=>[k,c.response_status==='answered'?c.value:null])),sourceVersion,previousContext)));
 freeze(false);showWizard(wizardStep,{save:false});saveDraft();
 for(const id of ['job-panel','result-panel','decision-form','error'])$(id).hidden=true;
 $('decision-form').reset();$('profile-form').scrollIntoView({block:'start'});
};
$('clear-device-data').onclick=async()=>{
 if(!confirm('将清除此浏览器保存的问卷草稿、任务入口和评价草稿。已提交的回答不会被删除。确定继续吗？'))return;
 try{
  await api('/api/session/reset',{});
  for(const store of [draftStorage,sessionStorage])for(const key of Object.keys(store))if(key.startsWith('eb:'))removeBrowser(store,key);
  location.replace('/');
 }catch(ex){error(ex.name==='AbortError'?'连接超时，请稍后再试。':ex.message);}
};
let wizardStep=0;
const wizardLabels=['家庭概况','家庭成员','电器安排','用电偏好','住房情况','补充与提交'];
const wizardHashes=['household','members','appliances','preferences','housing','research'];
function wizardSteps(){const base=schema?.profile_questions?.some(q=>q.type==='member_list')?[0,1,2,3]:[0,2,3];return schema?.profile_questions?.some(q=>q.research_only)?[...base,4,5]:base;}
function showWizard(step,{scroll=false,push=false,save=true}={}){
 const steps=wizardSteps();document.querySelector('.scenario-section').dataset.formPage=steps.at(-1);wizardStep=steps.includes(step)?step:steps[0];
 for(const section of document.querySelectorAll('[data-form-page]'))section.hidden=Number(section.dataset.formPage)!==wizardStep;
 for(const b of document.querySelectorAll('[data-wizard-step]')){const n=Number(b.dataset.wizardStep);b.hidden=!steps.includes(n);b.parentElement.hidden=b.hidden;b.parentElement.parentElement.style.setProperty('--step-count',steps.length);b.classList.toggle('active',n===wizardStep);b.setAttribute('aria-current',n===wizardStep?'step':'false');b.disabled=!!pendingSubmit;}
 const index=steps.indexOf(wizardStep);$('wizard-progress').textContent=`第 ${index+1} / ${steps.length} 步 · ${wizardLabels[wizardStep]}`;
 $('wizard-prev').hidden=index===0;$('wizard-next').hidden=index===steps.length-1;
 $('wizard-prev').disabled=$('wizard-next').disabled=!!pendingSubmit;
 $('wizard-next').textContent='下一步：'+(wizardLabels[steps[index+1]]||'');
 $('wizard-prev').textContent='上一步';syncMemberNavigation();
 $('wizard-current-note').textContent=currentJob?'已提交的回答可分步查看；修改请新建案例。':'切换页面不会丢失已填内容，最后一步再统一提交。';
 document.querySelector('.survey-hero').hidden=!!currentJob||wizardStep!==0;
 if(push)window.history.pushState(null,'','#'+wizardHashes[wizardStep]);
 if(save&&!currentJob)saveDraft();
 if(scroll){$('wizard-heading').focus({preventScroll:true});$('wizard-nav').scrollIntoView({block:'start'});}
}
function validateWizardStep(step){
 if(currentJob)return true;
 if(step===2&&!selectedDevices().length){showWizard(step,{scroll:true});error('请先选择本次纳入的电器；没有对应设备可选“以上都没有”。');document.querySelector('[name=p_B05]')?.focus();return false;}
 const invalid=[...document.querySelectorAll(`[data-form-page="${step}"] input,[data-form-page="${step}"] select`)].find(input=>input.willValidate&&!input.validity.valid);
 if(invalid){showWizard(step,{scroll:true});const card=invalid.closest('.member-card');if(card)showMember([...card.parentElement.children].indexOf(card),{scroll:true});error('这一部分还有未完成的必填项，请先补充。');invalid.reportValidity();return false;}
 return true;
}
function nextWizard(){
 if(!schema||pendingSubmit)return;
 if(wizardStep===1){const root=memberRoot(),index=Number(root?.dataset.activeMember)||0;
  const invalid=[...root.querySelectorAll('.member-card:not([hidden]) input')].find(x=>x.willValidate&&!x.validity.valid);
  if(invalid){error('请填写这位成员的生活节奏，其余问题可以留空。');invalid.reportValidity();return;}
  if(index<Number(root.dataset.count)-1){$('error').hidden=true;showMember(index+1,{scroll:true});return;}
 }
 if(!validateWizardStep(wizardStep))return;$('error').hidden=true;const steps=wizardSteps();showWizard(steps[Math.min(steps.indexOf(wizardStep)+1,steps.length-1)],{scroll:true,push:true});
}
function validateWholeQuestionnaire(){for(const step of wizardSteps())if(!validateWizardStep(step))return false;return true;}
$('wizard-next').onclick=nextWizard;
$('wizard-prev').onclick=()=>{if(pendingSubmit)return;$('error').hidden=true;const index=Number(memberRoot()?.dataset.activeMember)||0;if(wizardStep===1&&index>0){showMember(index-1,{scroll:true});return;}const steps=wizardSteps();showWizard(steps[Math.max(0,steps.indexOf(wizardStep)-1)],{scroll:true,push:true});};
for(const b of document.querySelectorAll('[data-wizard-step]'))b.onclick=()=>{if(!schema||pendingSubmit)return;const target=Number(b.dataset.wizardStep);if(target>wizardStep)for(const step of wizardSteps().filter(s=>s>=wizardStep&&s<target))if(!validateWizardStep(step))return;$('error').hidden=true;showWizard(target,{scroll:true,push:true});};
window.addEventListener('popstate',()=>{if(!schema||pendingSubmit||currentJob)return;const step=wizardHashes.indexOf(location.hash.slice(1));showWizard(step<0?0:step,{scroll:true});});

async function recoverReceipt(state){
 const local=readBrowser(draftStorage,'eb:household-receipt'),summaries=state.households||[];
 // A local receipt is only reused when the current session owns it.
 const selected=summaries.find(r=>r.id===local?.id)||summaries.at(-1);
 savedReceipt=null;savedHouseholdRecord=null;
 if(selected){try{const record=await api('/api/households/'+selected.id);savedHouseholdRecord=record;saveReceipt({...selected,...record},{answers:record.raw_answers,questionnaire_version:record.questionnaire_version,questionnaire_hash:record.questionnaire_hash,questionnaire_context_hash:record.questionnaire_context?.context_hash});}catch{removeBrowser(draftStorage,'eb:household-receipt');}}
}
function restoreSavedHousehold(){if(!savedHouseholdRecord)return false;restore(answerProfile(migrateAnswers(savedHouseholdRecord.raw_answers,savedHouseholdRecord.questionnaire_version,savedHouseholdRecord.questionnaire_context?.context_hash)));wizardStep=wizardSteps().at(-1);$('draft-status').textContent='已恢复家庭资料；请核对上方情境日期，补填已清空的季节习惯后重新保存。';return true;}
async function init(){
 $('generate').disabled=true;renderScores();
 try{
  schema=await api('/api/session');renderQuestions(schema.paired_questions);
  $('context-date').textContent='本次情境：'+schema.questionnaire_context.label;
  $('context-instruction').textContent=`请设想您家在 ${Number(schema.questionnaire_context.date.slice(5,7))} 月的一天，按那时的日常习惯填写。`;
  const human=schema.collection_mode==='human_pilot';
  $('admin-link').hidden=!schema.is_admin;
  $('collection-badge').textContent=schema.is_admin?'管理员测试':human?'家庭用电研究':'体验版';
  $('collection-footer').textContent='方案为模拟结果，不会改变家中电器的设置。';
  $('research-intro').innerHTML='<strong>填写小提示</strong><p>请由一位家人代表全家填写。不需要姓名或详细地址；拿不准的选填题可以跳过。</p>';
  $('research-notice').textContent=human?'您的回答将用于研究家庭用电选择，并帮助训练理解家庭偏好的人工智能模型。是否参与由您决定。':'本次为体验填写，回答会保存，用于改进问卷。是否参与由您决定。';
  $('research-consent-label').textContent=human?'我已阅读说明，自愿将本次回答用于上述研究。':'我自愿参与本次体验并提交回答。';
  $('scenario-facts').replaceChildren(...['提交后，我们会根据您填写的习惯生成两份用电安排。','看过时间、用电量和室温的对比后，请告诉我们是否愿意采用调整，并给出评分和原因。'].map(f=>el('li',f)));
  conditional();renderHistory(schema.jobs);
  await recoverReceipt(schema);
  const jobs=schema.jobs.filter(j=>j.flow==='paired_ep_v1'),active=readBrowser(draftStorage,'eb:active-view'),pendingPlan=readBrowser(draftStorage,'eb:pending-plan');
  let recoverJob;
  if(pendingPlan){try{const request=JSON.parse(pendingPlan.fingerprint),record=(schema.households||[]).find(r=>r.id===request.submission_id);const latest=record?.case_ids?.at(-1);if(latest&&latest!==request.retry_source_job_id&&!(request.known_case_ids||[]).includes(latest))recoverJob=latest;}catch{}}
  if(recoverJob){clearPending('eb:pending-plan');await loadJob(recoverJob);}
  else if(active?.mode==='draft'&&restoreDraft()){conditional();showWizard(wizardStep,{save:false});}
  else{
   const previous=jobs.find(j=>j.id===active?.id)||jobs.at(-1);
   const running=jobs.find(j=>j.id===active?.id&&!terminal.has(j.status))||jobs.find(j=>!terminal.has(j.status));
   if(running){await loadJob(running.id);}
   else{
    if(!restoreDraft())restoreSavedHousehold();conditional();
    const hashStep=wizardHashes.indexOf(location.hash.slice(1));
    showWizard(previous?0:hashStep>=0?hashStep:wizardStep,{save:false});
    if(previous){
     $('resume-panel').hidden=false;
     $('resume-message').textContent=previous.decision_saved?'您上次的评价已保存。可以查看记录，也可以继续填写家庭资料。':previous.status==='complete'?'您上次的用电安排已生成，还没有提交评价。可以继续查看并评价。':'您有一份生成记录，可以查看进度或重新尝试。';
     $('resume-result').textContent=previous.decision_saved?'查看已保存的评价':previous.status==='complete'?'查看上次结果并评价':'查看上次记录';
     $('resume-result').onclick=()=>{if(!pendingSubmit)loadJob(previous.id);};
    }
   }
  }
  availability();$('error').hidden=true;
 }catch(e){error('暂时无法加载问卷，正在自动重试。'+e.message);timer=setTimeout(init,3000);}
}init();
