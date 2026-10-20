  // UI91 presentation over frozen proposal data. No old physical result is read.
  function housePicture(p){
    const preview=housingPreview(p);
    return {...preview,children:preview.children.map(n=>n.tag==='svg'?housingDrawing(p,'detail'):n)};
  }
  function pendingDeviceModels(c,p){
    const groups=[];
    for(const d of p.devices){
      const source=c.changes.filter(x=>x.asset_id===d.asset_id);
      if(!source.length)continue;
      const change=changeRows({...c,changes:source},p)[0];
      if(!change)throw Error('调整计划缺少对应设备。');
      const rows=change.A.map((a,i)=>({label:'',A:a,B:change.B[i]}));
      const activeNeeds=new Set(source.flatMap(x=>['A','B'].flatMap(side=>Array.isArray(x[side])?x[side]:[x[side]]).filter(Boolean).map(r=>r.need_id)).filter(Boolean));
      const needs=c.context.needs.A.filter(n=>n.asset_id===d.asset_id&&(activeNeeds.size?activeNeeds.has(n.need_id):n.release_min<c.window_min[1]&&n.deadline_min>c.window_min[0]));
      const requirements=[...new Set(needs.map(n=>n.kind==='ev'
        ? `车辆${time(n.departure_min??n.deadline_min)}出发，目标电量${num(100*(n.required_departure_soc??.85),1)}%。`
        : ['washer','dryer','dishwasher'].includes(n.kind)
          ? `${time(n.release_min)}后可安排，需在${time(n.delivery_deadline_min??n.deadline_min)}前交付。`
          : n.kind==='water_heater'&&Number.isFinite(n.minimum_C)
            ? `${time(n.release_min)}–${time(n.deadline_min)}有用水需求，给定最低${num(n.minimum_C,1)}℃。` : '').filter(Boolean))];
      if(d.types.includes('ac'))requirements.push('温控请求须结合家庭角色和当天生活判断；请求温度不等于实际室温。');
      if(!requirements.length)requirements.push('按本户给定的生活安排与操作权限判断。');
      const previous=d.types.includes('ac')&&groups.find(g=>g.d.types.includes('ac')&&g.d.room_id===d.room_id&&JSON.stringify(g.rows)===JSON.stringify(rows));
      if(previous){previous.assets.push(d.asset_id);continue;}
      groups.push({d,assets:[d.asset_id],rows,requirements});
    }
    return groups;
  }

  function changesModel(c,p){
    if(c.outcome_status!=='not_computed'&&c.outcome_status!==c.physical_review?.status)throw Error('方案与仿真状态不一致。');
    const groups=pendingDeviceModels(c,p);
    const nodes=groups.map(g=>m('article',null,'device-comparison',[
      m('header',null,'device-heading',[
        m('span',null,'device-symbol',[iconNode(deviceName(g.d))]),
        m('h3',deviceName(g.d)+(g.assets.length>1?' ×'+g.assets.length:''),'device-title'),
        m('span',' · '+room(g.d.room_id),'device-location')
      ]),
      m('p',null,'family-requirement',[m('span','家庭要求','inline-label'),m('span',g.requirements.join(' '))]),
      sideBySide(g.rows),
      m('p',null,'life-effect',[m('strong','计划说明'),m('span',c.physical_review?.status==='computed'?'以上为操作与控制请求；本题配对仿真结果见下方。':'以上为操作与控制请求；实际运行、完成情况及生活后果尚未计算。')])
    ],{'data-asset-id':g.assets.join(' ')}));
    if(!nodes.length)nodes.push(m('p','这一天A、B安排相同。请按给定家庭判断是否接受。','no-direct-change'));
    const changed=new Set(groups.flatMap(g=>g.assets)),rest=p.devices.filter(d=>!changed.has(d.asset_id));
    if(rest.length)nodes.push(m('p',`其余${rest.length}项设备安排未变。`,'unchanged-note'));
    return nodes;
  }

  function requestModel(c){
    return c.VPP_requests.map(r=>m('p',`${span(r)}，希望${r.direction==='down'?'降低':'增加'}${num(r.target_kw)}kW；${time(r.notification_min)}通知。`,'vpp-request-line'));
  }

  function fullScheduleNodes(c,p){
    return [m('p','本题原始安排，包含跨夜和后续任务。运行及完成情况见“主要影响”。','section-note'),
      ...p.devices.flatMap(d=>[m('h3',asset(p,d.asset_id)),...['A','B'].flatMap(side=>{
        const events=Object.values(c.plans[side]).flat().filter(x=>x.asset_id===d.asset_id&&x.end_min>c.window_min[0]).sort((a,b)=>a.start_min-b.start_min||a.end_min-b.end_min);
        return [m('h4',side==='A'?'原安排A':'提议B'),...(events.length?events.map(x=>m('p',command(x,p))):[m('p','此范围内无安排。')])];
      })])];
  }

  function completeInformation(c,p){
    return m('details',null,'complete-information',[
      m('summary',null,'complete-information-entry',[
        m('span',null,'',[m('strong','查看完整资料'),m('small','家庭与剖面图、生活安排、完整A/B排程')]),
        m('span',null,'information-action',[],{'aria-hidden':'true'})
      ]),
      m('div',null,'complete-information-body',[
        m('section',null,'evidence-section',[m('h3','家庭、住房与生活安排'),...familyLines(c,p).map(s=>m('p',s)),housePicture(p)]),
        m('section',null,'evidence-section',[m('h3','完整A/B排程'),m('div',null,'',fullScheduleNodes(c,p),{id:'plans'})]),
        ...(c.physical_review?.model_scope?[m('section',null,'evidence-section',[
          m('h3','仿真资料的适用范围'),
          m('p',`A/B共用相同住房、典型天气和${c.physical_review.model_scope.A.history_days}天已提供的历史日程。模型为参考参数，未逐户实测校准；较短前史没有新增逐户收敛证明。`),
          ...(c.physical_review.model_scope.A.multi_AC_execution?.length?[m('p','同房多空调保留全部设备，分别按自己的设定控制盘管；房间按充分混合和固定设备优先级建模，不代表真实厂家控制器。')]:[]),
          m('p','电费按给定参考单价计算，不含补偿。程序完成、热水交付、出发电量与舒适感分别判断；未知后果不能补造。')
        ])]:[])
      ])
    ],{id:'plans-details','data-detail-id':'full-schedule'});
  }

  function impactModel(c,p){
    if(c.physical_review?.status==='computed')return computedReviewNodes(c,p);
    if(c.impact!==null||c.VPP_results!==null)throw Error('未获得可用配对结果时不能显示已有后果。');
    if(c.physical_review&&c.physical_review.status!=='not_computed'&&c.physical_review.status!=='unsupported_world')return [m('p','本题仿真未获得完整可用的A/B配对结果，实际后果未知；这不等于已经证明B在生活上失败。请结合已列计划判断。','cost-warning'),m('p','运行记录已保留，不替换B，也不将未知结果补零。','cost-scope'),completeInformation(c,p)];
    const metrics=['全屋电费','实际用电','实际室温','任务完成'];
    return [...(c.physical_review?.status==='unsupported_world'?[m('p','当前物理模型暂不支持本题的设备配置，尚无仿真结果。这是模型兼容问题，不代表B已经被证明失败。','cost-warning')]:[]),...metrics.map(label=>m('section',null,'overall-cost',[
      m('div',null,'overall-cost-heading',[m('h3',label)]),
      sideBySide([{label:'',A:'未计算',B:'未计算'}],'money-comparison')
    ])),m('section',null,'overall-vpp',[
      m('h3','电网响应（VPP）'),...requestModel(c),m('p','实际响应和达标情况：未计算。','vpp-outcome')
    ]),m('p','以上为冻结的调整提案。未计算不代表没有变化；后续仿真将按本题A/B版本另行关联。','cost-scope',[],{style:'grid-column:1 / -1'}),completeInformation(c,p)];
  }

  function computedReviewNodes(c,p){
    const review=c.physical_review,x=review.actual_outcomes,energy=x.metered_energy.primary_24h;
    const costs=x.simulated_facility_cost,fee=costs?.intervals.primary_24h;
    const card=(title,rows,note)=>m('section',null,'overall-cost',[
      m('div',null,'overall-cost-heading',[m('h3',title)]),sideBySide(rows,'money-comparison'),...(note?[m('p',note,'cost-scope')]:[])
    ]);
    const service=side=>{
      const ids=new Set(x.service_changes.services.filter(r=>['A','B'].some(s=>r[s]&&[r[s].requested_program_end_min,r[s].requested_retrieval_end_min].some(t=>t>=480&&t<1920))).map(r=>r.need_id));
      const rows=x.service_execution[side].filter(r=>ids.has(r.need_id));
      return `次日08:00前运行完成${rows.filter(r=>r.program_executed&&r.requested_program_end_min<1920).length}/${ids.size}批；已取出${rows.filter(r=>r.collected&&r.requested_retrieval_end_min<1920).length}/${ids.size}批`;
    };
    const rooms=new Set(p.display_housing.rooms.filter(r=>r.using_household_ids.includes(p.household_id)).map(r=>r.room_id));
    const temp=x.temperature_outcomes.filter(r=>rooms.has(r.room_id)).map(r=>({label:room(r.room_id),...Object.fromEntries(['A','B'].map(s=>[s,`${num(r[s].minimum_C,1)}—${num(r[s].maximum_C,1)}℃`]))}));
    const departureTimes=[...new Set(['A','B'].flatMap(s=>x.EV[s].installed?x.EV[s].trips.filter(t=>t.departure_min>=480).slice(0,1).map(t=>t.departure_min):[]))];
    const evRows=departureTimes.map(t=>({label:time(t),...Object.fromEntries(['A','B'].map(s=>{
      const v=x.EV[s].trips.find(z=>z.departure_min===t);
      const target=v?.target_shortfall_kWh;
      return [s,v?`出发前${num(v.pre_trip_kWh,2)}kWh；${target==null?'未声明出发目标':target>1e-6?'距目标少'+num(target,2)+'kWh':'达到给定目标'}`:'未获得可用出发记录'];
    }))}));
    const constraintNotes=(review.failed_checks||[]).map(k=>{
      const who=k.startsWith('A_')?'A：':k.startsWith('B_')?'B：':'';
      if(k.endsWith('_electrical_supply'))return who+'模拟功率曾超过参考回路容量；未模拟跳闸。';
      if(k.endsWith('_service_execution'))return who+'存在程序、取出操作未完成或服务逾期。';
      if(k.endsWith('_EV_departure_target'))return who+'当日或后续行程中存在未达到给定出发电量的情况。';
      if(k.endsWith('_declared_comfort'))return who+'存在超出情境给定温度范围的时段；不代表已知真实个人感受。';
      if(k.includes('recovery')||k.includes('terminal'))return '后续恢复检查存在残差，不能把当日用电差直接当成等服务节能。';
      return who+'存在其他已记录的服务或约束检查问题。';
    });
    return [m('p','本题已完成同一住房、天气和前史下的A/B配对仿真；下列为模型估算，不是实测结果。','cost-scope',[],{style:'grid-column:1 / -1'}),
      card('当日住宅用电',[{label:'08:00—次日08:00',A:num(energy.A,3)+'度',B:num(energy.B,3)+'度'}],'住宅电表包含共同建模空间；不自动等于目标家庭实测分表。'),
      card('当日电费',[{label:'按情境单价计算',A:fee?.A==null?'未计算':num(fee.A,3)+'元',B:fee?.B==null?'未计算':num(fee.B,3)+'元'}],'只列当日给定单价覆盖的费用；不含VPP补偿，后续未覆盖费用不补零。'),
      card('本户使用房间的室温范围',temp,'全天范围，包含无人时段；不直接等于个人舒适评分。'),
      card('当日程序执行与取出',[{label:'按当日计划完成时点计数',A:service('A'),B:service('B')}],'程序运行、实际取出与全部生活需求是否满足是不同问题。'),
      ...(x.EV.A.installed?[card('车辆最近一次出发',evRows,'按原连接与行程核算；不假定出发目标必然满足。')]:[]),
      ...(p.devices.some(d=>d.types.includes('water_heater'))?[card('热水交付',[{label:'按本题用水要求',...Object.fromEntries(['A','B'].map(s=>[s,x.water_service[s]==null?'未单独核验':`${x.water_service[s].filter(w=>w.temperature_met&&w.quantity_met_with_density_tolerance).length}/${x.water_service[s].length}次满足给定水量与温度`]))}],'有热水器运行结果不等于已证明每次用水需求满足；未核验部分保持未知。')]:[]),
      m('section',null,'overall-vpp',[m('h3','电网响应（VPP）'),...x.events.map(e=>m('div',null,'vpp-event',[
        m('p',`${time(e.interval_min[0])}–${time(e.interval_min[1])}，要求降低${num(e.target_kw)}kW；按本题声明的可控设备电表比较。`,'vpp-request-line'),
        sideBySide([{label:'响应时段平均功率',A:num(e.A_kWh*60/(e.interval_min[1]-e.interval_min[0]),3)+'kW',B:num(e.B_kWh*60/(e.interval_min[1]-e.interval_min[0]),3)+'kW'}]),
        m('p',null,'vpp-outcome',[m('span',`实际平均${e.delta_kw>=0?'增加':'降低'}${num(Math.abs(e.delta_kw),3)}kW`),m('strong',e.target_met?'达标':'未达标')])
      ]))]),
      ...[...new Set(constraintNotes)].map(t=>m('p',t,'cost-warning',[],{style:'grid-column:1 / -1'})),
      m('p',`工程审计：${review.audit_status==='passed'?'通过':'有已记录的问题'}。以上约束检查涵盖当日及后续恢复区间；工程运行完成不等于VPP达标，也不预设家庭是否接受。`,'cost-scope',[],{style:'grid-column:1 / -1'}),completeInformation(c,p)
    ];
  }
