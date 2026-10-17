"""All-window input directives, computed from frozen A rather than B outcomes."""
from common import *

def considered(c,event):return c.get('_joint_events')or[event]

def program_target(c,event,task,duration,load,need,default,handling=False):
    es=c.get('_joint_events')
    if not es:return default,'single_window'
    start=task['start_min']
    if event['direction']=='up':
        if any(e['direction']=='up'and overlap((start,start+duration),(e['start_min'],e['end_min']))for e in es):
            return start,'preserve_A_program_already_serving_an_up_window'
        return default,'joint_family_assignment_to_up_window'
    earliest=max(DECISION,need['release_min'] if handling else load['end_min'])
    latest=need['deadline_min']-duration
    candidates={start,earliest,latest}
    for e in es:
        if e['direction']=='down':candidates.update([e['start_min']-duration,e['end_min']])
    valid=[t for t in candidates if earliest<=t<=latest and all(
        e['direction']!='down'or not overlap((t,t+duration),(e['start_min'],e['end_min']))for e in es)]
    if valid:return min(valid,key=lambda t:(abs(t-start),t)),'avoid_union_of_down_windows_using_A_release_and_deadline'
    return default,'all_down_windows_considered_but_no_common_input_gap'

def ev_start(c,event,old,full_minutes,offset,default):
    es=c.get('_joint_events')
    if not es:return default,'single_window'
    if event['direction']=='up':
        finish=old.get('actual_charge_end_min',old['end_min'])
        if any(e['direction']=='up'and overlap((old['start_min'],finish),(e['start_min'],e['end_min']))for e in es):
            return old['start_min'],'preserve_A_charging_already_serving_an_up_window'
        return default,'joint_family_assignment_to_up_window'
    candidates={old['start_min']}
    for e in es:
        if e['direction']=='down':candidates.add(max(old['start_min'],e['end_min']+offset))
    valid=[t for t in candidates if t+full_minutes<=old['end_min']and all(
        e['direction']!='down'or not overlap((t,t+full_minutes),(e['start_min'],e['end_min']))for e in es)]
    if valid:return min(valid),'first_connection_gap_outside_all_down_windows'
    return default,'all_down_windows_considered_but_connection_gap_insufficient'

def subtract_windows(start,end,events):
    pieces=[(start,end)]if start<end else[]
    for e in events:
        rest=[]
        for a,b in pieces:
            if not overlap((a,b),(e['start_min'],e['end_min'])):rest.append((a,b));continue
            if a<e['start_min']:rest.append((a,min(b,e['start_min'])))
            if e['end_min']<b:rest.append((max(a,e['end_min']),b))
        pieces=rest
    return pieces
