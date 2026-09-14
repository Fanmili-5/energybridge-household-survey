"""Read-only service observations. Never replace EB controls or score a household."""
from math import isfinite
from evaluation_window import clock

VERSION='eb.native_service_evidence.v3'


def evidence(clock_audit, physical, household, horizon=24, statistics_window=None):
    result={'version':VERSION, 'horizon_h':horizon}
    if statistics_window:result['statistics_window']=dict(statistics_window)
    def tasks_at(at):
        rows=[r for r in clock_audit.get('task_state_trace',[]) if r['start_h']<at-1e-8 and r['end_h']<=at+1e-8]
        return rows[-1].get('task_instances',[]) if rows and abs(rows[-1]['end_h']-at)<1e-6 else None
    result['task_instances_at_simulation_end']=tasks_at(horizon)
    if statistics_window:
        result['task_instances_at_statistics_end']=tasks_at(statistics_window['end_sim_h'])
    ev=household['appliances'].get('ev',{})
    if ev.get('present'):
        # Native EP callbacks start at the first zone boundary (00:10),
        # and may invoke a terminal callback at 24:00. Do not count its
        # prospective 24:00--24:10 state as today's final charging interval.
        rows=[r for r in clock_audit.get('ev_state_trace',[]) if 0<=r['start_h']<horizon-1e-8]
        complete=bool(rows) and rows[0]['start_h']<=rows[0]['end_h']-rows[0]['start_h']+1e-6 and abs(rows[-1]['end_h']-horizon)<1e-6
        complete=complete and all(abs(a['end_h']-b['start_h'])<1e-6 for a,b in zip(rows,rows[1:]))
        complete=complete and all(isfinite(r[k]) and 0<=r[k]<=1 for r in rows for k in ('soc_before','soc_after','target_soc'))
        result['ev']={'source':'native EVCharger state at zone boundaries; not measured battery data',
                      'status':'observed' if complete else 'unavailable'}
        if complete:
            observed=[r for r in clock_audit.get('ev_state_trace',[]) if 0<=r['start_h']<=horizon+1e-8]
            if statistics_window:
                result['ev']['statistics_boundary_states']=[
                    {'time_h':r['start_h'],'soc_before_step':r['soc_before'],
                     'departure_occurred':r['departure_occurred']}
                    for r in observed if any(abs(r['start_h']-statistics_window[k])<1e-6 for k in ('start_sim_h','end_sim_h'))]
            departure=rows[-1]['departure_h'];arrival=rows[-1]['arrival_h']
            next_departure=departure+(24 if departure<=arrival else 0)
            if statistics_window:next_departure=statistics_window['end_sim_h']
            result['ev'].update(observed_start_h=rows[0]['start_h'],day_end_soc=rows[-1]['soc_after'],target_soc=rows[-1]['target_soc'],
                departure_after_arrival_h=next_departure,
                departure_after_arrival_observed=any(abs(r['start_h']-next_departure)<1e-6 and r['departure_occurred'] for r in observed),
                departures=[{'time_h':r['start_h'],'soc_before_drive':r['soc_before'],
                             'target_soc':r['target_soc'],'target_met':r['soc_before']>=r['target_soc']-1e-6}
                            for r in observed if r['departure_occurred']])
    water=household['appliances'].get('water_heater',{})
    if water.get('present'):
        bath=float(water.get('bath_required_h',21))
        if statistics_window and bath<statistics_window['start_sim_h']:
            bath+=24
        samples=[r for key,series in physical.items() if key.lower()=='water heater tank temperature|water heater_tank_unit1'
                 for r in series if r['start_h']<bath+1e-8 and r['end_h']>=bath-1e-8]
        # At an exact boundary use the interval ending at that time, not a future average.
        ending=[r for r in samples if abs(r['end_h']-bath)<1e-6]
        if ending:samples=ending
        result['water_heater']={'source':'EnergyPlus SQLite Water Heater Tank Temperature',
            'requested_bath_h':bath,'delivered_water_status':'unverified',
            'status':'unavailable','reason':'Tank temperature is not delivered water temperature or volume'}
        if len(samples)==1 and samples[0]['unit']=='C' and isfinite(samples[0]['value']):
            r=samples[0]
            result['water_heater'].update(status='observed',tank_interval={'start_h':r['start_h'],'end_h':r['end_h'],'mean_c':r['value']})
    return result


def service_text(device, run):
    data=run.get('service_evidence',{})
    if device=='home_ev':
        ev=data.get('ev',{})
        if ev.get('status')!='observed':return None
        pieces=[f"{clock(d['time_h'])}离家前电量 {d['soc_before_drive']:.1%}（目标 {d['target_soc']:.0%}，{'达到' if d['target_met'] else '未达到'}）" for d in ev['departures'] if abs(d['time_h']-ev['departure_after_arrival_h'])<1e-6 or not ev['departure_after_arrival_observed']]
        if not data.get('statistics_window') and not any(abs(d['time_h']-data.get('horizon_h',24))<1e-6 for d in ev['departures']):
            pieces.append(f"{clock(data.get('horizon_h',24))}电量 {ev['day_end_soc']:.1%}")
        return '；'.join(pieces)
    water=data.get('water_heater',{})
    if water.get('status')!='observed':return None
    r=water['tank_interval']
    return f"{clock(r['start_h'])}—{clock(r['end_h'])}水箱温度 {r['mean_c']:.1f}℃（平均）"


def task_outcomes(clock_audit, horizon):
    """Exclude a terminal callback's prospective interval from completion claims."""
    rows=[r for r in clock_audit.get('task_state_trace',[]) if r['start_h']<horizon-1e-8 and r['end_h']<=horizon+1e-8]
    if not rows:return {}
    if abs(rows[-1]['end_h']-horizon)>1e-6:raise ValueError('Task observation does not cover comparison cutoff')
    return rows[-1]['first_day_tasks']
