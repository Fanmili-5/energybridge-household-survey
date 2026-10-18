"""Literal plan patches and service checks; no automatic schedule repair."""
import copy
from .common import digest


def plan_commands(plan):
    return {key: sorted(copy.deepcopy(plan[key]), key=lambda x: (
        x['start_min'], x['asset_id'], x.get('task_id', x.get('operation_id', x.get('kind', '')))))
        for key in ('tasks', 'operations', 'controls')}


def plan_hash(plan):
    normalized = plan_commands(plan)
    for row in normalized['controls']:
        row.pop('_ab_control_id', None)
    return digest(normalized)


def overlap(a, z, b, y):
    return max(0, min(z, y) - max(a, b))


def apply(plan, patches):
    result = copy.deepcopy(plan_commands(plan))
    for patch in patches:
        if patch['type'] == 'rows':
            key, identity = patch['collection'], patch['identity']
            replacements = {r[identity]: r for r in patch['rows']}
            if not set(replacements) <= {r[identity] for r in result[key]}:
                raise ValueError('PATCH_ADDS_UNKNOWN_ROW')
            result[key] = [copy.deepcopy(replacements.get(r[identity], r)) for r in result[key]]
        elif patch['type'] == 'control_interval':
            new = []
            for row in result['controls']:
                lo, hi = max(row['start_min'], patch['start_min']), min(row['end_min'], patch['end_min'])
                if row['asset_id'] != patch['asset_id'] or row['kind'] != patch['kind'] or lo >= hi:
                    new.append(row)
                    continue
                if row['start_min'] < lo:
                    new.append({**row, 'end_min': lo})
                new.append({**row, **patch['values'], 'start_min': lo, 'end_min': hi})
                if hi < row['end_min']:
                    new.append({**row, 'start_min': hi})
            result['controls'] = new
        else:
            raise ValueError('UNKNOWN_PATCH_TYPE')
    return plan_commands(result)


def operation_issues(context, plan, changed_ids):
    """Check requested handling against existing people, rooms and bookings."""
    issues = set()
    for op in plan['operations']:
        if op['operation_id'] not in changed_ids:
            continue
        a, z = op['start_min'], op['end_min']
        windows = context['operator_windows'].get(op['operator_id'], [])
        if not any(left <= a and z <= right for left, right in windows):
            issues.add('OPERATOR_UNAVAILABLE')
        for b in context['reservations']:
            if b['room_id'] == op['room_id'] and overlap(a, z, b['start_min'], b['end_min']):
                issues.add('FACILITY_RESERVED')
        for other in plan['operations']:
            if other['operation_id'] == op['operation_id']:
                continue
            if overlap(a, z, other['start_min'], other['end_min']):
                if other['operator_id'] == op['operator_id']:
                    issues.add('OPERATOR_DOUBLE_BOOKED')
                if other['room_id'] == op['room_id'] and not op['kind'].startswith('EV_') and not other['kind'].startswith('EV_'):
                    issues.add('ROOM_DOUBLE_BOOKED')
    return issues


def program_issues(context, plan, need_id):
    need = next(n for n in context['needs'] if n['need_id'] == need_id)
    chain = [t for t in plan['tasks'] if t['need_id'] in (need_id, need_id + ':dry')]
    handling = [o for o in plan['operations'] if o['need_id'] == need_id]
    loads = [o for o in handling if o['kind'] == 'load']
    unloads = [o for o in handling if o['kind'] == 'unload']
    if len(loads) != 1 or len(unloads) != 1 or not chain:
        return ['INCOMPLETE_PROGRAM_CHAIN']
    load, unload = loads[0], unloads[0]
    issues = operation_issues(context, plan, {o['operation_id'] for o in handling})
    first, finish = min(t['start_min'] for t in chain), max(t['end_min'] for t in chain)
    if load['start_min'] < need['release_min']:
        issues.add('LOAD_BEFORE_RELEASE')
    if load['end_min'] > first:
        issues.add('PROGRAM_BEFORE_LOAD_END')
    if unload['start_min'] < finish:
        issues.add('RETRIEVAL_BEFORE_PROGRAM_END')
    if unload['end_min'] > need['deadline_min']:
        issues.add('SERVICE_DEADLINE_MISSED')
    if unload['start_min'] - finish > need.get('maximum_retrieval_wait_min', float('inf')):
        issues.add('RETRIEVAL_WAIT_EXCEEDED')
    for other in plan['operations']:
        if other['kind'] != 'load' or other['need_id'] == need_id or other['asset_id'] != load['asset_id']:
            continue
        retrieval = next((o for o in plan['operations'] if o['need_id'] == other['need_id'] and o['kind'] == 'unload'), None)
        end = retrieval['end_min'] if retrieval else context['horizon_min'][1]
        if overlap(load['start_min'], unload['end_min'], other['start_min'], end):
            issues.add('ASSET_HOLD_CONFLICT')
    return sorted(issues)
