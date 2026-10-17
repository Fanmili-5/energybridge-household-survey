"""EB-normalized exogenous VPP requests; no household A/B outcome selection."""
import importlib.util,collections
from common import *
SCHEDULE=REPO/'upstream_2b17ae6/experiments/benchmark/configs/vpp_events_7day_variable.json'
HELPER=REPO/'upstream_2b17ae6/energybridge/data/vpp_events.py'
_spec=importlib.util.spec_from_file_location('eb_vpp_events',HELPER);_eb=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_eb)
TEMPLATES=_eb.load_vpp_events_config(SCHEDULE,sim_days=7)

def for_case(w,c):
    station=w['layout']['source_parameter_reference']['weather'][0]['station_key'];key=[station,c['date'],'V39-grid-event']
    group=1+rank(*key)%7;direction='up'if rank(*key,'direction')%5==0 else'down';targets=[.5,1.,2.];target_index=rank(*key,'target')%3;result=[]
    templates=[t for t in TEMPLATES if t['day']==group]
    directions=[direction]*len(templates);indices=[target_index]*len(templates)
    if len(templates)>1:
        # Exogenous factorial coverage: retain same-direction days and add both
        # ordered mixed directions. Equal/unequal goals are an independent factor.
        # These are given test scenarios, never population or grid frequencies.
        shape=rank(*key,'multi-direction-v48')%4
        if shape>=2:directions=['down','up']if shape==2 else['up','down']
        if rank(*key,'multi-target-v48')%2:
            indices[1]=(target_index+1+rank(*key,'target-offset-v48')%2)%len(targets)
    for index,template in enumerate(templates):
        a=round(template['trigger_h']%24*60);b=a+round((template['end_h']-template['trigger_h'])*60)
        result.append({'event_id':'vpp:'+digest([station,c['date'],template['id']])[:20],'date':c['date'],'station_key':station,
          'notification_min':DECISION,'start_min':a,'end_min':b,'direction':directions[index],'target_kw':targets[indices[index]],'duration_minutes':b-a,
          'request_basis':'EB window templates;single-window direction and target unchanged;multi-window ordered directions and equal/unequal targets are independent researcher-given factors,not grid observations',
          'multi_window_design':{'directions':directions,'target_kw':[targets[i]for i in indices],'input_only':True},
          'source_schedule_path':str(SCHEDULE.relative_to(REPO)),'source_schedule_sha256':sha(SCHEDULE),'source_template_id':template['id'],
          'same_station_date_has_same_requests':True,'selection_uses_household_assets_A_B_outcomes_or_answers':False,
          'controlled_meter_scope':'aggregate controlled dwelling devices plus separately supplied EV bay;not a single dwelling inlet',
          'compensation':{'value':None,'status':'not modelled;do not invent incentive income'},'request_target_is_not_guaranteed_feasible':True})
    return result

def known_load_series(plan,w):
    """Fixed programme request model only; EV comes from the continuous ledger."""
    assets={d['asset_id']:d for d in w['parameter_pack']['devices']};series=collections.defaultdict(float)
    for t in plan['tasks']:
        p=assets[t['asset_id']]['parameters'];kw=p.get(t['kind'],p)['power_kw']
        for m in range(t['start_min'],t['end_min'],10):series[m]+=kw
    return series

def energy(series,lo,hi):
    return sum(v*max(0,min(m+10,hi)-max(m,lo))/60 for m,v in series.items()if max(m,lo)<min(m+10,hi))

def response_reference(w,c,plan,events,assessment,ev):
    a=known_load_series(c['A'],w);requested=known_load_series(plan,w)
    realized={**plan,'tasks':assessment['conditional_recovery_reference']['realized_tasks']};conditional=known_load_series(realized,w)
    es={side:collections.defaultdict(float)for side in('A','B')}
    installed=ev['status']!='not_installed'
    if installed:
        for side in es:
            for step in ev[side]['charging_steps']:es[side][step['start_min']]+=step['grid_kWh']*6
    for m,v in es['A'].items():a[m]+=v
    for series in(requested,conditional):
        for m,v in es['B'].items():series[m]+=v
    result=[]
    for event in events:
        lo=event['start_min'];hi=event['end_min'];duration=(hi-lo)/60;sign=1 if event['direction']=='down'else-1
        result.append({'event_id':event['event_id'],'direction':event['direction'],'target_kw':event['target_kw'],
          'A_requested_known_kWh':energy(a,lo,hi),'B_requested_known_kWh':energy(requested,lo,hi),
          'B_conditional_recovery_known_kWh':energy(conditional,lo,hi),
          'requested_known_response_average_kw':sign*(energy(a,lo,hi)-energy(requested,lo,hi))/duration,
          'conditional_known_response_average_kw':sign*(energy(a,lo,hi)-energy(conditional,lo,hi))/duration,
          'requested_post2h_extra_kWh':energy(requested,hi,hi+120)-energy(a,hi,hi+120),
          'requested_pre2h_extra_kWh':energy(requested,max(DECISION,lo-120),lo)-energy(a,max(DECISION,lo-120),lo),
          'EV_A_grid_kWh':energy(es['A'],lo,hi),'EV_B_grid_kWh':energy(es['B'],lo,hi),
          'whole_portfolio_target_met':None,'physical_response_kw':None,'human_acceptance':None,
          'scope':'fixed washer/dryer/dishwasher requests plus conditional continuous EV SOC/charging;HVAC/tank excluded;not whole-house response or net saving',
          'reference_is_conditional_not_observed':True,'EV_SOC_continuity_used':True})
    ev_summary={'status':ev['status'],'continuous_reference_sha256':digest(ev),'same_trajectory_as_event_summary':True}
    if installed:
        periods={}
        for name,lo,hi in [('primary',480,1920),('after_primary_to_tail',1920,4320),('to_tail',480,4320),('full_reference',*ev['interval_min'])]:
            aa=energy(es['A'],lo,hi);bb=energy(es['B'],lo,hi);periods[name]={'interval_min':[lo,hi],'A_grid_kWh':aa,'B_grid_kWh':bb,'delta_grid_kWh':bb-aa}
        last=ev['last_changed_permission_end_min'];end=ev['interval_min'][1];snap=next((x for x in ev['snapshots']if x['minute']==last),None)
        ev_summary.update(periods=periods,recovery_status=ev['recovery_status'],common_SOC_restored_min=ev['actual_stable_SOC_match_min'],actual_stable_SOC_match_min=ev['actual_stable_SOC_match_min'],intervention_end_min=ev['intervention_end_min'],post_intervention_SOC_confirmation_min=ev['post_intervention_SOC_confirmation_min'],time_display_basis='actual stable SOC match;intervention closure and post-closure confirmation are separate',
          last_changed_permission_end_min=last,last_B_permission_end_min=ev['last_B_permission_end_min'],recovery_start_basis=ev['recovery_start_basis'],battery_deficit_at_request_end_kWh=max(0,-snap['delta_battery_kWh'])if snap else None,
          after_request_extra_grid_kWh=energy(es['B'],last,end)-energy(es['A'],last,end),
          target_unmet_departures=[{'departure_min':x['departure_min'],'target_shortfall_battery_kWh':max(0,ev['target_SOC']*ev['capacity_kWh']-x['pre_trip_kWh']),'minimum_reserve_unmet_after_trip':x['minimum_reserve_unmet_after_trip'],'unserved_traction_kWh':x['unserved_traction_kWh']}for x in ev['B']['trips']if x['target_SOC_unmet']or not x['trip_executable_in_reference']],
          future_permissions_unchanged=True,no_added_handling_or_external_energy=True)
    return {'events':result,'known_load_requested_primary_delta_kWh':energy(requested,480,1920)-energy(a,480,1920),
      'known_load_requested_after_primary_to_tail_delta_kWh':energy(requested,1920,4320)-energy(a,1920,4320),
      'known_load_requested_to_tail_delta_kWh':energy(requested,480,4320)-energy(a,480,4320),
      'EV_continuous_impact':ev_summary,'whole_physical_net_saving_kWh':None,
      'whole_thermal_electric_physical_acceptance':False,'A_generated_without_VPP':True,'no_outcome_selection':True,
      'energy_basis':'programme fixed-power requests plus the identical continuous conditional EV trajectory;not old per-connection delivered-energy metadata'}
