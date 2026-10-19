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
        elif patch['type'] == 'control_pause':
            new = []
            for row in result['controls']:
                lo, hi = max(row['start_min'], patch['start_min']), min(row['end_min'], patch['end_min'])
                if any(row.get(k) != patch[k] for k in ('asset_id', 'kind', 'need_id')) or lo >= hi:
                    new.append(row)
                    continue
                if row['start_min'] < lo:
                    new.append({**row, 'end_min': lo})
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
        original = next((r for r in context['A']['operations'] if r['operation_id'] == op['operation_id']), None)
        contract = context.get('authority')
        if contract and original != op:
            if op['operator_id'] in contract['immutable_operator_ids']:
                issues.add('CONTEXT_OPERATOR_IMMUTABLE')
            if op['operator_id'] not in contract['assets'][op['asset_id']]['authorized_operator_ids']:
                issues.add('OPERATOR_NOT_AUTHORIZED_FOR_ASSET')
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


def chain_need_ids(plan, need_id):
    result = {need_id}
    root_assets = {t['asset_id'] for t in plan['tasks'] if t['need_id'] == need_id}
    # Legacy automatic combos use ':dry' without a second handling chain.
    result.update(t['need_id'] for t in plan['tasks'] if t['need_id'] == need_id + ':dry' and t['asset_id'] in root_assets)
    while True:
        enlarged = result | {t['need_id'] for t in plan['tasks'] if t.get('depends_on_need_id') in result}
        if enlarged == result:
            return result
        result = enlarged


def _program_issues(context, plan, need_id):
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
    preload = first - load['end_min']
    if need.get('timer_allowed') is False and preload != 0:
        issues.add('TIMER_NOT_AVAILABLE')
    if preload > need.get('maximum_preload_wait_min', float('inf')):
        issues.add('PRELOAD_WAIT_EXCEEDED')
    if 'machine_windows_min' in need and not any(
            a <= first % 1440 and (finish - 1) % 1440 < z and first // 1440 == (finish - 1) // 1440
            for a, z in need['machine_windows_min']):
        issues.add('MACHINE_WINDOW_VIOLATED')
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


def program_issues(context, plan, need_id):
    if not any(t['need_id'] == need_id for t in plan['tasks']) or not any(o['need_id'] == need_id and o['kind'] == 'load' for o in plan['operations']):
        return ['INCOMPLETE_PROGRAM_CHAIN']
    nids = chain_need_ids(plan, need_id)
    issues = set()
    handled = {o['need_id'] for o in plan['operations'] if o['kind'] == 'load'}
    required = {need_id} | {t['need_id'] for t in plan['tasks'] if t['need_id'] in nids and t.get('depends_on_need_id')}
    if required - handled:
        issues.add('INCOMPLETE_PROGRAM_CHAIN')
    for nid in nids & handled:
        issues.update(_program_issues(context, plan, nid))
        for task in (t for t in plan['tasks'] if t['need_id'] == nid and t.get('depends_on_need_id')):
            parent = next((o for o in plan['operations'] if o['need_id'] == task['depends_on_need_id'] and o['kind'] == 'unload'), None)
            load = next(o for o in plan['operations'] if o['need_id'] == nid and o['kind'] == 'load')
            if parent is None or parent['end_min'] > load['start_min']:
                issues.add('PREREQUISITE_NOT_COLLECTED')
    return sorted(issues)


def request_issues(context, plan):
    """A request may move commands, not identities, actors, durations or the past."""
    issues = set()
    for key, ident in (('tasks', 'task_id'), ('operations', 'operation_id')):
        before = {r[ident]: r for r in context['A'][key]}; after = {r[ident]: r for r in plan[key]}
        if before.keys() != after.keys() or len(after) != len(plan[key]):
            issues.add('REQUEST_CHANGES_ORIGINAL_ROW_SET')
        for rid in before.keys() & after.keys():
            a, b = before[rid], after[rid]
            if {k: v for k, v in a.items() if k not in ('start_min', 'end_min')} != {k: v for k, v in b.items() if k not in ('start_min', 'end_min')} or a['end_min'] - a['start_min'] != b['end_min'] - b['start_min']:
                issues.add('REQUEST_CHANGES_ORIGINAL_RESOURCE_OR_DURATION')
            if min(a['start_min'], b['start_min']) < context['decision_min'] and a != b:
                issues.add('REQUEST_REWRITES_PREDECISION_COMMAND')
    def past_changes(rows):
        # Equal state multisets iff their clipped interval boundary deltas agree.
        # Linear construction avoids scanning a multi-day trajectory per boundary.
        changes = {}
        for r in rows:
            lo, hi = r['start_min'], min(r['end_min'], context['decision_min'])
            if lo >= hi:
                continue
            payload = digest({k: v for k, v in r.items() if k not in ('start_min', 'end_min', '_ab_control_id')})
            for t, delta in ((lo, 1), (hi, -1)):
                key = (payload, t)
                changes[key] = changes.get(key, 0) + delta
        return {k: v for k, v in changes.items() if v}
    if past_changes(context['A']['controls']) != past_changes(plan['controls']):
        issues.add('REQUEST_REWRITES_PREDECISION_CONTROL')
    return sorted(issues)


def control_issues(context, plan):
    """Check final combined thresholds, including jointly inverted heat/cool bands."""
    devices = {d['asset_id']: d for d in context['devices']}
    issues = set()
    for c in plan['controls']:
        if c['kind'] == 'ac_setpoint':
            heat, cool = c['heating_setpoint_C'], c['cooling_setpoint_C']
            if heat >= cool:
                issues.add('THERMOSTAT_DEADBAND_INVERTED')
            if not 5 <= heat <= 35 or not 15 <= cool <= 40:
                issues.add('SETPOINT_OUTSIDE_REFERENCE_RANGE')
        elif c['kind'] == 'tank_setpoint' and not 10 <= c['value_C'] <= devices[c['asset_id']]['parameters']['maximum_C']:
            issues.add('SETPOINT_OUTSIDE_HARDWARE_RANGE')
    return sorted(issues)
