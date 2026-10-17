"""EB-normalized exogenous VPP requests; no household A/B outcome selection."""
import importlib.util,collections
from common import *
SCHEDULE=REPO/'upstream_2b17ae6/experiments/benchmark/configs/vpp_events_7day_variable.json'
HELPER=REPO/'upstream_2b17ae6/energybridge/data/vpp_events.py'
_spec=importlib.util.spec_from_file_location('eb_vpp_events',HELPER);_eb=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_eb)
TEMPLATES=_eb.load_vpp_events_config(SCHEDULE,sim_days=7)

def for_case(w,c):
    station=w['layout']['source_parameter_reference']['weather'][0]['station_key'];key=[station,c['date'],'V39-grid-event']
    group=1+rank(*key)%7;direction='up'if rank(*key,'direction')%5==0 else'down';target=[.5,1.,2.][rank(*key,'target')%3];result=[]
    for template in TEMPLATES:
        if template['day']!=group:continue
        a=round(template['trigger_h']%24*60);b=a+round((template['end_h']-template['trigger_h'])*60)
        result.append({'event_id':'vpp:'+digest([station,c['date'],template['id']])[:20],'date':c['date'],'station_key':station,
          'notification_min':DECISION,'start_min':a,'end_min':b,'direction':direction,'target_kw':target,'duration_minutes':b-a,
          'request_basis':'EB window templates and down/up/target_kw/duration schema;target0.5/1/2kW and80/20 direction coverage are researcher-given,not grid observations',
          'source_schedule_path':str(SCHEDULE.relative_to(REPO)),'source_schedule_sha256':sha(SCHEDULE),'source_template_id':template['id'],
          'same_station_date_has_same_requests':True,'selection_uses_household_assets_A_B_outcomes_or_answers':False,
          'controlled_meter_scope':'aggregate controlled dwelling devices plus separately supplied EV bay;not a single dwelling inlet',
          'compensation':{'value':None,'status':'not modelled;do not invent incentive income'},'request_target_is_not_guaranteed_feasible':True})
    return result

def known_load_series(plan,w):
    assets={d['asset_id']:d for d in w['parameter_pack']['devices']};series=collections.defaultdict(float)
    for t in plan['tasks']:
        p=assets[t['asset_id']]['parameters'];kw=p.get(t['kind'],p)['power_kw']
        for m in range(t['start_min'],t['end_min'],10):series[m]+=kw
    for x in plan['controls']:
        if x['kind']!='ev_charge_window':continue
        kw=assets[x['asset_id']]['parameters']['charger_kw']
        for m in range(x['start_min'],x['actual_charge_end_min'],10):series[m]+=kw*(x['last_step_power_fraction']if m==x['actual_charge_end_min']-10 else 1)
    return series

def response_reference(w,c,plan,events,assessment):
    a=known_load_series(c['A'],w);requested=known_load_series(plan,w)
    realized={**plan,'tasks':assessment['conditional_recovery_reference']['realized_tasks']};conditional=known_load_series(realized,w)
    def energy(series,lo,hi):return sum(v*max(0,min(m+10,hi)-max(m,lo))/60 for m,v in series.items()if max(m,lo)<min(m+10,hi))
    result=[]
    for event in events:
        lo=event['start_min'];hi=event['end_min'];duration=(hi-lo)/60;sign=1 if event['direction']=='down'else-1
        row={'event_id':event['event_id'],'direction':event['direction'],'target_kw':event['target_kw'],
          'A_requested_known_kWh':energy(a,lo,hi),'B_requested_known_kWh':energy(requested,lo,hi),
          'B_conditional_recovery_known_kWh':energy(conditional,lo,hi),
          'requested_known_response_average_kw':sign*(energy(a,lo,hi)-energy(requested,lo,hi))/duration,
          'conditional_known_response_average_kw':sign*(energy(a,lo,hi)-energy(conditional,lo,hi))/duration,
          'requested_post2h_extra_kWh':energy(requested,hi,hi+120)-energy(a,hi,hi+120),
          'requested_pre2h_extra_kWh':energy(requested,max(DECISION,lo-120),lo)-energy(a,max(DECISION,lo-120),lo),
          'whole_portfolio_target_met':None,'physical_response_kw':None,'human_acceptance':None,
          'scope':'known washer/dryer/dishwasher programs and EV at common connection-state projection only;HVAC/tank excluded;not whole-house response or net saving',
          'conditional_reference_is_not_observed_recovery_or_continuous_B_SOC':True}
        result.append(row)
    return {'events':result,'known_load_requested_primary_delta_kWh':energy(requested,480,1920)-energy(a,480,1920),
      'known_load_requested_after_primary_to_tail_delta_kWh':energy(requested,1920,4320)-energy(a,1920,4320),
      'known_load_requested_to_tail_delta_kWh':energy(requested,480,4320)-energy(a,480,4320),'whole_physical_net_saving_kWh':None,
      'whole_thermal_electric_physical_acceptance':False,'A_generated_without_VPP':True,'no_outcome_selection':True}
