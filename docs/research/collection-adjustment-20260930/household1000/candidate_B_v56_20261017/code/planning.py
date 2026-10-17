"""Before-B device/event planning from fixed A state; no delivery/acceptance lookup."""
import math
from common import *
FACTORS=(.25,.5,1.,1.5)
RESERVE_FRACTIONS=(.4,.65,.85,.95,1.05,1.25,1.5)
def ceil10(x):return int(math.ceil(x/10-1e-9)*10)
def intersection(a,b,c,d):return max(0,min(b,d)-max(a,c))

def ev_timer_options(a,p,e):
    exact=a['battery_energy_kWh']/(p['charger_kw']*p['efficiency'])*60
    latest=a['end_min']-ceil10(exact)
    return [(start,intersection(start,start+exact,e['start_min'],e['end_min']))for start in range(a['start_min'],int(latest)+1,10)]

_CTX={}
def operation_allowed(source,op,t,excluded):
    day=next((d for d in source['days']if d['date']==str(dt.date.fromisoformat(source['date'])+dt.timedelta(days=t//1440))),None)
    if day is None:return False
    local=t%1440
    if not any(a<=local and local+10<=z for a,z in day['activity']['operator_windows_min'].get(op['operator_id'],[])):return False
    if any(o['need_id']not in excluded and overlap((t,t+10),(o['start_min'],o['end_min']))and(op['operator_id']==o['operator_id']or op['room_id']==o['room_id'])for o in source['A']['operations']):return False
    base=t//1440*1440
    blocks=[(r['room_id'],base+r['start_min'],base+r['end_min'])for r in day['shared']['facility_reservations']]
    bath=next((r['room_id']for r in source.get('spatial_rooms',[])if r.get('census_room_class')=='bath'),None)
    if op['room_id']in('washroom','bathroom','bath'):blocks +=[(op['room_id'],base+x,base+x+10)for x in day['activity']['family_context']['bath_times_min'].values()]
    return not any(room==op['room_id']and overlap((t,t+10),(a,z))for room,a,z in blocks)

def program_candidates(source,aid,family):
    from service_nodes import enumerate_candidates
    return enumerate_candidates(source,aid,family,operation_allowed)


def contexts(w,source,defs):
    cachekey=(source['case_id'],digest(source['VPP_events']),digest(source['A']))
    if cachekey in _CTX:return _CTX[cachekey]
    from state_reference import event_state
    result={};assets={x['asset_id']:x for x in w['parameter_pack']['devices']}
    for key,d in defs.items():
        family=d['family'];aid=d['asset_ids'][0];device=assets[aid]
        u=rank('B53-request-behavior',source['case_id'],key)%10
        behavior='normal_response'if u<6 else'partial_response'if u==6 else'service_pressure'if u==7 else'opposing_request'if u==8 else'limited_opportunity_request'
        if any(x.get('unfavourable_variant_selected')for x in source['classification']['design_intent']['action_designs']if x['device_family']==family):behavior='opposing_request'
        candidates=program_candidates(source,aid,family)if family in('washer','dishwasher')else[]
        observations=[]
        for e in source['VPP_events']:
            details={}
            if family=='ev':
                controls=[]
                for a in source['A']['controls']:
                    if a['kind']!='ev_charge_window'or a['asset_id']!=aid or a['start_min']<DECISION:continue
                    bs=[x for x in source['B']['controls']if x['kind']=='ev_charge_window'and x['asset_id']==aid and x['need_id']==a['need_id']]
                    if any((x['start_min'],x['end_min'],x['stop_at_target_soc'])!=(a['start_min'],a['end_min'],a['stop_at_target_soc'])for x in bs):controls.append(a)
                conn=sum(intersection(a['start_min'],a['end_min'],e['start_min'],e['end_min'])for a in controls)
                charged=sum(intersection(a['start_min'],min(a['end_min'],a['start_min']+a['battery_energy_kWh']/(device['parameters']['charger_kw']*device['parameters']['efficiency'])*60),e['start_min'],e['end_min'])for a in controls)
                # Up capacity is bounded by actual required energy, not the full
                # uncharged connection. Down only exists while A would charge.
                timer_options=[(a,ev_timer_options(a,device['parameters'],e))for a in controls]
                changes=[(value-intersection(a['start_min'],a['start_min']+a['battery_energy_kWh']/(device['parameters']['charger_kw']*device['parameters']['efficiency'])*60,e['start_min'],e['end_min']))*(1 if e['direction']=='up'else-1)for a,options in timer_options for start,value in options]
                opportunity=max([0.]+changes)
                details={'A_connection_overlap_min':conn,'A_fixed_charge_overlap_min':charged,'feasible_timer_start_count':sum(len(options)for a,options in timer_options),'required_target_preserved_in_opportunity':True,'only_source_adjustable_windows_scored':True,'reference_is_not_observed_SOC':True}
            elif family in('washer','dishwasher'):
                def minutes(chain,delta):return sum(intersection(t['start_min']+delta,t['end_min']+delta,e['start_min'],e['end_min'])for t in chain)
                def energy(chain,delta):return sum(intersection(t['start_min']+delta,t['end_min']+delta,e['start_min'],e['end_min'])/60*device['parameters'].get(t['kind'],device['parameters'])['power_kw']for t in chain)
                current=sum(minutes(c['chain'],0)for c in candidates);current_energy=sum(energy(c['chain'],0)for c in candidates)
                changes=[(energy(c['chain'],q['delta_min'])-energy(c['chain'],0))*(1 if e['direction']=='up'else-1)for c in candidates for q in c['feasible_candidates']]
                maxgain=max([0]+changes);rated=max([device['parameters'].get(t['kind'],device['parameters'])['power_kw']for c in candidates for t in c['chain']]+[.1]);opportunity=maxgain*60/rated
                details={'A_fixed_program_overlap_min':current,'A_fixed_program_event_kWh':current_energy,'input_opportunity_kWh':maxgain,'input_opportunity_min_is_energy_equivalent_at_kw':rated,'eligibility_basis':'release+loading+operator+room+program_chain+retrieval+deadline;10min feasible input grid;power-weighted whole chain','feasible_candidate_count':sum(len(c['feasible_candidates'])for c in candidates),'service_boundaries':[{'need_id':c['need_id'],'release_min':c['release_min'],'deadline_min':c['deadline_min'],'earliest_feasible_start_min':min([c['A_start_min']+q['delta_min']for q in c['feasible_candidates']],default=None)}for c in candidates],'linked_automatic_dryer_included':family=='washer'and'dryer'in device['types']}
            else:
                kind='ac_setpoint'if family=='ac'else'tank_setpoint';permission=sum(intersection(x['start_min'],x['end_min'],e['start_min'],e['end_min'])for x in source['A']['controls']if x['kind']==kind and x['asset_id']==aid)
                reference=event_state(source,device,e)
                possible_up=0
                if reference.get('status')=='native_A_reference':
                    samples=reference['timestep_profile'].get('indoor_C'if family=='ac'else'tank_C',[])
                    axis=reference['request_axis']
                    for minute,temperature in samples:
                        a=next((x for x in source['A']['controls']if x['kind']==kind and x['asset_id']==aid and x['start_min']<=minute<x['end_min']),None)
                        if a is None:continue
                        if family=='ac':within=temperature<=a['heating_setpoint_C']+2 if axis=='heating'else temperature>=a['cooling_setpoint_C']-2
                        else:within=temperature<=min(65.,device['parameters']['maximum_C'],a['value_C']+5)
                        possible_up+=10*within
                opportunity=min(permission,reference.get('active_minutes',0))if e['direction']=='down'else possible_up
                details={'A_routine_permission_overlap_min':permission,'native_A_event_state':reference,'maximum_dose_threshold_crossing_minutes':possible_up,'opportunity_is_conditional_on_B_temperature_response':True,'physical_B_response_kw':None}
            observations.append({'event_id':e['event_id'],'direction':e['direction'],'target_kw':e['target_kw'],'start_min':e['start_min'],'end_min':e['end_min'],'input_opportunity_min':opportunity,**details})
        selected=max(observations,key=lambda x:(x['input_opportunity_min'],rank(source['case_id'],key,x['event_id'],'state-event-choice')))
        originalbehavior=behavior
        if selected['input_opportunity_min']<=1e-8 and behavior in('normal_response','partial_response'):behavior='limited_opportunity_request'
        if family=='ev'and behavior=='partial_response':behavior='service_window_request'
        thermal=selected.get('native_A_event_state',{})
        result[key]={'behavior':behavior,'input_behavior_assignment':originalbehavior,'event':selected,'all_event_input_states':observations,'program_service_candidates':candidates,'no_VPP_opportunity':selected['input_opportunity_min']<=1e-8,
          'thermal_axis_reference':thermal.get('request_axis','heating'),'thermal_axis_basis':thermal.get('axis_basis','not_applicable_or_unknown'),
          'reserve_budget_fraction':RESERVE_FRACTIONS[rank('B53-reserve-budget',source['case_id'],key)%len(RESERVE_FRACTIONS)],
          'reserve_placement':['event_start','event_end','after_event','before_departure','after_connection'][rank('B53-reserve-placement',source['case_id'],key)%5],
          'EV_request_path':['explicit_duration_budget','event_only_permission','departure_anchored_postponement','event_end_cutoff'][rank('B54-causal-EV-path',source['case_id'],key)%4],
          'service_fallback_policy':['load_then_run','retrieve_at_existing_visit','before_next_service'][rank('B55-service-habit',source['household_id'],key)%3],'selected_before_B':True,'uses_B_success_or_human_acceptance':False,'no_opportunity_policy':'input_service_boundary_or_unused_permission;no_response_claim;no_extra_handling'}
    _CTX.clear();_CTX[cachekey]=result
    return result


def ev_window(a,p,table,grade,context):
    exact=a['battery_energy_kWh']/(p['charger_kw']*p['efficiency'])*60;full=ceil10(exact)
    e=context['event'];behavior=context['behavior'];lo,hi=a['start_min'],a['end_min'];end=hi
    pressure=behavior in('service_pressure','service_window_request','partial_response')
    path=context['EV_request_path']
    if pressure:
        budget=max(10,ceil10(full*context['reserve_budget_fraction']))
        if path=='explicit_duration_budget':
            anchor={'event_start':e['start_min'],'event_end':e['end_min']-budget,'after_event':e['end_min'],'before_departure':hi-budget,'after_connection':lo}[context['reserve_placement']]
            start=max(lo,min(max(lo,hi-budget),anchor));end=min(hi,start+budget)
        elif path=='event_only_permission':
            start=max(lo,e['start_min']);end=min(hi,e['end_min'])
            if start>=end:start=max(lo,hi-budget);end=hi
        elif path=='departure_anchored_postponement':
            # A late-start timer consumes the real departure margin. The
            # independent time dose may leave less than the required energy.
            allowance=max(10,ceil10(exact*(.25,.5,1.,2.)[grade]));start=max(lo,hi-allowance)
        else:
            if e['end_min']<=lo:
                # An expired event cannot define a ten-minute charging dose.
                # Use the independently given departure reserve-budget policy.
                start=max(lo,hi-budget);end=hi
            else:start=lo;end=min(hi,e['end_min'])
    else:
        direction=e['direction']
        if behavior=='opposing_request':direction='up'if direction=='down'else'down'
        charged=intersection(lo,lo+exact,e['start_min'],e['end_min']);options=ev_timer_options(a,p,e)
        sign=1 if direction=='up'else-1
        candidates=[(start,(value-charged)*sign)for start,value in options if (value-charged)*sign>1e-8]
        if behavior=='limited_opportunity_request'or not candidates:
            start=lo;end=min(hi,lo+full)
        else:
            goal=e['target_kw']/p['charger_kw']*(e['end_min']-e['start_min'])*FACTORS[grade]
            enough=[x for x in candidates if x[1]>=goal-1e-8]
            start=min(enough,key=lambda x:(x[0],x[1]))[0]if enough else max(candidates,key=lambda x:(x[1],-x[0]))[0]
    start=min(hi-10,max(lo,int(start)));end=min(hi,max(start+10,int(end)))
    return start,end


def service_choice(source,a,c,options,context):
    from service_nodes import reachable_choice
    return reachable_choice(c,options,context['service_fallback_policy'])

def program_delta(source,a,native,old_delta,context,parameters):
    from service_nodes import select_program
    return select_program(source,a,native,old_delta,context,parameters)['delta_min']
