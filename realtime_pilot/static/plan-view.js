/* Rendering only: all evidence comes from the frozen participant_view. */
"use strict";
window.EBView=(()=>{
  const n=(tag,text,cls)=>{const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x;};
  function icon(device){
    const paths={ac:'M4 4h16v7H4z M7 7h10 M7 15v4 M12 14v7 M17 15v4',washer:'M5 3h14v18H5z M5 7h14 M8 5h1 M12 5h1 M16 14a4 4 0 1 1-8 0 4 4 0 0 1 8 0',dishwasher:'M5 3h14v18H5z M5 7h14 M8 5h1 M8 11v6 M12 11v6 M16 11v6',dryer:'M5 3h14v18H5z M5 7h14 M8 5h1 M16 14a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M10 14h4',electric_water_heater:'M7 3h10a2 2 0 0 1 2 2v12H5V5a2 2 0 0 1 2-2 M8 17v4 M16 17v4 M10 8h4 M12 6v4',home_ev:'M4 14l2-6h12l2 6v4H4z M7 18v3 M17 18v3 M7 15h1 M16 15h1 M9 4h6',none:'M6 6l12 12 M18 6 6 18'};
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('class','appliance-icon');svg.setAttribute('aria-hidden','true');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.5');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');
    const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',paths[device]||paths.none);svg.append(path);return svg;
  }
  const dayName=day=>day===0?'当天':day===1?'次日':`第${day+1}天`;
  const clock=(h,withDay=false)=>{const m=Math.round(h*60),day=Math.floor(m/1440),time=`${String(Math.floor(m%1440/60)).padStart(2,'0')}:${String(m%60).padStart(2,'0')}`;return (withDay||day?dayName(day)+' ':'')+time;};
  // All positions use elapsed hours, never hour-of-day modulo 24.
  function visibleSpans(spans,c){return (spans||[]).map(s=>({...s,start_h:Math.max(c.start_h,s.start_h),end_h:Math.min(c.end_h,s.end_h)})).filter(s=>s.end_h>s.start_h).sort((a,b)=>a.start_h-b.start_h||a.end_h-b.end_h);}
  function periods(spans,device,c){
    const out=[],thermal=['ac','electric_water_heater'].includes(device);
    for(const s of visibleSpans(spans,c)){
      const label=thermal?s.label:device==='home_ev'?'充电':'运行',previous=out.at(-1);
      // A power change does not start a new appliance task; temperature changes do.
      if(previous&&Math.abs(previous.end_h-s.start_h)<1e-5&&previous.label===label)previous.end_h=s.end_h;
      else out.push({...s,label});
    }
    return out;
  }
  // Run endpoints ignore internal setpoint/power changes, but never bridge an idle gap.
  function runEndpoints(spans,c){
    const runs=[];
    for(const s of visibleSpans(spans,c)){
      const previous=runs.at(-1);
      if(previous&&s.start_h<=previous.end_h+1e-5)previous.end_h=Math.max(previous.end_h,s.end_h);
      else runs.push({start_h:s.start_h,end_h:s.end_h});
    }
    return runs.flatMap(r=>[r.start_h,r.end_h]);
  }
  // Stagger annotations, never the bars: the two schedules stay on two rows.
  function labelLayout(items,width){
    const lanes=[];
    return items.map(item=>{
      const left=Math.max(0,Math.min(width-item.width,item.x-item.width/2)),right=left+item.width;
      let lane=lanes.findIndex(edge=>edge+6<=left);if(lane<0)lane=lanes.length;lanes[lane]=right;
      return {...item,left,lane};
    });
  }
  const observers=new WeakMap();
  const pct=(h,c)=>100*(h-c.start_h)/(c.end_h-c.start_h);
  const ticks=c=>{
    const step=Math.max(4,Math.ceil((c.end_h-c.start_h)/10)*2),out=[c.start_h,c.end_h];
    for(let h=Math.ceil(c.start_h/24)*24;h<c.end_h;h+=24)if(h>c.start_h)out.push(h);
    for(let h=Math.ceil(c.start_h/step)*step;h<c.end_h;h+=step)if(out.every(v=>Math.abs(v-h)>=step*.7))out.push(h);
    return out.sort((a,b)=>a-b);
  };
  function days(c){const out=[];for(let d=Math.floor(c.start_h/24);d*24<c.end_h;d++)out.push({day:d,start:Math.max(c.start_h,d*24),end:Math.min(c.end_h,(d+1)*24)});return out;}
  function accountingBands(c){const w=c.statistics_window;if(!w)return [];return [{start:c.start_h,end:Math.min(c.end_h,w.start_sim_h)},{start:Math.max(c.start_h,w.end_sim_h),end:c.end_h}].filter(b=>b.end>b.start);}
  function decoration(track,c){
    for(const d of days(c)){const band=n('span',undefined,'day-background day-'+d.day);band.style.left=pct(d.start,c)+'%';band.style.width=(pct(d.end,c)-pct(d.start,c))+'%';band.setAttribute('aria-hidden','true');track.append(band);if(d.start>c.start_h){const boundary=n('span',undefined,'day-boundary');boundary.style.left=pct(d.start,c)+'%';boundary.setAttribute('aria-hidden','true');track.append(boundary);}}
    for(const h of ticks(c)){const grid=n('span',undefined,'grid-mark');grid.style.left=pct(h,c)+'%';grid.setAttribute('aria-hidden','true');track.append(grid);}
    const shade=n('span',undefined,'event-shade');shade.style.left=pct(c.event_start_h,c)+'%';shade.style.width=(pct(c.event_end_h,c)-pct(c.event_start_h,c))+'%';shade.setAttribute('aria-hidden','true');track.append(shade);
    for(const b of accountingBands(c)){const mask=n('span',undefined,'outside-statistics');mask.style.left=pct(b.start,c)+'%';mask.style.width=(pct(b.end,c)-pct(b.start,c))+'%';mask.setAttribute('aria-hidden','true');track.append(mask);}
    if(c.statistics_window){for(const h of [c.statistics_window.start_sim_h,c.statistics_window.end_sim_h]){const mark=n('span',undefined,'statistics-boundary');mark.style.left=pct(h,c)+'%';mark.setAttribute('aria-hidden','true');track.append(mark);}}
    if(Number.isFinite(c.notification_h)){const mark=n('span',undefined,'notification-mark');mark.style.left=pct(c.notification_h,c)+'%';mark.setAttribute('aria-hidden','true');track.append(mark);}
  }
  const deviceIds={'空调':'ac','洗衣机':'washer','洗碗机':'dishwasher','烘干机':'dryer','电热水器':'electric_water_heater','电动车充电':'home_ev','家用电动车充电':'home_ev'};
  function schedule(root,view){
    const c=view.schedule_chart;if(!c){for(const row of view.rows||[])root.append(n('p',`${row.device}：调整前 ${row.original}；调整后 ${row.proposal}`));return;}
    const context=n('div',undefined,'schedule-context');
    const contextItems=[['错峰',`${clock(c.event_start_h)}—${clock(c.event_end_h)}`],['展示时段',`${clock(c.start_h,true)}—${clock(c.end_h,true)}`]];if(Number.isFinite(c.notification_h))contextItems.unshift(['通知',clock(c.notification_h)]);
    if(c.statistics_window)contextItems.push(['统计24小时',`${clock(c.statistics_window.start_sim_h,true)}—${clock(c.statistics_window.end_sim_h,true)}`]);
    for(const [label,value] of contextItems){const item=n('span');item.append(document.createTextNode(label+' '),n('strong',value));context.append(item);}root.append(context);
    const board=n('div',undefined,'schedule-board'),scroll=n('div',undefined,'schedule-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','完整电器时间轴：每个电器上方调整前，下方调整后');scroll.classList.add('fit-timeline');
    const canvas=n('div',undefined,'shared-schedule'),axis=n('div',undefined,'shared-axis');axis.append(n('span','时间','schedule-axis-label'));const scale=n('div',undefined,'time-axis'),dayScale=n('div',undefined,'day-axis');for(const d of days(c)){const band=n('span',dayName(d.day),'day-label day-'+d.day);band.style.left=pct(d.start,c)+'%';band.style.width=(pct(d.end,c)-pct(d.start,c))+'%';dayScale.append(band);}scale.append(dayScale);
    for(const h of ticks(c)){const tick=n('span',clock(h).replace(/^(次日|第\d+天) /,''),'tick');tick.style.left=pct(h,c)+'%';if(h===c.start_h)tick.classList.add('first');if(h===c.end_h)tick.classList.add('last');scale.append(tick);}axis.append(scale);canvas.append(axis);
    const detail=n('p',undefined,'schedule-detail');detail.hidden=true;detail.setAttribute('aria-live','polite');
    const annotatedTracks=[];
    function show(label,device){detail.hidden=false;detail.textContent=label;for(const row of canvas.querySelectorAll('.schedule-row'))row.classList.toggle('highlighted',row.dataset.device===device);}
    for(const row of c.rows){
      const device=row.device_id||deviceIds[row.device]||'none',group=n('section',undefined,'schedule-group device-pair');group.dataset.device=device;
      const heading=n('h3'),name=n('strong',undefined,'device-pair-name');name.append(icon(device),document.createTextNode(row.device+(['ac','electric_water_heater'].includes(device)?' · 温度设定':'')));heading.append(name);group.append(heading);if(canvas.querySelector('.device-pair')){const ruler=axis.cloneNode(true);ruler.classList.add('device-ruler');group.append(ruler);}
      for(const side of ['original','proposal']){
        const line=n('div',undefined,'schedule-row device-'+device);line.dataset.device=device;line.dataset.side=side;
        const label=n('div',undefined,'schedule-device');label.append(n('strong',side==='original'?'调整前':'调整后'));
        const track=n('div',undefined,'schedule-track');decoration(track,c);line.append(label,track);
        const bars=[];let count=0;for(const span of visibleSpans(row[side],c)){const start=span.start_h,end=span.end_h;count++;
          const text=`${side==='original'?'调整前':'调整后'} · ${row.device} · ${clock(start,true)} 开始 → ${clock(end,true)} ${span.end_status==='observation_cutoff'?'仍有运行记录':'结束'} · ${span.label}`,bar=n('button',undefined,'schedule-bar '+side);bar.type='button';bar.dataset.startH=String(start);bar.dataset.endH=String(end);bar.style.left=pct(start,c)+'%';bar.style.width=(pct(end,c)-pct(start,c))+'%';if((end-start)/(c.end_h-c.start_h)<.07)bar.classList.add('short-bar');bar.append(n('span',['ac','electric_water_heater'].includes(device)?span.label:device==='home_ev'?'充电':'运行')); bar.title=text;bar.setAttribute('aria-label',text);bar.onfocus=bar.onclick=()=>show(text,device);track.append(bar);bars.push({bar,start,end});
        }
        const runs=periods(row[side],device,c),boundaries=runEndpoints(row[side],c);
        const annotations=boundaries.map(hour=>{
          const label=n('span',clock(hour),'endpoint-label'),stem=n('span',undefined,'endpoint-stem');
          if((row[side]||[]).some(s=>Math.abs(s.end_h-hour)<1e-5&&s.end_status==='observation_cutoff')){label.textContent+=' →';label.title='此时仍有运行记录';}
          label.dataset.hour=String(hour);label.setAttribute('aria-label',clock(hour,true));stem.setAttribute('aria-hidden','true');
          track.append(label,stem);return {hour,label,stem};
        });
        const settings=runs.map(run=>{const label=n('span',run.label,'endpoint-setting');track.append(label);return {run,label};});
        annotatedTracks.push({track,bars,annotations,settings});
        if(!count)track.append(n('span',row.active?'未运行':'本情境不使用','schedule-empty'));group.append(line);
      }
      canvas.append(group);
    }
    function layoutEndpoints(){
      for(const {track,bars,annotations,settings} of annotatedTracks){
        const width=track.clientWidth;if(!width)continue;
        const positions=labelLayout(annotations.map(a=>({x:pct(a.hour,c)/100*width,width:a.label.offsetWidth})),width);
        const tiers=Math.max(1,...positions.map(p=>p.lane+1)),barTop=tiers*22+10;
        positions.forEach((pos,i)=>{
          const a=annotations[i],top=(tiers-1-pos.lane)*22+4;
          a.label.style.left=pos.left+'px';a.label.style.top=top+'px';
          a.stem.style.left=Math.min(width-1,pos.x)+'px';a.stem.style.top=(top+18)+'px';a.stem.style.height=(barTop-top-18)+'px';
        });
        for(const b of bars)b.bar.style.top=barTop+'px';
        const captions=labelLayout(settings.map(a=>({x:pct((a.run.start_h+a.run.end_h)/2,c)/100*width,width:a.label.offsetWidth})),width);
        captions.forEach((pos,i)=>{settings[i].label.style.left=pos.left+'px';settings[i].label.style.top=(barTop+26+pos.lane*18)+'px';});
        const captionTiers=Math.max(1,...captions.map(p=>p.lane+1));track.style.height=(positions.length?barTop+26+captionTiers*18+10:62)+'px';
        track.parentElement.querySelector('.schedule-device').style.paddingTop=barTop+'px';
      }
    }
    scroll.append(canvas);board.append(scroll,detail);
    const zoom=n('div',undefined,'timeline-zoom'),fit=n('button','完整时段'),expand=n('button','放大查看');
    for(const b of [fit,expand])b.type='button';
    function setZoom(large){
      scroll.classList.toggle('fit-timeline',!large);fit.setAttribute('aria-pressed',String(!large));expand.setAttribute('aria-pressed',String(large));
      scroll.setAttribute('aria-label',large?'电器时间轴已放大，可左右滑动查看当日与次日':'完整电器时间轴：每个电器上方调整前，下方调整后');
      requestAnimationFrame(()=>{
        layoutEndpoints();
        if(!large){scroll.scrollLeft=0;return;}
        const track=canvas.querySelector('.schedule-track');if(!track)return;
        const middle=(c.event_start_h+c.event_end_h)/2;
        const x=track.getBoundingClientRect().left-scroll.getBoundingClientRect().left+scroll.scrollLeft+pct(middle,c)/100*track.clientWidth;
        const labelWidth=canvas.querySelector('.schedule-device')?.offsetWidth||0;
        scroll.scrollLeft=Math.max(0,x-(labelWidth+scroll.clientWidth)/2);
      });
    }
    fit.onclick=()=>setZoom(false);expand.onclick=()=>setZoom(true);zoom.append(fit,expand);root.append(zoom,board);setZoom(false);let lastWidth=-1;const observer=new ResizeObserver(()=>{if(canvas.clientWidth===lastWidth)return;lastWidth=canvas.clientWidth;layoutEndpoints();});observer.observe(canvas);observers.set(root,observer);

    const legend=n('div',undefined,'schedule-legend');legend.append(n('span','浅黄色：错峰时段'+(c.statistics_window?' · 淡色区域不计入24小时电量与成本':'')+(Number.isFinite(c.notification_h)?' · 虚线：通知时刻':'')));root.append(legend);
  }
  function outcomes(root,view){
    if(view.statistics_label)root.append(n('p',view.statistics_label,'statistics-caption'));
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
  function render(root,view){observers.get(root)?.disconnect();root.replaceChildren();schedule(root,view);}
  return {render,outcomes,temperature,icon,timeline:{clock,ticks,days,visibleSpans,periods,runEndpoints,labelLayout,accountingBands}};
})();
