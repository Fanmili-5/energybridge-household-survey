"""Outcome-blind construction invariants, separate from household service stress.

These are executable-plan semantics, not comfort, acceptance or response tests.
Raw requests violating them are retained in the engineering ledger, never
repaired or replaced after checking. Context/authority gates remain separate.
"""
from collections import defaultdict
from .model import chain_need_ids


ENGINEERING_ISSUES = frozenset({
    'INCOMPLETE_PROGRAM_CHAIN', 'PROGRAM_BEFORE_LOAD_END',
    'RETRIEVAL_BEFORE_PROGRAM_END', 'LOAD_BEFORE_RELEASE',
    'PREREQUISITE_NOT_COLLECTED', 'TIMER_NOT_AVAILABLE',
    'THERMOSTAT_DEADBAND_INVERTED', 'SETPOINT_OUTSIDE_REFERENCE_RANGE',
    'SETPOINT_OUTSIDE_HARDWARE_RANGE', 'OVERLAPPING_PATCH_IDENTITIES',
    'INVALID_PLAN_INTERVAL', 'PROGRAM_ORDER_CHANGED',
    'SIMULTANEOUS_PROGRAMS_ON_ONE_ASSET', 'ASSET_HOLD_CONFLICT',
    'EV_CONTROL_OUTSIDE_CONNECTED_INTERVAL', 'INCOMPLETE_EV_CONNECTION',
})

SERVICE_ISSUES = frozenset({
    'OPERATOR_UNAVAILABLE', 'OPERATOR_DOUBLE_BOOKED', 'ROOM_DOUBLE_BOOKED',
    'FACILITY_RESERVED', 'PRELOAD_WAIT_EXCEEDED', 'MACHINE_WINDOW_VIOLATED',
    'SERVICE_DEADLINE_MISSED', 'RETRIEVAL_WAIT_EXCEEDED',
    'CHARGE_EXCEEDS_ORIGINAL_CONNECTION', 'SITE_KNOWN_PROFILE_EXCEEDS_SUPPLY',
    'SITE_CAPACITY_NOT_CERTIFIED',
})


def program_construction_issues(c, tasks, operations):
    """Derive each variant's precedence/capability domain before admission.

    Do not use people calendars, convenience windows or service deadlines here:
    an internally coherent request can still conflict with those requirements.
    """
    out = set()
    needs = {n['need_id']: n for n in c['needs']}
    handled = {o['need_id'] for o in operations if o['kind'] == 'load'}
    for nid in handled:
        jobs = [t for t in tasks if t['need_id'] in (nid, nid + ':dry')]
        loads = [o for o in operations if o['need_id'] == nid and o['kind'] == 'load']
        unloads = [o for o in operations if o['need_id'] == nid and o['kind'] == 'unload']
        if len(loads) != 1 or len(unloads) != 1 or not jobs or nid not in needs:
            out.add('INCOMPLETE_PROGRAM_CHAIN'); continue
        first, end = min(t['start_min'] for t in jobs), max(t['end_min'] for t in jobs)
        load, unload, need = loads[0], unloads[0], needs[nid]
        if load['start_min'] < need['release_min']: out.add('LOAD_BEFORE_RELEASE')
        if load['end_min'] > first: out.add('PROGRAM_BEFORE_LOAD_END')
        if unload['start_min'] < end: out.add('RETRIEVAL_BEFORE_PROGRAM_END')
        if need.get('timer_allowed') is False and load['end_min'] != first:
            out.add('TIMER_NOT_AVAILABLE')
        for task in jobs:
            parent = task.get('depends_on_need_id')
            if parent:
                retrieval = next((o for o in operations if o['need_id'] == parent and o['kind'] == 'unload'), None)
                if retrieval is None or retrieval['end_min'] > load['start_min']:
                    out.add('PREREQUISITE_NOT_COLLECTED')
        original = sorted((t for t in c['A']['tasks'] if t['need_id'] in (nid,nid+':dry')),
                          key=lambda t: (t['start_min'],t['end_min'],t['task_id']))
        ordered = sorted(jobs,key=lambda t:(t['start_min'],t['end_min'],t['task_id']))
        if [t['task_id'] for t in original] != [t['task_id'] for t in ordered]:
            out.add('PROGRAM_ORDER_CHANGED')
    if any(r['end_min'] <= r['start_min'] for r in tasks + operations):
        out.add('INVALID_PLAN_INTERVAL')
    return sorted(out)


def engineering_issues(c, b, needs=(), reported=()):
    """Check final combinations too, including conflicts with unchanged batches."""
    unclassified=set(reported)-ENGINEERING_ISSUES-SERVICE_ISSUES
    if unclassified:raise ValueError('UNCLASSIFIED_COLLECTION_ISSUE:'+','.join(sorted(unclassified)))
    out = set(reported) & ENGINEERING_ISSUES
    affected = set()
    for nid in needs: affected.update(chain_need_ids(b,nid))
    tasks = [t for t in b['tasks'] if t['need_id'] in affected]
    ops = [o for o in b['operations'] if o['need_id'] in affected]
    out.update(program_construction_issues(c,tasks,ops))
    original = {t['task_id']:t for t in c['A']['tasks']}
    changed = {t['task_id'] for t in b['tasks'] if t != original.get(t['task_id'])}
    by_asset = defaultdict(list)
    for t in b['tasks']: by_asset[t['asset_id']].append(t)
    for group in by_asset.values():
        active = []
        for task in sorted(group,key=lambda t:(t['start_min'],t['end_min'])):
            active = [p for p in active if p['end_min'] > task['start_min']]
            if any(task['task_id'] in changed or p['task_id'] in changed for p in active):
                out.add('SIMULTANEOUS_PROGRAMS_ON_ONE_ASSET')
            active.append(task)
    if any(r['end_min'] <= r['start_min'] for k in b for r in b[k]):
        out.add('INVALID_PLAN_INTERVAL')
    # Plug/unplug operations are fixed. A late pause may leave an energy deficit
    # (retained service stress), but may never invent charging while unplugged.
    def ev_groups(plan):
        groups=defaultdict(list)
        for r in plan['controls']:
            if r['kind']=='ev_charge_window':groups[(r['asset_id'],r['need_id'])].append(r)
        return {k:sorted(v,key=lambda r:(r['start_min'],r['end_min'])) for k,v in groups.items()}
    before_ev,after_ev=ev_groups(c['A']),ev_groups(b)
    changed_ev={k for k in before_ev.keys()|after_ev.keys() if before_ev.get(k)!=after_ev.get(k)}
    for r in b['controls']:
        if r['kind'] != 'ev_charge_window': continue
        # First/last connections of a multi-month source calendar can be
        # censored. Unchanged boundaries outside this case are not a B failure.
        if ((r['asset_id'],r['need_id']) not in changed_ev and
                (r['end_min']<=c['horizon_min'][0] or r['start_min']>=c['horizon_min'][1])):
            continue
        ops=[o for o in b['operations'] if o['asset_id']==r['asset_id'] and o['need_id']==r['need_id']]
        plugs=[o for o in ops if o['kind']=='EV_plug'];unplugs=[o for o in ops if o['kind']=='EV_unplug']
        if len(plugs)!=1 or len(unplugs)!=1:
            out.add('INCOMPLETE_EV_CONNECTION')
        elif r['start_min'] < plugs[0]['end_min'] or r['end_min'] > unplugs[0]['start_min']:
            out.add('EV_CONTROL_OUTSIDE_CONNECTED_INTERVAL')
    return sorted(out)
