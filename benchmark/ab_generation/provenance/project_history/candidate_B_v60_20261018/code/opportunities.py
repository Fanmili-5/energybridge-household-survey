"""Enumerate causal B requests from ALL installed controllers and frozen A.

No B EnergyPlus result, human answer, net saving or target success is used to
choose a request. Physical efficacy remains a separately measured outcome.
"""
import math
from common import *
from strengths import controller_key, grade_table, patch_control
from planning import operation_allowed
from service_nodes import enumerate_candidates, reachable_choice

def ceil10(x):return int(math.ceil(x/10-1e-9)*10)
def intersection(a,b,c,d):return max(0,min(b,d)-max(a,c))
SERVICE_ONLY_BASES={'exact_existing_life_node','real_departure_readiness_reserve_request_without_VPP_gain'}

def all_definitions(w,c):
    out={}
    for device in w['parameter_pack']['devices']:
        if not set(device['types'])&{'washer','dishwasher','ac','water_heater','ev'}:continue
        key=controller_key(device)
        out.setdefault(key,{'controller_key':key,'family':key.split(':')[0],
            'asset_ids':[],'base_grade_index':rank('B58-independent-device-dose',c['case_id'],key)%4})['asset_ids'].append(device['asset_id'])
    return out

def behavior(c,key):
    # Benchmark design factors, not a claim about population frequencies or
    # household willingness. Genuine existing failure cases are preserved too.
    return 'opposing_request'if rank('B58-request-direction',c['case_id'],key)%8==0 else'normal_response'

def context(c,d,event,basis,details,beh=None):
    return {'behavior':beh or behavior(c,d['controller_key']),'event':copy.deepcopy(event),
        'all_event_input_states':details,'request_basis':basis,
        'opportunity_reference':'frozen A46 actual operating forecast and original life constraints',
        'no_B_result_or_human_answer_used':True,'no_opportunity_filler_allowed':True}

def event_gain(chain,delta,e,parameters):
    return sum((intersection(t['start_min']+delta,t['end_min']+delta,e['start_min'],e['end_min'])-
                intersection(t['start_min'],t['end_min'],e['start_min'],e['end_min']))/60*
               parameters.get(t['kind'],parameters)['power_kw']for t in chain)

def program_options(w,c,d,batches=None):
    aid=d['asset_ids'][0];family=d['family'];device=next(x for x in w['parameter_pack']['devices']if x['asset_id']==aid)
    table=grade_table(family,d['base_grade_index'],device);cap=table['requested_shift_min'];beh=behavior(c,d['controller_key'])
    if batches is None:batches=enumerate_candidates(c,aid,family,operation_allowed,all_A_tasks=True)
    out=[]
    for batch in batches:
        rows=[q for q in batch['feasible_candidates']if q['delta_min']
            and(q['program_start_min']<1920 and(q['program_start_min']>=DECISION or q['delta_min']==0))]
        for event in c['VPP_events']:
            direction=event['direction']
            if beh=='opposing_request':direction='up'if direction=='down'else'down'
            responding=[(q,event_gain(batch['chain'],q['delta_min'],event,device['parameters']))for q in rows
                if abs(q['delta_min'])<=cap]
            responding=[(q,g)for q,g in responding if g*(1 if direction=='up'else-1)>1e-7]
            if not responding:continue
            # Native programme doses must produce a programme change. Prefer
            # the assigned half-to-full dose band when it is feasible; a short
            # boundary change remains explicitly limited, never upgraded.
            dose_floor=ceil10(cap/2)
            in_band=[(q,g)for q,g in responding if abs(q['delta_min'])>=dose_floor]
            limited=not bool(in_band)
            if in_band:responding=in_band
            goal=event['target_kw']*(event['end_min']-event['start_min'])/60
            enough=[(q,g)for q,g in responding if abs(g)>=goal]
            cost=lambda q:(abs(q['delta_min']),abs(q['load_min']-batch['A_load_min'])+abs(q['unload_min']-batch['A_unload_min']),q['program_start_min'],q['unload_min'])
            q,g=min(enough,key=lambda z:cost(z[0]))if enough else min(responding,key=lambda z:(-abs(z[1]),cost(z[0])))
            out.append({'controller':d,'kind':'program','batch':batch,'choice':q,'event':event,
                'basis':'feasible_VPP_whole_chain_shift','behavior':beh,'A_reference_delta_event_kWh':g,
                'context':context(c,d,event,'feasible_VPP_whole_chain_shift',[],beh),
                'evidence':{'whole_load_to_retrieval_occupation_checked':True,'linked_dryer_included':True,
                    'release_operator_room_deadline_checked':True,'nonzero_program_overlap_change_kWh':g,
                    'native_programme_dose_band_min':[dose_floor,cap],
                    'limited_by_original_service_constraints':limited}})
        # A changed original retrieval/return/deadline node is a genuine human
        # service consequence even when this device has no VPP opportunity.
        for policy in('load_then_run','retrieve_at_existing_visit','before_next_service'):
            choice=reachable_choice(batch,rows,policy,minimum_change=True)
            if choice is None:continue
            event=min(c['VPP_events'],key=lambda e:abs(e['start_min']-choice['program_start_min']))
            out.append({'controller':d,'kind':'program','batch':batch,'choice':choice,'event':event,
                'basis':'exact_existing_life_node','behavior':'service_window_request',
                'A_reference_delta_event_kWh':event_gain(batch['chain'],choice['delta_min'],event,device['parameters']),
                'context':context(c,d,event,'exact_existing_life_node',[],'service_window_request'),
                'evidence':{'selected_node':choice['selected_node'],'node_reached_exactly':True,
                    'whole_load_to_retrieval_occupation_checked':True,'VPP_response_claim':False}})
    return out

def ev_options(w,c,d):
    aid=d['asset_ids'][0];device=next(x for x in w['parameter_pack']['devices']if x['asset_id']==aid);p=device['parameters'];out=[]
    # This is the common-A continuous SOC ledger, not nominal permission time.
    steps=c['EV_continuous_reference']['A']['charging_steps'];beh=behavior(c,d['controller_key'])
    for a in c['A']['controls']:
        if a['kind']!='ev_charge_window'or a['asset_id']!=aid or not DECISION<=a['start_min']<1920:continue
        active=[x for x in steps if x['need_id']==a['need_id']and x['grid_kWh']>1e-9]
        if not active:continue
        energy=sum(x['grid_kWh']for x in active);exact=energy/p['charger_kw']*60
        latest=a['end_min']-ceil10(exact)
        if latest<=a['start_min']:continue
        def overlap_energy(start,e):
            return p['charger_kw']*intersection(start,start+exact,e['start_min'],e['end_min'])/60
        for event in c['VPP_events']:
            current=sum(x['grid_kWh']*intersection(x['start_min'],x['end_min'],event['start_min'],event['end_min'])/(x['end_min']-x['start_min'])for x in active)
            direction=event['direction']
            if beh=='opposing_request':direction='up'if direction=='down'else'down'
            candidates=[]
            # Native timer grid; discard every start that produces no actual
            # A charging overlap change, regardless of connection length.
            for start in range(a['start_min']+10,latest+1,10):
                gain=overlap_energy(start,event)-current
                if gain*(1 if direction=='up'else-1)>1e-7:candidates.append((start,gain))
            if not candidates:continue
            dose=(.25,.5,1.,1.5)[d['base_grade_index']];goal=event['target_kw']*(event['end_min']-event['start_min'])/60*dose
            enough=[x for x in candidates if abs(x[1])>=goal]
            start,gain=min(enough,key=lambda x:x[0])if enough else min(candidates,key=lambda x:(-abs(x[1]),x[0]))
            out.append({'controller':d,'kind':'ev','original':a,'start_min':start,'end_min':a['end_min'],
                'event':event,'basis':'continuous_A_charge_shift_into_or_out_of_VPP','behavior':beh,
                'context':context(c,d,event,'continuous_A_charge_shift_into_or_out_of_VPP',[],beh),
                'evidence':{'A_actual_grid_kWh_in_connection':energy,'A_charging_steps':active,
                    'A_event_grid_kWh':current,'predicted_event_delta_kWh':gain,
                    'required_target_and_original_plug_unplug_preserved':True,
                    'unused_permission_tail_is_not_opportunity':True}})
        # A separate readiness proposal is legitimate when there is no VPP
        # charging opportunity: charge on the existing connection, finish a
        # declared reserve before its real disconnect/departure. This changes
        # charging/SOC availability, rather than trimming an idle tail. It is
        # expressly NOT presented as a VPP response or a household preference.
        if not any(x['original']['need_id']==a['need_id']for x in out):
            reserve=(240,120,60,30)[d['base_grade_index']]
            start=a['end_min']-ceil10(exact)-reserve
            anchor={'kind':'ready_before_real_disconnect','minute':a['end_min'],'reserve_min':reserve}
            if start>=1920:
                # Use a real recorded night-parking/bedtime boundary when a
                # departure-anchored timer would leave the whole case window.
                # The timer needs no person to return or plug in again.
                plug=next(o for o in c['A']['operations']if o['need_id']==a['need_id']and o['kind']=='EV_plug')
                day=next(x for x in c['days']if x['date']==str(dt.date.fromisoformat(c['date'])+dt.timedelta(days=a['start_min']//1440)))
                sleeps=[x for x in day['activity']['member_calendars'].get(plug['operator_id'],[])if x['activity']=='sleep_rest'and x['start_min']>=720]
                times=[a['start_min']//1440*1440+x['start_min']for x in sleeps]
                times=[t for t in times if a['start_min']<t<=latest and t<1920]
                if times:
                    start=min(times);anchor={'kind':'recorded_operator_night_rest_start','minute':start,'operator_id':plug['operator_id']}
            if start>a['start_min']and start<1920:
                event=min(c['VPP_events'],key=lambda e:abs(e['end_min']-start))
                basis='real_departure_readiness_reserve_request_without_VPP_gain'
                out.append({'controller':d,'kind':'ev','original':a,'start_min':start,'end_min':a['end_min'],
                    'event':event,'basis':basis,'behavior':'service_window_request',
                    'context':context(c,d,event,basis,[],'service_window_request'),
                    'evidence':{'A_actual_grid_kWh_in_connection':energy,'A_charging_steps':active,
                        'readiness_reserve_requested_min':reserve,'real_connection_end_min':a['end_min'],
                        'actual_timer_anchor':anchor,'readiness_reserve_actual_min':a['end_min']-start-ceil10(exact),
                        'A_event_grid_kWh':sum(x['grid_kWh']*intersection(x['start_min'],x['end_min'],event['start_min'],event['end_min'])/(x['end_min']-x['start_min'])for x in active),
                        'VPP_response_claim':False,'not_inferred_household_preference':True,
                        'required_target_and_original_plug_unplug_preserved':True,
                        'unused_permission_tail_is_not_opportunity':True}})
    return out

def control_at(c,kind,aid,t):
    return next((x for x in c['A']['controls']if x['kind']==kind and x['asset_id']==aid and x['start_min']<=t<x['end_min']),None)

def occupied(c,room,t):
    if 'days'not in c:return True # Small physics fixtures have no calendar.
    day=next((x for x in c['days']if x['date']==str(dt.date.fromisoformat(c['date'])+dt.timedelta(days=t//1440))),None)
    return bool(day and any(x.get('location')=='home'and x.get('room_id')==room and x['start_min']<=t%1440<x['end_min']
        for rows in day['activity']['member_calendars'].values()for x in rows))

def contiguous_end(c,kind,aid,start,limit,room=None):
    """Fan-mode records do not end a continuous thermostat intervention."""
    end=start
    while end<limit:
        if control_at(c,kind,aid,end)is None or(room is not None and not occupied(c,room,end)):break
        end+=10
    return min(end,limit)

def thermal_options(w,c,d,reference):
    assets={x['asset_id']:x for x in w['parameter_pack']['devices']};family=d['family'];kind='ac_setpoint'if family=='ac'else'tank_setpoint'
    table=grade_table(family,d['base_grade_index'],assets[d['asset_ids'][0]]);beh=behavior(c,d['controller_key']);out=[]
    delta=table['setpoint_delta_C'if family=='ac'else'target_delta_C'];cap=table['exposure_cap_min']
    for event in c['VPP_events']:
        wanted=event['direction']
        if beh=='opposing_request':wanted='up'if wanted=='down'else'down'
        eligible=[]
        for t in reference['grid_min']:
            if not event['start_min']<=t<event['end_min']:continue
            index=(t-DECISION)//10;changes=[]
            for aid in d['asset_ids']:
                a=control_at(c,kind,aid,t);ref=reference['devices'][aid]
                if a is None:continue
                if family=='ac'and not occupied(c,assets[aid].get('room_id'),t):continue
                temp=ref['temperature_at_start_C'][index]
                if family=='ac':
                    heat=a['heating_setpoint_C'];cool=a['cooling_setpoint_C']
                    axis='heating'if abs(temp-heat)<abs(temp-cool)else'cooling'
                    native=heat if axis=='heating'else cool
                    new=native+delta*(1 if(axis=='heating')==(wanted=='up')else-1)
                    # Do not count fan or cold-weather crankcase standby, or
                    # a saturated unit far from either requested thermostat.
                    active=ref['thermal_system_kWh_excluding_fan'][index]>.025
                    if wanted=='down':possible=(new+.15<=temp<=heat+.4 if axis=='heating'else cool-.4<=temp<=new-.15)
                    else:possible=(heat-.4<=temp<=new-.25 if axis=='heating'else new+.25<=temp<=cool+.4)
                    if not possible:continue
                    values={'heating_setpoint_C':new if axis=='heating'else min(heat,new-2.),
                        'cooling_setpoint_C':new if axis=='cooling'else max(cool,new+2.),
                        'fan_operating_mode':a.get('fan_operating_mode',0)}
                else:
                    new=max(45.,min(65.,assets[aid]['parameters']['maximum_C'],a['value_C']+delta*(1 if wanted=='up'else-1)))
                    if abs(new-a['value_C'])<1e-8:continue
                    deadband=assets[aid]['parameters']['deadband_C'];active=ref['electric_kWh'][index]>.001
                    possible=active and temp>=new+.15 if wanted=='down'else temp<=new-deadband-.15
                    if possible and wanted=='up':
                        # A target change cannot add electricity while this
                        # fixed-power element is already on throughout the
                        # whole proposed exposure. Read future A headroom,
                        # including a possible extension after A cycles off.
                        par=assets[aid]['parameters']
                        maximum_kWh=par['heater_capacity_W']/par['efficiency']/1000/6
                        end=contiguous_end(c,kind,aid,t,min(event['end_min'],t+cap))
                        available=sum(max(0.,maximum_kWh-ref['electric_kWh'][(minute-DECISION)//10])for minute in range(t,end,10))
                        possible=available>1e-6
                    if not possible:continue
                    axis='tank';values={'value_C':new}
                changes.append({'asset_id':aid,'values':values,'axis':axis,'A_temperature_C':temp,'A_active':active,
                    'A_electric_kWh':ref['electric_kWh'][index],'A_control':a})
            if changes and(wanted=='up'or any(x['A_active']for x in changes)):eligible.append((t,changes))
        if not eligible:continue
        # Select a real interval that can carry the assigned exposure before
        # falling back to an explicitly shortened episode. Internal fan-mode
        # changes are preserved, rather than silently clipping a 60min request
        # to the first 10min control record.
        def length(row):
            t,changes=row
            return max(contiguous_end(c,kind,x['asset_id'],t,min(event['end_min'],t+cap),
                assets[x['asset_id']].get('room_id')if family=='ac'else None)-t for x in changes)
        lo,first=min(eligible,key=lambda row:(-length(row),row[0]));hi=min(event['end_min'],lo+cap)
        patches=[]
        for change in first:
            aid=change['asset_id'];end=contiguous_end(c,kind,aid,lo,hi,assets[aid].get('room_id')if family=='ac'else None)
            for a in c['A']['controls']:
                if a['kind']!=kind or a['asset_id']!=aid:continue
                begin=max(lo,a['start_min']);stop=min(end,a['end_min'])
                if begin>=stop:continue
                if family=='ac':
                    axis=change['axis'];native=a['heating_setpoint_C'if axis=='heating'else'cooling_setpoint_C']
                    new=native+delta*(1 if(axis=='heating')==(wanted=='up')else-1)
                    values={'heating_setpoint_C':new if axis=='heating'else min(a['heating_setpoint_C'],new-2.),
                        'cooling_setpoint_C':new if axis=='cooling'else max(a['cooling_setpoint_C'],new+2.),
                        'fan_operating_mode':a.get('fan_operating_mode',0)}
                else:values={'value_C':max(45.,min(65.,assets[aid]['parameters']['maximum_C'],a['value_C']+delta*(1 if wanted=='up'else-1)))}
                patches.append({**change,'A_control':a,'values':values,'start_min':begin,'end_min':stop})
        if not patches:continue
        out.append({'controller':d,'kind':'thermal','patches':patches,'event':event,
            'basis':'A_active_thermostat_or_attainable_threshold_crossing','behavior':beh,
            'context':{**context(c,d,event,'A_active_thermostat_or_attainable_threshold_crossing',[],beh),
                'thermal_axis_reference':first[0]['axis']},
            'evidence':{'A_reference_path':reference.get('_path'),'A_reference_sha256':reference.get('_sha256'),
                'qualifying_interval_count':len(eligible),'direction_requested':wanted,
                'exposure_requested_min':cap,'exposure_available_min':max(x['end_min']for x in patches)-lo,
                'limited_by_original_service_constraints':max(x['end_min']for x in patches)-lo<min(cap,event['end_min']-event['start_min']),
                'occupied_room_required':family=='ac','continuous_A_permission_not_internal_record':True,
                'actual_B_thermal_effect_not_guaranteed':True,'fan_and_standby_alone_not_eligible':True,
                'saturated_far_from_setpoint_not_curtailment_opportunity':True}})
    return out

def catalogue(w,c,reference,program_batches=None):
    defs=all_definitions(w,c);result={}
    for key,d in sorted(defs.items()):
        if d['family']in('washer','dishwasher'):options=program_options(w,c,d,(program_batches or{}).get(key))
        elif d['family']=='ev':options=ev_options(w,c,d)
        else:options=thermal_options(w,c,d,reference)
        result[key]=options
    return defs,result

def apply(plan,c,option):
    d=option['controller'];event=option['event'];key=d['controller_key']
    if option['kind']=='program':
        batch=option['batch'];q=option['choice'];nid=batch['need_id'];delta=q['delta_min']
        formation={'need_id':nid,'asset_id':d['asset_ids'][0],'controller_key':key,
            'request_basis':option['basis'],'selection_rule':'actual_VPP_chain_overlap_or_exact_input_life_node',
            'selected_node':q.get('selected_node'),'life_node_reached':q.get('selected_node')is not None,
            'input_behavior':option['behavior'],'release_min':batch['release_min'],'deadline_min':batch['deadline_min'],
            'A_start_min':batch['A_start_min'],'B_start_min':q['program_start_min'],'actual_shift_min':delta,
            'B_load_min':q['load_min'],'B_unload_min':q['unload_min'],'B_chain_finish_min':q['finish_min'],
            'individual_A_context_feasible':True,'joint_B_constraints_checked_separately':True,
            'selected_event_id':event['event_id'],'no_response_claim':option['basis']=='exact_existing_life_node',
            'asset_hold_conflicts_A':q['asset_hold_conflicts']}
        plan.setdefault('program_request_plans',[]).append(formation)
        for task in plan['tasks']:
            if delta and task['need_id']in(nid,nid+':dry'):
                task['start_min']+=delta;task['end_min']+=delta;task['request_formation']=formation
        for op in plan['operations']:
            if op['need_id']==nid and op['kind']in('load','unload'):
                op['start_min']=q[op['kind']+'_min'];op['end_min']=op['start_min']+10
    elif option['kind']=='ev':
        a=option['original'];x=next(x for x in plan['controls']if x==a);shift=option['start_min']-a['start_min']
        x.update(start_min=option['start_min'],end_min=option['end_min'],
            actual_charge_end_min=a['actual_charge_end_min']+shift,
            formation_path='actual_A_charging_shift;original_connection_and_target_preserved')
    else:
        for patch in option['patches']:
            kind='ac_setpoint'if d['family']=='ac'else'tank_setpoint';aid=patch['asset_id'];lo=patch['start_min'];hi=patch['end_min']
            patch_control(plan,{'B':c['A']},kind,aid,lo,hi,patch['values'])
            plan.setdefault('thermal_phase_requests',[]).append({'controller_key':key,'asset_id':aid,
                'kind':kind,'phase':'event','start_min':lo,'end_min':hi,
                'load_direction_requested':option['evidence']['direction_requested'],
                'selected_event_id':event['event_id'],'event_interval_min':[event['start_min'],event['end_min']],
                'behavior':option['behavior'],'A_permission_present':True,'withdraw_permission':False,
                'restore_A_at_min':hi,'B_physical_success_required':False})

def option_key(o):
    return (o['basis']in SERVICE_ONLY_BASES,o.get('evidence',{}).get('limited_by_original_service_constraints',False),
        rank('B58-option',o['controller']['controller_key'],o['event']['event_id'],o.get('choice'),o.get('start_min')))

def select(c,defs,options,coverage):
    # The availability of a genuine event action is decided BEFORE fairness
    # across controller families. A life-node fallback must not crowd out an
    # available event action or pad a portfolio to a requested device count.
    event_options={k:[o for o in values if o['basis']not in SERVICE_ONLY_BASES]for k,values in options.items()}
    eligible=[k for k,x in event_options.items()if x]
    if not eligible:return []
    desired=1+rank('B58-input-portfolio-size',c['case_id'])%3
    focus=c.get('scenario_formation',{}).get('focus_controller_key')
    keys=sorted(eligible,key=lambda k:(k!=focus,coverage.get(k,0),coverage.get('family:'+defs[k]['family'],0),rank('B58-controller',c['case_id'],k)))[:desired]
    chosen=[min(event_options[k],key=option_key)for k in keys]
    for k in keys:
        coverage[k]=coverage.get(k,0)+1;f='family:'+defs[k]['family'];coverage[f]=coverage.get(f,0)+1
    return chosen
