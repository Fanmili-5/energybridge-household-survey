"""Service evidence from native task state and EP outputs; never household scores."""
from evaluation_window import clock


def water_outcomes(traces,horizon):
    from paired_ep import find
    draws=[]
    for device in ('Sinks_unit1','Showers_unit1','Baths_unit1'):
        flow=find(traces,'Water Use Equipment Total Mass Flow Rate',device,horizon=horizon,unit='kg/s')
        mixed=find(traces,'Water Use Equipment Mixed Water Temperature',device,horizon=horizon)
        target=find(traces,'Water Use Equipment Target Water Temperature',device,horizon=horizon)
        for f,m,t in zip(flow,mixed,target):
            if f['end_h']<=72 or f['value']<=1e-8:continue
            draws.append({'equipment':device,'start_h':f['start_h'],'end_h':f['end_h'],
                          'mixed_c':m['value'],'target_c':t['value'],'flow_kg_s':f['value']})
    return {'source':'EP mixed water at template demand points; not reported household shower habits',
            'demand_schedule':'shared research template','draws':draws,
            'mixed_min_c':min((r['mixed_c'] for r in draws),default=None),
            'mixed_max_c':max((r['mixed_c'] for r in draws),default=None),
            'target_min_c':min((r['target_c'] for r in draws),default=None),
            'target_max_c':max((r['target_c'] for r in draws),default=None),
            'below_target':any(r['mixed_c']<r['target_c']-.1 for r in draws)}


def task_outcomes(suite):
    results={}
    for device,app in suite._shiftable.items():
        if not app.present:continue
        record=app._days[3]
        results[device]={'completed':record.completed,'scheduled_sim_h':record.scheduled_abs_h,
                         'actual_start_sim_h':record.run_start_abs_h,
                         'completed_sim_h':record.run_start_abs_h+app.duration_h if record.completed else None,
                         'source':'native EB task record for evaluation day, including overnight continuation'}
    return results


def water_periods(water):
    """Per-fixture draw episodes; do not sum overlapping fixtures as elapsed time."""
    groups=[]
    names={'Sinks_unit1':'水槽','Showers_unit1':'淋浴','Baths_unit1':'浴缸'}
    for r in sorted(water['draws'],key=lambda r:(r['equipment'],r['start_h'])):
        if groups and groups[-1]['equipment']==r['equipment'] and abs(groups[-1]['end_h']-r['start_h'])<1e-6:
            g=groups[-1];g['end_h']=r['end_h'];g['rows'].append(r)
        else:groups.append({'equipment':r['equipment'],'start_h':r['start_h'],'end_h':r['end_h'],'rows':[r]})
    output=[]
    for g in sorted(groups,key=lambda g:(g['start_h'],g['equipment'])):
        rows=g['rows'];low=[]
        for r in rows:
            if r['mixed_c']>=r['target_c']-.1:continue
            if low and abs(low[-1][1]-r['start_h'])<1e-6:low[-1][1]=r['end_h']
            else:low.append([r['start_h'],r['end_h']])
        label=f"{names.get(g['equipment'],g['equipment'])} · {clock(g['start_h']-72)}—{clock(g['end_h']-72)}"
        temp=f"出水 {min(r['mixed_c'] for r in rows):.1f}—{max(r['mixed_c'] for r in rows):.1f}℃；目标 {min(r['target_c'] for r in rows):.1f}—{max(r['target_c'] for r in rows):.1f}℃"
        periods=[{'start_h':round(a-72,6),'end_h':round(b-72,6),'text':f'{clock(a-72)}—{clock(b-72)}（约{round((b-a)*60)}分钟）'} for a,b in low]
        output.append({'label':label,'temperature':temp,'below_target_periods':periods,
                       'detail':('低于目标超过0.1℃：'+'、'.join(p['text'] for p in periods)) if periods else '所记录用水时段未低于目标超过0.1℃。'})
    return output


def display_services(original,baseline,proposal):
    from proposal_contract import DEVICES
    rows=[]
    for device,record in original['devices'].items():
        if not record.get('active') or device=='ac':continue
        row={'device':DEVICES[device]}
        for label,run in [('original',baseline),('proposal',proposal)]:
            cutoff=run.get('evaluation_window',{}).get('end_label','24:00')
            if device=='home_ev':
                ev=run.get('ev_departure')
                if ev:
                    row[label]=f"{clock(ev['sim_h']-72)}离家前，模拟电量 {ev['soc']*100:.1f}%；研究目标 {ev['target_soc']*100:.1f}%（"+('达到' if ev['target_met'] else '未达到')+'）。电池与行驶耗电为研究参数。'
                else:row[label]='尚无离家前电量记录，不能判定充电是否满足需求'
            elif device=='electric_water_heater':
                water=run.get('water_outcome')
                if water and water['draws']:
                    row[label+'_water_periods']=water_periods(water)
                    row[label]=f"研究用水情境：混合出水 {water['mixed_min_c']:.1f}—{water['mixed_max_c']:.1f}℃，目标 {water['target_min_c']:.1f}—{water['target_max_c']:.1f}℃；"+('部分时段未达到目标。' if water['below_target'] else '所记录时段达到目标。')
                else:row[label]='没有可用的用水温度记录，不能判定热水需求已满足'
            else:
                task=run.get('task_outcomes',{}).get(device)
                if task:
                    row[label]=f"{clock(task['completed_sim_h']-72)} 已完成" if task['completed'] else f'截至{cutoff}尚未完成'
                else:
                    day=next((r for r in run.get('execution',{}).get('services',{}).get(device,[]) if r.get('day')==3),None)
                    row[label]=('截至'+cutoff+'已完成（EB执行记录）') if day and day['completed'] else '截至'+cutoff+'尚未完成'

        rows.append(row)
    return rows
