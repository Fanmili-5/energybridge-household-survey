"""Conditional recovery reference; never replaces the original request failure."""
import collections
import math
from common import *

def reference_recovery(w,c,plan):
    days={};blocks=[];bath=w['activity_contract']['room_map']['bath']
    for d in c['days']:
        ix=(dt.date.fromisoformat(d['date'])-dt.date.fromisoformat(c['date'])).days;days[ix]=d
        blocks +=[(bath,ix*1440+t,ix*1440+t+10)for t in d['activity']['family_context']['bath_times_min'].values()]
        blocks +=[(r['room_id'],ix*1440+r['start_min'],ix*1440+r['end_min'])for r in d['shared']['facility_reservations']]
    original={o['operation_id']:o for o in c['A']['operations']};ops={o['operation_id']:copy.deepcopy(o)for o in plan['operations']}
    unchanged={oid for oid,o in ops.items()if original.get(oid)==o};bookings=[];available={};moves=[]
    def fits(o,t):
        if t<DECISION:return True
        day=days.get(t//1440);local=t%1440
        if day is None or not any(a<=local and local+10<=b for a,b in day['activity']['operator_windows_min'].get(o['operator_id'],[])):return False
        if any(room==o['room_id']and overlap((a,b),(t,t+10))for room,a,b in blocks):return False
        return not any(oid!=o['operation_id']and overlap((a,b),(t,t+10))and(person==o['operator_id']or room==o['room_id'])for oid,person,room,a,b in bookings)
    def book(o):bookings.append((o['operation_id'],o['operator_id'],o['room_id'],o['start_min'],o['end_min']))
    # Existing commitments receive priority. This rule is fixed before outcomes,
    # and grants no new people, extra visit, or willingness to accept B.
    for oid in sorted(unchanged,key=lambda oid:(ops[oid]['start_min'],oid)):
        o=ops[oid];available[oid]=fits(o,o['start_min'])
        if available[oid]:book(o)
    for o in sorted((o for oid,o in ops.items()if oid not in unchanged and o['kind']!='unload'),key=lambda o:(o['start_min'],o['operation_id'])):
        available[o['operation_id']]=fits(o,o['start_min'])
        if available[o['operation_id']]:book(o)
    groups=collections.defaultdict(list)
    for t in plan['tasks']:groups[t.get('upstream_need_id',t['need_id'])].append(t)
    for o in sorted((o for oid,o in ops.items()if oid not in unchanged and o['kind']=='unload'),key=lambda o:(o['start_min'],o['operation_id'])):
        ts=groups.get(o['need_id'],[]);end=max((t['end_min']for t in ts),default=o['start_min']);requested=o['start_min']
        lo=max(DECISION,end,requested);found=None
        for t in range(math.ceil(lo/10)*10,4320,10):
            if fits(o,t):found=t;break
        available[o['operation_id']]=found is not None
        if found is not None:
            o['start_min']=found;o['end_min']=found+10;book(o)
            if found!=requested:moves.append({'operation_id':o['operation_id'],'operator_id':o['operator_id'],'requested_start_min':requested,'reference_start_min':found,'same_existing_operation_not_added':True})
    needs={n['need_id']:n for n in c['needs_A']};holds=collections.defaultdict(list);records=[];tasks=[];physical=[]
    for o in ops.values():
        if o['kind'].startswith('EV_')and available.get(o['operation_id'],True):physical.append(o)
    for load in sorted((o for o in ops.values()if o['kind']=='load'),key=lambda o:(o['start_min'],o['operation_id'])):
        nid=load['need_id'];ts=groups.get(nid,[]);unload=next((o for o in ops.values()if o['need_id']==nid and o['kind']=='unload'),None)
        if not ts or unload is None:continue
        n=needs[nid];start=min(t['start_min']for t in ts);end=max(t['end_min']for t in ts);reasons=[]
        if not available.get(load['operation_id'],True):reasons.append('LOAD_OPERATOR_OR_FACILITY_UNAVAILABLE')
        if load['start_min']<n['release_min']or load['end_min']>start or start-load['end_min']>720:reasons.append('GIVEN_LOADING_CONTRACT_NOT_MET')
        if any(load['start_min']<b and unload['end_min']>a for a,b in holds[load['asset_id']]):reasons.append('PRIOR_BATCH_NOT_YET_CLEARED')
        ran=not reasons;collected=ran and available.get(unload['operation_id'],True)and unload['start_min']>=end
        if ran:
            tasks.extend(ts);physical.append(load)
            holds[load['asset_id']].append((load['start_min'],unload['end_min']if collected else 4320))
            if collected:physical.append(unload)
        if collected and unload['end_min']>n['deadline_min']:reasons.append('SERVICE_DEADLINE_STILL_MISSED')
        if collected and unload['start_min']-end>n['maximum_retrieval_wait_min']:reasons.append('RETRIEVAL_WAIT_STILL_EXCEEDED')
        requested=next(o for o in plan['operations']if o['operation_id']==unload['operation_id'])['start_min']
        if max(end,requested)>=DECISION:
            records.append({'need_id':nid,'program_executed':ran,'collected':collected,'requested_retrieval_min':requested,
                'reference_retrieval_min':unload['start_min']if collected else None,'recovered_after_request':collected and unload['start_min']>requested,
                'deadline_satisfied':collected and unload['end_min']<=n['deadline_min'],'remaining_contract_violations':reasons})
    return {'schema':'eb.conditional_same_operator_recovery.v37','conditional_reference_not_observed_behavior':True,
        'requires_actor_performing_recovery_not_assumed_acceptance':True,'original_request_failures_retained':True,
        'policy':'unchanged A commitments first;only existing unloads move to next same-operator/facility slot;no helpers or extra operations',
        'unavailable_loads_not_repaired':True,'conservative_fixed_reservations_include_other_original_requests':True,
        'operation_adjustments':moves,'batch_results':records,'realized_tasks':tasks,'realized_operations':physical,
        'physical_energy_thermal_or_human_outcomes':None}
