"""A-only, resource-conditioned benchmark dispatch scenes, frozen before B.

These are constructed household decision scenarios, not observations of grid
event frequencies. Directions, targets, durations and event counts are inherited.
Only one event clock may be re-anchored to an existing A operating/service episode.
No B EnergyPlus result, saving, respondent score or success label is consulted.
"""
from common import *
from opportunities import (all_definitions,program_options,ev_options,thermal_options,
    SERVICE_ONLY_BASES,occupied,ceil10,option_key)
from strengths import grade_table
from planning import operation_allowed
from service_nodes import enumerate_candidates,reachable_choice

def event_at(c,event,start):
    result=copy.deepcopy(event);duration=event['end_min']-event['start_min']
    result.update(start_min=start,end_min=start+duration,
        event_id='vpp:'+digest(['B60-A-only-scene',c['case_id'],event['event_id'],start])[:20])
    return result

def blocks(times):
    result=[]
    for t in sorted(set(times)):
        if result and result[-1][1]==t:result[-1][1]=t+10
        else:result.append([t,t+10])
    return result

def anchors(w,c,d,ref,batches,duration):
    """Only real A starts, finishes, feasible timers and service boundaries."""
    assets={x['asset_id']:x for x in w['parameter_pack']['devices']};family=d['family'];out=set()
    def add(t):
        # Do not invent an out-of-horizon clock or a pre-decision instruction.
        t=ceil10(t)
        if DECISION<=t and t+duration<=1920:out.add(t)
    if family in('washer','dishwasher'):
        table=grade_table(family,d['base_grade_index'],assets[d['asset_ids'][0]])
        for batch in batches:
            rows=[q for q in batch['feasible_candidates']if q['delta_min']
                and q['program_start_min']>=DECISION
                and abs(q['delta_min'])<=table['requested_shift_min']]
            if not rows:continue
            choices=[]
            for policy in('load_then_run','retrieve_at_existing_visit','before_next_service'):
                q=reachable_choice(batch,rows,policy)
                if q:choices.append(q)
            choices.extend([min(rows,key=lambda q:q['program_start_min']),max(rows,key=lambda q:q['program_start_min'])])
            for task in batch['chain']:
                add(task['start_min']);add(task['end_min']-duration)
                for q in choices:
                    add(task['start_min']+q['delta_min']);add(task['end_min']+q['delta_min']-duration)
    elif family=='ev':
        p=assets[d['asset_ids'][0]]['parameters']
        for a in c['A']['controls']:
            if a['kind']!='ev_charge_window'or a['asset_id']not in d['asset_ids']or not DECISION<=a['start_min']<1920:continue
            steps=[x for x in c['EV_continuous_reference']['A']['charging_steps']if x['need_id']==a['need_id']and x['grid_kWh']>1e-9]
            if not steps:continue
            exact=sum(x['grid_kWh']for x in steps)/p['charger_kw']*60
            add(steps[0]['start_min']);add(steps[-1]['end_min']-duration)
            # Real connection end bounds the last complete charging cycle.
            add(a['end_min']-ceil10(exact));add(a['end_min']-duration)
            for day in c['days']:
                base=(dt.date.fromisoformat(day['date'])-dt.date.fromisoformat(c['date'])).days*1440
                for rows in day['activity']['member_calendars'].values():
                    for x in rows:
                        t=base+x['start_min']
                        if x['activity']=='sleep_rest'and a['start_min']<t<=a['end_min']-ceil10(exact):add(t)
    else:
        kind='ac_setpoint'if family=='ac'else'tank_setpoint'
        for aid in d['asset_ids']:
            device=assets[aid];r=ref['devices'][aid]
            active=[]
            for t in ref['grid_min']:
                a=next((x for x in c['A']['controls']if x['kind']==kind and x['asset_id']==aid and x['start_min']<=t<x['end_min']),None)
                if a is None or(family=='ac'and not occupied(c,device.get('room_id'),t)):continue
                i=(t-DECISION)//10
                if (r['thermal_system_kWh_excluding_fan'][i]>.025 if family=='ac'else r['electric_kWh'][i]>.001):active.append(t)
            for lo,hi in blocks(active):add(lo);add(hi-duration)
            for a in c['A']['controls']:
                if a['kind']==kind and a['asset_id']==aid:
                    add(a['start_min']);add(a['end_min']-duration)
    return sorted(out)

def prepare(w,c,ref,coverage):
    defs=all_definitions(w,c);batches={};candidates=[]
    for key,d in sorted(defs.items()):
        family=d['family']
        if family in('washer','dishwasher'):
            batches[key]=enumerate_candidates(c,d['asset_ids'][0],family,operation_allowed,all_A_tasks=True)
        probes=[];parents={}
        for index,event in enumerate(c['VPP_events']):
            starts=set(anchors(w,c,d,ref,batches.get(key,[]),event['end_min']-event['start_min']))
            starts.add(event['start_min'])
            for start in sorted(starts):
                e=event_at(c,event,start)
                # Other given windows remain fixed. No overlap is introduced.
                if any(j!=index and overlap((e['start_min'],e['end_min']),(x['start_min'],x['end_min']))for j,x in enumerate(c['VPP_events'])):continue
                probes.append(e);parents[e['event_id']]=(index,event)
        trial={**c,'VPP_events':probes}
        if family in('washer','dishwasher'):options=program_options(w,trial,d,batches[key])
        elif family=='ev':options=ev_options(w,trial,d)
        else:options=thermal_options(w,trial,d,ref)
        real=[o for o in options if o['basis']not in SERVICE_ONLY_BASES]
        for option in real:
            index,parent=parents[option['event']['event_id']]
            candidates.append((key,option,index,parent))
    if not candidates:raise ValueError('NO_REAL_A_SCENE_OPPORTUNITY:'+c['case_id'])
    # Coverage operates inside the real opportunity set, never by adding a
    # retrieval-only controller. No candidate is ranked by an actual B outcome.
    focus=min({k for k,_,_,_ in candidates},key=lambda k:(coverage.get(k,0),coverage.get('family:'+defs[k]['family'],0),rank('B60-focus-controller',c['case_id'],k)))
    choices=[x for x in candidates if x[0]==focus]
    def choice_key(row):
        _,option,_,parent=row
        return (option['evidence'].get('limited_by_original_service_constraints',False),
            option['event']['start_min']!=parent['start_min'],option_key(option))
    _,chosen,index,parent=min(choices,key=choice_key)
    events=copy.deepcopy(c['VPP_events']);events[index]=copy.deepcopy(chosen['event'])
    events.sort(key=lambda e:e['start_min'])
    for event in events:
        event.update(request_basis='B60 A-only resource-conditioned decision scenario;EB duration/direction/target factors;not observed grid dispatch',
            same_station_date_has_same_requests=False,
            selection_uses_household_assets_A_B_outcomes_or_answers=True,
            selection_uses_frozen_A_and_constraints=True,selection_uses_B_results_or_human_answers=False,
            scenario_id='scene:'+digest(['B60',c['case_id']])[:20],
            multi_window_design={'directions':[e['direction']for e in events],'target_kw':[e['target_kw']for e in events],
                'input_only':True,'event_count_and_direction_target_duration_factors_inherited':True})
    scene={**c,'VPP_events':events,'scenario_formation':{
        'schema':'eb.A_only_decision_scene.v60','focus_controller_key':focus,'focus_family':defs[focus]['family'],
        'original_events':copy.deepcopy(c['VPP_events']),'focus_event_parent_id':parent['event_id'],
        'focus_event_id':chosen['event']['event_id'],'clock_changed':parent['start_min']!=chosen['event']['start_min'],
        'focus_input_opportunity_basis':chosen['basis'],'candidate_real_controller_count':len({k for k,_,_,_ in candidates}),
        'conditioned_on_A_operating_opportunities':True,'not_a_grid_or_population_frequency_sample':True,
        'B_physical_results_or_human_answers_used':False,'target_success_not_guaranteed':True}}
    from opportunities import catalogue
    definitions,options=catalogue(w,scene,ref,batches)
    assert any(o['basis']not in SERVICE_ONLY_BASES for o in options[focus])
    return scene,definitions,options
