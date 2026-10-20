  function housingPreview(p){
    const drawing=housingDrawing(p,'preview');
    if(drawing.tag!=='svg')return drawing;
    const rooms=p.display_housing.rooms.filter(r=>Array.isArray(r.usable_rect_m));
    const own=rooms.filter(r=>(r.using_household_ids||[]).includes(p.household_id)),legend=own.length?own:rooms;
    return m('figure',null,'housing-preview',[
      m('div',null,'housing-preview-heading',[m('h3','房屋剖面示意'),m('span',p.display_housing.shared_household_count_design>1?'含合住空间':'独立居住')]),
      drawing,
      m('div',null,'housing-plan-key',[...(rooms.some(r=>roomUse(p,r)==='own')?[m('span','本户房间','plan-key own')]:[]),...(rooms.some(r=>roomUse(p,r)==='shared')?[m('span','共用空间','plan-key shared')]:[]),...(legend.length<rooms.length?[m('span','其他住户','plan-key other')]:[])]),
      ...(p.devices.some(d=>d.types.includes('ev')&&d.room_id.startsWith('external'))?[m('p',null,'housing-outdoor',[iconNode('电动车'),m('span','住宅外独立车位 · 电动车充电')])]:[])
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
        ...lines.filter(t=>t.startsWith('今天：')||t.startsWith('调整边界：')).map(t=>m('p',t,'daily-life')),
        m('div',null,'household-devices',deviceLabels(p).map(label=>m('span',null,'household-device',[iconNode(label),m('span',label)]))),
        ...support.map(s=>m('p',s,'family-support'))
      ]),housingPreview(p)
    ]),m('p',role,'role-focus')];
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
