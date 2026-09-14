"""Read-only presentation of native EB trajectories and EP meter outputs."""
from copy import deepcopy
from math import isclose
from evaluation_window import clock
from presentation import plan_chart, segments, thermal_chart
from proposal_contract import DEVICES
from native_support import upstream


def metrics(baseline, proposal, scenario):
    lo=scenario['event']['trigger_h']; hi=scenario['event']['end_h']
    def summarize(run):
        daily=sum(r['kwh'] for r in run['electricity'] if 0<r['end_h']<=run['horizon'])
        event=sum(r['kwh'] for r in run['electricity'] if lo<r['end_h']<=hi)
        temps=[r['c'] for r in run['temperature'] if lo<r['end_h']<=hi]
        if not temps: raise ValueError('Missing event temperature observations')
        price=run['native']['day_ahead_price_metrics']
        if not price.get('available') or price.get('price_unit')!='normalized TOU cost/kWh':
            raise ValueError('Missing native normalized tariff metrics')
        if not isclose(daily,price.get('priced_energy_kwh',float('nan')),rel_tol=0,abs_tol=1e-5):
            raise ValueError('Tariff and EnergyPlus energy cover different intervals')
        return {'daily_kwh':daily,'daily_cost_normalized':price['total_cost_eur'],'comparison_kwh':daily,
                'event_kwh':event,
                'event_mean_kw':event/(hi-lo),'event_temp_min_c':min(temps),'event_temp_max_c':max(temps)}
    if any(run['horizon']!=scenario['evaluation_window']['end_sim_h'] for run in (baseline,proposal)):
        raise ValueError('Native branches do not share the comparison cutoff')
    a,b=summarize(baseline),summarize(proposal)
    matched=baseline['idf_sha256']==proposal['idf_sha256'] and baseline['weather_sha256']==proposal['weather_sha256']
    if not matched: raise ValueError('Native branches have different physical inputs')
    if scenario.get('environment'):
        expected=scenario['environment']['environment_hash']
        for branch in (baseline,proposal):
            if branch.get('asset_binding',{}).get('simulation_environment',{}).get('environment_hash')!=expected:
                raise ValueError('Native branches do not share the frozen questionnaire environment')
    return {'status':'paired_energyplus_complete','original':a,'proposal':b,
            'cost_unit':'normalized TOU cost/kWh',
            'relative_cost_reduction':a['daily_cost_normalized']-b['daily_cost_normalized'],
            'event_reduction_kwh':a['event_kwh']-b['event_kwh'],
            'comparison_check':{'passed':True,'basis':'same_native_idf_weather_household_price_and_horizon'},
            'prefix_check':{'passed':None,'status':'not_applicable_native_independent_policies'},
            'comparison_window':scenario['evaluation_window'],
            'scope':'native no_dr vs agent; independent control from simulation start, not identical pre-event states'}


def display(original, baseline, proposal, scenario, prediction):
    def intervals(run, device):
        spans=[]
        key={'home_ev':'ev','electric_water_heater':'water_heater'}.get(device,device)
        for row in run['controls']:
            start=max(0,row['start_h']);end=min(run['horizon'],row['end_h'])
            if start>=end:continue
            if device=='ac':value=row['cooling_setpoint'] if row['hvac_available'] else None
            elif device=='electric_water_heater':value=row['actuators'].get(key)
            else:
                kw=row['native_device_power_kw'].get(key)
                value=None if kw is None else kw*1000/upstream()[0]._APPL_DESIGN_W[key]
            if value is None or device not in ('ac','electric_water_heater') and value<=1e-8:continue
            value=round(value,5)
            if spans and abs(spans[-1][1]-start)<1e-6 and spans[-1][2]==value:spans[-1][1]=end
            else:spans.append([start,end,value])
        return spans
    rows=[];charts=[]
    for device,record in original['devices'].items():
        a=intervals(baseline,device);b=intervals(proposal,device)
        chart={'device_id':device,'device':DEVICES[device],'active':True,'changed':a!=b,
               'original':segments(a,device,upstream()[0]._APPL_DESIGN_W),
               'proposal':segments(b,device,upstream()[0]._APPL_DESIGN_W)}
        charts.append(chart)
        def words(side):
            return '；'.join(x['description'] for x in chart[side]) or '本比较日无运行记录'
        rows.append({'device_id':device,'device':DEVICES[device],'original':words('original'),
                     'proposal':words('proposal'),'changed':a!=b,'change':'有调整' if a!=b else '不变'})
    timeline=[]
    from presentation import execution_explanation
    for day in proposal['native']['all_day_decisions']:
        for decision in day:
            if not 0<=decision['h']<proposal['horizon']:continue
            app=decision.get('actuator_application',{})
            lifecycle=decision.get('adaptive_decision_audit',{}).get('plan_lifecycle',{})
            fallback=any(s.get('status') in {'fallback','fallback_after_rejection'} for s in lifecycle.get('stages',{}).values())
            timeline.append({'time':clock(decision['h']),'trigger':'EB 复查',
                'observed_temperature':f"{decision['room_temp_c']:.1f}℃",
                'explanation':execution_explanation({'application':app,'controller':{'fallback_used':fallback}}),
                'explanation_source':'native_actuator_application'})
    thermal=thermal_chart(original,baseline,proposal,scenario)
    chart=plan_chart(charts,scenario)
    chart['note']='色条表示运行时段或设定值。空调色条上的温度是制冷设定，不是室温或供暖温度；供暖沿用 EB 研究设定。室温请看下方曲线。'
    execution_notice='方案未控制真实设备。电器时间轴展示原 EB 电器模型的运行安排；住宅用电量与室温来自 EP。'
    missing=proposal['asset_binding'].get('unbound_native_device_ports',[])
    if missing:
        execution_notice+='原住宅缺少部分电器动态接口，其调度变化不全部反映在住宅电表中。'
    from native_worker import native_plan_outcomes
    if any(x['fallback_used'] for x in native_plan_outcomes(proposal['native'])):
        execution_notice+='本轮含 EB 原生回退安排，请按展示结果评价。'
    return {'title':'日常对照与 EB 调整安排','context':scenario,'prediction':prediction,'rows':rows,
        'schedule_chart':chart,'temperature_chart':thermal,'has_changes':any(r['changed'] for r in rows),
        'baseline_source':'native_no_dr_random_routine','question':'您是否同意采用 EB 的这套调整安排？',
        'notice':f"两份安排均从当日00:00模拟至{scenario['evaluation_window']['end_label']}；次日运行也计入比较。",
        'assumptions':('；'.join(scenario['facts'][1:]) if scenario.get('environment') else '使用原 EB 天津住宅、天气与分时价格权重。')+'相对成本不是人民币金额。住宅未校准到您家。热水条表示设定温度，不证明出水满足需求。',
        'selection_reason':'请根据两份模拟安排和结果，代表家庭作出判断。没有模拟家庭替您预先决定是否接受。',
        'execution_notice':execution_notice,
        'timeline':timeline,'service_rows':service_rows(original,baseline,proposal),'comparison_metrics':[]}


def service_rows(original,baseline,proposal):
    from native_service_evidence import service_text
    rows=[]
    for device in original['devices']:
        if device=='ac':continue
        row={'device':DEVICES[device],'device_id':device}
        for side,run in [('original',baseline),('proposal',proposal)]:
            if device in ('washer','dishwasher','dryer'):
                task=run['task_outcomes'].get(device,{})
                row[side]='截至'+clock(run.get('horizon',24))+('已完成' if task.get('completed') else '未完成')
            else:row[side]=service_text(device,run)
        # Missing observations stay in the audit artifacts, not participant copy.
        if row['original'] is not None and row['proposal'] is not None:rows.append(row)
    return rows
