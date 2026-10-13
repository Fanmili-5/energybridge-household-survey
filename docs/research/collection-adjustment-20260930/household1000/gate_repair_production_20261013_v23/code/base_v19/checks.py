"""Independent input integrity and descriptive constraint annotations; no answer labels."""
import collections
from common import *
def prefix(plan,decision):
    return {k:sorted([{**a,'end_min':min(a['end_min'],decision)} for a in plan[k] if a['start_min']<decision],key=canonical) for k in ('tasks','controls','operations')}
def assess(p):
    hard=[];flags={s:[] for s in ('A','B')};ns={n['need_id']:n for n in p['needs_A']};assets={d['asset_id']:d for d in p['world']['devices']}
    if p['needs_A']!=p['needs_B']:hard.append('NEEDS_CHANGED')
    if digest(p['A'])!=p['A_frozen_before_B_sha256']:hard.append('A_CHANGED_AFTER_B')
    if prefix(p['A'],p['decision_abs_min'])!=prefix(p['B'],p['decision_abs_min']):hard.append('PRE_NOTICE_INPUT_CHANGED')
    if digest(p['world']['devices'])!=p['devices_sha256']:hard.append('DEVICE_PARAMETERS_CHANGED')
    for side in ('A','B'):
        plan=p[side];tasks={t['need_id']:t for t in plan['tasks']};ops=plan['operations']
        if plan['parameter_pack_sha256']!=p['parameter_pack_sha256']:hard.append(side+':PARAMETER_PACK_BINDING')
        if len(tasks)!=len(plan['tasks']):hard.append(side+':DUPLICATE_PROGRAM')
        for t in plan['tasks']:
            n=ns.get(t['need_id'])
            if not n or t['asset_id'] not in assets or t['kind'] not in assets[t['asset_id']]['types']:hard.append(side+':PROGRAM_BINDING');continue
            if t['end_min']-t['start_min']!=n['duration_min']:hard.append(side+':PROGRAM_DURATION_CHANGED')
            if t['start_min']<n['release_min'] or t['end_min']>n['deadline_min']:flags[side].append('PROGRAM_RELEASE_OR_DEADLINE')
        for n in ns.values():
            if n['kind'] in ('washer','dryer','dishwasher') and n['need_id'] not in tasks:hard.append(side+':PROGRAM_MISSING')
            if n['kind']=='dryer' and n['need_id'] in tasks:
                u=tasks.get(n['upstream_need_id']);t=tasks[n['need_id']]
                if not u or t['start_min']!=u['end_min']:hard.append(side+':AUTOMATIC_WASH_DRY_CHAIN')
            if n['kind'] in ('washer','dishwasher') and n['need_id'] in tasks:
                load=[o for o in ops if o['need_id']==n['need_id'] and o['kind']=='load'];unload=[o for o in ops if o['need_id']==n['need_id'] and o['kind']=='unload']
                if len(load)!=1 or len(unload)!=1:hard.append(side+':HANDLING_COVERAGE');continue
                last=tasks.get(n['need_id']+':dry',tasks[n['need_id']])['end_min']
                if load[0]['end_min']>tasks[n['need_id']]['start_min']:flags[side].append('LOAD_AFTER_PROGRAM_START')
                if unload[0]['start_min']<last or unload[0]['end_min']>n['delivery_deadline_min']:flags[side].append('RETRIEVAL_OR_DELIVERY_CONFLICT')
        for action in plan['tasks']+plan['controls']+ops:
            if any(type(action[k]) is not int or action[k]%10 for k in ('start_min','end_min')) or action['end_min']<=action['start_min']:hard.append(side+':CLOCK_OR_DURATION')
        for o in ops:
            if not any(a<=o['start_min'] and o['end_min']<=b for a,b in p['world']['operator_windows'].get(o['operator_id'],[])):flags[side].append('OPERATOR_OUTSIDE_AVAILABLE_WINDOW')
        for i,o in enumerate(ops):
            if any(o['operator_id']==z['operator_id'] and overlap((o['start_min'],o['end_min']),(z['start_min'],z['end_min'])) for z in ops[i+1:]):flags[side].append('OPERATOR_DOUBLE_BOOKED')
        for aid,d in assets.items():
            acts=[t for t in plan['tasks']+plan['controls'] if t['asset_id']==aid]
            for i,a in enumerate(acts):
                if any(overlap((a['start_min'],a['end_min']),(z['start_min'],z['end_min'])) for z in acts[i+1:]):flags[side].append('SHARED_ASSET_OVERLAP')
            if 'ac' in d['types'] and any(c.get('value_C',0)>d['reference_upper_setpoint_C'] for c in plan['controls'] if c['asset_id']==aid):flags[side].append('AC_GIVEN_CONTROL_BOUND')
    return {'integrity_errors':sorted(set(hard)),'constraint_flags':{s:sorted(set(x)) for s,x in flags.items()},'role_response':None,'flags_are_not_human_rejection_labels':True}
