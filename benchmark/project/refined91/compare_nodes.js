  // The reading path contains no device disclosures. Evidence has one entry.
  function presentationNodes(c,p){return {family:familyModel(c,p),request:requestModel(c),changes:changesModel(c,p),impacts:impactModel(c,p)};}
  function housingPreview(p){
    const drawing=housingDrawing(p,'preview');
    if(drawing.tag!=='svg')return drawing;
    const rooms=p.display_housing.rooms.filter(r=>Array.isArray(r.usable_rect_m));
    const own=rooms.filter(r=>(r.using_household_ids||[]).includes(p.household_id)),legend=own.length?own:rooms;
    return m('figure',null,'housing-preview',[
      m('div',null,'housing-preview-heading',[m('h3','房屋剖面示意'),m('span',p.display_housing.shared_household_count_design>1?'含合住空间':'独立居住')]),
      drawing,
      m('div',null,'housing-plan-key',[...(rooms.some(r=>roomUse(p,r)==='own')?[m('span','本户房间','plan-key own')]:[]),...(rooms.some(r=>roomUse(p,r)==='shared')?[m('span','共用空间','plan-key shared')]:[]),...(legend.length<rooms.length?[m('span','其他住户','plan-key other')]:[])]),
      ...(p.devices.some(d=>d.types.includes('ev')&&d.room_id.startsWith('external'))?[m('p',null,'housing-outdoor',[iconNode('电动车'),m('span','住宅外独立车位 · 电动车充电')])]:[]),
      m('figcaption','布局取自模型；墙高和设备具体位置仅作示意。')
    ]);
  }
  function familyModel(c,p) {
    const h=p.display_housing,lines=familyLines(c,p),role=lines.find(x=>x.startsWith('你代入'));
    const house=`${h.shared_household_count_design>1?'本户分摊':'建筑面积'}${num(p.household_area_m2,1)}㎡ · ${h.target_H7}间${h.shared_household_count_design>1?' · '+h.shared_household_count_design+'户合住':' · 独立居住'}`;
    const relations=p.relationships.length?lines[1]:null;
    const support=(p.support||[]).filter(t=>!t.startsWith('家务由日程中有空'));
    return [m('div',null,'household-layout',[
      m('div',null,'family-overview',[
        m('p',`${p.province} · ${p.members_count}人 · ${p.generations}代`,'family-facts'),
        m('p',lines[0],'family-members'),...(relations?[m('p',relations,'family-relation')]:[]),
        m('p',house,'housing-summary'),
        m('div',null,'household-devices',deviceLabels(p).map(label=>m('span',null,'household-device',[iconNode(label),m('span',label)]))),
        ...support.map(s=>m('p',s,'family-support'))
      ]),housingPreview(p)
    ]),m('p',role,'role-focus')];
  }
  function pairedRows(x) {
    const rows=x.rows.filter(r=>r.A!==r.B),programmes=rows.filter(r=>['洗衣','烘干'].includes(r.label));
    if(programmes.length===2&&programmes[0].delta===programmes[1].delta&&programmes.every(r=>!/[（]/.test(r.A+r.B))){
      const a=programmes[0],b=programmes[1];
      return [{label:'洗烘运行',A:a.A.split('–')[0]+'–'+b.A.split('–').at(-1),B:a.B.split('–')[0]+'–'+b.B.split('–').at(-1)},...rows.filter(r=>!programmes.includes(r))];
    }
    return rows;
  }
  function sideBySide(rows,cls='') {
    return m('div',null,`ab-comparison row-count-${rows.length} ${cls}`,[...['A','B'].map(side=>
      m('section',null,'compare-side side-'+side,[
        m('h4',null,'compare-label',[m('b',side),m('span',side==='A'?'原安排':'调整后')]),
        ...rows.map(r=>m('div',null,'compare-row',[
          ...(r.label?[m('p',r.label.replace(/^调整 · /,'本次调整 · '),'compare-context')]:[]),
          m('p',r[side],'compare-value')
        ]))
      ],{'aria-label':'方案'+side}))
    ]);
  }
  function daySummary(c,g){
    const x=dailyACModel(c,g);
    return x.same?`全天温控：A、B均开启${durationLabel(x.A.minutes)}。下面只比较本次调整时段。`:
      `全天温控：A开启${durationLabel(x.A.minutes)}，B开启${durationLabel(x.B.minutes)}${x.A.minutes===x.B.minutes?'，开启时段不同':''}。`;
  }
  function changesModel(c,p) {
    const all=compactDeviceModels(c,p),primary=all.filter(x=>x.expandedByDefault),rest=all.filter(x=>!x.expandedByDefault);
    const nodes=primary.map(x=>{
      const rows=pairedRows(x),failures=x.impacts.filter(t=>/未取出|未运行|未执行|未充到|距目标少|行程电量不足|升用水低于/.test(t));
      const titleParts=x.g.title.split(' · '),name=titleParts.shift(),location=titleParts.join(' · ');
      return m('article',null,'device-comparison',[
        m('header',null,'device-heading',[
          m('span',null,'device-symbol',[iconNode(name)]),
          m('h3',name,'device-title'),...(location?[m('span',` · ${location}`,'device-location')]:[])
        ]),
        m('p',null,'family-requirement',[m('span','家庭要求','inline-label'),m('span',x.needs.join(' '))]),
        ...(x.g.d.types.includes('ac')?[m('p',daySummary(c,x.g),'day-context')]:[]),
        ...(rows.length?[sideBySide(rows)]:[m('p','A、B运行指令相同；以下影响来自其他设备的联合调整。','no-direct-change')]),
        m('p',null,'life-effect'+(x.issue?' has-service-issue':''),[m('strong','生活影响'),m('span',(failures.length?failures:x.impacts).join(' '))])
      ],{'data-asset-id':x.g.d.asset_id});
    });
    if(!primary.length)nodes.push(m('p','这一天A、B安排相同。请按给定家庭判断是否接受。','no-direct-change'));
    if(rest.length)nodes.push(m('p',`其余${rest.length}项设备安排未变。`,'unchanged-note'));
    return nodes;
  }
  function requestModel(){return [];}

  // Convert inherited evidence disclosures to ordinary sections: there is no
  // second set of arrows behind the one complete-information entry.
  function evidenceNode(n){
    const out={...n,children:(n.children||[]).map(evidenceNode)};
    if(out.attrs){out.attrs={...out.attrs};delete out.attrs['data-detail-id'];}
    if(n.tag==='details'){out.tag='section';out.cls='evidence-subsection';}
    if(n.tag==='summary'){out.tag='h4';out.cls='evidence-subheading';}
    return out;
  }
  function fullScheduleNodes(c,p){
    return [m('p','本题原始安排，包含跨夜和后续任务。运行及完成情况见“主要影响”。','section-note'),
      ...p.devices.map(d=>m('section',null,'plan-block',[
        m('h3',asset(p,d.asset_id)),m('div',null,'plan-columns',['A','B'].map(side=>{
          const events=Object.values(c.plans[side]).flat().filter(x=>x.asset_id===d.asset_id&&x.end_min>c.window_min[0]).sort((a,b)=>a.start_min-b.start_min||a.end_min-b.end_min);
          return m('div',null,'',[m('h4',side==='A'?'原安排A':'提议B'),...(events.length?events.map(x=>m('p',command(x,p))):[m('p','此范围内无安排。')])]);
        }))
      ]))];
  }
  function completeInformation(c,p){
    const h=p.display_housing;
    const sections=[
      m('section',null,'evidence-section',[
        m('h3','家庭、住房与剖面图'),...familyLines(c,p).map(s=>m('p',s)),
        m('p',`已配设备：${deviceLabels(p).join('、')}。`),
        m('p',`本户建筑面积${num(p.household_area_m2,1)}㎡；整套模型可用面积${num(h.usable_total_area_m2,1)}㎡；${h.stock_reference_features?.elevator==='present'?'有电梯':h.stock_reference_features?.elevator==='absent'?'无电梯':'电梯信息未提供'}。`),housePicture(p)
      ]),
      m('section',null,'evidence-section',[
        m('h3','各设备全天安排与计算明细'),...compactDeviceModels(c,p).map(x=>m('section',null,'evidence-device',[
          m('h4',x.g.title),m('p',`家庭要求：${x.needs.join(' ')}`),
          ...(x.g.d.types.includes('ac')?[evidenceNode(acDayContext(c,x.g))]:[]),pairLines(x.g.A,x.g.B),
          ...x.g.impacts.map(t=>m('p',t)),
          m('p',`当日用电：A ${num(x.g.energy.A,3)}；B ${num(x.g.energy.B,3)}度。`),
          comparisonTable(financialRows(c,x.g)),...feeDetails(c,x.g).map(evidenceNode)
        ]))
      ]),
      m('section',null,'evidence-section',[
        m('h3','整体用电、室温与计费依据'),
        m('p',`当日全屋用电：A ${num(c.impact.energy_changes.primary.facility_A_kWh,3)}；B ${num(c.impact.energy_changes.primary.facility_B_kWh,3)}度。`),
        ...overallServiceNodes(c),...temperatureEffect(c,p).lines.map(t=>m('p',t)),
        ...feeDetails(c).map(evidenceNode),...detailedRequestModel(c),
        m('p','VPP补偿未设定，未从电费中扣减。VPP是否达标是客观结果，是否接受由填写者按家庭角色判断。')
      ]),
      m('section',null,'evidence-section',[m('h3','完整A/B排程'),m('div',null,'',fullScheduleNodes(c,p),{id:'plans'})])
    ];
    return m('details',null,'complete-information',[
      m('summary',null,'complete-information-entry',[
        m('span',null,'',[m('strong','查看完整资料'),m('small','家庭与剖面图、全天排程、电量及计费依据')]),m('span',null,'information-action',[],{'aria-hidden':'true'})
      ]),m('div',null,'complete-information-body',sections.map(evidenceNode))
    ],{id:'plans-details','data-detail-id':'full-schedule'});
  }
  function impactModel(c,p) {
    const fees=wholeMoney(c,'observation');
    const cost=m('section',null,'overall-cost',[
      m('div',null,'overall-cost-heading',[m('h3','全屋电费'),m('strong',fees.delta===0?'费用相同':`B比A${moneyDifference(fees.delta)}`,'money-delta')]),
      sideBySide([{label:'',A:yuan(fees.A),B:yuan(fees.B)}],'money-comparison'),
      m('p',`含后续恢复，计至${c.pricing.observation_end.replace('T',' ')}；VPP补偿未设定，未计入。`,'cost-scope')
    ]);
    const vpp=m('section',null,'overall-vpp',[m('h3','电网响应（VPP）'),...c.VPP_results.map(result=>{
      const req=c.VPP_requests.find(r=>r.event_id===result.event_id);
      return m('div',null,'vpp-event',[
        m('p',`${span(req)}，要求${req.direction==='up'?'增加':'降低'}${num(req.target_kw)}kW；${time(req.notification_min)}通知。`,'vpp-request-line'),
        m('p',null,'vpp-outcome',[m('span',`实际${result.delta_kw>=0?'增加':'降低'}${num(Math.abs(result.delta_kw),2)}kW`),m('strong',result.target_met?'达标':'未达标')])
      ]);
    })]);
    const warnings=[];
    if(c.pricing.known_service_deficit||c.pricing.source_constraint_flags.length)warnings.push(m('p','存在未完成服务或约束冲突；少支出不代表同等服务更便宜。','cost-warning'));
    if(c.pricing.recovery.status==='not_restored_within_horizon')warnings.push(m('p','观察期结束仍未恢复，之后的费用未验证。','cost-warning'));
    return [cost,vpp,...warnings,completeInformation(c,p)];
  }
