"""Participant-visible charts derived from the paired execution, without scores."""
from evaluation_window import clock, window_for


def plan_chart(rows, scenario):
    end = window_for(scenario)['end_sim_h'] - 72
    rows=[{**row,'summary':change_summary(row)} for row in rows]
    return {'version': 'eb.plan_chart.v2', 'start_h': 0, 'end_h': end,
            'notification_h': scenario['decision_h'],
            'event_start_h': scenario['event']['trigger_h'],
            'event_end_h': scenario['event']['end_h'],
            'end_label': clock(end), 'rows': rows,
            'note': '色条表示模拟中实际生效的安排；空白表示没有对应运行记录。热水条表示温度设定，不表示持续耗电或实际出水温度。'}


def segments(spans, device, design_w):
    result=[]
    for start,end,value in spans:
        if device in ('ac','electric_water_heater'):
            label=f'{value:g}℃' + (' 待机' if device=='electric_water_heater' and value==40 else '')
            meaning='空调设定' if device=='ac' else '热水温度设定'
        else:
            key='ev' if device=='home_ev' else device
            label=f'{value*design_w[key]/1000:.3f} kW';meaning='运行功率'
        result.append({'start_h':round(start,6),'end_h':round(end,6),'label':label,
                       'description':f'{clock(start)}—{clock(end)} · {meaning} {label}'})
    return result


def thermal_chart(original,baseline,proposal,scenario):
    if not original['devices'].get('ac',{}).get('active'):return None
    end=window_for(scenario)['end_sim_h']-72
    periods=[('响应前',0,scenario['event']['trigger_h']),
             ('响应期间',scenario['event']['trigger_h'],scenario['event']['end_h']),
             ('响应结束后',scenario['event']['end_h'],end)]
    series={};summary=[]
    for side,run in [('original',baseline),('proposal',proposal)]:
        series[side]=[{'hour':round(r['end_h']-72,6),'c':round(r['c'],1)}
                      for r in run.get('temperature',[]) if 72<r['end_h']<=72+end+1e-7]
    if not all(series.values()):return None
    for label,start,stop in periods:
        row={'label':label,'time':f'{clock(start)}—{clock(stop)}'}
        for side in series:
            values=[r['c'] for r in series[side] if start<r['hour']<=stop+1e-7]
            row[side]=f'{min(values):.1f}—{max(values):.1f}℃' if values else '无记录'
        summary.append(row)
    return {'start_h':0,'end_h':end,'series':series,'periods':summary,
            'note':'同一居住区域的模拟室温，每10分钟一个记录，保留1位小数。它是室温，不是空调设定温度；请按您家的感受判断。'}


def change_summary(row):
    """Describe only observed schedule differences, with no quality judgement."""
    if not row['active']:return '本情境不使用。'
    if not row['changed']:return '两份安排的运行时间与设定相同。'
    a,b=row['original'],row['proposal']
    if len(a)==len(b)==1 and a[0]['label']==b[0]['label'] and abs((a[0]['end_h']-a[0]['start_h'])-(b[0]['end_h']-b[0]['start_h']))<1e-5:
        delta=round((b[0]['start_h']-a[0]['start_h'])*60)
        if delta:return f"开始时间 {clock(a[0]['start_h'])} → {clock(b[0]['start_h'])}，{'推迟' if delta>0 else '提前'} {abs(delta)} 分钟。"
    times=sorted({s[k] for s in a+b for k in ('start_h','end_h')});changes=[]
    def value(spans,h):return next((s['label'] for s in spans if s['start_h']<=h<s['end_h']),'未运行')
    for start,end in zip(times,times[1:]):
        before,after=value(a,(start+end)/2),value(b,(start+end)/2)
        if before==after:continue
        if changes and changes[-1][1]==start and changes[-1][2:]==[before,after]:changes[-1][1]=end
        else:changes.append([start,end,before,after])
    if not changes:return '存在小于当前显示精度的变化；请查看完整安排。'
    summary='；'.join(f'{clock(s)}—{clock(e)}：{a} → {b}' for s,e,a,b in changes[:2])
    return summary+('；另有'+str(len(changes)-2)+'段变化，见时间轴。' if len(changes)>2 else '。')
