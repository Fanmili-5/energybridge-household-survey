'use strict';
(function(root) {
  const REVISION = 'eb.questionnaire50.collection.v69';
  const LABELS = {ac:'空调',washer:'洗衣',dryer:'烘干',dishwasher:'洗碗机',water_heater:'电热水器',ev:'电动车',load:'装载',unload:'取出',EV_plug:'接上充电插头',EV_unplug:'拔下充电插头'};
  const num = (x, digits=2) => Number.isFinite(x) ? String(Number(x.toFixed(digits))) : '未提供';
  const range = x => Array.isArray(x) && x.length === 2 ? `${num(x[0],1)}—${num(x[1],1)}℃` : '无有人时记录';
  const room = id => {
    const key = String(id).toLowerCase();
    return ({combined_bed_living:'起居兼卧室',corridor:'走廊',kitchen:'厨房',washroom:'卫生间',external_dedicated_ev_bay:'车位',living:'起居室',living_room:'起居室',living_hall:'起居厅',bedroom:'卧室',utility_niche:'家务区'}[key] || key.replace(/^private_0*(\d+)$/,'房间$1').replace(/^shared_storage_0*(\d+)$/,'共用储物间$1').replace(/^bedroom[_-]?(\d+)$/,'卧室$1').replace(/^service[_-]?(\d+)$/,'家务区$1'));
  };
  function time(minute) {
    const day = Math.floor(minute / 1440), value = ((minute % 1440) + 1440) % 1440;
    const prefix = day === 0 ? '' : day === 1 ? '次日' : day === -1 ? '前一天' : day < 0 ? `前${-day}天` : `第${day+1}天`;
    return prefix + String(Math.floor(value/60)).padStart(2,'0') + ':' + String(value%60).padStart(2,'0');
  }
  const span = x => `${time(x.start_min)}–${time(x.end_min)}`;
  const signed = x => !Number.isFinite(x) ? '未计算' : Math.abs(x) < 0.0005 ? '基本相同' : `${x>0?'多':'少'}${num(Math.abs(x),3)}度`;
  const deviceName = d => d.types.includes('washer') && d.types.includes('dryer') ? '洗烘一体机' : d.types.map(k=>LABELS[k]).join('、');
  const person = (p,id) => p.members.find(m=>m.member_id===id)?.local_id.replace(/^m0*/, '成员') || '上门协助者';
  const asset = (p,id) => {
    const d = p.devices.find(d=>d.asset_id===id);
    return d ? `${deviceName(d)} · ${room(d.room_id)}` : '电器';
  };

  function thermostatAxes(change) {
    const axes = [];
    for (const key of ['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode']) {
      const values = states => (states||[]).map(x=>key==='cooling_setpoint_C' ? (x[key]??x.value_C) : x[key]);
      if (JSON.stringify(values(change.A)) !== JSON.stringify(values(change.B))) axes.push(key);
    }
    return axes;
  }
  function control(states, kind, axes) {
    if (!states?.length) return kind==='ev_charge_window' ? '暂停充电' : kind==='tank_setpoint' ? '暂停加热' : '暂停温控';
    return states.map(x=>{
      if (kind==='ev_charge_window') return `允许充电（到${num((x.stop_at_target_soc??.85)*100,1)}%停止）`;
      if (kind==='tank_setpoint') return `加热目标${num(x.value_C,1)}℃`;
      const shown = axes?.length ? axes : ['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode'];
      return shown.map(key=>key==='heating_setpoint_C' ? `制热${num(x[key],1)}℃` : key==='cooling_setpoint_C' ? `制冷${num(x[key]??x.value_C,1)}℃` : x.fan_operating_mode===1 ? '持续送风' : '自动送风').join('，');
    }).join(' / ');
  }
  function command(x,p) {
    if (!x) return '未安排';
    const value = ['ac_setpoint','tank_setpoint','ev_charge_window'].includes(x.kind) ? control([x],x.kind) : LABELS[x.kind]||'电器操作';
    return `${value} ${span(x)}${x.operator_id?'（'+person(p,x.operator_id)+'）':''}`;
  }
  function changeRows(c,p) {
    const groups = new Map();
    for (const x of c.changes) {
      if (!groups.has(x.asset_id)) groups.set(x.asset_id,{asset:asset(p,x.asset_id),A:[],B:[],sourceChanges:0,units:1,isAC:p.devices.find(d=>d.asset_id===x.asset_id)?.types.includes('ac')});
      const row = groups.get(x.asset_id);
      if (x.group==='controls') {
        const axes = x.kind==='ac_setpoint' ? thermostatAxes(x) : null;
        const a=control(x.A,x.kind,axes),b=control(x.B,x.kind,axes),previous=row.lastControl;
        if(previous && previous.kind===x.kind && previous.end_min===x.start_min && previous.a===a && previous.b===b) {
          previous.end_min=x.end_min;
          row.A[row.A.length-1]=`${span(previous)} ${a}`;
          row.B[row.B.length-1]=`${span(previous)} ${b}`;
        } else {
          row.A.push(`${span(x)} ${a}`);row.B.push(`${span(x)} ${b}`);
          row.lastControl={kind:x.kind,start_min:x.start_min,end_min:x.end_min,a,b};
        }
      } else {
        for (const side of ['A','B']) row[side].push(command(x[side],p));
        row.lastControl=null;
      }
      row.sourceChanges++;
    }
    const visible=[];
    for(const row of groups.values()) {
      const duplicate=row.isAC && visible.find(x=>x.isAC&&x.asset===row.asset&&JSON.stringify(x.A)===JSON.stringify(row.A)&&JSON.stringify(x.B)===JSON.stringify(row.B));
      if(duplicate){duplicate.units++;duplicate.sourceChanges+=row.sourceChanges;}
      else visible.push(row);
    }
    return visible.map(({asset,A,B,sourceChanges,units})=>({asset:units>1?asset.replace('空调 ·',`空调（${units}台） ·`):asset,A,B,sourceChanges,units}));
  }

  function familyLines(c,p) {
    const policy = p.role_policy, permission = policy.permissions;
    const relations = {partner_or_spouse_of:'伴侣',child_of:'子女',parent_of:'父母',sibling_of:'兄弟姐妹',child_partner_of:'子女的伴侣',grandchild_of:'孙辈',parent_of_partner_of:'伴侣的父母'};
    const lines = [];
    lines.push(p.members.map(m=>`${person(p,m.member_id)} ${m.age_years}岁${m.sex==='female'?'女':m.sex==='male'?'男':''}`).join('；'));
    if (p.relationships.length) lines.push(p.relationships.map(r=>`${person(p,r.subject)}是${person(p,r.object)}的${relations[r.type]||'家人'}`).join('；'));
    lines.push(`你代入${person(p,policy.holder.person_id)}${policy.holder.resident?'':'（非同住责任人）'}，${policy.economics.cost_priority_given?'更重视节省开支':'更重视舒适、日程与服务'}；${permission.automatic_within_declared_bounds?'约定范围内可自动调整，需通知':'调整前需逐次确认'}${permission.same_day_reconfirmation?'，当天变化需再次确认':''}${permission.protected_service_veto?'；优先保障受照护家人的服务':''}。`);
    lines.push(`调整边界：平时制冷${num(policy.thermal.usual_setpoint_C,1)}℃，临时最多上调${num(policy.thermal.temporary_increase_C,1)}℃、${policy.thermal.maximum_change_duration_min}分钟；家务开始时间可协商${policy.service_policy.reschedule_limit_min}分钟。`);
    const day = c.context.days.find(d=>d.date===c.date);
    if (day) {
      const family = day.family;
      const baths = [...new Set(Object.values(family.bath_times_min||{}))].sort((a,b)=>a-b).map(time);
      lines.push(`今天：晚餐${time(family.dinner_min)}${baths.length?'；洗澡'+baths.join('、'):''}。`);
    }
    const activeNeeds = new Set(['A','B'].flatMap(side=>['tasks','operations'].flatMap(group=>c.plans[side][group].filter(x=>x.start_min<c.window_min[1]&&x.end_min>c.window_min[0]).map(x=>x.need_id))));
    const needs = new Set();
    for (const need of c.context.needs.A) {
      if (['washer','dryer','dishwasher'].includes(need.kind) && activeNeeds.has(need.need_id)) {
        const d = p.devices.find(d=>d.asset_id===need.asset_id);
        needs.add(`${d?deviceName(d):LABELS[need.kind]}需在${time(need.delivery_deadline_min??need.deadline_min)}前完成`);
      }
      if (need.kind==='ev' && need.release_min<c.window_min[1] && need.deadline_min>c.window_min[0]) needs.add(`车辆${time(need.departure_min??need.deadline_min)}出发，目标电量${num((need.required_departure_soc??.85)*100,1)}%`);
    }
    if (needs.size) lines.push('需求：'+[...needs].join('；')+'。');
    // Assistance changes whether a proposed manual operation is plausible.
    for (const support of p.support||[]) lines.push(support);
    return lines;
  }

  function temperatureEffect(c,p) {
    const rows = c.impact.display.temperature_card.rows;
    const changedRooms = new Set(c.changes.filter(x=>x.kind==='ac_setpoint').map(x=>p.devices.find(d=>d.asset_id===x.asset_id)?.room_id?.toLowerCase()));
    const selected = rows.filter(r=>{
      const d = r.B_own_occupied_air_delta_durations['0.5'];
      return d.B_warmer.total_minutes+d.B_cooler.total_minutes>0 || changedRooms.has(r.room.toLowerCase());
    });
    const lines = selected.map(r=>{
      const one = r.B_own_occupied_air_delta_durations['1.0'];
      const threshold = one.B_warmer.total_minutes+one.B_cooler.total_minutes>0 ? '1.0' : '0.5';
      const d = r.B_own_occupied_air_delta_durations[threshold], changes = [];
      if(d.B_warmer.total_minutes) changes.push(`高于A ${num(Number(threshold),1)}℃以上${d.B_warmer.total_minutes}分钟`);
      if(d.B_cooler.total_minutes) changes.push(`低于A ${num(Number(threshold),1)}℃以上${d.B_cooler.total_minutes}分钟`);
      return `${room(r.room)}：A ${range(r.A_occupied_air_C)}，B ${range(r.B_occupied_air_C)}${changes.length?'；'+changes.join('，'):'；未出现超过0.5℃的温差'}。`;
    });
    return {label:'室温',lead:lines.length?null:rows.length?'未出现超过0.5℃的温差':'无有人时记录',lines,
            note:rows.length?'按B有人时与A同时刻比较，时长按10分钟估算。':'没有可比较的有人时记录。',
            selectedRooms:selected.map(r=>r.room)};
  }
  function serviceEffect(c) {
    const card = c.impact.display.task_delivery_card, lines = [];
    let affected = false;
    for (const side of ['A','B']) {
      const x = card[side];
      if(x.failed_retrieval_batches) {lines.push(`${side}有${x.failed_retrieval_batches}批物品未取出${x.future_unexecuted_batches?'，不假设人工补救时，后续'+x.future_unexecuted_batches+'批未运行':''}。`);affected=true;}
      else if(x.unexecuted_batches) {lines.push(`${side}有${x.unexecuted_batches}批未运行。`);affected=true;}
      if(x.retrieval_pending_after_horizon) {lines.push(`${side}在观察结束时仍有${x.retrieval_pending_after_horizon}批待取出。`);affected=true;}
      for(const r of x.EV_shortfall_details) {
        const pieces=[];
        if(r.target_shortfall_kWh>1e-6) pieces.push(`出发目标电量少${num(r.target_shortfall_kWh,3)}kWh`);
        if(r.unserved_traction_kWh>1e-6) pieces.push(`行程用电未交付${num(r.unserved_traction_kWh,3)}kWh`);
        else pieces.push('本次行程电量可满足');
        if(r.minimum_reserve_shortfall_kWh>1e-6) pieces.push('行程后低于保留电量');
        lines.push(`${side} ${time(r.departure_min)}：${pieces.join('，')}。`);affected=true;
      }
      if(!x.reported_hot_water_target_met) {lines.push(`${side}热水未达到给定用水目标。`);affected=true;}
    }
    if(card.source_B_constraint_flags.length && !affected) {lines.push('B存在操作或资源约束冲突。');affected=true;}
    if(card.state_recovery_status==='not_restored_within_horizon') lines.push('后续观察结束时，状态仍与A有差异。');
    return {label:'任务完成',lead:affected?'有未满足的任务或要求':'已列任务均完成',lines,warning:affected,
            note:affected?'电量减少需结合这些后果判断。':'未记录出发电量或热水目标不足。'};
  }
  function vppEffect(c) {
    const results = c.VPP_results, met = results.filter(x=>x.target_met).length;
    return {label:'VPP响应',lead:`${met}/${results.length}个窗口达到目标`,lines:results.map(r=>{
      const request=c.VPP_requests.find(x=>x.event_id===r.event_id);
      const actual=r.relation==='unchanged'?'用电基本未变':`平均${r.delta_kw>=0?'增加':'降低'}${num(Math.abs(r.delta_kw),3)}kW`;
      return `${span(request)}：希望${request.direction==='up'?'增加':'降低'}${num(request.target_kw)}kW；B${actual}，${r.target_met?'达标':'未达标'}。`;
    })};
  }
  function effects(c,p) {
    const e=c.impact.energy_changes, primary=e.primary, observation=e.observation;
    return [
      {label:'用电',lead:`当天${signed(primary.facility_B_minus_A_kWh)}`,
       lines:[`A ${num(primary.facility_A_kWh,3)}度 → B ${num(primary.facility_B_kWh,3)}度。`,
              `含后续观察${signed(observation.facility_B_minus_A_kWh)}（至${observation.end.replace('T',' ')}）。`]},
      temperatureEffect(c,p),serviceEffect(c),vppEffect(c)
    ];
  }
  function answer(raw) {
    const a={decision:raw.decision||null,reason:raw.reason?.trim()||null};
    for(const k of ['score','comfort_score','energy_score','vpp_score']) a[k]=raw[k]===''||raw[k]==null?null:Number(raw[k]);
    root.EBRequiredResponse(a);
    if(!a.reason) throw Error('请填写主要原因。');
    return a;
  }

  function deviceLabels(p) {
    const groups=new Map();
    for(const d of p.devices){const key=deviceName(d)+'|'+d.room_id;const g=groups.get(key)||{d,count:0};g.count++;groups.set(key,g);}
    return [...groups.values()].map(({d,count})=>deviceName(d)+(count>1?'×'+count:'')+(p.devices.filter(x=>deviceName(x)===deviceName(d)).length>count?' · '+room(d.room_id):''));
  }
  // One model drives both visible DOM and the server's exact-text binding.
  const m=(tag,text=null,cls='',children=[],attrs={})=>({tag,text,cls,children,attrs});
  const textOf=n=>(n.text??'')+(n.children||[]).map(textOf).join('');
  const sideLabel=side=>m('p',null,'side-label',[m('strong',side),m('span',side==='A'?'原安排':'提议方案')]);
  const iconNode=kind=>({...m('svg',null,'device-icon',[],{'aria-hidden':'true',viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.5','stroke-linecap':'round','stroke-linejoin':'round'}),icon:kind});
  const metricCell=(side,value,unit='')=>m('div',null,'metric-cell'+(side==='B'?' proposal':''),[sideLabel(side),m('p',null,'metric-value',[m('span',value),...(unit?[m('small',unit)]:[])])]);
  function familyModel(c,p){
    const lines=familyLines(c,p);
    return [m('p',`${p.province} · ${p.members_count}人 · ${p.generations}代`,'family-facts',[m('span',`${num(p.household_area_m2,1)}㎡`)]),
      ...lines.map((s,i)=>m('p',s,i===0?'family-members':i===2?'family-line role':'family-line')),
      m('div',null,'family-meta',deviceLabels(p).map(s=>m('span',null,'device-tag',[iconNode(s),m('span',s)])))];
  }
  function requestModel(c){
    const notices=[...new Set(c.VPP_requests.map(x=>time(x.notification_min)))];
    return [m('p','这一天的VPP请求','request-title'),m('p',c.VPP_requests.length?c.VPP_requests.map(x=>`${span(x)}，${x.direction==='up'?'增加':'降低'}负荷${num(x.target_kw)}kW`).join('；'):'未设置VPP请求','request-events'),m('p',`通知时间：${notices.join('、')||'未设置'}`,'request-notice')];
  }
  function changesModel(c,p){
    const rows=changeRows(c,p);
    return rows.length?rows.map(r=>m('div',null,'change-card',[m('h3',null,'',[iconNode(r.asset),m('span',r.asset)]),m('div',null,'change-pair',['A','B'].map(side=>m('div',null,'change-side'+(side==='B'?' proposal':''),[sideLabel(side),...r[side].map(s=>m('p',s,'change-command'))])))])):[m('p','本题A/B实际安排相同，仍请独立评价。','no-change')];
  }
  function serviceLines(c,side){
    const card=c.impact.display.task_delivery_card,x=card[side],lines=[];
    if(x.failed_retrieval_batches)lines.push(`${x.failed_retrieval_batches}批物品未取出${x.future_unexecuted_batches?'；不假设人工补救时，后续'+x.future_unexecuted_batches+'批未运行':''}。`);
    else if(x.unexecuted_batches)lines.push(`${x.unexecuted_batches}批未运行。`);
    if(x.retrieval_pending_after_horizon)lines.push(`观察结束时仍有${x.retrieval_pending_after_horizon}批待取出。`);
    for(const r of x.EV_shortfall_details){
      const details=[];
      if(r.target_shortfall_kWh>1e-6)details.push(`出发目标电量少${num(r.target_shortfall_kWh,3)}kWh`);
      if(r.unserved_traction_kWh>1e-6)details.push(`行程用电未交付${num(r.unserved_traction_kWh,3)}kWh`);else details.push('本次行程电量可满足');
      if(r.minimum_reserve_shortfall_kWh>1e-6)details.push('行程后低于保留电量');
      lines.push(`${time(r.departure_min)}：${details.join('，')}。`);
    }
    if(!x.reported_hot_water_target_met)lines.push('热水未达到给定用水目标。');
    if(!lines.length)lines.push('已列任务均完成。');
    if(side==='B'&&card.source_B_constraint_flags.length)lines.push('存在操作或资源约束冲突。');
    return lines;
  }
  function impactModel(c,p){
    const e=c.impact.energy_changes,primary=e.primary,observation=e.observation;
    const cards=[m('div',null,'impact-card',[
      m('div',null,'impact-title',[m('h3','用电量'),m('span','当日08:00—次日08:00','impact-subtitle')]),
      m('div',null,'metric-pair',[metricCell('A',num(primary.facility_A_kWh,3),'度'),metricCell('B',num(primary.facility_B_kWh,3),'度')]),
      m('p',`B比A${signed(primary.facility_B_minus_A_kWh)}。`,'metric-note'),
      m('p',`含后续观察：A ${num(observation.facility_A_kWh,3)}度，B ${num(observation.facility_B_kWh,3)}度；B比A${signed(observation.facility_B_minus_A_kWh)}（至${observation.end.replace('T',' ')}）。`,'effect-detail')])];
    const temperature=temperatureEffect(c,p),rooms=c.impact.display.temperature_card.rows.filter(r=>temperature.selectedRooms.includes(r.room));
    const thermal=[m('div',null,'impact-title',[m('h3','有人时的室温')])];
    for(const r of rooms){
      const one=r.B_own_occupied_air_delta_durations['1.0'];
      const threshold=one.B_warmer.total_minutes+one.B_cooler.total_minutes>0?'1.0':'0.5';
      const d=r.B_own_occupied_air_delta_durations[threshold],changes=[];
      if(d.B_warmer.total_minutes)changes.push(`B高于A ${num(Number(threshold),1)}℃以上${d.B_warmer.total_minutes}分钟`);
      if(d.B_cooler.total_minutes)changes.push(`B低于A ${num(Number(threshold),1)}℃以上${d.B_cooler.total_minutes}分钟`);
      thermal.push(m('div',null,'exposure-row',[m('h4',room(r.room)),m('div',null,'metric-pair',[metricCell('A',range(r.A_occupied_air_C)),metricCell('B',range(r.B_occupied_air_C))]),m('p',changes.length?changes.join('；')+'。':'未出现超过0.5℃的温差。','effect-line')]));
    }
    if(!rooms.length)thermal.push(m('p',temperature.lead,'effect-line'));
    thermal.push(m('p',c.impact.display.temperature_card.rows.length?'室温范围取A/B各自有人时段；温差时长按B有人时段与A同刻比较，按10分钟估算。':'没有可比较的有人时记录。','effect-detail'));
    cards.push(m('div',null,'impact-card',thermal));
    const service=serviceEffect(c),task=c.impact.display.task_delivery_card;
    const serviceNodes=[m('div',null,'impact-title',[m('h3','生活任务是否完成')]),m('div',null,'metric-pair',['A','B'].map(side=>m('div',null,'metric-cell'+(side==='B'?' proposal':''),[sideLabel(side),m('div',null,'service-cell',serviceLines(c,side).map(s=>m('p',s)))])))];
    if(service.warning)serviceNodes.push(m('p','用电减少需结合任务未完成或约束冲突的后果判断。','effect-line warning'));
    if(task.state_recovery_status==='not_restored_within_horizon')serviceNodes.push(m('p','后续观察结束时，状态仍与A有差异。','effect-detail'));
    cards.push(m('div',null,'impact-card',serviceNodes));
    const vpp=[m('div',null,'impact-title',[m('h3','VPP达标（客观结果）'),m('span',`${c.VPP_results.filter(x=>x.target_met).length}/${c.VPP_results.length}个窗口达标`,'impact-subtitle')])];
    for(const r of c.VPP_results){
      const req=c.VPP_requests.find(x=>x.event_id===r.event_id),hours=(req.end_min-req.start_min)/60;
      const actual=r.relation==='unchanged'?'用电基本未变':`实际平均${r.delta_kw>=0?'增加':'降低'}${num(Math.abs(r.delta_kw),3)}kW`;
      vpp.push(m('div',null,'vpp-result',[m('p',`${span(req)}：希望${req.direction==='up'?'增加':'降低'}${num(req.target_kw)}kW`,'vpp-target'),m('div',null,'vpp-pair',['A','B'].map(side=>m('div',null,side==='B'?'proposal':'',[sideLabel(side),m('span',`${num(r[side+'_controlled_kWh']/hours,3)}kW`)]))),m('p',`${actual}，${r.target_met?'达到目标':'未达到目标'}。`,'vpp-outcome')]));
    }
    vpp.push(m('p','A/B数值为响应窗口内可调设备的平均功率。','effect-detail'));
    cards.push(m('div',null,'impact-card',vpp));return cards;
  }
  function displayed(c,p){
    const result={family:familyModel(c,p).map(textOf).join(''),request:requestModel(c).map(textOf).join(''),changes:changesModel(c,p).map(textOf).join(''),impacts:impactModel(c,p).map(textOf).join('')};
    result.schedule='本题原始安排，包含跨夜和后续任务。运行及完成情况见“主要影响”。';
    for(const d of p.devices){result.schedule+=asset(p,d.asset_id);for(const side of ['A','B']){result.schedule+=side==='A'?'原安排A':'提议B';const events=Object.values(c.plans[side]).flat().filter(x=>x.asset_id===d.asset_id&&x.end_min>c.window_min[0]).sort((a,b)=>a.start_min-b.start_min||a.end_min-b.end_min);result.schedule+=events.length?events.map(x=>command(x,p)).join(''):'此范围内无安排。';}}
    return result;
  }

  root.EBSimple50={revision:REVISION,displayed,num,range,time,signed,control,thermostatAxes,changeRows,familyLines,effects,serviceEffect,temperatureEffect,vppEffect,answer};
  if(typeof document==='undefined') return;

  const q=id=>document.getElementById(id);
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  let index,current,profile,row,serial=0,loading=true,plansRendered=false;
  async function json(path,hash) {
    const r=await fetch(path);if(!r.ok)throw Error('加载失败，请刷新重试。');
    const bytes=await r.arrayBuffer();
    if(hash) {const actual=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');if(actual!==hash)throw Error('数据版本不匹配，请重新打开当前预览。');}
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  function paint(box,nodes){
    function make(n){
      const svg=['svg','path','circle','rect'].includes(n.tag);
      const element=svg?document.createElementNS('http://www.w3.org/2000/svg',n.tag):document.createElement(n.tag);
      if(n.cls)element.setAttribute('class',n.cls);
      for(const [key,value]of Object.entries(n.attrs||{}))element.setAttribute(key,value);
      if(n.text!=null)element.textContent=n.text;
      if(n.icon){
        const paths=[['空调','M3 4h18v8H3z M6 9h12 M7 15v3 M12 15v5 M17 15v3'],['电动车','M5 8l2-4h10l2 4 M4 8h16v10H4z M7 18v2 M17 18v2 M7 11h2 M15 11h2 M13 10l-3 4h4l-3 3'],['电热水器','M6 3h12v16H6z M9 7h6 M9 11h6 M9 19v3 M15 19v3'],['洗碗','M4 3h16v18H4z M4 7h16 M8 5h1 M7 11h10 M8 11l1 6h6l1-6'],['烘干','M5 3h14v18H5z M5 8h14 M8 5.5h1 M9 11v6 M12 11v6 M15 11v6']];
        const d=paths.find(([name])=>n.icon.includes(name))?.[1]||'M5 3h14v18H5z M5 8h14 M8 5.5h1 M15 5.5h1 M8 14a4 4 0 1 0 8 0a4 4 0 1 0-8 0';
        const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',d);element.append(path);
      }
      for(const child of n.children||[])element.append(make(child));return element;
    }
    box.replaceChildren(...nodes.map(make));
  }
  function renderFamily(){paint(q('family'),familyModel(current,profile));}
  function renderChanges(){
    paint(q('vpp-request'),requestModel(current));paint(q('changes'),changesModel(current,profile));
    q('plans-details').open=false;q('plans').replaceChildren();plansRendered=false;
  }
  function renderPlans() {
    if(plansRendered||!current)return;plansRendered=true;
    const box=q('plans');box.append(el('p','本题原始安排，包含跨夜和后续任务。运行及完成情况见“主要影响”。','section-note'));
    for(const d of profile.devices) {
      const block=el('div',null,'plan-block');block.append(el('h3',asset(profile,d.asset_id)));const columns=el('div',null,'plan-columns');
      for(const side of ['A','B']) {
        const col=el('div');col.append(el('h4',side==='A'?'原安排A':'提议B'));
        const events=Object.values(current.plans[side]).flat().filter(x=>x.asset_id===d.asset_id&&x.end_min>current.window_min[0]).sort((a,b)=>a.start_min-b.start_min||a.end_min-b.end_min);
        for(const x of events)col.append(el('p',command(x,profile)));
        if(!events.length)col.append(el('p','此范围内无安排。'));columns.append(col);
      }
      block.append(columns);box.append(block);
    }
  }
  function renderEffects(){paint(q('impacts'),impactModel(current,profile));}
  function restore(){q('response-form').reset();q('response-status').textContent='';root.EBCollection.onCaseShown(current,profile,row,index);}
  async function show() {
    const turn=++serial;loading=true;document.body.setAttribute('aria-busy','true');q('task').hidden=true;q('load-status').textContent='正在加载…';
    const target=index.cases.find(x=>x.household_id===q('household').value&&x.date===q('case-date').value);
    try {
      const [p,c]=await Promise.all([json(`households/${target.household_id}.json`,index.profiles_sha256[target.household_id]),json(target.path,target.sha256)]);
      if(turn!==serial)return;row=target;profile=p;current=c;renderFamily();renderChanges();renderEffects();restore();
      q('task').hidden=false;q('load-status').textContent=`第${q('case-date').selectedIndex+1}/${index.cases.length}题 · ${current.date} 08:00至次日08:00`;
      history.replaceState(null,'','?'+new URLSearchParams({household:target.household_id,date:target.date}));loading=false;
    } catch(e){if(turn===serial)q('load-status').textContent=e.message;}
    finally{if(turn===serial)document.body.setAttribute('aria-busy','false');}
  }
  function dates(wanted) {
    q('case-date').replaceChildren();
    for(const x of index.cases.filter(x=>x.household_id===q('household').value)){const o=el('option',x.date);o.value=x.date;q('case-date').append(o);}
    if(wanted&&[...q('case-date').options].some(x=>x.value===wanted))q('case-date').value=wanted;
    q('case-date').disabled=false;show();
  }
  q('household').addEventListener('change',()=>dates());q('case-date').addEventListener('change',show);
  q('plans-details').addEventListener('toggle',()=>{if(q('plans-details').open)renderPlans();root.EBCollection.observeSchedule(q('plans-details').open);});
  q('clear-response').addEventListener('click',()=>{if(!loading)root.EBCollection.revert();});
  q('response-form').addEventListener('submit',e=>{e.preventDefault();if(!loading&&q('response-form').reportValidity())root.EBCollection.submit();});
  json('index.json').then(data=>{
    index=data;
    for(const [i,hid]of index.households.entries()){const o=el('option',`第${i+1}户 · ${hid.slice(-4)}`);o.value=hid;q('household').append(o);}
    const params=new URLSearchParams(location.search);if(index.households.includes(params.get('household')))q('household').value=params.get('household');
    q('household').disabled=false;dates(params.get('date')||data.resume_date);
  }).catch(e=>q('load-status').textContent=e.message);
})(typeof window==='undefined'?globalThis:window);
