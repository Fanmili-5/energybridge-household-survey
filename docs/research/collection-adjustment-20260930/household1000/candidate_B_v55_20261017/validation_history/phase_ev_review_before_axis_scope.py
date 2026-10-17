"""Full-population phase, service-anchor and independent EV energy-ledger audit."""
import sys,collections,math
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *

def audit(row):
    errors=[];counts=collections.Counter();program=collections.Counter();examples={};world=None;y=None
    def fail(case,code):errors.append([case,code])
    for rr in row['rounds']:
        p=read(OUT/rr['path']);case=p['case_id'];counts['cases']+=1
        if world is None:world=read(A_STAGE/p['A_source']['world_path'])
        assets={x['asset_id']:x for x in world['parameter_pack']['devices']}
        parent=p['revision_parent'];prior=read(PARENT_B/parent['case_path'])
        if sha(PARENT_B/parent['case_path'])!=parent['case_sha256']or prior['A']!=p['A']or prior['needs_A']!=p['needs_A']:fail(case,'PARENT_OR_A46_CHANGED')
        for phase in p['B'].get('thermal_phase_requests',[]):
            counts['thermal_phase:'+phase['phase']]+=1
            lo,hi=phase['start_min'],phase['end_min'];e0,e1=phase['event_interval_min'];aid=phase['asset_id'];kind=phase['kind']
            if phase['phase']=='preparation'and (hi>e0 or phase['load_direction_requested']!='up'):fail(case,'PREPARATION_PHASE_DIRECTION_OR_TIME')
            if phase['phase']=='event'and not e0<=lo<hi<=e1:fail(case,'EVENT_PHASE_TIME')
            for t in range(lo,hi,10):
                a=next((x for x in p['A']['controls']if x['kind']==kind and x['asset_id']==aid and x['start_min']<=t<x['end_min']),None)
                b=next((x for x in p['B']['controls']if x['kind']==kind and x['asset_id']==aid and x['start_min']<=t<x['end_min']),None)
                if phase['phase']=='preparation'and b and a:
                    if kind=='tank_setpoint'and b['value_C']<a['value_C']-1e-8:fail(case,'PREPARATION_LOWERED_TANK_TARGET')
                    if kind=='ac_setpoint'and(b['heating_setpoint_C']<a['heating_setpoint_C']-1e-8 or b['cooling_setpoint_C']>a['cooling_setpoint_C']+1e-8):fail(case,'PREPARATION_RELAXED_AC_TARGET')
        # B is identical to A outside the explicitly formed thermal phase intervals.
        if p['B'].get('thermal_phase_requests'):
            for aid in {z['asset_id']for z in p['B']['thermal_phase_requests']}:
                rows=[z for z in p['B']['thermal_phase_requests']if z['asset_id']==aid];kind=rows[0]['kind'];fields=['value_C']if kind=='tank_setpoint'else['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode']
                arows=[z for z in p['A']['controls']if z['asset_id']==aid and z['kind']==kind];brows=[z for z in p['B']['controls']if z['asset_id']==aid and z['kind']==kind]
                for t in range(480,4320,10):
                    if any(z['start_min']<=t<z['end_min']for z in rows):continue
                    def val(xs):
                        x=next((z for z in xs if z['start_min']<=t<z['end_min']),None);return tuple(x[k]for k in fields)if x else None
                    if val(arows)!=val(brows):fail(case,'THERMAL_A_RECOVERY_NOT_RESTORED');break
        for obs in p['proposal']['actual_device_strengths']:
            if obs['device_family']not in('washer','dishwasher'):continue
            for q in obs['program_changes']:
                if q['kind']not in('washer','dishwasher'):continue
                f=q['request_formation'];basis=f['request_basis'];pol=f['service_fallback_policy'];direction='advance'if q['start_shift_minutes']<0 else'delay'
                program[(q['kind'],basis,pol,direction)]+=1
                if basis=='service_boundary_request':
                    req=next(x for x in p['proposal']['requested_device_strengths']if x['controller_key']==obs['controller_key']);c=next(c for c in req['input_state_plan']['program_service_candidates']if c['need_id']==q['task_id']);choices=[z for z in c['feasible_candidates']if 0<abs(z['delta_min'])<=f['requested_shift_cap_min']]
                    counts['service_boundary_programs']+=1
                    counts['service_boundary_at_latest']+=q['start_shift_minutes']==max(choices,key=lambda z:z['finish_min'])['delta_min']
        ev=p['EV_continuous_reference']
        if ev['status']=='not_installed':continue
        counts['EV_installed_cases']+=1
        if y is None:y=read(A_STAGE/p['A_source']['annual_A_path'])
        offset=(dt.date.fromisoformat(p['date'])-dt.date.fromisoformat(y['anchor'])).days*1440;cap=ev['capacity_kWh'];start,end=ev['interval_min']
        expected_initial=y['initial_states']['EV_SOC']*cap
        for x in y['EV_battery_energy_events']:
            lo,z=x['start_min'],x['end_min'];point=offset+start
            if z==lo:expected_initial+=x['battery_kWh']if lo<point else 0
            elif lo<point:expected_initial+=x['battery_kWh']*min(1.,(point-lo)/(z-lo))
        if abs(expected_initial-ev['initial_energy_kWh'])>1e-7:fail(case,'EV_COMMON_INITIAL_STATE')
        aw=[{**z,'start_min':z['start_min']-offset,'end_min':z['end_min']-offset}for d in y['days'].values()for z in d['controls']if z['kind']=='ev_charge_window'and z['start_min']<offset+end and z['end_min']>offset+start]
        bwcase=[z for z in p['B']['controls']if z['kind']=='ev_charge_window'];ids={z['need_id']for z in bwcase};bw=[z for z in aw if z['need_id']not in ids]+bwcase
        operations={z['operation_id']:z for z in y['operations']if z['kind'].startswith('EV_')};connections={}
        for z in operations.values():
            if z['kind']=='EV_plug':
                unplug=operations[z['need_id']+':EV_unplug'];connections[z['need_id']]=(z['end_min']-offset,unplug['start_min']-offset)
        for side,windows in [('A',aw),('B',bw)]:
            r=ev[side];events=[]
            if abs(r['energy_balance_error_kWh'])>1e-6:fail(case,'EV_ENERGY_BALANCE')
            for c in r['charging_steps']:
                t=c['start_min'];active=[z for z in windows if z['need_id']==c['need_id']and z['start_min']<=t<t+10<=z['end_min']];conn=connections[c['need_id']]
                if len(active)!=1 or not conn[0]<=t<t+10<=conn[1]:fail(case,'EV_CHARGE_OUTSIDE_ORIGINAL_PERMISSION_CONNECTION')
                if c['battery_kWh']>ev['charger_kW']*ev['efficiency']/6+1e-7 or abs(c['grid_kWh']*ev['efficiency']-c['battery_kWh'])>1e-7:fail(case,'EV_CHARGE_RATE_OR_EFFICIENCY')
                events.append((c['end_min'],0,'charge',c))
            expected_trips=[z for z in y['journeys']if start+offset<=z['absolute_departure_min']<=end+offset and(r['stop_at_unexecutable_trip_min']is None or z['absolute_departure_min']<=r['stop_at_unexecutable_trip_min']+offset)]
            if [z['absolute_departure_min']-offset for z in expected_trips]!=[z['departure_min']for z in r['trips']]:fail(case,'EV_TRIP_CALENDAR_CHANGED')
            for q,raw in zip(r['trips'],expected_trips):
                if q['traction_kWh']!=raw['traction_kWh']:fail(case,'EV_TRIP_ENERGY_CHANGED')
                events.append((q['departure_min'],1,'trip',q))
            energy=ev['initial_energy_kWh']
            for t,_,kind,x in sorted(events,key=lambda z:(z[0],z[1])):
                if kind=='charge':
                    energy+=x['battery_kWh']
                    if abs(energy-x['SOC_after']*cap)>1e-6:fail(case,'EV_UNRECORDED_SOC_RESET')
                else:
                    if abs(energy-x['pre_trip_kWh'])>1e-6:fail(case,'EV_PRE_TRIP_CONTINUITY')
                    energy=max(0,energy-x['traction_kWh'])
                    if abs(energy-x['post_trip_kWh'])>1e-6:fail(case,'EV_POST_TRIP_CONTINUITY')
                if energy< -1e-7 or energy>cap+1e-7:fail(case,'EV_SOC_HARDWARE_BOUND')
            if abs(energy-r['end_energy_kWh'])>1e-6:fail(case,'EV_FINAL_CONTINUITY')
        counts['EV_changed_request_cases']+=bool(ev['changed_need_ids']);counts['EV_recovery:'+ev['recovery_status']]+=1
        for q in ev['B']['trips']:
            counts['EV_B_target_unmet_departures']+=q['target_SOC_unmet'];counts['EV_B_minimum_reserve_unmet_departures']+=q['minimum_reserve_unmet_after_trip'];counts['EV_B_unexecutable_departures']+=not q['trip_executable_in_reference']
        if case in('ordinary-v6-0001__2025-09-30','ordinary-v6-0048__2025-04-02','ordinary-v6-1000__2025-07-23'):examples[case]={'path':rr['path'],'EV_continuous_reference':ev,'thermal_phases':p['B'].get('thermal_phase_requests',[]),'actual':p['proposal']['actual_device_strengths']}
    return errors,dict(counts),[(list(k),v)for k,v in program.items()],examples

def main():
    from concurrent.futures import ProcessPoolExecutor
    verify_inputs();sig=rules_id();bindings=sha(OUT/'PAIR_BINDINGS10000.json');rows=read(OUT/'PAIR_BINDINGS10000.json')['records'];errors=[];counts=collections.Counter();program=collections.Counter();examples={}
    with ProcessPoolExecutor(max_workers=4)as pool:
        for i,(ee,cc,pp,xx)in enumerate(pool.map(audit,rows),1):
            errors.extend(ee);counts.update(cc);program.update({tuple(k):v for k,v in pp});examples.update(xx)
            if i%100==0:print({'phase_EV_households':i,'errors':len(errors)},flush=True)
    assert sig==rules_id()and bindings==sha(OUT/'PAIR_BINDINGS10000.json')
    report={'passed':not errors,'rules_sha256':sig,'bindings_sha256':bindings,'counts':dict(counts),'program_fallback_distribution':[{'device_family':k[0],'basis':k[1],'policy':k[2],'direction':k[3],'count':v}for k,v in sorted(program.items())],'errors':errors,'all10000_retained':True,'scope':'raw phase direction/time/A restoration and continuous fixed-charger ledger under given trips/permissions;not full B physics or human acceptance'}
    save(OUT/'PHASE_EV_REVIEW.json',report);save(OUT/'review/阶段与连续电量案例.json',examples);print(canonical(report))
    if errors:raise SystemExit(2)
if __name__=='__main__':main()
