"""Continuous conditional SOC on the given A46 trips and physical connections.

Each counterfactual starts at the same pre-decision A state. Future A permissions
are replayed as target-SOC controllers; their old delivered-energy metadata is
never used to reset B SOC or limit recovery. No additional trip/plug/energy/help
is introduced. A physically impossible trip stops that branch's trajectory.
"""
from functools import lru_cache
from common import *

@lru_cache(maxsize=2)
def annual(path):return read(A_STAGE/path)

def ledger_energy(y,minute,capacity):
    energy=y['initial_states']['EV_SOC']*capacity
    for x in y['EV_battery_energy_events']:
        a,z=x['start_min'],x['end_min']
        if a==z:
            if a<minute:energy+=x['battery_kWh']
        elif a<minute:energy+=x['battery_kWh']*min(1.,(minute-a)/(z-a))
    return energy

def replay(start,end,initial,p,windows,connections,trips):
    energy=initial;trace=[];charges=[];trip_rows=[];stop=None;inputs={t:x for t,x in trips}
    for t in range(start,end+1,10):
        if t in inputs:
            trip=inputs[t];required=trip['traction_kWh'];before=energy;unserved=max(0,required-before)
            after=max(0,before-required)
            trip_rows.append({'departure_min':t,'arrival_min':trip['absolute_arrival_min'],'traction_kWh':required,'pre_trip_kWh':before,'post_trip_kWh':after,'target_SOC_unmet':before<p['target_soc']*p['capacity_kwh']-1e-7,'minimum_reserve_unmet_after_trip':after<p['min_soc']*p['capacity_kwh']-1e-7,'unserved_traction_kWh':unserved,'trip_executable_in_reference':unserved<=1e-7})
            energy=after
            if unserved>1e-7:
                stop=t;trace.append([t,energy]);break
        trace.append([t,energy])
        if t==end:break
        active=[x for x in windows if x['start_min']<=t<x['end_min']]
        if len(active)>1:raise ValueError('OVERLAPPING_EV_PERMISSION_IN_CONTINUOUS_REFERENCE')
        if not active:continue
        x=active[0];connection=connections.get(x['need_id'])
        if connection is None:raise ValueError('EV_WINDOW_HAS_NO_ORIGINAL_CONNECTION')
        lo,hi=connection
        if not lo<=t<t+10<=hi:continue
        target=x['stop_at_target_soc']*p['capacity_kwh'];battery=min(p['charger_kw']*p['efficiency']/6,max(0,target-energy),max(0,p['capacity_kwh']-energy))
        if battery>1e-9:
            energy+=battery;charges.append({'start_min':t,'end_min':t+10,'battery_kWh':battery,'grid_kWh':battery/p['efficiency'],'need_id':x['need_id'],'SOC_after':energy/p['capacity_kwh']})
    return {'trace':trace,'charging_steps':charges,'trips':trip_rows,'stop_at_unexecutable_trip_min':stop,'end_energy_kWh':energy,'energy_balance_error_kWh':energy-initial-sum(x['battery_kWh']for x in charges)+sum(min(x['traction_kWh'],x['pre_trip_kWh'])for x in trip_rows)}

def continuous_reference(w,case,plan):
    device=next((d for d in w['parameter_pack']['devices']if 'ev'in d['types']),None)
    if device is None:return {'schema':'eb.continuous_EV.v56','status':'not_installed','human_acceptance':None}
    par=device['parameters'];y=annual(case['A_source']['annual_A_path']);offset=(dt.date.fromisoformat(case['date'])-dt.date.fromisoformat(y['anchor'])).days*1440
    aw=[{**x,'start_min':x['start_min']-offset,'end_min':x['end_min']-offset}for d in y['days'].values()for x in d['controls']if x['kind']=='ev_charge_window']
    caseA=[x for x in case['A']['controls']if x['kind']=='ev_charge_window'];caseB=[x for x in plan['controls']if x['kind']=='ev_charge_window']
    touched={x['need_id']for x in caseB};bw=[x for x in aw if x['need_id']not in touched]+copy.deepcopy(caseB)
    # Original A/B requests may contain historical windows; compare executable
    # permissions by need, not derived A-delivery metadata.
    def sig(xs):return sorted((x['start_min'],x['end_min'],x['stop_at_target_soc'])for x in xs)
    changed={nid for nid in touched if sig([x for x in caseA if x['need_id']==nid])!=sig([x for x in caseB if x['need_id']==nid])}
    last=max([x['end_min']for x in caseA+caseB if x['need_id']in changed],default=1920);b_permission_end=max([x['end_min']for x in caseB if x['need_id']in changed],default=None);end=last+7*1440
    annual_end=(dt.date.fromisoformat(y['end_exclusive'])-dt.date.fromisoformat(y['anchor'])).days*1440-offset
    end=min(end,annual_end-10);start=DECISION
    initial=ledger_energy(y,offset+start,par['capacity_kwh'])
    ops=[{**o,'start_min':o['start_min']-offset,'end_min':o['end_min']-offset}for o in y['operations']if o['kind'].startswith('EV_')]
    connections={};unplugs={o['need_id']:o for o in ops if o['kind']=='EV_unplug'}
    for o in ops:
        if o['kind']!='EV_plug':continue
        unplug=unplugs[o['need_id']];connections[o['need_id']]=(o['end_min'],unplug['start_min'])
    trips=[(x['absolute_departure_min']-offset,{**x,'absolute_arrival_min':x['absolute_arrival_min']-offset})for x in y['journeys']if offset+start<=x['absolute_departure_min']<=offset+end]
    a=replay(start,end,initial,par,[x for x in aw if x['start_min']<end and start<x['end_min']],connections,trips);b=replay(start,end,initial,par,[x for x in bw if x['start_min']<end and start<x['end_min']],connections,trips)
    at=dict(a['trace']);bt=dict(b['trace']);diff=[(t,bt[t]-at[t])for t in sorted(at.keys()&bt.keys())];first=next((t for t,z in diff if abs(z)>1e-7),None)
    recovery=next((t for t,z in diff if first is not None and t>first and t>=last and abs(z)<1e-7),None)
    snapshots=[]
    keep={start,end,last}|{x['departure_min']for x in a['trips']+b['trips']}|{t for t in range(start,end+1,10)if t%1440==0}
    if first is not None:keep.add(first)
    if recovery is not None:keep.add(recovery)
    for t in sorted(keep):
        if t in at and t in bt:snapshots.append({'minute':t,'A_SOC':at[t]/par['capacity_kwh'],'B_SOC':bt[t]/par['capacity_kwh'],'delta_battery_kWh':bt[t]-at[t]})
    event_rows=[]
    for event in case['VPP_events']:
        energies={side:sum(c['grid_kWh']for c in replayed['charging_steps']if event['start_min']<=c['start_min']<event['end_min'])for side,replayed in [('A',a),('B',b)]}
        event_rows.append({'event_id':event['event_id'],'A_grid_kWh':energies['A'],'B_grid_kWh':energies['B'],'delta_kw':(energies['B']-energies['A'])*60/(event['end_min']-event['start_min'])})
    for r in (a,b):r.pop('trace')
    return {'schema':'eb.continuous_EV.v56','status':'conditional_fixed_charger_reference','scope':'same A predecision battery state;given trips and original plug/unplug;B permission then original A recovery permissions;constant charger/efficiency;not observed SOC,acceptance or complete electrochemical physics','annual_A_sha256':case['A_source']['annual_A_sha256'],'asset_id':device['asset_id'],'capacity_kWh':par['capacity_kwh'],'charger_kW':par['charger_kw'],'efficiency':par['efficiency'],'target_SOC':par['target_soc'],'minimum_SOC':par['min_soc'],'initial_energy_kWh':initial,'initial_state_basis':'integrated frozen annual A battery ledger at decision;not reset per connection','interval_min':[start,end],'last_changed_permission_end_min':last,'last_B_permission_end_min':b_permission_end,'recovery_start_basis':'end of both A and B permissions for changed original connections;removed permission remains an intervention until original A window closes;not fixed primary-day cutoff','changed_need_ids':sorted(changed),'A':a,'B':b,'first_SOC_difference_min':first,'common_SOC_restored_after_request_min':recovery,'recovery_status':'no_SOC_difference'if first is None else'restored_on_given_permissions'if recovery is not None else'future_unknown_after_impossible_trip'if b['stop_at_unexecutable_trip_min']is not None else'not_restored_within_horizon','snapshots':snapshots,'events':event_rows,'no_added_trips_or_handling_or_external_energy':True,'future_permissions_unchanged':True,'conditional_B_is_independent_for_each_case':True,'human_acceptance':None,'full_physical_acceptance':False}
