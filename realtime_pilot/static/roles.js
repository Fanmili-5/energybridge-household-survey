const $ = id => document.getElementById(id);
const requestedPreviewRole=new URLSearchParams(location.search).get('role');
const state = {session:null,profile:null,day:null,pendingKey:null,
  previewRole:/^cityrole-(0[0-2]\d\d|0300)$/.test(requestedPreviewRole||'')?requestedPreviewRole:'cityrole-0001'};
const scoreLabels = {score:'整体合适程度',comfort_score:'舒适程度',energy_score:'费用与用电',vpp_score:'错峰与可控性'};
const deviceLabels = {ac:'空调',washer:'洗衣机',dryer:'烘干机',dishwasher:'洗碗机',electric_water_heater:'电热水器',home_ev:'家用电动汽车'};
const roleLabels = {reference_adult:'主要说明人',spouse:'伴侣',child:'子女',parent_of_reference_adult:'长辈',spouse_of_child:'子女伴侣',sibling:'兄弟姐妹'};
const routineLabels={out_regular:'通常定时外出',home_regular:'通常在家',mixed:'在家与外出交替',irregular:'作息不固定'};
const comfortLabels={temp_tolerant:'温度变化较能适应',normal_comfort:'接受小幅变化',temp_sensitive:'更在意室温'};
const noncontrastReasons={common_initialization_day:'共同起点日，两种安排相同',no_legal_today_plan_change:'当天没有合法的计划调整，两种安排没有当日可比较差异'};
const housingLabels={apartment:'公寓住宅',house:'独立住宅',independent_dwelling:'独立居住住宅',shared_dwelling:'合住住宅',shared_dwelling_private_rooms_with_allocated_common_area:'合住：私有房间与分摊共用面积'};
const controlLabels={household_selected_devices:'仅本户约定设备',household_private_devices:'仅本户私有设备',assigned_private_rooms_ac_only:'仅本户指定私有房间空调'};
function show(id,visible){$(id).hidden=!visible;}
function text(id,value){$(id).textContent=value==null||value===''?'—':String(value);}
function node(tag,content,cls){const n=document.createElement(tag);if(content!=null)n.textContent=String(content);if(cls)n.className=cls;return n;}
function kwh(value){if(value==null)return '未提供';const v=Number(value);if(!Number.isFinite(v))return '未提供';if(v===0)return '0';if(v>0&&v<.01)return '少于0.01';return v.toFixed(2);}
async function api(path,options={}){const response=await fetch(path,{credentials:'same-origin',...options});let body=await response.json();if(!response.ok)throw Error(body.error||`请求失败 ${response.status}`);return body;}
async function post(path,payload){return api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});}
function fail(error){text('notice',error.message||String(error));}
function profileView(data){state.profile=data;const h=data.household;
  const qById=Object.fromEntries(data.question_facts.map(q=>[q.question_id,q]));const q=id=>qById[id]?.display||'未知';
  text('role-code',h.role_id);text('city',`${h.province} · ${h.city}`);text('weather-source','CSWD 典型年模拟夏季');text('hero-day-weather',data.first_day_weather||'逐日天气待重新核验');
  const shared=h.housing_form==='shared_dwelling_private_rooms_with_allocated_common_area';$('unit-diagram').toggleAttribute('hidden',shared);$('shared-diagram').toggleAttribute('hidden',!shared);
  text('home-type',housingLabels[h.housing_form]||housingLabels[h.building_type]||h.housing_form);text('whole-area',h.whole_dwelling_building_area_m2?`${Number(h.whole_dwelling_building_area_m2).toFixed(1)} m²`:'未知');
  text('owned-area',h.household_accounted_net_area_m2?`${Number(h.household_accounted_net_area_m2).toFixed(1)} m²`:'未知');
  text('common-area',Number(h.common_allocated_area_m2)>0?`${Number(h.common_allocated_area_m2).toFixed(1)} m²`:'无');
  text('control-scope',controlLabels[h.private_control_scope]||'仅本户约定设备');
  text('income',h.monthly_income_scenario_yuan?`约 ${h.monthly_income_scenario_yuan} 元`:'未知');text('bill',h.monthly_bill_scenario_yuan?`约 ${h.monthly_bill_scenario_yuan} 元`:'未知');
  text('bill-note',`${h.bill_pressure_description||''}。这些是合成情境，不是本户实测。`);
  text('cost-attitude',`节费重视 ${h.cost_importance_1_5}/5`);text('comfort-attitude',`舒适重视 ${h.comfort_importance_1_5}/5`);text('grid-attitude',`错峰重视 ${h.grid_importance_1_5}/5`);
  text('climate-city',h.city);text('climate-station',h.weather_station_key);text('climate-distance',h.weather_station_distance_km?`${Number(h.weather_station_distance_km).toFixed(1)} km`:'未知');text('day-weather',data.first_day_weather||'逐日天气待重新核验');
  text('home-context',`${q('X_BUILDING')}；${q('X_TENURE')}；面积回答 ${q('X_AREA')}，${q('X_AREA_BASIS')}。住房原型 ${h.source_catalog_key} 是仿真代理，不是本户实测。`);
  text('control-condition',`自动控制边界：${q('A_EB_CONTROL')}。希望提前通知：${q('P_NOTICE')}。受保护活动：${q('X_PROTECTED')}。`);
  text('full-role-card',h.actor_card_full);
  const members=$('member-list');members.replaceChildren();for(const m of data.members){const card=node('div',null,'member');card.append(node('b',`${roleLabels[m.relationship_to_reference_adult]||m.relationship_to_reference_adult} · ${m.age_years_design} 岁`),node('small',`${routineLabels[m.routine]||'作息有个体差异'} · ${comfortLabels[m.comfort]||'温感待说明'}`));members.append(card);}
  const devices=$('device-list');devices.replaceChildren();for(const d of data.devices){devices.append(node('span',`${deviceLabels[d.device]||d.device} × ${d.owned_unit_count}`));}
  text('quick-household',`${h.family_size} 人 · 年龄 ${data.members.map(m=>m.age_years_design).join('、')} 岁`);
  text('quick-devices',data.devices.map(d=>`${deviceLabels[d.device]||d.device}×${d.owned_unit_count}`).join('、')||'无纳入模拟的设备');
  text('quick-economy',`月收入情境约${h.monthly_income_scenario_yuan}元 · 上月电费约${h.monthly_bill_scenario_yuan}元`);
  text('quick-attitudes',`节费${h.cost_importance_1_5}/5 · 舒适${h.comfort_importance_1_5}/5 · 错峰${h.grid_importance_1_5}/5`);
  const memberDetail=$('member-details');memberDetail.replaceChildren();for(const m of data.members){const item=node('div',null,'detail-item');const windows=data.member_windows.filter(w=>w.member_id===m.member_id);const when=windows.map(w=>`${w.day_type==='weekday'?'工作日':'周末'} ${w.start_local_time}—${w.end_local_time}`).join('；')||'在家时段未知';item.append(node('b',`${roleLabels[m.relationship_to_reference_adult]||m.relationship_to_reference_adult} · ${m.age_years_design} 岁`),node('span',when),node('small',`作息：${routineLabels[m.routine]||'未知'}；温感：${comfortLabels[m.comfort]||'未知'}。具体成员需求与参与条件见完整角色卡。`));memberDetail.append(item);}
  const deviceDetail=$('device-details');deviceDetail.replaceChildren();for(const d of data.devices){const item=node('div',null,'detail-item');const name=deviceLabels[d.device]||d.device;const timeline=[`通常使用：${q(`H_${d.device}`)}`];if(d.device==='ac'){timeline.push(`制冷设定：${q('H_ac_temp')}`);timeline.push(`舒适范围：${q('P_AC_RANGE')}`);timeline.push(`可接受变化：${q('P_AC_CHANGE')}`);}else if(['washer','dryer','dishwasher'].includes(d.device)){timeline.push(`可从：${q(`E_${d.device}`)}`);timeline.push(`最晚：${q(`D_${d.device}`)}`);timeline.push(`持续：${q(`T_${d.device}`)}`);}else if(d.device==='electric_water_heater'){timeline.push(`最晚用水：${q('D_electric_water_heater')}`);timeline.push(`用水需求：${q('P_HOT_WATER')}`);timeline.push(`预热选择：${q('P_PREHEAT')}`);}else if(d.device==='home_ev'){timeline.push(`最晚完成：${q('D_home_ev')}`);timeline.push(`目标电量：${q('P_EV_TARGET')}`);timeline.push(`保底电量：${q('P_EV_RESERVE')}`);}item.append(node('b',`${name} × ${d.owned_unit_count}`),node('span',timeline.join('；')),node('small',`使用与调整条件：${d.operation_condition||'未知'}`));deviceDetail.append(item);}
  const question=$('question-facts');question.replaceChildren();for(const fact of data.question_facts){const item=node('div',null,'question-fact');item.append(node('small',fact.question_prompt||fact.question_id),node('span',fact.display));question.append(item);}
}
function ratingPanel(side){const box=$(side==='left'?'rating-left':'rating-right');box.replaceChildren(node('h4',side==='left'?'左侧方案评分':'右侧方案评分'));
  for(const [field,label] of Object.entries(scoreLabels)){const row=node('label',null,'rating-row');row.append(node('span',label));const select=document.createElement('select');select.name=`${side}-${field}`;for(const [v,t] of [['','未评分'],['1','1'],['2','2'],['3','3'],['4','4'],['5','5']]){const o=node('option',t);o.value=v;select.append(o);}row.append(select);box.append(row);}}
function ratings(side){const result={};for(const field of Object.keys(scoreLabels)){const value=document.querySelector(`[name="${side}-${field}"]`).value;result[field]=value===''?null:Number(value);}return result;}
function planView(id,plan){const box=$(id);box.replaceChildren();if(plan.branch_history_summary)box.append(node('p',`此前轨迹：${plan.branch_history_summary}`));
  const list=node('ul');for(const item of plan.device_schedule){list.append(node('li',typeof item==='string'?item:JSON.stringify(item)));}box.append(list);
  for(const [label,value,unit] of [['本户全部房间全天等权平均仿真温度',plan.indoor_temperature_c,'℃'],['受控设备代理电量',plan.controlled_device_kwh,' kWh'],['任务结果',plan.task_completion,'']]){
    const shown=unit===' kWh'?kwh(value):value==null?'未提供':value;box.append(node('p',`${label}：${shown}${value==null?'':unit}`));}
  box.append(node('small','温度按本户全部房间与24小时等权平均，含未受控空调房间；不是受控房间温度、个人即时体验或舒适评分。电量仅为本户受控设备代理量，不等于全户电表。'));
}
function fillPrior(answer){$('feedback-form').reset();if(!answer)return;
  const radio=document.querySelector(`[name="choice"][value="${answer.choice}"]`);if(radio)radio.checked=true;$('reason').value=answer.reason;
  for(const side of ['left','right'])for(const field of Object.keys(scoreLabels)){const value=answer.ratings_by_side?.[side]?.[field];document.querySelector(`[name="${side}-${field}"]`).value=value==null?'':String(value);}
}
async function loadDay(index){try{const day=await api(`/api/roles/day/${index}`);state.day=day;state.pendingKey=null;show('day-panel',true);text('day-number',`第 ${index} 天`);text('day-context',day.context);text('day-status',day.response_status==='submitted'?'已回答':day.response_status==='skipped'?'已跳过':day.response_status==='acknowledged'?'已确认':day.collectable?'待回答':'无需偏好');
  text('day-weather',day.weather.summary||JSON.stringify(day.weather));text('hero-day-weather',day.weather.summary||'模拟天气待核');planView('plan-left',day.plans.left);planView('plan-right',day.plans.right);
  show('noncontrast',!day.collectable);if(!day.collectable)text('noncontrast',`这一天不索取偏好：${noncontrastReasons[day.noncollectable_reason]||'没有有效对照'}`);
  show('day-action-box',day.response_status==='viewed');show('ack-day',!day.collectable&&day.response_status==='viewed');show('skip-day',day.collectable&&day.response_status==='viewed');
  show('feedback-form',day.collectable);fillPrior(day.prior_answer);show('withdraw-day',Boolean(day.prior_answer));
  for(const b of $('day-nav').querySelectorAll('button'))b.classList.toggle('active',Number(b.dataset.day)===index);
}catch(error){fail(error);}}
async function dayNav(days,selected=1){const nav=$('day-nav');nav.replaceChildren();for(const d of days){const b=node('button',`第 ${d.day_index} 天`);b.type='button';b.dataset.day=d.day_index;b.disabled=!d.unlocked;if(['submitted','answered','acknowledged','skipped'].includes(d.status))b.classList.add('done');b.addEventListener('click',()=>loadDay(d.day_index));nav.append(b);}show('day-nav',true);await loadDay(days[selected-1]?.unlocked?selected:days.find(d=>d.unlocked&&!['answered','acknowledged','skipped'].includes(d.status))?.day_index||1);}
function frozenWithdrawals(info){const box=$('frozen-day-list');box.replaceChildren();for(const item of info.withdrawable_events||[]){const button=node('button',`撤回第 ${item.day_index} 天回答`,'secondary');button.type='button';button.addEventListener('click',async()=>{if(!confirm(`撤回第 ${item.day_index} 天的当前回答？`))return;try{const result=await post('/api/roles/withdraw-day',{target_event_id:item.event_id,withdrawal_key:crypto.randomUUID()});await refresh();text('notice',`第 ${item.day_index} 天已撤回；回执 ${result.receipt.slice(0,12)}。`);}catch(error){fail(error);}});box.append(button);}show('frozen-withdrawals',Boolean(info.actor_id&&(!info.ready||!info.current_enrollment)&&(info.withdrawable_events||[]).length));}
async function refresh(selectedDay=1){try{const info=await api('/api/roles/session');state.session=info;const engineering=info.collection_mode==='engineering_preview';text('study-state',info.ready?(engineering?'真实模拟 · 工程试填':'案例已接入'):'仅固定角色预览');$('notice').textContent=info.reason||'';
  await profileView(await api(`/api/roles/preview/${info.role_id||(engineering?state.previewRole:info.preview_role_id)}`));
  show('engineering-picker',Boolean(engineering&&info.ready&&!info.actor_id));$('role-choice').value=state.previewRole;
  text('consent-heading',engineering?'工程试填前请阅读':'参与前请阅读');text('consent-label',engineering?'我已阅读工程试填说明':'我已阅读并同意本批研究说明');text('consent-button',engineering?'开始工程试填并固定角色':'开始并固定角色');text('feedback-submit',engineering?'保存工程试填回答':'保存这一天的回答');text('withdraw-all',engineering?'撤回本批工程试填及全部回答':'撤回本批同意及全部回答');
  if(engineering&&info.ready)text('collection-intro','工程试填：以下是已核验的真实离线模拟案例。试填仅作界面和流程检查，不是正式偏好样本；回答不会改变十天轨迹。');
  frozenWithdrawals(info);show('withdraw-all',Boolean(info.actor_id&&info.consent_active));
  if(!info.ready||info.actor_id&&!info.current_enrollment){show('consent-box',false);show('day-nav',false);show('day-panel',false);text('day-weather','逐日天气待重新核验');text('hero-day-weather','逐日天气待重新核验');return;}
  if(!info.consent_active){show('consent-box',!info.actor_id);text('consent-text',info.consent_text||'该会话已撤回，请联系研究人员。');show('day-nav',false);show('day-panel',false);return;}
  show('consent-box',false);text('collection-intro',engineering?'工程试填：以下是已核验的真实离线模拟案例。试填仅作界面和流程检查，不是正式偏好样本；回答不会改变十天轨迹。请按日期顺序查看、回答或明确跳过。':'以下是两条预先生成的十天安排；当前判断不会改变后续轨迹。请按日期顺序查看、回答或明确跳过。');await dayNav(info.days,selectedDay);
}catch(error){fail(error);}}
$('ack-day').addEventListener('click',async()=>{if(!state.day)return;try{const day=state.day;const result=await post('/api/roles/day-action',{day_index:day.day_index,action:'acknowledge',idempotency_key:crypto.randomUUID()});await refresh(result.next_day_index||day.day_index);text('notice','这一天的背景已确认，可以继续查看下一天。');}catch(error){fail(error);}});
$('skip-day').addEventListener('click',async()=>{if(!state.day)return;const reason=prompt('请简要说明跳过这一天评价的原因：');if(reason===null)return;try{const day=state.day;const result=await post('/api/roles/day-action',{day_index:day.day_index,action:'skip',skip_reason:reason,idempotency_key:crypto.randomUUID()});await refresh(result.next_day_index||day.day_index);text('notice','这一天已明确跳过，可以继续下一天。');}catch(error){fail(error);}});
$('consent-button').addEventListener('click',async()=>{if(!$('consent-check').checked){text('notice','请先阅读并勾选同意。');return;}try{const payload={accept:true,consent_version:state.session.consent_version};if(state.session.collection_mode==='engineering_preview')payload.requested_role_id=state.previewRole;await post('/api/roles/consent',payload);await refresh();}catch(error){fail(error);}});
$('feedback-form').addEventListener('submit',async event=>{event.preventDefault();if(!state.day)return;const chosen=document.querySelector('[name="choice"]:checked');if(!chosen){text('notice','请选择一项判断。');return;}
  const day=state.day;state.pendingKey ||= crypto.randomUUID();try{const result=await post('/api/roles/feedback',{schema_version:'eb.role_ten_day_blind_feedback.v1',casebank_sha256:day.casebank_sha256,profile_sha256:day.profile_sha256,actor_pseudonym:state.session.actor_id,role_id:day.role_id,case_id:day.case_id,day_index:day.day_index,display_order_hash:day.display_order_hash,choice:chosen.value,reason:$('reason').value,ratings_by_side:{left:ratings('left'),right:ratings('right')},idempotency_key:state.pendingKey});state.pendingKey=null;await refresh(day.day_index);text('notice',result.future_exposure?'回答已保存；此前查看过后续日，本次改写不计入严格时序分析。':'这一天的回答已保存。');}catch(error){fail(error);}});
$('withdraw-day').addEventListener('click',async()=>{if(!state.day?.prior_event_id||!confirm('撤回这一天的当前回答？'))return;try{const day=state.day;await post('/api/roles/withdraw-day',{target_event_id:day.prior_event_id,withdrawal_key:crypto.randomUUID()});await refresh(day.day_index);text('notice','这一天的回答已撤回。');}catch(error){fail(error);}});
$('withdraw-all').addEventListener('click',async()=>{if(!confirm('撤回本批同意及全部回答？此操作后不能继续本批填写。'))return;try{await post('/api/roles/withdraw-actor',{confirm:true});await refresh();text('notice','本批同意与回答已撤回。');}catch(error){fail(error);}});
for(let i=1;i<=300;i++){const role=`cityrole-${String(i).padStart(4,'0')}`;const option=node('option',`合成家庭 ${String(i).padStart(4,'0')}`);option.value=role;$('role-choice').append(option);}
$('role-choice').addEventListener('change',async()=>{state.previewRole=$('role-choice').value;try{await profileView(await api(`/api/roles/preview/${state.previewRole}`));}catch(error){fail(error);}});
ratingPanel('left');ratingPanel('right');refresh();
