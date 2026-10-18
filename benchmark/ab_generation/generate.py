"""Enumerate requests before paired simulation; preserve absent opportunities."""
import copy
import math
from .common import digest
from .model import apply, chain_need_ids, overlap, plan_commands, plan_hash, program_issues

DEFAULT_RULES = {
    'schema': 'eb.ab_generation.rules.v1', 'seed': 20261019, 'step_min': 10,
    'program_shifts_min': [-120, -60, -30, 30, 60, 120],
    'handling_modes': ['timer_only', 'shift_chain'],
    'thermal_delta_C': [0.5, 1.0], 'thermal_duration_min': [20, 60],
    'thermal_request_directions': ['aligned', 'opposing'],
    'ev_delays_min': [30, 60, 120],
    'thermal_active_min_kWh': 0.001,
    'selection_policies': ['least_disruption', 'known_profile_cost', 'known_profile_vpp'],
    'joint_family_limit': 2,
}


def binding(context):
    base = copy.deepcopy({k: v for k, v in context.items()
                          if k not in ('reference', 'tariff', 'events', 'assignment', 'retained_B_request')})
    base['A'] = plan_commands(base['A'])
    for row in base['A']['controls']:
        row.pop('_ab_control_id', None)
    return {'A_commands_sha256': plan_hash(context['A']),
            'context_sha256': digest(base)}


def validate(context, rules):
    if context.get('schema') != 'eb.ab_generation.context.v1':
        raise ValueError('UNKNOWN_CONTEXT_SCHEMA')
    if set(rules) != set(DEFAULT_RULES) or rules.get('schema') != DEFAULT_RULES['schema']:
        raise ValueError('UNKNOWN_RULE_KEYS_OR_SCHEMA')
    if rules['step_min'] != 10:
        raise ValueError('ONLY_10_MINUTE_GRID_SUPPORTED')
    for key in ('program_shifts_min', 'thermal_duration_min', 'ev_delays_min'):
        if not rules[key] or any(type(v) is not int or v % 10 for v in rules[key]):
            raise ValueError('INVALID_TIME_GRID:' + key)
    if any(v <= 0 for v in rules['thermal_duration_min'] + rules['ev_delays_min'] + rules['thermal_delta_C']):
        raise ValueError('NONPOSITIVE_DOSE')
    if set(rules['handling_modes']) - {'timer_only', 'shift_chain'} or set(rules['thermal_request_directions']) - {'aligned', 'opposing'}:
        raise ValueError('UNKNOWN_DESIGN_LEVEL')
    if set(rules['selection_policies']) - {'least_disruption', 'known_profile_cost', 'known_profile_vpp'}:
        raise ValueError('UNKNOWN_SELECTION_POLICY')
    if type(rules['joint_family_limit']) is not int or not 1 <= rules['joint_family_limit'] <= 2:
        raise ValueError('JOINT_FAMILY_LIMIT_MUST_BE_1_OR_2')
    ids = [d['asset_id'] for d in context['devices']]
    if len(ids) != len(set(ids)):
        raise ValueError('DUPLICATE_ASSET')
    if context['decision_min'] % 10 or context['horizon_min'][0] > context['decision_min']:
        raise ValueError('INVALID_DECISION')
    for kind, ident in [('tasks', 'task_id'), ('operations', 'operation_id')]:
        rows = context['A'][kind]
        if len({x[ident] for x in rows}) != len(rows):
            raise ValueError('DUPLICATE_ROW_ID')
    for rows in plan_commands(context['A']).values():
        for row in rows:
            if row['asset_id'] not in ids or row['start_min'] >= row['end_min'] or row['start_min'] % 10 or row['end_min'] % 10:
                raise ValueError('INVALID_PLAN_ROW')
    if context['reference']['binding'] != binding(context):
        raise ValueError('STALE_A_REFERENCE')
    for e in context['events']:
        if not (context['decision_min'] <= e['start_min'] < e['end_min'] <= context['horizon_min'][1]) or e['direction'] not in ('up', 'down') or e['start_min'] % 10 or e['end_min'] % 10:
            raise ValueError('INVALID_FROZEN_EVENT')
    if context.get('assignment', {}).get('mode', 'fresh_candidates') not in ('fresh_candidates', 'identical_control', 'preserved_failure_replay'):
        raise ValueError('UNKNOWN_ASSIGNMENT')
    if context.get('assignment', {}).get('mode') == 'preserved_failure_replay' and 'retained_B_request' not in context:
        raise ValueError('ORIGINAL_FAILURE_REQUEST_REQUIRED')
    tariff = sorted(context['tariff'], key=lambda x: x['start_min'])
    if any(r['start_min'] >= r['end_min'] for r in tariff) or any(a['end_min'] > b['start_min'] for a, b in zip(tariff, tariff[1:])):
        raise ValueError('INVALID_TARIFF_INTERVALS')
    # The same resource's control rows must define an unambiguous baseline.
    groups = {}
    for row in context['A']['controls']:
        groups.setdefault((row['asset_id'], row['kind']), []).append(row)
    for rows in groups.values():
        ordered = sorted(rows, key=lambda x: x['start_min'])
        if any(a['end_min'] > b['start_min'] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('OVERLAPPING_BASELINE_CONTROLS')


def event_energy(profile, event):
    return sum(x['power_kw'] * overlap(x['start_min'], x['end_min'], event['start_min'], event['end_min']) / 60 for x in profile)


def cost(profile, tariff):
    if any(sum(overlap(x['start_min'], x['end_min'], r['start_min'], r['end_min']) for r in tariff) != x['end_min'] - x['start_min'] for x in profile):
        return None
    return sum(x['power_kw'] * rate['price_per_kWh'] * overlap(x['start_min'], x['end_min'], rate['start_min'], rate['end_min']) / 60
               for x in profile for rate in tariff)


def candidate(context, family, asset, factors, patches, issues, profiles=None):
    """Predictions concern commanded constant-power profiles, never final EP."""
    a, b = profiles if profiles is not None else (None, None)
    if a is None:
        metrics = {'delta_cost': None, 'event_delta_kWh': None, 'aligned_event_kWh': None,
                   'prediction_scope': 'thermal_response_requires_paired_simulation'}
    else:
        events = [{'event_id': e['event_id'], 'delta_kWh': event_energy(b, e) - event_energy(a, e)} for e in context['events']]
        ca, cb = cost(a, context['tariff']), cost(b, context['tariff'])
        metrics = {'delta_cost': cb - ca if ca is not None and cb is not None else None,
                   'event_delta_kWh': events,
                   'aligned_event_kWh': sum(x['delta_kWh'] * (1 if e['direction'] == 'up' else -1) for x, e in zip(events, context['events'])),
                   'prediction_scope': 'commanded_constant_power_profile;not_final_executed_outcome'}
    row = {'family': family, 'asset_id': asset, 'factors': factors, 'patches': patches,
           'static_issues': sorted(set(issues)), 'prediction': metrics,
           'actual_outcomes': None, 'human_acceptance': None}
    row['id'] = digest({'binding': context['reference']['binding'], 'candidate': row})[:24]
    return row


def program_candidates(context, device, rules):
    aid, rows, unavailable = device['asset_id'], [], []
    needs = [n for n in context['needs'] if n['asset_id'] == aid and n['kind'] in ('washer', 'dishwasher')]
    for need in needs:
        nid = need['need_id']
        if not any(t['need_id'] == nid for t in context['A']['tasks']):
            continue
        chain_ids = chain_need_ids(context['A'], nid)
        chain = [t for t in context['A']['tasks'] if t['need_id'] in chain_ids]
        if not chain or min(t['start_min'] for t in chain) < context['decision_min'] or min(t['start_min'] for t in chain) >= context['horizon_min'][1]:
            continue
        ops = [o for o in context['A']['operations'] if o['need_id'] in chain_ids and o['kind'] in ('load', 'unload')]
        if not any(o['need_id'] == nid and o['kind'] == 'load' for o in ops) or not any(o['need_id'] == nid and o['kind'] == 'unload' for o in ops):
            unavailable.append({'asset_id': aid, 'need_id': nid, 'reason': 'INCOMPLETE_PROGRAM_CHAIN'})
            continue
        devices = {d['asset_id']: d for d in context['devices']}
        def profile(tasks):
            return [{**t, 'power_kw': devices[t['asset_id']]['parameters'].get(t['kind'], devices[t['asset_id']]['parameters'])['power_kw']} for t in tasks]
        for delta in rules['program_shifts_min']:
            for handling in rules['handling_modes']:
                if delta == 0:
                    continue
                tasks = [{**t, 'start_min': t['start_min'] + delta, 'end_min': t['end_min'] + delta} for t in chain]
                moved = [{**o, 'start_min': o['start_min'] + delta, 'end_min': o['end_min'] + delta} for o in ops] if handling == 'shift_chain' else copy.deepcopy(ops)
                patches = [{'type': 'rows', 'collection': 'tasks', 'identity': 'task_id', 'rows': tasks},
                           {'type': 'rows', 'collection': 'operations', 'identity': 'operation_id', 'rows': moved}]
                issues = program_issues(context, apply(context['A'], patches), nid)
                if min(t['start_min'] for t in tasks) < context['decision_min']:
                    issues.append('PROGRAM_BEFORE_DECISION')
                if handling == 'shift_chain' and min(o['start_min'] for o in ops + moved) < context['decision_min']:
                    issues.append('CHANGES_PREDECISION_HANDLING')
                factors = {'need_id': nid, 'program_shift_min': delta, 'handling_mode': handling,
                           'manual_change_min': sum(abs(b['start_min'] - a['start_min']) for a, b in zip(ops, moved)),
                           'requested_duration_min': 0, 'setpoint_delta_C': 0}
                rows.append(candidate(context, need['kind'], aid, factors, patches, issues, (profile(chain), profile(tasks))))
    return rows, unavailable


def thermal_candidates(context, device, rules):
    aid, rows, unavailable = device['asset_id'], [], []
    family = 'ac' if 'ac' in device['types'] else 'water_heater'
    kind = 'ac_setpoint' if family == 'ac' else 'tank_setpoint'
    reference = context['reference'].get('thermal', {}).get(aid)
    if reference is None:
        return [], [{'asset_id': aid, 'reason': 'CURRENT_A_THERMAL_REFERENCE_UNAVAILABLE'}]
    state = {x['minute']: x for x in reference}
    baseline = [c for c in context['A']['controls'] if c['asset_id'] == aid and c['kind'] == kind]
    def control(t):
        return next((x for x in baseline if x['start_min'] <= t < x['end_min']), None)
    for event in context['events']:
        for direction in rules['thermal_request_directions']:
            wanted = event['direction'] if direction == 'aligned' else ('up' if event['direction'] == 'down' else 'down')
            possible = []
            for t in range(event['start_min'], event['end_min'], 10):
                a, r = control(t), state.get(t)
                if a is None or r is None:
                    continue
                if family == 'ac' and not any(l <= t and t + 10 <= h for l, h in context['occupancy'].get(device['room_id'], [])):
                    continue
                if wanted == 'down' and r['electric_kWh'] <= rules['thermal_active_min_kWh']:
                    continue
                if wanted == 'up' and r['headroom_kWh'] <= rules['thermal_active_min_kWh']:
                    continue
                possible.append(t)
            if not possible:
                unavailable.append({'asset_id': aid, 'event_id': event['event_id'], 'direction': direction, 'reason': 'NO_CURRENT_A_OPERATING_HEADROOM'})
                continue
            for duration in rules['thermal_duration_min']:
                # Prefer a contiguous occupied/permission interval; never join across gaps.
                starts = []
                for lo in possible:
                    hi = lo
                    while hi < min(event['end_min'], lo + duration) and control(hi) is not None and hi in state:
                        if family == 'ac' and not any(l <= hi and hi + 10 <= h for l, h in context['occupancy'].get(device['room_id'], [])):
                            break
                        hi += 10
                    starts.append((lo, hi))
                lo, hi = min(starts, key=lambda x: (-(x[1] - x[0]), x[0]))
                for delta in rules['thermal_delta_C']:
                    patches, issues = [], []
                    axis = 'tank' if family != 'ac' else ('heating' if abs(state[lo]['temperature_C'] - control(lo)['heating_setpoint_C']) < abs(state[lo]['temperature_C'] - control(lo)['cooling_setpoint_C']) else 'cooling')
                    change = delta * (1 if (axis in ('heating', 'tank')) == (wanted == 'up') else -1)
                    for a in baseline:
                        begin, end = max(lo, a['start_min']), min(hi, a['end_min'])
                        if begin >= end:
                            continue
                        if family == 'ac':
                            key = axis + '_setpoint_C'
                            values = {key: a[key] + change}
                            if axis == 'cooling' and 'value_C' in a:
                                values['value_C'] = values[key]
                            heat = values.get('heating_setpoint_C', a['heating_setpoint_C'])
                            cool = values.get('cooling_setpoint_C', a['cooling_setpoint_C'])
                            if heat >= cool:
                                issues.append('THERMOSTAT_DEADBAND_INVERTED')
                        else:
                            values = {'value_C': a['value_C'] + change}
                            if not 10 <= values['value_C'] <= device['parameters']['maximum_C']:
                                issues.append('SETPOINT_OUTSIDE_HARDWARE_RANGE')
                        patches.append({'type': 'control_interval', 'asset_id': aid, 'kind': kind,
                                        'start_min': begin, 'end_min': end, 'values': values})
                    factors = {'event_id': event['event_id'], 'direction': direction, 'thermal_axis': axis,
                               'setpoint_delta_C': delta, 'requested_duration_min': duration,
                               'available_duration_min': hi - lo, 'manual_change_min': 0,
                               'program_shift_min': 0, 'baseline_restored_after_min': hi}
                    rows.append(candidate(context, family, aid, factors, patches, issues))
    return rows, unavailable


def ev_candidates(context, device, rules):
    aid, rows = device['asset_id'], []
    for a in context['A']['controls']:
        if a['asset_id'] != aid or a['kind'] != 'ev_charge_window' or a['start_min'] < context['decision_min'] or a['start_min'] >= context['horizon_min'][1]:
            continue
        steps = [s for s in context['reference'].get('ev_charging_steps', []) if s['need_id'] == a['need_id'] and s['grid_kWh'] > 0]
        if not steps:
            continue  # Idle permission tails are not charging opportunities.
        for delay in rules['ev_delays_min']:
            new = {**a, 'start_min': a['start_min'] + delay}
            if 'actual_charge_end_min' in new:
                new['actual_charge_end_min'] += delay
            if new['start_min'] >= new['end_min']:
                continue
            issues = []
            if max(s['end_min'] for s in steps) + delay > a['end_min']:
                issues.append('CHARGE_EXCEEDS_ORIGINAL_CONNECTION')
            patches = [{'type': 'rows', 'collection': 'controls', 'identity': '_ab_control_id',
                        'rows': [{**new, '_ab_control_id': a['_ab_control_id']}]}]
            before = [{**s, 'power_kw': s['grid_kWh'] * 60 / (s['end_min'] - s['start_min'])} for s in steps]
            after = [{**s, 'start_min': s['start_min'] + delay, 'end_min': s['end_min'] + delay} for s in before]
            factors = {'need_id': a['need_id'], 'ev_delay_min': delay, 'manual_change_min': 0,
                       'program_shift_min': 0, 'setpoint_delta_C': 0, 'requested_duration_min': 0,
                       'original_connection_end_min': a['end_min'], 'full_continuous_SOC_validation': 'pending_paired_execution'}
            rows.append(candidate(context, 'ev', aid, factors, patches, issues, (before, after)))
    return rows, []


def disruption(row):
    f = row['factors']
    return (f['manual_change_min'], f['setpoint_delta_C'] * f['requested_duration_min'],
            abs(f['program_shift_min']) + f.get('ev_delay_min', 0))


def generate(context, rules=None):
    context = copy.deepcopy(context)
    input_context_sha256 = digest(context)
    rules = {**DEFAULT_RULES, **(rules or {})}
    validate(context, rules)
    a_hash = plan_hash(context['A'])
    # Internal identities are stripped before exporting a physical request.
    for row in context['A']['controls']:
        row['_ab_control_id'] = digest(row)
    candidates, unavailable = [], []
    for d in sorted(context['devices'], key=lambda x: x['asset_id']):
        types = set(d['types'])
        fn = program_candidates if types & {'washer', 'dishwasher'} else ev_candidates if 'ev' in types else thermal_candidates if types & {'ac', 'water_heater'} else None
        if fn:
            rows, gaps = fn(context, d, rules)
            candidates.extend(rows)
            unavailable.extend(gaps)
    candidates.sort(key=lambda x: x['id'])
    selections = {}
    eligible = [x for x in candidates if not x['static_issues']]
    assignment = context.get('assignment', {'mode': 'fresh_candidates'})
    for policy in rules['selection_policies']:
        pool = eligible
        if policy == 'known_profile_cost':
            pool = [x for x in pool if x['prediction']['delta_cost'] is not None]
        if policy == 'known_profile_vpp':
            pool = [x for x in pool if x['prediction']['aligned_event_kWh'] is not None]
        def key(row):
            tie = digest([rules['seed'], context['case_id'], policy, row['id']])
            if policy == 'known_profile_cost':
                return (row['prediction']['delta_cost'], disruption(row), tie)
            if policy == 'known_profile_vpp':
                return (-row['prediction']['aligned_event_kWh'], disruption(row), tie)
            return (disruption(row), tie)
        if assignment['mode'] == 'identical_control':
            selected, status = [], 'assigned_identical_control'
        elif assignment['mode'] == 'preserved_failure_replay':
            selected, status = [], 'original_failure_request_preserved'
        elif pool:
            selected, status = [min(pool, key=key)], 'candidate_selected'
        else:
            selected, status = [], 'no_comparable_opportunity'
        patches = [p for row in selected for p in row['patches']]
        plan = (plan_commands(context['retained_B_request']) if assignment['mode'] == 'preserved_failure_replay'
                else apply(context['A'], patches))
        for c in plan['controls']:
            c.pop('_ab_control_id', None)
        selections[policy] = {'candidate_ids': [x['id'] for x in selected], 'status': status,
                              'plan_B': plan, 'B_commands_sha256': plan_hash(plan),
                              'actual_outcomes': None, 'human_acceptance': None}
    # A joint request is a separate experimental candidate; detect new conflicts,
    # retain the combined proposal with its failures rather than repairing it.
    joint = []
    by_family = {}
    for row in eligible:
        by_family.setdefault(row['family'], []).append(row)
    if rules['joint_family_limit'] == 2:
        families = sorted(by_family)
        for i, family in enumerate(families):
            for other in families[i + 1:]:
                left = min(by_family[family], key=lambda x: (disruption(x), x['id']))
                right = min(by_family[other], key=lambda x: (disruption(x), x['id']))
                if left['asset_id'] == right['asset_id']:
                    continue
                patches = left['patches'] + right['patches']
                plan = apply(context['A'], patches)
                issues = []
                for row in (left, right):
                    if row['family'] in ('washer', 'dishwasher'):
                        issues.extend(program_issues(context, plan, row['factors']['need_id']))
                joint.append({'candidate_ids': [left['id'], right['id']], 'patches': patches,
                              'static_issues': sorted(set(issues)), 'actual_outcomes': None,
                              'status': 'joint_request_failure_retained' if issues else 'joint_static_check_passed'})
    return {'schema': 'eb.ab_generation.result.v1', 'case_id': context['case_id'],
            'binding': context['reference']['binding'], 'A_commands_sha256': a_hash,
            'context_sha256': input_context_sha256,
            'reference_sha256': digest(context['reference']), 'rules_sha256': digest(rules),
            'assignment': assignment, 'candidates': candidates, 'unavailable': unavailable,
            'selections': selections, 'joint_candidates': joint,
            'paired_execution_status': 'not_run', 'human_acceptance': None,
            'final_B_outcomes_used_for_selection': False}
