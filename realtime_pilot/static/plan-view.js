/* Rendering only: all evidence comes from the frozen participant_view. */
"use strict";
window.EBView=(()=>{
  const n=(tag,text,cls)=>{const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x;};
  function icon(device){
    const paths={ac:'M4 4h16v7H4z M7 7h10 M7 15v4 M12 14v7 M17 15v4',washer:'M5 3h14v18H5z M5 7h14 M8 5h1 M12 5h1 M16 14a4 4 0 1 1-8 0 4 4 0 0 1 8 0',dishwasher:'M5 3h14v18H5z M5 7h14 M8 5h1 M8 11v6 M12 11v6 M16 11v6',dryer:'M5 3h14v18H5z M5 7h14 M8 5h1 M16 14a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M10 14h4',electric_water_heater:'M7 3h10a2 2 0 0 1 2 2v12H5V5a2 2 0 0 1 2-2 M8 17v4 M16 17v4 M10 8h4 M12 6v4',home_ev:'M4 14l2-6h12l2 6v4H4z M7 18v3 M17 18v3 M7 15h1 M16 15h1 M9 4h6',none:'M6 6l12 12 M18 6 6 18'};
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('class','appliance-icon');svg.setAttribute('aria-hidden','true');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.5');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');
    const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',paths[device]||paths.none);svg.append(path);return svg;
  }
  const clock=h=>{let m=Math.round(h*60);const day=Math.floor(m/1440);m%=1440;return h===24?'24:00':`${day?'次日':''}${String(Math.floor(m/60)).padStart(2,'0')}:${String(m%60).padStart(2,'0')}`;};
  const pct=(h,c)=>100*(h-c.start_h)/(c.end_h-c.start_h);
  const ticks=c=>{const out=[],step=Math.max(4,Math.ceil((c.end_h-c.start_h)/10)*2);for(let h=c.start_h;h<c.end_h;h+=step)out.push(h);if(out.length>1&&c.end_h-out[out.length-1]<step*.75)out.pop();out.push(c.end_h);return out;};
  function decoration(track,c){
    for(const h of ticks(c)){const grid=n('span',undefined,'grid-mark');grid.style.left=pct(h,c)+'%';grid.setAttribute('aria-hidden','true');track.append(grid);}
    const shade=n('span',undefined,'event-shade');shade.style.left=pct(c.event_start_h,c)+'%';shade.style.width=(pct(c.event_end_h,c)-pct(c.event_start_h,c))+'%';shade.setAttribute('aria-hidden','true');track.append(shade);
    if(Number.isFinite(c.notification_h)){const mark=n('span',undefined,'notification-mark');mark.style.left=pct(c.notification_h,c)+'%';mark.setAttribute('aria-hidden','true');track.append(mark);}
  }
  const deviceIds={'空调':'ac','洗衣机':'washer','洗碗机':'dishwasher','烘干机':'dryer','电热水器':'electric_water_heater','电动车充电':'home_ev','家用电动车充电':'home_ev'};
  function schedule(root,view){
    const c=view.schedule_chart;if(!c){root.append(n('p','这条历史记录没有时间轴数据，请展开文字安排。','hint'));return;}
    const context=n('div',undefined,'schedule-context');
    const contextItems=[['错峰',`${clock(c.event_start_h)}—${clock(c.event_end_h)}`],['比较至',c.end_label]];if(Number.isFinite(c.notification_h))contextItems.unshift(['通知',clock(c.notification_h)]);
    for(const [label,value] of contextItems){const item=n('span');item.append(document.createTextNode(label+' '),n('strong',value));context.append(item);}root.append(context);
    const board=n('div',undefined,'schedule-board'),scroll=n('div',undefined,'schedule-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','完整用电时间轴：上方 DR 对照，下方 EB 调整；可左右滚动');
    const canvas=n('div',undefined,'shared-schedule'),axis=n('div',undefined,'shared-axis');axis.append(n('span','电器 / 时间','schedule-axis-label'));const scale=n('div',undefined,'time-axis');
    for(const h of ticks(c)){const tick=n('span',clock(h),'tick');tick.style.left=pct(h,c)+'%';if(h===c.start_h)tick.classList.add('first');if(h===c.end_h)tick.classList.add('last');scale.append(tick);}axis.append(scale);canvas.append(axis);
    const detail=n('p','点选运行条，查看具体时间与设定。','schedule-detail');detail.setAttribute('aria-live','polite');
    const picker=n('select');picker.setAttribute('aria-label','按电器与方案选择运行片段');picker.append(n('option','选择运行片段'));picker.options[0].value='';
    function show(label,device){detail.textContent=label;for(const row of canvas.querySelectorAll('.schedule-row'))row.classList.toggle('highlighted',row.dataset.device===device);}
    for(const side of ['original','proposal']){
      const group=n('section',undefined,'schedule-group '+side),heading=n('h3');heading.append(n('strong',side==='original'?'DR 对照':'EB 调整后'),n('span',side==='original'?'未经 EB 策略调整':'根据本次事件重新安排'));group.append(heading);
      for(const row of c.rows){
        const device=deviceIds[row.device]||'none',line=n('div',undefined,'schedule-row device-'+device);line.dataset.device=device;line.dataset.side=side;
        const label=n('div',undefined,'schedule-device');label.append(icon(device),n('span',row.device));const track=n('div',undefined,'schedule-track');decoration(track,c);line.append(label,track);
        let count=0;for(const span of row[side]||[]){const start=Math.max(c.start_h,span.start_h),end=Math.min(c.end_h,span.end_h);if(end<=start)continue;count++;
          const text=`${side==='original'?'DR 对照':'EB 调整后'} · ${row.device} · ${span.description}`,bar=n('button',undefined,'schedule-bar '+side);bar.type='button';bar.style.left=pct(start,c)+'%';bar.style.width=(pct(end,c)-pct(start,c))+'%';if((end-start)/(c.end_h-c.start_h)<.07)bar.classList.add('short-bar');bar.append(n('span',span.label));bar.title=text;bar.setAttribute('aria-label',text);bar.onfocus=bar.onclick=()=>show(text,device);track.append(bar);
          const option=n('option',text);option.value=text;option.dataset.device=device;picker.append(option);
        }
        if(!count)track.append(n('span',row.active?'没有运行记录':'本情境不使用','schedule-empty'));group.append(line);
      }
      canvas.append(group);
    }
    scroll.append(canvas);board.append(scroll,detail);root.append(board);
    requestAnimationFrame(()=>{
      if(!scroll.isConnected||scroll.scrollWidth<=scroll.clientWidth)return;
      const track=canvas.querySelector('.schedule-track');if(!track)return;
      const middle=(c.event_start_h+c.event_end_h)/2;
      const x=track.getBoundingClientRect().left-scroll.getBoundingClientRect().left+scroll.scrollLeft+pct(middle,c)/100*track.clientWidth;
      const labelWidth=canvas.querySelector('.schedule-device')?.offsetWidth||0;
      scroll.scrollLeft=Math.max(0,x-(labelWidth+scroll.clientWidth)/2);
    });
    const legend=n('div',undefined,'schedule-legend');legend.append(n('span','上下同一刻度 · 同一种颜色代表同一台电器'),n('span','浅黄色：错峰时段'+(Number.isFinite(c.notification_h)?' · 虚线：通知时刻':'')));root.append(legend);
    const changed=c.rows.filter(r=>r.changed);root.append(n('p',changed.length?'有调整：'+changed.map(r=>r.device).join('、')+'。':'本次两份安排相同。','schedule-change-note'));
    root.append(n('p',c.note,'hint'));const more=n('details',undefined,'supporting-detail schedule-help');more.append(n('summary','全部运行片段（文字列表）'),picker);picker.onchange=()=>show(picker.value||'点选运行条，查看具体时间与设定。',picker.selectedOptions[0].dataset.device);root.append(more);
  }
  function outcomes(root,view){
    const metrics=view.metrics||[];
    const selected=[metrics.find(m=>m.label==='比较期总费用'),metrics.find(m=>m.label.startsWith('比较期总用电')),metrics.find(m=>m.label==='响应时段用电量')].filter(Boolean);
    const grid=n('div',undefined,'outcome-grid');
    for(const m of selected){const card=n('article',undefined,'outcome-card');card.append(n('h3',m.label));for(const side of ['original','proposal']){const row=n('div',undefined,'metric-pair '+side);row.append(n('span',side==='original'?'原安排':'EB 调整'),n('strong',m[side]));card.append(row);}grid.append(card);}root.append(grid);
    if(selected.length)root.append(n('p','两份安排按相同时间范围比较。费用少不代表任务一定完成，请同时查看下面的使用结果。','hint'));
    const services=n('div',undefined,'service-grid compact-services');
    for(const r of view.service_rows||[]){
      const card=n('article',undefined,'service-card');card.append(n('h3',r.device));
      // Deduplicate only identical supplied text AND identical underlying water records.
      const same=r.original===r.proposal&&JSON.stringify(r.original_water_periods||[])===JSON.stringify(r.proposal_water_periods||[]);
      card.classList.toggle('service-identical',same);
      for(const side of same?['original']:['original','proposal']){
        const group=n('div',undefined,'service-side'),row=n('div',undefined,'service-pair');
        row.append(n('span',same?'两份安排一致':side==='original'?'原安排':'EB 调整'),n('p',r[side]));group.append(row);
        const periods=r[side+'_water_periods'];
        if(periods?.length){
          const low=periods.filter(p=>p.below_target_periods.length);
          if(low.length)group.append(n('p',`${low.length} 组研究用水记录中存在低于目标的时段。`,'water-summary'));
          const details=n('details',undefined,'water-detail');details.append(n('summary','查看用水温度与具体时段'),n('p','以下为研究模板记录；连续区间不代表一次洗澡的时长。','hint'));
          for(const period of periods){const item=n('div');item.append(n('strong',period.label),n('p',period.temperature),n('p',period.detail));if(period.below_target_periods.length)item.append(n('p','低于目标：'+period.below_target_periods.map(t=>t.text).join('、')));details.append(item);}group.append(details);
        }
        card.append(group);
      }
      services.append(card);
    }
    root.append(services);
  }
  const svgNode=(tag,attrs,text)=>{const x=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs||{}))x.setAttribute(k,String(v));if(text!==undefined)x.textContent=text;return x;};
  function temperature(root,view){
    const t=view.temperature_chart,c=view.schedule_chart;if(!t||!c)return;
    root.append(n('h3','模拟室温对比'));
    const values=[...t.series.original,...t.series.proposal].map(p=>p.c);let low=Math.floor(Math.min(...values)-.5),high=Math.ceil(Math.max(...values)+.5);if(high-low<2)high=low+2;
    const x=h=>50+(h-t.start_h)/(t.end_h-t.start_h)*770,y=v=>178-(v-low)/(high-low)*145;
    const svg=svgNode('svg',{viewBox:'0 0 850 220',role:'img','aria-label':'原安排和 EB 调整后的室温曲线；下方提供各时段温度范围'});svg.append(svgNode('title',{},'模拟室温对比'));
    svg.append(svgNode('rect',{x:x(c.event_start_h),y:25,width:x(c.event_end_h)-x(c.event_start_h),height:153,fill:'#fef0cf'}));
    for(let i=0;i<=4;i++){const v=low+(high-low)*i/4;svg.append(svgNode('line',{x1:50,x2:820,y1:y(v),y2:y(v),stroke:'#e0e7e9'}),svgNode('text',{x:42,y:y(v)+4,'text-anchor':'end',fill:'#5b6974','font-size':12},`${v.toFixed(1)}°`));}
    for(const h of ticks(c))svg.append(svgNode('text',{x:x(h),y:205,'text-anchor':h===c.start_h?'start':h===c.end_h?'end':'middle',fill:'#5b6974','font-size':12},clock(h)));
    for(const side of ['original','proposal'])svg.append(svgNode('polyline',{points:t.series[side].map(p=>`${x(p.hour)},${y(p.c)}`).join(' '),fill:'none',stroke:side==='original'?'#65788a':'#127968','stroke-width':side==='original'?2:2.5,'stroke-dasharray':side==='original'?'6 4':'none','vector-effect':'non-scaling-stroke'}));
    const wrap=n('div',undefined,'thermal-scroll');wrap.tabIndex=0;wrap.setAttribute('aria-label','室温曲线，可横向滚动');wrap.append(svg);
    const legend=n('div',undefined,'chart-legend');legend.append(n('span','┄ 原安排（虚线）'),n('span','━ EB 调整（实线）'),n('span','浅黄色区域：错峰时段'));
    const cards=n('div',undefined,'temperature-periods');for(const p of t.periods){const card=n('div');card.append(n('strong',p.label),n('small',p.time),n('p',`原安排 ${p.original}`),n('p',`EB 调整 ${p.proposal}`));cards.append(card);}root.append(cards);const more=n('section',undefined,'supporting-detail temperature-chart');more.append(wrap,legend,n('p',t.note,'hint'));root.append(more);
  }
  function render(root,view){root.replaceChildren();schedule(root,view);}
  return {render,outcomes,temperature,icon};
})();
