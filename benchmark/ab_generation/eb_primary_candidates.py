"""Literal EB start_h and continuous charge-window candidates; no human handling."""
import math
from .eb_primary import active
from .model import apply,request_issues,control_issues
from .power import site_capacity

def checks(c,patches):
    b=apply(c['A'],patches);gate=request_issues(c,b)
    from .eb_agent_contract import plan_errors
    gate+=plan_errors(c,b)
    changed={r['asset_id'] for p in patches for r in p.get('rows',[])}|{p['asset_id'] for p in patches if 'asset_id' in p}
    gate+=['TARGET_CONTROL_NOT_AUTHORIZED' for aid in changed if not c['authority']['assets'][aid]['target_control_authorized']]
    power=site_capacity(c,b)
    return sorted(set(gate+control_issues(c,b)+power['issues'])),sorted(set(gate)),power

def engineering(c,b):
    from .unified.independent import audit
    errors=audit(c,c['A'],b)
    from .connection_states import covers
    if covers(c,b):errors=[x for x in errors if x!='EV_OUTSIDE_CONNECTION']
    if b['operations']:errors.append('NON_EB_MANUAL_OPERATION')
    return sorted(set(errors))

def programmes(c,d):
    from .collection_candidates import _profile
    byneed={t['need_id']:t for t in c['A']['tasks']}
    for n in c['needs']:
        if n['asset_id']!=d['asset_id'] or n['kind'] not in ('washer','dryer','dishwasher'):continue
        t=byneed.get(n['need_id'])
        if t is None or t['start_min']<c['decision_min']:continue
        duration=t['end_min']-t['start_min']
        lo=max(c['decision_min'],n['start_window_min'][0]);hi=min(n['start_window_min'][1]-1,n['deadline_min']-duration,1440-duration)
        for start in range(math.ceil(lo/10)*10,math.floor(hi/10)*10+1,10):
            delta=start-t['start_min'];after={**t,'start_min':start,'end_min':start+duration}
            yield dict(unit=n['need_id'],family=n['kind'],asset_id=d['asset_id'],service_need_id=n['need_id'],
                mechanism='start_time_shift',construction_route='original_EB_start_h_command',
                branch='earlier' if delta<0 else 'later',needs=[n['need_id']],
                patches=[dict(type='rows',collection='tasks',identity='task_id',rows=[after])],
                profiles={'A':_profile(c,[t]),'B':_profile(c,[after])},
                magnitude=dict(dose_coordinate=abs(delta),machine_shift_min=abs(delta),signed_machine_shift_min=delta,
                    service_slack_min=n['deadline_min']-after['end_min'],
                    manual_total_shift_min=0,manual_max_shift_min=0))

def ev_windows(c,d):
    from .eb_alignment import _ev_profiles
    aid=d['asset_id']
    for original in c['A']['controls']:
        if original['asset_id']!=aid or original['kind']!='ev_charge_window':continue
        nid=original['need_id'];steps=[s for s in c['reference']['ev_charging_steps'] if s['need_id']==nid]
        if not steps:continue
        physical=next(p for p in c['physical_ev_connections'] if p['need_id']==nid)
        energy=sum(s['grid_kWh'] for s in steps);rating=d['parameters']['charger_kw']
        length=math.ceil((energy/rating*60-1e-8)/10)*10
        anchor=min(s['start_min'] for s in steps)
        # Canonical local hours are applied by the dated queue;EV alone may start/finish after midnight.
        lo=max(c['decision_min'],physical['start_min']);hi=physical['end_min']-length
        for start in range(math.ceil(lo/10)*10,math.floor(hi/10)*10+1,10):
            end=start+length
            if any(start<e['end_min'] and end>e['start_min'] for e in c['events']):continue
            row={**original,'start_min':start,'end_min':end}
            patch=dict(type='rows',collection='controls',identity='_unified_id',rows=[row])
            plan=apply(c['A'],[patch]);after=_ev_profiles(c,plan,(),side='B').get((aid,nid),[])
            delivered=sum(s['grid_kWh'] for s in after)
            if delivered+1e-8<energy:continue
            yield dict(unit='ev:'+nid,family='ev',asset_id=aid,service_need_id=nid,
                mechanism='ev_defer',branch='later',needs=[],patches=[patch],
                profiles={'A':[{**s,'asset_id':aid,'power_kw':s['grid_kWh']*6} for s in steps],
                          'B':[{**s,'asset_id':aid} for s in after]},
                magnitude=dict(dose_coordinate=max(0,start-anchor),pause_min=max(0,start-anchor),
                    service_slack_min=physical['end_min']-max(s['end_min'] for s in after),
                    energy_shortfall_kWh=0.0,required_A_grid_kWh=energy,manual_total_shift_min=0,manual_max_shift_min=0))

def wh_windows(c,d,cfg):
    """A single native preheat(start,end,temp), using EB normal/preheat templates."""
    from .common import digest
    original=next((r for r in c['A']['controls'] if r['asset_id']==d['asset_id'] and r['kind']=='tank_setpoint' and 0<=r['start_min']<1440),None)
    if original is None:return
    normal_duration=original['end_min']-original['start_min']
    native=c['native_execution_contract']['primary_water_heater_configuration']
    prestart=round(native['pre_heat_window_start_h']*60);preend=round(native['pre_heat_window_end_h']*60)
    lengths={normal_duration,preend-prestart};doses=set(cfg['precondition_min'])
    starts={original['start_min'],prestart}
    starts.update(original['start_min']+sign*lead for lead in doses for sign in (-1,1))
    windows={(start,start+length) for start in starts for length in lengths}
    for event in c['events']:
        windows.update((edge-length,edge) for edge in (event['start_min'],event['end_min']) for length in lengths)
    temp=original['value_C'];maximum=min(75,d['parameters']['maximum_C'])
    temperatures={temp}|{temp+sign*delta for delta in cfg['tank_delta_C'] for sign in (-1,1)}
    for start,end in sorted(windows):
        if not c['decision_min']<=start<end<=min(1440,round(native['bath_required_h']*60)):continue
        if end-start>min(480,preend-prestart+60):continue
        for target in sorted(temperatures):
            if not 45<=target<=maximum:continue
            after={**original,'start_min':start,'end_min':end,'value_C':target}
            delta=target-temp;shift=start-original['start_min']
            yield dict(unit='WH:'+d['asset_id'],family='water_heater',asset_id=d['asset_id'],service_need_id=None,
                mechanism='preheat_window_shift' if shift or end!=original['end_min'] else 'tank_temperature',
                branch='earlier' if shift<0 else 'later' if shift>0 else 'aligned' if delta<0 else 'opposing',
                needs=[],patches=[dict(type='rows',collection='controls',identity='_unified_id',rows=[after])],profiles=None,
                magnitude=dict(dose_coordinate=abs(shift) if shift else abs(delta),service_delta_C=abs(delta),
                    actual_max_command_delta_C=abs(delta),duration_min=end-start,precondition_min=max(0,-shift),
                    axis='tank',direction='aligned' if delta<=0 else 'opposing',
                    native_preheat_window={'A':[original['start_min'],original['end_min'],temp],'B':[start,end,target]},
                    manual_total_shift_min=0,manual_max_shift_min=0))
