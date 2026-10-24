"""Literal engineering auditor; imports no generator/admission classifier."""
from collections import defaultdict


def audit(c,A,B):
    errors=set();devices={d['asset_id']:d for d in c['devices']}
    for collection,identity in [('tasks','task_id'),('operations','operation_id')]:
        original={r[identity]:r for r in A[collection]}
        after={r[identity]:r for r in B[collection]}
        if set(original)!=set(after):errors.add('IDENTITY_SET_CHANGED')
        for key,row in after.items():
            if row['asset_id'] not in devices:errors.add('UNKNOWN_ASSET')
            if row['end_min']<=row['start_min']:errors.add('NONPOSITIVE_INTERVAL')
            a=original.get(key)
            if a and row['end_min']-row['start_min']!=a['end_min']-a['start_min']:errors.add('DURATION_CHANGED')
            if a:
                for field in ('asset_id','kind','operator_id','power_kw','batch_energy_kWh','need_id'):
                    if row.get(field)!=a.get(field):errors.add('IMMUTABLE_FIELD_CHANGED:'+field)
                if a['start_min']<c['decision_min'] and a!=row:errors.add('PAST_REWRITTEN')
                if a!=row and row['start_min']<c['decision_min']:errors.add('PROPOSAL_BEFORE_DECISION')
                if collection=='operations' and row!=a:
                    authorized=c.get('authority',{}).get('assets',{}).get(row['asset_id'],{}).get('authorized_operator_ids',[])
                    if row['operator_id'] not in authorized:errors.add('UNQUALIFIED_OPERATOR')
                    if row['operator_id'] in c.get('authority',{}).get('immutable_operator_ids',[]):errors.add('IMMUTABLE_OPERATOR_CHANGED')
    tasks=defaultdict(list)
    for r in B['tasks']:tasks[r['asset_id']].append(r)
    for group in tasks.values():
        group=sorted(group,key=lambda r:r['start_min'])
        if any(a['end_min']>b['start_min'] for a,b in zip(group,group[1:])):errors.add('MACHINE_OVERLAP')
    # Service declarations determine whether this batch requires both phases.
    # A dual-capability appliance can also serve an explicitly wash-only batch.
    automatic={n['need_id']:n for n in c['needs'] if n.get('kind')=='washer' and
               (n.get('automatic_child_need_id') or n.get('wash_only_delivery')=='auto combo wash then dry')}
    for aid,d in devices.items():
        phases={t['need_id']:t for t in tasks[aid]}
        for t in phases.values():
            if t['kind']!='washer' or t['need_id'] not in automatic:continue
            declaration=automatic[t['need_id']]
            child_id=declaration.get('automatic_child_need_id',t['need_id']+':dry')
            child=phases.get(child_id)
            if child is None or child['kind']!='dryer':errors.add('MISSING_AUTOMATIC_DRY_PHASE')
            elif child['start_min']!=t['end_min']:errors.add('AUTOMATIC_PHASE_NOT_IMMEDIATE')
            if any(o['asset_id']==aid and o['need_id']==child_id for o in B['operations']):
                errors.add('INVENTED_AUTOMATIC_TRANSFER')
    needs={n['need_id']:n for n in c['needs']}
    loads={o['need_id']:o for o in B['operations'] if o['kind']=='load'}
    unloads={o['need_id']:o for o in B['operations'] if o['kind']=='unload'}
    for nid,load in loads.items():
        group=[t for t in B['tasks'] if t['need_id']==nid or
            (t['need_id']==nid+':dry' and t['asset_id']==load['asset_id'])]
        if not group or nid not in unloads:
            # Frozen excerpts can end after a preload and before its task.
            # Unchanged, outside-window boundary evidence is unknown, not a B
            # logic error. Any changed/in-window incomplete chain still fails.
            original=next((o for o in A['operations'] if o['operation_id']==load['operation_id']),None)
            outside=load['start_min']>=c['horizon_min'][1] or load['end_min']<=c['horizon_min'][0]
            if load==original and outside:continue
            errors.add('INCOMPLETE_CHAIN');continue
        if load['end_min']>min(t['start_min'] for t in group):errors.add('START_BEFORE_LOAD')
        if unloads[nid]['start_min']<max(t['end_min'] for t in group):errors.add('UNLOAD_BEFORE_END')
        if nid in needs and load['start_min']<needs[nid]['release_min']:errors.add('LOAD_BEFORE_RELEASE')
        if nid in needs and needs[nid].get('timer_allowed') is False and load['end_min']!=min(t['start_min'] for t in group):errors.add('TIMER_NOT_SUPPORTED')
    holds=defaultdict(list)
    for nid,l in loads.items():
        if nid in unloads:holds[l['asset_id']].append((l['start_min'],unloads[nid]['end_min'],nid))
    for intervals in holds.values():
        intervals=sorted(intervals)
        if any(a[1]>b[0] for a,b in zip(intervals,intervals[1:])):errors.add('MACHINE_HELD_BY_OTHER_BATCH')
    for t in B['tasks']:
        parent=t.get('depends_on_need_id')
        if parent and t['need_id'] in loads:
            if parent not in unloads or unloads[parent]['end_min']>loads[t['need_id']]['start_min']:errors.add('DRY_BEFORE_WASH_TRANSFER')
    for r in B['controls']:
        if r['asset_id'] not in devices:errors.add('UNKNOWN_CONTROL_ASSET');continue
        if r['end_min']<=r['start_min']:errors.add('NONPOSITIVE_CONTROL_INTERVAL')
        if r['kind']=='ac_setpoint':
            heat,cool=r['heating_setpoint_C'],r['cooling_setpoint_C']
            if heat>=cool or cool-heat<r.get('heating_and_cooling_deadband_C',0)-1e-9:errors.add('INVALID_THERMOSTAT_ORDER')
            if not 5<=heat<=35 or not 15<=cool<=40:errors.add('INVALID_THERMOSTAT_RANGE')
            if 'value_C' in r and r['value_C']!=cool and r not in A['controls']:errors.add('COOLING_ALIAS_INCONSISTENT')
        if r['kind']=='tank_setpoint' and not 10<=r['value_C']<=devices[r['asset_id']]['parameters']['maximum_C']:errors.add('INVALID_TANK_RANGE')
        if r['kind']=='ev_charge_window':
            ops=[o for o in B['operations'] if o['asset_id']==r['asset_id'] and o['need_id']==r.get('need_id')]
            plug=[o for o in ops if o['kind']=='EV_plug'];unplug=[o for o in ops if o['kind']=='EV_unplug']
            initial=next((p for p in c.get('physical_ev_connections',[]) if p['need_id']==r.get('need_id') and p.get('origin')=='given_anchor_connection' and p['start_min']<=r['start_min']<r['end_min']<=p['end_min'] and len(unplug)==1 and p['end_min']==unplug[0]['start_min']),None)
            # Only changed control windows require complete physical endpoints.
            if r not in A['controls'] and not (initial and not plug) and (len(plug)!=1 or len(unplug)!=1 or
                r['start_min']<plug[0]['end_min'] or r['end_min']>unplug[0]['start_min']):errors.add('EV_OUTSIDE_CONNECTION')
    return sorted(errors)
