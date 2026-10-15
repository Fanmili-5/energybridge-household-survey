"""Input-only contrast admission. Encoding thresholds are not human JNDs."""
import collections
from common import *

PROTOCOL={'schema':'eb.task_contrast_protocol.v29','version':'v29.1',
 'minimum_temperature_request_C':.5,'minimum_temperature_changed_minutes':30,
 'minimum_program_start_change_min':20,'minimum_availability_difference_min':20,
 'minimum_manual_time_change_min':10,'human_JND_validated':False,
 'energy_difference_floor':None,'human_answer_generated':False,
 'preserved':['household','policy','hardware','dates','mandatory_needs','frozen_A','common_history'],
 'same_outcome_classes':['temperature_permission_tradeoff','charging_permission_tradeoff','no_cooling_need_extra_request'],
 'no_implicit_near_indifference_controls':True}

def control_segments(p,kind=None):
    keys={(x['asset_id'],x['kind'])for s in('A','B')for x in p[s]['controls']if kind is None or x['kind']==kind};out=[]
    for aid,typ in sorted(keys):
        sides={s:[x for x in p[s]['controls']if x['asset_id']==aid and x['kind']==typ]for s in('A','B')}
        edges=sorted({x[k]for xs in sides.values()for x in xs for k in('start_min','end_min')})
        for start,end in zip(edges,edges[1:]):
            values={s:next((x.get('value_C',True)for x in xs if x['start_min']<=start and end<=x['end_min']),None)for s,xs in sides.items()}
            if values['A']==values['B']:continue
            row={'asset_id':aid,'kind':typ,'start_min':start,'end_min':end,'A':values['A'],'B':values['B']}
            if out and all(out[-1][k]==row[k]for k in('asset_id','kind','A','B'))and out[-1]['end_min']==start:out[-1]['end_min']=end
            else:out.append(row)
    return out

def metrics(p):
    lo,hi=p['primary_evaluation_min'];segments=[{**x,'start_min':max(lo,x['start_min']),'end_min':min(hi,x['end_min'])}for x in control_segments(p)if overlap((x['start_min'],x['end_min']),(lo,hi))]
    temp=[x for x in segments if x['kind']=='ac_setpoint'and x['A']is not None and x['B']is not None]
    changes=[abs(x['B']-x['A'])for x in temp]
    avail=[x for x in segments if(x['A']is None)!=(x['B']is None)]
    shifts=[];manual=[]
    for field,key,dest in [('tasks','task_id',shifts),('operations','operation_id',manual)]:
        a={x[key]:x for x in p['A'][field]};b={x[key]:x for x in p['B'][field]}
        for uid in a.keys()|b.keys():
            x=a.get(uid);y=b.get(uid)
            if x==y or not any(z and overlap((z['start_min'],z['end_min']),(lo,hi))for z in(x,y)):continue
            dest.append(abs(y['start_min']-x['start_min'])if x and y else(y or x)['end_min']-(y or x)['start_min'])
    kinds=[]
    if max(shifts,default=0)>=PROTOCOL['minimum_program_start_change_min']:kinds.append('program_timing_tradeoff')
    if max(manual,default=0)>=PROTOCOL['minimum_manual_time_change_min']:kinds.append('manual_action_tradeoff')
    if temp and min(changes)>=PROTOCOL['minimum_temperature_request_C']-1e-8 and sum(x['end_min']-x['start_min']for x in temp)>=PROTOCOL['minimum_temperature_changed_minutes']:kinds.append('temperature_permission_tradeoff')
    availability=collections.Counter()
    for x in avail:availability[x['kind']]+=x['end_min']-x['start_min']
    if availability['ev_charge_window']>=PROTOCOL['minimum_availability_difference_min']:kinds.append('charging_permission_tradeoff')
    if availability['tank_setpoint']>=PROTOCOL['minimum_availability_difference_min']:kinds.append('hotwater_timing_tradeoff')
    if availability['ac_setpoint']>=PROTOCOL['minimum_availability_difference_min']:kinds.append('cooling_availability_tradeoff')
    family_claim_consistent=True
    if p['proposal']['family']=='additional_AC_request_without_cooling_need':
        added=[x for x in avail if x['kind']=='ac_setpoint'and x['A']is None and x['B']is not None]
        family_claim_consistent=bool(added)and sum(x['end_min']-x['start_min']for x in added)>=PROTOCOL['minimum_availability_difference_min']and not any(n['kind']=='ac'and n['asset_id']==x['asset_id']and overlap((n['release_min'],n['deadline_min']),(x['start_min'],x['end_min']))for n in p['needs_A']for x in added)
        kinds=['no_cooling_need_extra_request']if family_claim_consistent else[]
    micro=any(0<x<PROTOCOL['minimum_temperature_request_C']-1e-8 for x in changes)
    return {'admitted':bool(kinds)and not micro and family_claim_consistent,'dimensions':kinds,'micro_temperature_request':micro,'family_claim_consistent':family_claim_consistent,
      'temperature_deltas_C':sorted(set(round(x,8)for x in changes)),
      'temperature_changed_asset_minutes':sum(x['end_min']-x['start_min']for x in temp),
      'availability_changed_asset_minutes':dict(availability),'program_shifts_min':shifts,'manual_time_changes_min':manual,
      'classification_is_not_acceptance_label':True,'perceptual_or_behavioral_validity_proven':False}

def classify_equal_outcome(p):
    kinds=metrics(p)['dimensions']
    return next((k for k in PROTOCOL['same_outcome_classes']if k in kinds),'other_visible_timing_or_handling_contrast')

def invariant_errors(p,old,w,old_world_sha):
    from checks import assess
    errors=[]
    if sha(OUT/'worlds'/f'{w["household_id"]}.json')!=old_world_sha:errors.append('HOUSEHOLD_OR_POLICY_CHANGED')
    for key in('household_id','date','world_sha256','parameter_pack_sha256','devices_sha256','needs_A','needs_B','A','dated_activity_days','world','common_initialization_binding','common_A_departure_care_bookings'):
        if p[key]!=old[key]:errors.append('FROZEN_CHANGED:'+key)
    errors+=assess(p)['integrity_errors']
    if assess(p)['constraint_flags']['A']:errors.append('NORMAL_A_CONFLICT')
    if not metrics(p)['admitted']:errors.append('CONTRAST_NOT_ADMITTED')
    return errors
