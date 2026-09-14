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
    const c=view.schedule_chart;if(!c){for(const row of view.rows||[])root.append(n('p',`${row.device}：调整前 ${row.original}；调整后 ${row.proposal}`));return;}
    const context=n('div',undefined,'schedule-context');
    const contextItems=[['错峰',`${clock(c.event_start_h)}—${clock(c.event_end_h)}`],['比较至',c.end_label]];if(Number.isFinite(c.notification_h))contextItems.unshift(['通知',clock(c.notification_h)]);
    for(const [label,value] of contextItems){const item=n('span');item.append(document.createTextNode(label+' '),n('strong',value));context.append(item);}root.append(context);
    const board=n('div',undefined,'schedule-board'),scroll=n('div',undefined,'schedule-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','完整电器时间轴：每个电器上方调整前，下方调整后');scroll.classList.add('fit-timeline');
    const canvas=n('div',undefined,'shared-schedule'),axis=n('div',undefined,'shared-axis');axis.append(n('span','电器 / 时间','schedule-axis-label'));const scale=n('div',undefined,'time-axis');
    for(const h of ticks(c)){const tick=n('span',clock(h),'tick');tick.style.left=pct(h,c)+'%';if(h===c.start_h)tick.classList.add('first');if(h===c.end_h)tick.classList.add('last');scale.append(tick);}axis.append(scale);canvas.append(axis);
    const detail=n('p','点选运行条，查看具体时间与设定。','schedule-detail');detail.setAttribute('aria-live','polite');
    function show(label,device){detail.textContent=label;for(const row of canvas.querySelectorAll('.schedule-row'))row.classList.toggle('highlighted',row.dataset.device===device);}
    for(const row of c.rows){
      const device=deviceIds[row.device]||'none',group=n('section',undefined,'schedule-group device-pair');group.dataset.device=device;
      const heading=n('h3'),name=n('strong',undefined,'device-pair-name');name.append(icon(device),document.createTextNode(row.device));heading.append(name);group.append(heading);
      for(const side of ['original','proposal']){
        const line=n('div',undefined,'schedule-row device-'+device);line.dataset.device=device;line.dataset.side=side;
        const label=n('div',undefined,'schedule-device');label.append(n('strong',side==='original'?'调整前':'调整后'));
        const track=n('div',undefined,'schedule-track');decoration(track,c);line.append(label,track);
        let count=0;for(const span of row[side]||[]){const start=Math.max(c.start_h,span.start_h),end=Math.min(c.end_h,span.end_h);if(end<=start)continue;count++;
          const text=`${side==='original'?'调整前':'调整后'} · ${row.device} · ${span.description}`,bar=n('button',undefined,'schedule-bar '+side);bar.type='button';bar.style.left=pct(start,c)+'%';bar.style.width=(pct(end,c)-pct(start,c))+'%';if((end-start)/(c.end_h-c.start_h)<.07)bar.classList.add('short-bar');bar.append(n('span',span.label));bar.title=text;bar.setAttribute('aria-label',text);bar.onfocus=bar.onclick=()=>show(text,device);track.append(bar);
        }
        if(!count)track.append(n('span',row.active?'未运行':'本情境不使用','schedule-empty'));group.append(line);
      }
      canvas.append(group);
    }
    scroll.append(canvas);board.append(scroll,detail);
    const zoom=n('div',undefined,'timeline-zoom'),fit=n('button','完整时段'),expand=n('button','放大查看');
    for(const b of [fit,expand])b.type='button';
    function setZoom(large){
      scroll.classList.toggle('fit-timeline',!large);fit.setAttribute('aria-pressed',String(!large));expand.setAttribute('aria-pressed',String(large));
      scroll.setAttribute('aria-label',large?'电器时间轴已放大，可左右滑动查看当日与次日':'完整电器时间轴：每个电器上方调整前，下方调整后');
      requestAnimationFrame(()=>{
        if(!large){scroll.scrollLeft=0;return;}
        const track=canvas.querySelector('.schedule-track');if(!track)return;
        const middle=(c.event_start_h+c.event_end_h)/2;
        const x=track.getBoundingClientRect().left-scroll.getBoundingClientRect().left+scroll.scrollLeft+pct(middle,c)/100*track.clientWidth;
        const labelWidth=canvas.querySelector('.schedule-device')?.offsetWidth||0;
        scroll.scrollLeft=Math.max(0,x-(labelWidth+scroll.clientWidth)/2);
      });
    }
    fit.onclick=()=>setZoom(false);expand.onclick=()=>setZoom(true);zoom.append(fit,expand);root.append(zoom,board);setZoom(false);
    const hint=n('p','放大后可左右滑动；点选运行条查看具体时间。','schedule-mobile-hint');root.append(hint);
    const legend=n('div',undefined,'schedule-legend');legend.append(n('span','浅黄色：错峰时段'+(Number.isFinite(c.notification_h)?' · 虚线：通知时刻':'')));root.append(legend);
    if(c.note)root.append(n('p',c.note,'hint schedule-note'));
  }
  function outcomes(root,view){
    const wrap=n('div',undefined,'outcomes-table-wrap'),table=n('table',undefined,'outcomes-table');
    const head=n('thead'),titles=n('tr');for(const title of ['比较项','调整前','调整后']){const th=n('th',title);th.scope='col';titles.append(th);}head.append(titles);table.append(head);
    const body=n('tbody');body.id=root.id==='outcome-cards'?'metrics':'preview-metrics';
    for(const m of view.metrics||[]){const row=n('tr',undefined,'outcome-metric');const label=n('th',m.label);label.scope='row';row.append(label);for(const side of ['original','proposal']){const cell=n('td'),parts=/^(-?\d+(?:\.\d+)?) (.+)$/.exec(m[side]);if(parts)cell.append(n('strong',parts[1]),n('small',parts[2],'metric-unit'));else cell.textContent=m[side];row.append(cell);}body.append(row);}
    for(const r of view.service_rows||[]){
      const row=n('tr',undefined,'outcome-service'),label=n('th',r.device);label.scope='row';row.append(label);
      for(const side of ['original','proposal']){
        const cell=n('td');cell.append(n('p',r[side]));
        for(const period of r[side+'_water_periods']||[]){
          const text=[period.label,period.temperature,period.detail];
          if(period.below_target_periods?.length)text.push('低于目标：'+period.below_target_periods.map(t=>t.text).join('、'));
          cell.append(n('p',text.filter(Boolean).join('；'),'water-period'));
        }
        row.append(cell);
      }
      body.append(row);
    }
    table.append(body);wrap.append(table);root.append(wrap);
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
