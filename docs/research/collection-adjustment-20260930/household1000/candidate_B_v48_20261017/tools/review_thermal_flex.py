"""Independent full-case readback of actual actions, future use and physical request scope."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def control(plan,aid,t):return next((x for x in plan['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid and x['start_min']<=t<x['end_min']),None)
def main():
    counts=collections.Counter();bad=[];examples={};adverse_cases=set();pre_cases=set();proposed_cases=set();up_new_cases=set()
    for ri,row in enumerate(read(OUT/'PAIR_BINDINGS10000.json')['records']):
        for rr in row['rounds']:
            p=read(OUT/rr['path']);q=p['proposal'];counts['cases']+=1;ctx=p['thermal_control_context'];events={e['event_id']:e for e in p['VPP_events']};allowed_new=collections.defaultdict(set)
            for ch in q['changes']:
                if ch['device_family']!='ac':continue
                e=events[ch['selected_event_id']]
                if ch['paused_minutes']:
                    counts['pause_actions_read_back']+=1
                    if ch['control_action_direction']!='down'or ch['effective_request_direction']!='down':bad.append([p['case_id'],'PAUSE_INCORRECTLY_LABELLED_UP'])
                    for aid in ch['affected_asset_ids']:
                        if any(control(p['B'],aid,t)is not None for t in range(ch['start_min'],ch['end_min'],10)):bad.append([p['case_id'],'PAUSE_NOT_ACTUALLY_WITHDRAWN'])
                    if e['direction']=='up':
                        counts['up_pause_actions_explicitly_adverse']+=1;adverse_cases.add(p['case_id'])
                        if not ch['deliberate_reverse_direction']or ch['adverse_variant']!='pause_opposes_up_request'or not q['explicit_adverse_request']:bad.append([p['case_id'],'ADVERSE_PAUSE_NOT_LABELLED'])
                        examples.setdefault('up_pause_kept',{'case_id':p['case_id'],'path':rr['path'],'change':ch,'event':e})
                if not ch.get('preconditioning'):continue
                proposed_cases.add(p['case_id']);z=ch['preconditioning'];target=z['target_actual_room_use_min'];counts['preconditioning_requests']+=1
                if not z['authorization_required']or z['human_acceptance']is not None or z['physical_success']is not None:bad.append([p['case_id'],'PRECONDITIONING_CONSENT_OR_SUCCESS_FABRICATED'])
                if z['preparation_command_changed']:pre_cases.add(p['case_id']);counts['actual_preconditioning_requests']+=1
                if not z['phases']:counts['insufficient_lead_no_op_requests']+=1
                for phase in z['phases']:
                    a,b=phase['start_min'],phase['end_min'];counts['thermal_phases_read_back']+=1
                    changed=any(phase['actual_minutes_by_asset'].values())
                    if phase['is_actual_command_change']!=changed or (phase['control_action_direction']=='unchanged')==changed:bad.append([p['case_id'],'FALSE_THERMAL_PHASE_CHANGE'])
                    if not changed and phase['phase']!='event_relaxation':counts['unchanged_preparation_requests_kept']+=1
                    if a<480 or a>=b:bad.append([p['case_id'],'PREDECISION_OR_EMPTY_THERMAL_PHASE'])
                    if phase['phase']!='event_relaxation'and not 0<target-a<=120:bad.append([p['case_id'],'UNBOUNDED_OR_UNRELATED_THERMAL_STORAGE'])
                    for aid,minutes in phase['actual_minutes_by_asset'].items():
                        rz=ctx[aid]
                        if not any(lo<=target<hi for lo,hi in rz['actual_occupied_intervals_min']):bad.append([p['case_id'],'NO_REAL_FUTURE_ROOM_USE'])
                        new=[]
                        for t in minutes:
                            if not a<=t<b or not any(lo<=t<t+10<=hi for lo,hi in rz['hardware_request_intervals_min']):bad.append([p['case_id'],'OUTSIDE_HARDWARE_REQUEST_SCOPE'])
                            aa=control(p['A'],aid,t);bb=control(p['B'],aid,t)
                            if bb is None:bad.append([p['case_id'],'DECLARED_PHASE_NOT_IN_COMMAND']);continue
                            h=aa['heating_setpoint_C']if aa else rz['usual_heating_setpoint_C'];v=aa['cooling_setpoint_C']if aa else rz['usual_cooling_setpoint_C']
                            if abs(bb['heating_setpoint_C']-h-phase['heating_delta_C'])>1e-8 or abs(bb['cooling_setpoint_C']-v-phase['cooling_delta_C'])>1e-8:bad.append([p['case_id'],'PHASE_DIRECTION_OR_VALUE_NOT_ACTUAL'])
                            if bb['cooling_setpoint_C']-bb['heating_setpoint_C']<2.-1e-8:bad.append([p['case_id'],'PHASE_DEADBAND_BELOW2'])
                            if aa is None:new.append(t);allowed_new[aid].add(t)
                            elif aa['fan_operating_mode']!=bb['fan_operating_mode']:bad.append([p['case_id'],'EXISTING_FAN_MODE_CHANGED'])
                        if len(new)*10!=phase['A_permission_added_minutes_by_asset'][aid]:bad.append([p['case_id'],'FALSE_NEW_PERMISSION_MINUTES'])
                        counts['new_permission_minutes']+=len(new)*10
                        if new and e['direction']=='up':up_new_cases.add(p['case_id']);examples.setdefault('up_before_return',{'case_id':p['case_id'],'path':rr['path'],'change':ch,'event':e})
                if z['preparation_command_changed']and e['direction']=='down':examples.setdefault('down_two_phase',{'case_id':p['case_id'],'path':rr['path'],'change':ch,'event':e});counts['down_two_phase_requests']+=1
            for aid in ctx:
                new={t for x in p['B']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid for t in range(x['start_min'],x['end_min'],10)if control(p['A'],aid,t)is None}
                if new!=allowed_new[aid]:bad.append([p['case_id'],aid,'UNEXPLAINED_OR_MISSING_NEW_HVAC_PERMISSION'])
            if p['needs_A']!=p['needs_B']or p['human_response']!={'accepted':None,'scores':None,'reason':None}:bad.append([p['case_id'],'NEEDS_OR_ANSWERS_CHANGED'])
        if(ri+1)%200==0:print({'thermal_flex_households':ri+1,'errors':len(bad)},flush=True)
    counts.update(up_pause_cases_explicitly_adverse=len(adverse_cases),preconditioning_cases=len(pre_cases),preconditioning_request_cases=len(proposed_cases),up_cases_with_permission_beyond_A=len(up_new_cases))
    r={'accepted':not bad and counts['cases']==10000 and counts['preconditioning_cases']>0 and counts['up_cases_with_permission_beyond_A']>0,'rules_sha256':rules_id(),'counts':dict(counts),'errors':bad,'no_physical_success_or_acceptance_filter':True,'full_physical_acceptance':False}
    save(OUT/'THERMAL_FLEX_REVIEW.json',r);save(OUT/'review/三项修正实际案例.json',examples);print(canonical(r))
    if not r['accepted']:raise SystemExit(2)
if __name__=='__main__':main()
