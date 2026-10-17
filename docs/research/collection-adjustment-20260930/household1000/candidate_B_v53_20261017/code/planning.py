"""Before-B device/event planning from fixed A state; no delivery/acceptance lookup."""
import math
from common import *
FACTORS=(.25,.5,1.,1.5)
RESERVE_FRACTIONS=(.4,.65,.85,.95,1.05,1.25,1.5)
def ceil10(x):return int(math.ceil(x/10-1e-9)*10)
def intersection(a,b,c,d):return max(0,min(b,d)-max(a,c))

def contexts(w,source,defs):
    result={};assets={x['asset_id']:x for x in w['parameter_pack']['devices']}
    for key,d in defs.items():
        family=d['family'];aid=d['asset_ids'][0];device=assets[aid]
        u=rank('B53-request-behavior',source['case_id'],key)%10
        behavior='normal_response'if u<6 else'partial_response'if u==6 else'service_pressure'if u==7 else'opposing_request'if u==8 else'limited_opportunity_request'
        if any(x.get('unfavourable_variant_selected')for x in source['classification']['design_intent']['action_designs']if x['device_family']==family):behavior='opposing_request'
        observations=[]
        for e in source['VPP_events']:
            conn=overlap_min=0;details={}
            if family=='ev':
                controls=[x for x in source['A']['controls']if x['kind']=='ev_charge_window'and x['asset_id']==aid and x['start_min']>=DECISION]
                for a in controls:
                    conn+=intersection(a['start_min'],a['end_min'],e['start_min'],e['end_min'])
                    overlap_min+=intersection(a['start_min'],a['actual_charge_end_min'],e['start_min'],e['end_min'])
                opportunity=max(0,conn-overlap_min)if e['direction']=='up'else overlap_min
                details={'A_connection_overlap_min':conn,'A_fixed_charge_overlap_min':overlap_min,'reference_is_not_observed_SOC':True}
            elif family in('washer','dishwasher'):
                tasks=[t for t in source['A']['tasks']if t['asset_id']==aid and t['kind']in((family,'dryer')if family=='washer'else(family,))and t['start_min']>=DECISION]
                overlap_min=sum(intersection(t['start_min'],t['end_min'],e['start_min'],e['end_min'])for t in tasks)
                opportunity=overlap_min if e['direction']=='down'else max(0,e['duration_minutes']-overlap_min)
                details={'A_fixed_program_overlap_min':overlap_min,'linked_automatic_dryer_included':family=='washer'and'dryer'in device['types'],'A_fixed_program_event_kWh':sum(intersection(t['start_min'],t['end_min'],e['start_min'],e['end_min'])/60*device['parameters'].get(t['kind'],device['parameters'])['power_kw']for t in tasks)}
            else:
                kind='ac_setpoint'if family=='ac'else'tank_setpoint'
                overlap_min=sum(intersection(x['start_min'],x['end_min'],e['start_min'],e['end_min'])for x in source['A']['controls']if x['kind']==kind and x['asset_id']==aid)
                opportunity=overlap_min
                details={'A_routine_permission_overlap_min':overlap_min,'compressor_or_heater_active_state':'not_observed;thermal_rollout_pending'}
            observations.append({'event_id':e['event_id'],'direction':e['direction'],'target_kw':e['target_kw'],'start_min':e['start_min'],'end_min':e['end_min'],'input_opportunity_min':opportunity,**details})
        selected=max(observations,key=lambda x:(x['input_opportunity_min'],rank(source['case_id'],key,x['event_id'],'state-event-choice')))
        day=next(x for x in source['days']if x['date']==source['date'])
        result[key]={'behavior':behavior,'event':selected,'all_event_input_states':observations,
          'thermal_axis_reference':'heating'if day['weather']['mean_C']<source['thermal_control_context'].get(aid,{}).get('usual_heating_setpoint_C',22.)else'cooling',
          'thermal_axis_basis':'given_daily_outdoor_mean_and_A_thermostat;not_observed_operating_mode',
          'reserve_budget_fraction':RESERVE_FRACTIONS[rank('B53-reserve-budget',source['case_id'],key)%len(RESERVE_FRACTIONS)],
          'reserve_placement':['event_start','event_end','after_event','before_departure','after_connection'][rank('B53-reserve-placement',source['case_id'],key)%5],
          'selected_before_B':True,'uses_B_success_or_human_acceptance':False}
    return result


def ev_window(a,p,table,grade,context):
    full=ceil10(a['battery_energy_kWh']/(p['charger_kw']*p['efficiency'])*60)
    step=max(10,ceil10(full*(.25,.5,1.,2.)[grade]));e=context['event'];behavior=context['behavior']
    lo,hi=a['start_min'],a['end_min'];end=hi
    if behavior=='service_pressure':
        budget=max(10,ceil10(full*context['reserve_budget_fraction']))
        anchor={'event_start':e['start_min'],'event_end':e['end_min']-budget,'after_event':e['end_min'],'before_departure':hi-budget,'after_connection':lo}[context['reserve_placement']]
        start=max(lo,min(max(lo,hi-budget),anchor));end=min(hi,start+budget)
    else:
        direction=e['direction']
        if behavior=='opposing_request':direction='up'if direction=='down'else'down'
        connection=intersection(lo,hi,e['start_min'],e['end_min']);charged=intersection(lo,lo+full,e['start_min'],e['end_min'])
        if behavior=='limited_opportunity_request' or not connection or(direction=='down'and not charged):start=lo+step
        elif direction=='up':
            desired=min(full,connection,max(10,ceil10(e['target_kw']/p['charger_kw']*connection*FACTORS[grade])))
            start=max(lo,e['start_min']-full+desired)
            # Already-covering A is recorded as limited opportunity; retain a
            # native-time adjustment request, never invented handling or loads.
            if start==lo:start=lo+min(step,max(10,ceil10(full/4)))
        else:
            span=max(10,e['end_min']-lo)
            start=lo+max(10,ceil10(span*min(1.5,e['target_kw']/p['charger_kw']*FACTORS[grade])))
        start=min(hi-10,max(lo,start))
    return int(start),int(max(start+10,end))


def program_delta(source,a,native,old_delta,context,power_kw):
    e=context['event'];behavior=context['behavior'];direction=e['direction']
    if behavior=='opposing_request':direction='up'if direction=='down'else'down'
    if behavior not in('normal_response','partial_response','opposing_request'):return old_delta
    chain=[t for t in source['A']['tasks']if t['need_id']in(a['need_id'],a['need_id']+':dry')]
    chain_end=max(t['end_min']for t in chain);chain_duration=chain_end-a['start_min']
    overlap_min=sum(intersection(t['start_min'],t['end_min'],e['start_min'],e['end_min'])for t in chain)
    if direction=='down':
        if not overlap_min:return old_delta
        desired=e['end_min']-a['start_min']
    else:
        target=min(chain_duration,e['end_min']-e['start_min'],max(10,ceil10(e['target_kw']/power_kw*(e['end_min']-e['start_min']))))
        desired=e['start_min']-chain_duration+target-a['start_min']
    load=next(x for x in source['A']['operations']if x['kind']=='load'and x['need_id']==a['need_id'])
    oldload=next(x for x in source['B']['operations']if x['operation_id']==load['operation_id'])
    need=next(x for x in source['needs_A']if x['need_id']==a['need_id'])
    advance_capacity=(min(a['start_min']-DECISION,load['start_min']-max(DECISION,need['release_min']))if oldload['start_min']!=load['start_min']else a['start_min']-max(DECISION,load['end_min']))
    # No earlier service is available at the input release/loading boundary.
    # Keep the existing source timing-pressure direction, with actual grade
    # read back afterwards; never search outcomes or add another operation.
    if not desired or(desired<0 and advance_capacity<=0):return old_delta
    return (1 if desired>0 else-1)*min(native,abs(desired))
