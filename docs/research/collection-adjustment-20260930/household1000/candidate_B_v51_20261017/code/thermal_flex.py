"""Prospective two-phase thermal requests; hardware envelope differs from A routine."""
import collections
from common import *

def covered(spans,a,b):return all(any(lo<=t<t+10<=hi for lo,hi in spans)for t in range(a,b,10))
def opportunity_options(c,e):
    options=[]
    for aid,z in sorted(c.get('thermal_control_context',{}).items()):
        actual=z['actual_occupied_intervals_min'];hardware=z['hardware_request_intervals_min'];maximum=z['maximum_preconditioning_lead_min']
        if e['direction']=='up':
            targets=[a for a,b in actual if e['start_min']<a<=e['end_min']+maximum]
            for target in targets:
                a=max(DECISION,e['start_min'],target-maximum);b=min(target,e['end_min'])
                if a<b and covered(hardware,a,b) and not covered(z['A_permission_intervals_min'],a,b):options.append({'asset_id':aid,'room_id':z['room_id'],'target_use_min':target,'maximum_pre_start_min':a,'pre_end_min':b})
        else:
            for lo,hi in actual:
                if not overlap((lo,hi),(e['start_min'],e['end_min'])):continue
                target=max(lo,e['start_min']);a=max(DECISION,e['start_min']-maximum,target-maximum);b=e['start_min']
                if a<b and covered(hardware,a,b):options.append({'asset_id':aid,'room_id':z['room_id'],'target_use_min':target,'maximum_pre_start_min':a,'pre_end_min':b})
    return options

def closest_reference(c,aid,target):
    xs=[x for x in c['A']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid]
    return min(xs,key=lambda x:(0 if x['start_min']<=target<x['end_min']else min(abs(x['start_min']-target),abs(x['end_min']-target)),x['start_min'],x['need_id']))

def apply_bounds(plan,c,aids,a,b,dh,dc,add,target):
    added={};actual={}
    for aid in aids:
        xs=[x for x in plan['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid and overlap((a,b),(x['start_min'],x['end_min']))]
        bounds=sorted({a,b}|{max(a,min(b,x[k]))for x in xs for k in('start_min','end_min')});pieces=[];minutes=[];new_minutes=[]
        for lo,hi in zip(bounds,bounds[1:]):
            old=next((x for x in xs if x['start_min']<=lo<hi<=x['end_min']),None)
            if old is None and not add:continue
            if old is not None and dh==0 and dc==0:continue
            ref=old or closest_reference(c,aid,target);z=c['thermal_control_context'][aid]
            h=ref['heating_setpoint_C']if old else z['usual_heating_setpoint_C'];v=ref['cooling_setpoint_C']if old else z['usual_cooling_setpoint_C']
            q={**ref,'start_min':lo,'end_min':hi,'heating_setpoint_C':h+dh,'cooling_setpoint_C':v+dc,'value_C':v+dc,'heating_and_cooling_deadband_C':v+dc-h-dh}
            if old is None:q.update(fan_operating_mode=0,actuation_purpose='prospective_thermal_storage;linked_to_existing_comfort_service')
            pieces.append(q);minutes.extend(range(lo,hi,10))
            new_minutes.extend(t for t in range(lo,hi,10)if not any(x['kind']=='ac_setpoint'and x['asset_id']==aid and x['start_min']<=t<x['end_min']for x in c['A']['controls']))
        for old in xs:
            if dh==0 and dc==0:continue
            plan['controls'].remove(old)
            if old['start_min']<a:plan['controls'].append({**old,'end_min':a})
            if old['end_min']>b:plan['controls'].append({**old,'start_min':b})
        plan['controls'].extend(pieces);added[aid]=len(new_minutes)*10;actual[aid]=minutes
    return added,actual

def make_preconditioning(plan,w,c,e,level):
    options=opportunity_options(c,e)
    if not options:raise ValueError('NO_LIFE_SUPPORTED_PRECONDITIONING_OPPORTUNITY')
    x=min(options,key=lambda x:(-min(x['pre_end_min']-x['maximum_pre_start_min'],60),abs(x['target_use_min']-e['start_min']),rank(c['case_id'],e['event_id'],x['asset_id'],x['target_use_min'])))
    target=x['target_use_min'];lead=[20,40,60,120][level];a=max(x['maximum_pre_start_min'],(target if e['direction']=='up'else e['start_min'])-lead);b=x['pre_end_min']
    # An insufficient given lead yields a real unchanged candidate; no
    # fabricated10min action is added merely to distinguish dose levels.
    short_lead=a>=b
    if short_lead:
        return {'device_family':'ac','asset_id':x['asset_id'],'affected_asset_ids':[],'room_id':x['room_id'],'mode':'dual_thermostat','start_min':e['start_min'],'end_min':e['end_min'],'delta_C':0,'heating_delta_C':0,'cooling_delta_C':0,'paused_minutes':0,'event_overlap_minutes':0,'requested_delta_C':0,'requested_duration_min':0,'minimum_deadband_C':2.,'effective_request_direction':'unchanged','requested_event_direction':e['direction'],'intended_control_direction':e['direction'],'control_action_direction':'unchanged','deliberate_reverse_direction':False,'thermal_direction_basis':'two_phase_thermal_storage_request;no_outdoor_mode_guess','availability_basis':'hardware_request_envelope_separate_from_A_routine','preconditioning':{'target_actual_room_use_min':target,'phases':[],'preparation_command_changed':False,'maximum_lead_min':120,'requested_lead_min':lead,'given_lead_has_no_event_overlap':True,'authorization_required':True,'human_acceptance':None,'physical_success':None},'indoor_state_available':False,'response_status':'uncertain_pending_physics','event_id':e['event_id'],'selected_event_id':e['event_id'],'input_limitation':'given_preconditioning_lead_has_no_event_overlap','description':'给定提前量与该事件不重叠，保留A；未补造短开机动作','thermal_or_energy_consequence':'pending_indoor_state_physics'}
    aids=sorted(aid for aid,z in c['thermal_control_context'].items()if z['room_id']==x['room_id'])
    if not all(covered(c['thermal_control_context'][aid]['hardware_request_intervals_min'],a,b)for aid in aids):raise ValueError('PRECONDITIONING_OUTSIDE_HARDWARE_REQUEST_ENVELOPE')
    scale=min(1.5,max(.5,e.get('target_kw',1.)));requested=[.5,1.,2.,4.][level]*scale
    references=[closest_reference(c,aid,target)for aid in aids];smallest=min(z['cooling_setpoint_C']-z['heating_setpoint_C']for z in references)
    # Include pre-existing controls and their possibly different base deadbands.
    touched=[z for z in plan['controls']if z['kind']=='ac_setpoint'and z['asset_id']in aids and overlap((a,b),(z['start_min'],z['end_min']))]
    smallest=min([smallest]+[z['cooling_setpoint_C']-z['heating_setpoint_C']for z in touched]);delta=min(requested,max(0.,(smallest-2.)/2))
    added,actual=apply_bounds(plan,c,aids,a,b,delta,-delta,True,target)
    preparation_changed=any(actual.values())
    phases=[{'phase':'prepare_thermal_storage'if e['direction']=='down'else'event_preconditioning','start_min':a,'end_min':b,'control_action_direction':'up'if preparation_changed else'unchanged','is_actual_command_change':preparation_changed,'heating_delta_C':delta,'cooling_delta_C':-delta,'actual_minutes_by_asset':actual,'A_permission_added_minutes_by_asset':added,'limitation':None if preparation_changed else'minimum_deadband_and_existing_A_permission_leave_preparation_unchanged'}]
    if e['direction']=='down':
        start=e['start_min'];end=e['end_min'];_,primary=apply_bounds(plan,c,aids,start,end,-requested,requested,False,target)
        phases.append({'phase':'event_relaxation','start_min':start,'end_min':end,'control_action_direction':'down'if any(primary.values())else'unchanged','is_actual_command_change':any(primary.values()),'heating_delta_C':-requested,'cooling_delta_C':requested,'actual_minutes_by_asset':primary,'A_permission_added_minutes_by_asset':{aid:0 for aid in aids}})
        dh,dc=-requested,requested
    else:start,end=a,b;dh,dc=delta,-delta
    def clock(m):return('当日'if m<1440 else'次日')+f'{m%1440//60:02d}:{m%60:02d}'
    description=(f'提出{clock(a)}—{clock(b)}提前温控，制热边界+{delta:g}℃、制冷边界−{delta:g}℃，服务于{clock(target)}已有房间使用'if preparation_changed else'最小温控间隔与A原许可使准备阶段指令不变；本项不计为实际提前温控')
    if e['direction']=='down':description+=f'；事件{clock(start)}—{clock(end)}在A原许可内放宽双边界{requested:g}℃'
    description+='；需用户同意，实际负荷、热储能及舒适效果待仿真'
    event_minutes={t for phase in phases for ts in phase['actual_minutes_by_asset'].values()for t in ts if e['start_min']<=t<e['end_min']}
    action_direction=e['direction']if event_minutes else'unchanged'
    actual_aids=sorted({aid for phase in phases for aid,ts in phase['actual_minutes_by_asset'].items()if ts})
    return {'device_family':'ac','asset_id':x['asset_id'],'affected_asset_ids':actual_aids,'room_id':x['room_id'],'mode':'dual_thermostat','start_min':start,'end_min':end,'delta_C':dc,'heating_delta_C':dh,'cooling_delta_C':dc,'paused_minutes':0,'event_overlap_minutes':len(event_minutes)*10,'requested_delta_C':requested,'requested_duration_min':end-start,'minimum_deadband_C':2.,'effective_request_direction':action_direction,'requested_event_direction':e['direction'],'control_action_direction':action_direction,'intended_control_direction':e['direction'],'deliberate_reverse_direction':False,'thermal_direction_basis':'two_phase_thermal_storage_request;no_outdoor_mode_guess','availability_basis':'hardware_request_envelope_separate_from_A_routine','preconditioning':{'target_actual_room_use_min':target,'phases':phases,'preparation_command_changed':preparation_changed,'maximum_lead_min':120,'requested_lead_min':lead,'given_lead_has_no_event_overlap':False,'authorization_required':True,'human_acceptance':None,'physical_success':None},'indoor_state_available':False,'response_status':'uncertain_pending_physics','event_id':e['event_id'],'selected_event_id':e['event_id'],'description':description,'thermal_or_energy_consequence':'pending_indoor_state_physics'}
