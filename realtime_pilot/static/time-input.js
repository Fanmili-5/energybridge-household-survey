/* Time controls keep the questionnaire's canonical option values unchanged. */
window.EBTime = (() => {
  const names={ac:'空调',washer:'洗衣机',dishwasher:'洗碗机',dryer:'烘干机',electric_water_heater:'电热水器',home_ev:'电动汽车充电'};
  const glyphs={ac:'❄',washer:'◉',dishwasher:'▤',dryer:'≈',electric_water_heater:'♨',home_ev:'ϟ'};
  const starts={morning:8,noon:12,evening:18,night:20,late:22};
  const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const icon=device=>EBView.icon(device);
  function clock(h){const m=Math.round(h*60);return `${m>1440?'次日 ':''}${String(Math.floor(m/60)%24).padStart(2,'0')}:${String(m%60).padStart(2,'0')}`.replace(/^00:00$/,h===24?'24:00':'00:00');}
  function answerHint(q){
    if(q.id==='H_ac_temp')return '填写空调遥控器上通常设置的温度。';
    if(q.id==='P_AC_CHANGE')return '填写最多能接受的室温变化幅度，例如 0.5℃；不是空调设定温度。';
    if(q.id==='P_AC_RANGE')return '填写希望保持的室内温度范围，不是室外天气的最低、最高温度。';
    if(q.id==='P_EV_TARGET')return '这是离家时希望达到的电量百分比。';
    if(q.id==='P_EV_RESERVE')return '这是为临时出行希望保留的电量，与离家时的目标电量分别填写。';
    if(['washer','dishwasher','dryer'].includes(q.device)){
      if(q.id.startsWith('H_'))return '按平时习惯，通常几点启动这项任务。';
      if(q.id.startsWith('T_'))return '填写从启动到完成需要的分钟数，不是结束时刻。';
      if(q.id.startsWith('E_'))return '允许调整时，最早从几点开始也可以；可以早于平时的启动时间。';
      if(q.id.startsWith('D_'))return '填写最晚必须完成的时刻，不是最晚开始的时刻。';
    }
    return '';
  }
  function mount(q,select,row){
    if(!q.device)return;
    if(q.group==='stated_preference'&&!['P_HOT_WATER','P_AC_CHANGE'].includes(q.id))return;
    if(q.id==='H_ac'){select.classList.add('ac-schedule-select');return;}
    if(q.options.some(o=>o.value==='off'))return; // Historical snapshots retain their original form.
    const empty=select.querySelector('option[value=""]');if(empty)empty.textContent=q.id==='H_ac_temp'?'尚未选择温度':q.id==='P_AC_CHANGE'?'尚未选择变化幅度':q.id.startsWith('T_')?'尚未选择时长':'尚未选择时间';
    const wrap=node('div',undefined,'time-control'),top=node('div',undefined,'time-readout');
    const output=node('output','尚未选择');output.htmlFor=select.id+'_slider';
    output.className='sr-only';top.append(output);wrap.append(top);
    const range=node('input');range.type='range';range.min=0;range.max=q.options.length-1;range.step=1;range.value=0;
    range.id=select.id+'_slider';range.setAttribute('aria-label',q.prompt);range.setAttribute('aria-describedby',select.id+'_slider_hint');
    const hint=node('span','未操作的滑块不会作为答案提交。','sr-only');hint.id=select.id+'_slider_hint';
    const marks=node('div',undefined,'time-marks');
    const indexes=q.options.length<=5?q.options.map((_,i)=>i):[0,Math.round((q.options.length-1)/2),q.options.length-1];
    for(const i of indexes){const label=q.options[i].label.match(/\d{2}:\d{2}/)?.[0]||q.options[i].label;const b=node('button',label);b.type='button';b.style.left=`${i/(q.options.length-1)*100}%`;if(i===0)b.className='first';if(i===q.options.length-1)b.className='last';b.onclick=()=>{select.value=JSON.stringify(q.options[i].value);select.dispatchEvent(new Event('change',{bubbles:true}));};marks.append(b);}
    range.oninput=()=>{select.value=JSON.stringify(q.options[Number(range.value)].value);select.dispatchEvent(new Event('change',{bubbles:true}));};
    select._timeSync=()=>{const i=q.options.findIndex(o=>JSON.stringify(o.value)===select.value);wrap.classList.toggle('unanswered',i<0);output.textContent=i<0?'尚未选择':q.options[i].label;if(i>=0)range.value=i;range.setAttribute('aria-valuetext',i<0?'尚未选择':q.options[i].label);};
    wrap.append(range,hint,marks);row.insertBefore(wrap,select);top.append(select);select.classList.add('precise-select');select._timeSync();
  }
  function temperatureRange(q,row,prefix,required){
    const answer=node('input');answer.type='hidden';answer.id=prefix+q.id;answer.dataset.temperatureAnswer='true';row.append(answer);
    const group=node('div',undefined,'temperature-range-input');group.setAttribute('role','group');group.setAttribute('aria-label',q.prompt);
    const fields=[];
    for(const [key,title] of [['low','希望不低于'],['high','希望不高于']]){
      const cell=node('div',undefined,'temperature-endpoint'),label=node('label',title+'（℃）');
      const number=node('input');number.type='number';number.min=q.minimum;number.max=q.maximum;number.step=q.step;number.required=required;number.id=answer.id+'_'+key;number.placeholder='请选择';label.htmlFor=number.id;
      const slider=node('input');slider.type='range';slider.min=q.minimum;slider.max=q.maximum;slider.step=q.step;slider.value=(q.minimum+q.maximum)/2;slider.setAttribute('aria-label',title+'（℃）');
      cell.append(label,number,slider);group.append(cell);fields.push({number,slider,cell});
      slider.oninput=()=>{number.value=slider.value;commit();};number.oninput=()=>commit();
    }
    function visuals(){for(const f of fields){f.cell.classList.toggle('unanswered',f.number.value==='');if(f.number.value!=='')f.slider.value=f.number.value;f.slider.setAttribute('aria-valuetext',f.number.value===''?'尚未选择':f.number.value+'℃');}}
    function commit(){
      const [a,b]=fields.map(f=>f.number);b.setCustomValidity(a.value!==''&&b.value!==''&&Number(a.value)>=Number(b.value)?'最高温度须高于最低温度':'');
      answer.value=a.value!==''&&b.value!==''?JSON.stringify(a.value+'_'+b.value):'';visuals();answer.dispatchEvent(new Event('change',{bubbles:true}));
    }
    answer._temperatureSync=()=>{let values=[];try{values=JSON.parse(answer.value||'null')?.split('_')||[];}catch{}fields.forEach((f,i)=>{f.number.value=values[i]??'';});fields[1].number.setCustomValidity('');visuals();};
    row.append(group,node('small','拖动或输入温度，精确到 0.1℃。'));answer._temperatureSync();
  }
  function timeline(container,{start,end,earliest,deadline,text}){
    container.replaceChildren();if(start==null||end==null){container.append(node('p',text||'选好时间后，这里会画出您的日常安排。','hint'));return;}
    const horizon=Math.max(end,deadline||24)>24?48:24;
    const labels=node('div',undefined,'habit-axis');for(const h of horizon===48?[0,12,24,36,48]:[0,6,12,18,24])labels.append(node('span',h===48?'次日 24:00':h===24&&horizon===48?'次日 00:00':clock(h)));
    const track=node('div',undefined,'habit-track');track.setAttribute('role','img');track.setAttribute('aria-label',text);
    function bar(a,b,cls){const e=node('span',undefined,cls);e.style.left=`${a/horizon*100}%`;e.style.width=`${Math.max(0,b-a)/horizon*100}%`;track.append(e);}
    if(earliest!=null&&deadline!=null)bar(earliest,deadline,'habit-window');bar(start,end,'habit-run');
    container.append(labels,track,node('p',text,'habit-caption'));
  }
  function group(container,questions,render,deviceContainer=container){
    const cards={};
    for(const q of questions.filter(q=>!['attitude','stated_preference'].includes(q.group)&&!q.device))render(q,q.id==='B05'?deviceContainer:container);
    const empty=node('div','选好上面的电器，这里就会展开对应的时间安排。','device-empty');deviceContainer.append(node('p','时间每 10 分钟一档；时长以分钟填写，温度可选到 0.1℃。','hint'),empty);
    const list=node('div',undefined,'device-cards');deviceContainer.append(list);
    // Display a task's normal start/duration first, then the allowed start/end window.
    const rank=q=>q.id.startsWith('H_')?0:q.id.startsWith('T_')?1:q.id.startsWith('E_')?2:3;
    const ordered=questions.filter(q=>q.device).sort((a,b)=>rank(a)-rank(b));
    for(const q of ordered){
      if(!cards[q.device]){const card=node('article',undefined,'device-input-card');card.dataset.deviceCard=q.device;
        const header=node('div',undefined,'device-card-heading');header.append(icon(q.device),node('h3',names[q.device]),node('span','日常安排','device-card-tag'));
        const fields=node('div',undefined,'device-fields'),preview=node('div',undefined,'habit-preview');preview.id='habit_'+q.device;
        card.append(header,fields,preview);list.append(card);cards[q.device]=fields;
      }render(q,cards[q.device]);
    }
  }
  function sync(){
    document.querySelectorAll('#profile-form select').forEach(s=>s._timeSync?.());
    const read=id=>{const s=document.getElementById('p_'+id);return s?.value?JSON.parse(s.value):null;};
    for(const card of document.querySelectorAll('[data-device-card]')){
      card.hidden=![...card.querySelectorAll('[data-question-id]')].some(r=>!r.hidden);
      const d=card.dataset.deviceCard,preview=document.getElementById('habit_'+d);let start,end,earliest,deadline,text;
      if(d==='ac'){const use=read('H_ac');let span={afternoon:[14,23],evening:[18,23],all_day:[0,24]}[use];if(use==='custom'&&read('H_ac_start')!=null&&read('H_ac_end')!=null){const a=Number(read('H_ac_start')),b=Number(read('H_ac_end'));span=[a,b+(b<a?24:0)];}if(span){[start,end]=span;text=`空调 ${clock(start)}—${clock(end)}${read('H_ac_temp')?' · '+read('H_ac_temp')+'℃':''}`;}}
      else{const v=read('H_'+d);start=v==null?null:starts[v]??Number(v);
        if(['washer','dishwasher','dryer'].includes(d)){
          const e=read('E_'+d),l=read('D_'+d),t=read('T_'+d);
          if(e!=null&&l!=null){earliest=Number(e);deadline=Number(l)+(Number(l)<earliest?24:0);if(start!=null&&Number(l)<earliest&&start<earliest)start+=24;}
          if(start!=null&&t!=null){end=start+Number(t);text=`通常 ${clock(start)}—${clock(end)} · ${Math.round(Number(t)*60)} 分钟`;if(deadline!=null)text+=`；允许调整范围 ${clock(earliest)}—${clock(deadline)}`;
            if(deadline!=null&&(start<earliest-1e-9||end>deadline+1e-9))text+='。当前常用安排不在允许范围内，请核对时间。';}
        }else{const last=read('D_'+d);if(start!=null&&last!=null){end=Number(last);const overnight=end<start;if(overnight)end+=24;text=`${d==='home_ev'?'接入充电':'加热'} ${clock(start)} → ${d==='home_ev'?'离家':'结束'} ${clock(end)}`;if(d==='electric_water_heater'&&(start===0||overnight||end<=start||end-start>8))text+='；真实安排可保存，当前原生模型暂不能生成此安排的模拟，请勿为生成而改填。';else if(end<=start)text+='；接入与离家时刻不能相同。';}}
      }
      timeline(preview,{start,end,earliest,deadline,text});
      if(earliest!=null&&deadline!=null&&end!=null)preview.append(node('small','浅色：允许调整的时间范围；深色：平时的运行时段。'));
    }
    const empty=document.querySelector('.device-empty');if(empty){const selected=[...document.getElementsByName('p_B05')].filter(x=>x.checked);empty.hidden=selected.some(x=>JSON.parse(x.value)!=='none');empty.textContent=selected.length?'您选择了以上都没有，可以继续填写下方的用电取舍。':'选好上面的电器，这里就会展开对应的时间安排。';}
  }
  function initial(root,original){
    root.replaceChildren(node('h3','您的原安排已保存'));
    for(const [d,r] of Object.entries(original.devices)){if(!r.active)continue;const card=node('article',undefined,'initial-device');card.append(node('strong',`${glyphs[d]||'◉'}  ${names[d]}`));const chart=node('div');let start=d==='ac'?r.use_start_h:r.start_h,end=d==='ac'?r.use_end_h:start+r.duration_h;
      if(r.deadline_h<r.earliest_h&&start<r.earliest_h){start+=24;end+=24;}
      timeline(chart,{start,end,text:`${clock(start)}—${clock(end)}${d==='ac'?' · '+r.setpoint+'℃':''}`});card.append(chart);root.append(card);}
    root.append(node('p','下面是依据已提交答案生成的安排，正在计算调整方案。','hint'));
  }
  return {mount,group,sync,initial,icon,temperatureRange,answerHint};
})();
