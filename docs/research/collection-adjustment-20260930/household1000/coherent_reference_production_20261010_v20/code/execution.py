"""Conditional reference execution: requested actions are not delivered services.

Explicit reference interlocks: an active sealed wash/dry/dish program cannot
be unloaded; removal of an idle loaded batch cancels its future program.
These are declared simulator policies, not a claim about every appliance.
"""
import collections,datetime as dt
from common import *
from activity_model import dated,resident_slot,ranges

def trip_windows(needs):
    return [[n['trip_departure_min'],n['release_min']] for n in needs if n['kind']=='ev']

def realize(w,plan,ws,needs):
    tasks=sorted(plan['tasks'],key=lambda t:(t['start_min'],t['need_id']))
    assets={d['asset_id']:d for d in w['parameter_pack']['devices']}
    byneed={t['need_id']:t for t in tasks};events=collections.defaultdict(list)
    for t in tasks:events[t['start_min']].append(('program',t))
    for o in plan['operations']:events[o['end_min'] if o['kind'] in ('load','EV_plug') else o['start_min']].append(('operation',o))
    busy={};loaded={};started=set();completed=[];oprows=[];visits=[];connected={};connections=[]
    away=trip_windows(needs);done_ops=[]
    for minute in sorted(events):
        for aid,item in list(busy.items()):
            if item['end_min']<=minute:
                loaded[aid]=('ready',item['batch_id']);del busy[aid]
        for typ,item in sorted(events[minute],key=lambda x:(x[0]!='operation',x[1].get('operation_id',x[1].get('task_id','')))):
            if typ=='program':
                aid=item['asset_id'];nid=item['need_id'];root=nid[:-4] if item['kind']=='dryer' and nid.endswith(':dry') else nid
                upstream=byneed.get(root)
                ready=loaded.get(aid)==('loaded',root) if item['kind']!='dryer' else root in started and upstream and upstream['end_min']==minute
                if ready and (aid not in busy or item['kind']=='dryer'):
                    started.add(nid);completed.append(item.copy())
                    final=byneed.get(root+':dry',item)
                    busy[aid]={'end_min':final['end_min'],'batch_id':root};loaded.pop(aid,None)
                continue
            o=item;opid=o['operator_id'];nid=o['need_id'];reason=None
            if not any(a<=o['start_min'] and o['end_min']<=b for a,b in ws.get(opid,[])):reason='outside_given_operator_window'
            if any(opid==z['operator_id'] and overlap((o['start_min'],o['end_min']),(z['start_min'],z['end_min'])) for z in done_ops):reason='operator_resource_conflict'
            if o['kind'].startswith('EV_') and any(overlap((o['start_min'],o['end_min']),ab) for ab in away):reason='vehicle_away'
            attempt=reason is None
            if attempt:visits.append(o.copy());done_ops.append(o)
            aid=byneed.get(nid,{}).get('asset_id')
            if o['kind'].startswith('EV_'):
                aid=next((a for a,d in assets.items() if 'ev' in d['types']),None)
                if aid is None:reason='EV_missing'
                if attempt and aid:
                    if o['kind']=='EV_plug':
                        if aid in connected:reason='already_connected'
                        else:connected[aid]=o['end_min']
                    else:
                        if aid not in connected:reason='not_connected'
                        else:connections.append({'asset_id':aid,'start_min':connected.pop(aid),'end_min':o['start_min']})
            elif attempt:
                if aid is None:reason='batch_program_missing'
                elif o['kind']=='load':
                    if aid in busy or aid in loaded:reason='asset_not_empty'
                    else:loaded[aid]=('loaded',nid)
                elif o['kind']=='unload':
                    if aid in busy:reason='program_interlock_active'
                    elif loaded.get(aid,('',None))[1]!=nid:reason='batch_not_available'
                    elif loaded[aid][0]=='loaded':loaded.pop(aid);reason='unclean_batch_removed_before_program'
                    else:loaded.pop(aid)
            oprows.append({**o,'physical_attempt_occurred':attempt,'succeeded':reason is None,'failure_reason':reason})
    horizon=max([x['end_min'] for x in plan['controls']]+[4320])
    for aid,minute in connected.items():connections.append({'asset_id':aid,'start_min':minute,'end_min':horizon,'unplug_missing':True})
    delivered={o['need_id']:o['end_min'] for o in oprows if o['kind']=='unload' and o['succeeded']}
    service=[]
    for n in needs:
        if n['kind'] not in ('washer','dishwasher'):continue
        nid=n['need_id'];last=byneed.get(nid+':dry',byneed.get(nid));ready=nid in started and (last is not None and last['need_id'] in started)
        service.append({'need_id':nid,'program_chain_ran':bool(ready),'delivered_min':delivered.get(nid),
            'delivery_deadline_min':n['delivery_deadline_min'],'delivered_before_given_bound':nid in delivered and delivered[nid]<=n['delivery_deadline_min'],
            'wearability_known':n.get('wearable_clothes_ready_after_required_chain') if n['kind']=='washer' else None})
    return {'realized_tasks':completed,'operations':oprows,'physical_visit_operations':visits,'connections':connections,
        'program_services':service,'requested_tasks_cancelled':[t['need_id'] for t in tasks if t['need_id'] not in started],
        'policies':'explicit reference program interlock,loading prerequisite,vehicle presence and connection; no implicit retry or automatic human rejection',
        'conditional_on_attempt_within_given_resource_windows':True,'actor_adoption':None}

def common_care_bookings(w,date,A,days):
    """Book any A departure coverage before B. Never grant B extra cover silently."""
    children=[m for m in w['members'] if m['age_years']<6];adults=[m for m in w['members'] if m['age_years']>=18]
    if not children:return []
    result=[]
    for d in range(days):
        day=dated(w,date+dt.timedelta(days=d));offset=1440*d
        ops=[{**o,'start_min':o['start_min']-offset,'end_min':o['end_min']-offset} for o in A['operations']]
        gaps=[]
        for s in range(144):
            home=[m for m in children if resident_slot(w,day,m['member_id'],s,ops,A['tasks'])['location']=='home']
            if not home:continue
            adult_home=any(resident_slot(w,day,m['member_id'],s,ops,A['tasks'])['location']=='home' for m in adults)
            external_home=any(v['start_min']<=s*10<v['end_min'] and 'care coverage' in v['reason'] for v in day['external_visits'])
            if not adult_home and not external_home:gaps.append(s*10)
        if gaps:
            # One bounded continuous appointment, shared by A and B.
            result.append({'person_id':w['household_id']+':given_A_departure_care_provider',
                'start_min':offset+min(gaps),'end_min':offset+max(gaps)+10,
                'reason':'pre-booked A manual-departure care; B shares exact appointment',
                'given_not_observed':True,'extra_B_care_authorized':False,'cost':None})
    return result

def post_operation_care(w,date,plan,bookings,days):
    out=[];children=[m for m in w['members'] if m['age_years']<6];adults=[m for m in w['members'] if m['age_years']>=18]
    if not children:return out
    for d in range(days):
        day=dated(w,date+dt.timedelta(days=d));off=d*1440
        ops=[{**o,'start_min':o['start_min']-off,'end_min':o['end_min']-off} for o in plan['operations']]
        for s in range(144):
            home=[m['member_id'] for m in children if resident_slot(w,day,m['member_id'],s,ops,plan['tasks'])['location']=='home']
            if not home:continue
            present=any(resident_slot(w,day,m['member_id'],s,ops,plan['tasks'])['location']=='home' for m in adults)
            covered=any(v['start_min']<=s*10<v['end_min'] and 'care coverage' in v['reason'] for v in day['external_visits']) or any(b['start_min']<=off+s*10<b['end_min'] for b in bookings)
            if not present and not covered:out.append({'start_min':off+s*10,'end_min':off+s*10+10,'child_ids':home,
                'condition':'given adult-presence contract not met; available teenagers do not imply authorized replacement',
                'human_rejection_label':None})
    return out
