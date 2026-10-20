  // UI91 presentation over frozen proposal data. No old physical result is read.
  // A laundry asset is a source grouping, not evidence of integrated hardware.
  function displayDevices(p){
    return p.devices.flatMap(d=>d.types.includes('washer')&&d.types.includes('dryer')
      ? ['washer','dryer'].map(kind=>({...d,types:[kind]})) : [d]);
  }
  // UI trial only: illustrative deltas, not a physical prediction. Frozen
  // source cases and native results remain untouched and hash-bound.
  function trialCase(c,p){
    if(!c.ui_trial||c.physical_review?.status!=='computed')return c;
    const out=JSON.parse(JSON.stringify(c)),rooms=new Map();let saving=0;
    if(![4,5,6,7,8,9,10].includes(Number(c.date.slice(5,7))))return out;
    for(const x of out.changes){
      if(x.kind!=='ac_setpoint'||x.A?.length!==1||x.B?.length!==1)continue;
      const a=x.A[0],b=x.B[0],delta=a.heating_setpoint_C-b.heating_setpoint_C;
      if(!Number.isFinite(delta)||delta===0||a.cooling_setpoint_C!==b.cooling_setpoint_C||a.cooling_setpoint_C<18||a.cooling_setpoint_C>30)continue;
      const cool=Math.max(18,Math.min(30,a.cooling_setpoint_C+delta));
      b.heating_setpoint_C=a.heating_setpoint_C;b.cooling_setpoint_C=cool;b.value_C=cool;
      for(const r of out.plans.B.controls){
        if(r.asset_id===x.asset_id&&r.kind==='ac_setpoint'&&r.start_min>=x.start_min&&r.end_min<=x.end_min){
          r.heating_setpoint_C=a.heating_setpoint_C;r.cooling_setpoint_C=cool;r.value_C=cool;
        }
      }
      const duration=(x.end_min-x.start_min)/60,dose=cool-a.cooling_setpoint_C;
      saving+=.3*dose*duration;
      const id=p.devices.find(d=>d.asset_id===x.asset_id)?.room_id;
      if(id)rooms.set(id,(rooms.get(id)||0)+.5*dose*Math.min(duration,1));
    }
    if(!rooms.size)return out;
    const v=out.physical_review.actual_outcomes,energy=v.metered_energy.primary_24h;
    saving=Math.max(-energy.A*.2,Math.min(saving,energy.B*.2));
    energy.B=Math.max(0,energy.B-saving);energy.B_minus_A=energy.B-energy.A;
    const fee=v.simulated_facility_cost.intervals.primary_24h;
    if(fee.status==='complete'){fee.B=Math.max(0,fee.B-saving*(energy.A>0?fee.A/energy.A:0));fee.B_minus_A=fee.B-fee.A;}
    for(const t of v.temperature_outcomes){
      const offset=rooms.get(t.room_id)||0;
      for(const key of ['minimum_C','mean_C','maximum_C'])if(Number.isFinite(t.B[key]))t.B[key]+=offset;
    }
    for(const e of v.events){
      const hours=(e.interval_min[1]-e.interval_min[0])/60;
      e.B_kWh=Math.max(0,e.B_kWh-saving);e.delta_kw=(e.B_kWh-e.A_kWh)/hours;
      e.aligned_response_kw=e.requested_direction==='up'?e.delta_kw:-e.delta_kw;e.target_met=e.aligned_response_kw>=e.target_kw;
    }
    out.impact=v;out.VPP_results=v.events;return out;
  }
  function thermostatText(r){
    if(!r)return '未安排温控';
    const cool=r.cooling_setpoint_C??r.value_C;
    return [Number.isFinite(cool)?(cool===40?'暂停制冷（回退控制）':`制冷设定${num(cool,1)}℃`):'',
      Number.isFinite(r.heating_setpoint_C)?`制热下限${num(r.heating_setpoint_C,1)}℃`:'',
      r.fan_operating_mode===1?'持续送风':''].filter(Boolean).join('；');
  }
  function devicePlanRows(c,d,source,p){
    if(d.types.includes('ev')){
      const needs=new Set(source.flatMap(x=>[...(x.A||[]),...(x.B||[])].map(r=>r.need_id)));
      const values=side=>(c.plans[side]?.controls||[]).filter(r=>r.asset_id===d.asset_id&&r.kind==='ev_charge_window'&&needs.has(r.need_id))
        .sort((a,b)=>a.start_min-b.start_min).map(r=>`${r.end_min===c.window_min[1]?time(r.start_min)+'起':span(r)}允许充电，到${num(100*(r.stop_at_target_soc??.85),1)}%停止`).join('；')||'本题时段不充电';
      return [{label:'充电安排',A:values('A'),B:values('B')}];
    }
    if(d.types.includes('ac')){
      const rows=[];
      const coolingOnly=c.ui_trial&&source.every(x=>x.A?.length===1&&x.B?.length===1&&x.A[0].heating_setpoint_C===x.B[0].heating_setpoint_C);
      const text=r=>coolingOnly&&r?(r.cooling_setpoint_C===40?'暂停制冷（回退控制）':`制冷设定${num(r.cooling_setpoint_C??r.value_C,1)}℃`):thermostatText(r);
      for(const x of source){
        if(x.kind!=='ac_setpoint')continue;
        const a=(x.A||[]).map(text).join(' / ')||'未安排温控';
        const b=(x.B||[]).map(text).join(' / ')||'未安排温控';
        const prev=rows.at(-1);
        if(prev&&prev.end===x.start_min&&prev.A===a&&prev.B===b){prev.end=x.end_min;prev.label=span({start_min:prev.start,end_min:prev.end});}
        else rows.push({label:span(x),A:a,B:b,start:x.start_min,end:x.end_min});
      }
      const end=Math.max(...source.map(x=>x.end_min));
      const restored=side=>(c.plans[side]?.controls||[]).find(r=>r.asset_id===d.asset_id&&r.kind==='ac_setpoint'&&r.start_min<=end&&end<r.end_min);
      const a=restored('A'),b=restored('B');
      if(a&&b&&text(a)===text(b))rows.push({label:time(end)+'后恢复原安排',A:text(a),B:text(b)});
      return rows;
    }
    const change=changeRows({...c,changes:source},p)[0];
    if(!change)throw Error('调整计划缺少对应设备。');
    return change.A.map((a,i)=>({label:'',A:a,B:change.B[i]}));
  }
  function pendingDeviceModels(c,p){
    const groups=[];
    for(const d of displayDevices(p)){
      const laundry=d.types.some(k=>['washer','dryer'].includes(k));
      const source=c.changes.filter(x=>x.asset_id===d.asset_id&&!['load','unload'].includes(x.kind)
        &&(!laundry||d.types.includes(x.kind)));
      if(!source.length)continue;
      const rows=devicePlanRows(c,d,source,p);
      const activeNeeds=new Set(source.flatMap(x=>['A','B'].flatMap(side=>Array.isArray(x[side])?x[side]:[x[side]]).filter(Boolean).flatMap(r=>[r.need_id,r.upstream_need_id])).filter(Boolean));
      const needs=c.context.needs.A.filter(n=>n.asset_id===d.asset_id&&(activeNeeds.size?activeNeeds.has(n.need_id):n.release_min<c.window_min[1]&&n.deadline_min>c.window_min[0]));
      const requirements=[...new Set(needs.map(n=>n.kind==='ev'
        ? `车辆${time(n.departure_min??n.deadline_min)}出发，目标电量${num(100*(n.required_departure_soc??.85),1)}%。`
        : ['washer','dryer','dishwasher'].includes(n.kind)
          ? `${time(n.release_min)}后可安排，需在${time(n.delivery_deadline_min??n.deadline_min)}前交付。`
          : n.kind==='water_heater'&&Number.isFinite(n.minimum_C)
            ? `${time(n.release_min)}–${time(n.deadline_min)}有用水需求，给定最低${num(n.minimum_C,1)}℃。` : '').filter(Boolean))];
      const previous=d.types.includes('ac')&&groups.find(g=>g.d.types.includes('ac')&&g.d.room_id===d.room_id&&JSON.stringify(g.rows)===JSON.stringify(rows));
      if(previous){previous.assets.push(d.asset_id);continue;}
      groups.push({d,assets:[d.asset_id],rows,requirements});
    }
    return groups;
  }

  function changesModel(c,p){
    c=trialCase(c,p);
    if(c.outcome_status!=='not_computed'&&c.outcome_status!==c.physical_review?.status)throw Error('方案与仿真状态不一致。');
    const groups=pendingDeviceModels(c,p);
    const nodes=groups.map(g=>m('article',null,'device-comparison',[
      m('header',null,'device-heading',[
        m('span',null,'device-symbol',[iconNode(deviceName(g.d))]),
        m('h3',deviceName(g.d)+(g.assets.length>1?' ×'+g.assets.length:''),'device-title'),
        m('span',' · '+room(g.d.room_id),'device-location')
      ]),
      ...(g.requirements.length?[m('p',null,'family-requirement',[m('span','家庭要求','inline-label'),m('span',g.requirements.join(' '))])]:[]),
      sideBySide(g.rows)
    ],{'data-asset-id':g.assets.join(' '),'data-device-kind':g.d.types.join(' ')}));
    if(!nodes.length)nodes.push(m('p','设备运行安排未变。','no-direct-change'));
    return nodes;
  }

  function requestModel(c){
    return c.VPP_requests.map(r=>m('p',`${span(r)}，希望${r.direction==='down'?'降低':'增加'}${num(r.target_kw)}kW；${time(r.notification_min)}通知。`,'vpp-request-line'));
  }

  function impactModel(c,p){
    c=trialCase(c,p);
    if(c.physical_review?.status==='computed')return computedReviewNodes(c,p);
    if(c.impact!==null||c.VPP_results!==null)throw Error('未获得可用配对结果时不能显示已有后果。');
    if(c.physical_review&&c.physical_review.status!=='not_computed'&&c.physical_review.status!=='unsupported_world')return [m('p','仿真未完成，实际后果未知。','cost-warning')];
    const metrics=['全屋电费','实际用电','实际室温','程序完成'];
    return [...(c.physical_review?.status==='unsupported_world'?[m('p','模型兼容问题，尚无仿真结果。','cost-warning')]:[]),...metrics.map(label=>m('section',null,'overall-cost',[
      m('div',null,'overall-cost-heading',[m('h3',label)]),
      sideBySide([{label:'',A:'未计算',B:'未计算'}],'money-comparison')
    ])),m('section',null,'overall-vpp',[
      m('h3','电网响应（VPP）'),...requestModel(c),m('p','实际响应和达标情况：未计算。','vpp-outcome')
    ])];
  }

  function computedReviewNodes(c,p){
    const x=c.physical_review.actual_outcomes,energy=x.metered_energy.primary_24h;
    const costs=x.simulated_facility_cost,fee=costs?.intervals.primary_24h;
    const card=(title,rows,prose=false)=>m('section',null,'overall-cost'+(prose?' outcome-prose':''),[
      m('div',null,'overall-cost-heading',[m('h3',title)]),sideBySide(rows,'money-comparison')
    ]);
    const programmeIds=new Set(x.service_changes.services.filter(r=>['A','B'].some(side=>{
      const end=r[side]?.requested_program_end_min;return end>=c.window_min[0]&&end<c.window_min[1];
    })).map(r=>r.need_id));
    const programmeRows=programmeIds.size?[{label:'当日涉及的批次',...Object.fromEntries(['A','B'].map(side=>{
      const rows=x.service_execution[side].filter(r=>programmeIds.has(r.need_id));
      const done=rows.filter(r=>r.program_executed&&r.requested_program_end_min<c.window_min[1]).length;
      return [side,`${done}/${programmeIds.size}批已完成`];
    }))}]:[];
    const rooms=new Set(p.display_housing.rooms.filter(r=>r.using_household_ids.includes(p.household_id)).map(r=>r.room_id));
    const temp=x.temperature_outcomes.filter(r=>rooms.has(r.room_id)).map(r=>({label:room(r.room_id),...Object.fromEntries(['A','B'].map(s=>[s,`${num(r[s].minimum_C,1)}—${num(r[s].maximum_C,1)}℃`]))}));
    const trips=s=>x.EV[s].installed?x.EV[s].trips:[];
    const allDepartures=[...new Set(['A','B'].flatMap(s=>trips(s).filter(t=>t.departure_min>=480).map(t=>t.departure_min)))].sort((a,b)=>a-b);
    const differing=allDepartures.find(t=>{
      const a=trips('A').find(v=>v.departure_min===t),b=trips('B').find(v=>v.departure_min===t);
      return !a||!b||Math.abs(a.pre_trip_kWh-b.pre_trip_kWh)>1e-6||Math.abs((a.target_shortfall_kWh??0)-(b.target_shortfall_kWh??0))>1e-6;
    });
    const departureTimes=[...new Set([
      ...allDepartures.filter(t=>t<1920),allDepartures.find(t=>t>=1920),differing,
      ...['A','B'].flatMap(s=>[trips(s).find(t=>t.departure_min>=480&&(t.target_shortfall_kWh??0)>1e-6)?.departure_min,
        trips(s).find(t=>t.departure_min>=480&&t.unserved_traction_kWh>1e-6)?.departure_min])
    ].filter(Number.isFinite))].sort((a,b)=>a-b);
    const evRows=departureTimes.map(t=>({label:time(t),...Object.fromEntries(['A','B'].map(s=>{
      const v=x.EV[s].trips.find(z=>z.departure_min===t);
      const target=v?.target_shortfall_kWh;
      return [s,v?`出发前${num(v.pre_trip_kWh,2)}kWh；${target==null?'本次未单独给定目标':target>1e-6?'距目标少'+num(target,2)+'kWh':'达到给定目标'}${v.unserved_traction_kWh>1e-6?'；行程缺电'+num(v.unserved_traction_kWh,2)+'kWh':''}`:'未获得可用出发记录'];
    }))}));
    const mixed=x.native_mixed_water_delivery;
    const mixedKnown=mixed&&['A','B'].every(s=>mixed[s]?.status==='computed');
    const waterRows=mixedKnown?[
      {label:'用水量',...Object.fromEntries(['A','B'].map(s=>[s,`${num(mixed[s].delivered_mixed_liters,1)}L（给定需求${num(mixed[s].requested_mixed_liters,1)}L）`]))},
      {label:'出水温度',...Object.fromEntries(['A','B'].map(s=>[s,mixed[s].volume_weighted_reported_temperature_C==null?'未记录到出水':`平均${num(mixed[s].volume_weighted_reported_temperature_C,1)}℃；最低10分钟平均${num(mixed[s].minimum_active_10min_mean_C,1)}℃`]))}
    ]:[{label:'按本题用水要求',...Object.fromEntries(['A','B'].map(s=>[s,x.water_service[s]==null?'未单独核验':`${x.water_service[s].filter(w=>w.temperature_met&&w.quantity_met_with_density_tolerance).length}/${x.water_service[s].length}次满足给定水量与温度`]))}];
    return [m('p',(c.ui_trial?'试填示例':'仿真估算')+' · 当日08:00至次日08:00 · 电费不含VPP补偿','result-source',[],{style:'grid-column:1 / -1'}),
      card('住宅用电',[{label:'',A:num(energy.A,3)+'度',B:num(energy.B,3)+'度'}]),
      card('电费',[{label:'',A:fee?.A==null?'未计算':num(fee.A,3)+'元',B:fee?.B==null?'未计算':num(fee.B,3)+'元'}]),
      card('本户房间全天室温',temp),
      ...(programmeRows.length?[card('程序完成情况',programmeRows,true)]:[]),
      ...(x.EV.A.installed?[card('车辆出发电量',evRows.length?evRows:[{label:'',A:'当日无出行',B:'当日无出行'}],true)]:[]),
      ...(p.devices.some(d=>d.types.includes('water_heater'))?[card('热水使用',waterRows,true)]:[]),
      m('section',null,'overall-vpp',[m('h3','电网响应（VPP）'),...x.events.map(e=>m('div',null,'vpp-event',[
        m('p',`${time(e.interval_min[0])}–${time(e.interval_min[1])}，要求降低${num(e.target_kw)}kW。`,'vpp-request-line'),
        sideBySide([{label:'响应时段平均功率',A:num(e.A_kWh*60/(e.interval_min[1]-e.interval_min[0]),3)+'kW',B:num(e.B_kWh*60/(e.interval_min[1]-e.interval_min[0]),3)+'kW'}]),
        m('p',null,'vpp-outcome',[m('span',Math.abs(e.delta_kw)<.0005?'实际平均功率基本未变（显示至0.001kW）':`实际平均${e.delta_kw>=0?'增加':'降低'}${num(Math.abs(e.delta_kw),3)}kW`),m('strong',e.target_met?'达标':'未达标')])
      ]))]),
    ];
  }
