"""Versioned, outcome-blind collection contract. These are experimental settings."""
import copy
import math
import re
from collections import Counter
from .common import canonical, digest
from .generate import DEFAULT_RULES, validate
from .model import apply, control_issues, program_issues, request_issues
from .power import site_capacity


DEFAULT = {
    'schema': 'eb.collection.design.v1', 'seed': 20261020,
    'first_date': '2025-07-15', 'days': 10, 'households': [],
    'event': {'event_id': 'fixed-vpp-18-19', 'start_min': 1080, 'end_min': 1140,
              'direction': 'down', 'target_kw': 1.5},
    'quantiles': [0.2, 0.5, 0.9], 'step_min': 10,
    'ac_delta_C': [0.5, 1.0, 2.0], 'tank_delta_C': [1.0, 3.0, 5.0],
    'thermal_duration_min': [20, 40, 60], 'ac_axes': ['cooling'],
    'precondition_min': 30, 'joint_budget': 192,
    'joint_trials_per_subset': 6, 'assignment_representatives_per_cell': 2,
    'solver_node_limit': 2000,
}


def design(value=None):
    c = {**copy.deepcopy(DEFAULT), **(value or {})}
    if set(c) != set(DEFAULT) or c['schema'] != DEFAULT['schema']:
        raise ValueError('UNKNOWN_COLLECTION_DESIGN')
    if c['days'] != 10 or c['step_min'] != 10 or c['event'] != DEFAULT['event']:
        raise ValueError('COLLECTION_REQUIRES_TEN_DAYS_AND_FIXED_18_19_EVENT')
    if type(c['seed']) is not int or len(c['households']) != len(set(c['households'])):
        raise ValueError('INVALID_COLLECTION_IDENTITIES')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', h) for h in c['households']):
        raise ValueError('UNSAFE_HOUSEHOLD_ID')
    if len(c['quantiles']) != 3 or not 0 < c['quantiles'][0] < c['quantiles'][1] < c['quantiles'][2] < 1:
        raise ValueError('THREE_ORDERED_INTERIOR_QUANTILES_REQUIRED')
    for k in ('ac_delta_C', 'tank_delta_C', 'thermal_duration_min'):
        if len(c[k]) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) or x <= 0 for x in c[k]) or c[k] != sorted(set(c[k])):
            raise ValueError('INVALID_COLLECTION_LEVELS:' + k)
    if any(x % 10 or x > 60 for x in c['thermal_duration_min']) or c['precondition_min'] <= 0 or c['precondition_min'] % 10:
        raise ValueError('INVALID_COLLECTION_DURATION')
    if not c['ac_axes'] or set(c['ac_axes']) - {'heating', 'cooling'}:
        raise ValueError('INVALID_DECLARED_REQUEST_AXES')
    for k in ('joint_budget', 'joint_trials_per_subset', 'assignment_representatives_per_cell', 'solver_node_limit'):
        if type(c[k]) is not int or c[k] <= 0:
            raise ValueError('INVALID_COLLECTION_BUDGET:' + k)
    return c


def working_context(context):
    """A bounded check index, not a replacement A; export/recheck uses full A.

    Keep complete program chains touching the materialization horizon and all
    rows of those chains, including their dependencies. No input row is mutated.
    """
    lo, hi = context['horizon_min']
    keep = {r['need_id'] for k in ('tasks', 'operations') for r in context['A'][k]
            if r['end_min'] > lo and r['start_min'] < hi}
    while True:
        enlarged = keep | {r['need_id'] for r in context['A']['tasks'] if r.get('depends_on_need_id') in keep}
        enlarged |= {r['depends_on_need_id'] for r in context['A']['tasks'] if r['need_id'] in keep and r.get('depends_on_need_id')}
        if enlarged == keep:
            break
        keep = enlarged
    c = dict(context)
    c['A'] = {k: [r for r in context['A'][k] if r['need_id'] in keep] for k in ('tasks', 'operations')}
    c['A']['controls'] = [{**r, 'start_min': max(lo, r['start_min']), 'end_min': min(hi, r['end_min'])}
        for r in context['A']['controls'] if r['end_min'] > lo and r['start_min'] < hi]
    c['reference'] = {**context['reference'], 'ev_charging_steps': [s for s in context['reference'].get('ev_charging_steps', [])
        if s['start_min'] >= lo and s['start_min'] < hi]}
    return c


def validate_context(c):
    validate(c, DEFAULT_RULES)
    if c['reference']['information_set']['mode'] != 'offline_unexecuted_A_plan':
        raise ValueError('COLLECTION_REQUIRES_UNEXECUTED_A_WITHOUT_B_OR_HUMAN_OUTCOMES')
    if c['events'] != [DEFAULT['event']]:
        raise ValueError('COLLECTION_EVENT_BINDING_MISMATCH')


def issues(c, patches, needs=()):
    b = apply(c['A'], patches)
    gate = request_issues(c, b)
    changed = {p.get('asset_id') for p in patches if p.get('asset_id')}
    changed |= {r['asset_id'] for p in patches for r in p.get('rows', [])}
    gate += ['TARGET_CONTROL_NOT_AUTHORIZED' for aid in changed
             if not c['authority']['assets'][aid]['target_control_authorized']]
    out = set(gate) | set(control_issues(c, b))
    for nid in needs:
        out.update(program_issues(c, b, nid))
    # Resource-authorization failures can emerge from dependent handling, not
    # only from the root asset. They are immutable gates, never ordinary stress.
    gate = sorted(set(gate) | (out & {'CONTEXT_OPERATOR_IMMUTABLE',
        'OPERATOR_NOT_AUTHORIZED_FOR_ASSET', 'TARGET_CONTROL_NOT_AUTHORIZED'}))
    power = site_capacity(c, b)
    out.update(power['issues'])
    return sorted(out), gate, power


def representatives(values, quantiles):
    values = sorted(set(values))
    if not values:
        return []
    return sorted({values[round(q * (len(values) - 1))] for q in quantiles})


def annotate_doses(rows, config):
    """Relative labels do not turn narrow windows into large absolute changes."""
    groups = {}
    for r in rows:
        groups.setdefault((r['unit'], r['mechanism'], r.get('branch', 'none')), []).append(r)
    for group in groups.values():
        values = sorted({r['magnitude']['dose_coordinate'] for r in group if not r['issues']})
        for r in group:
            v = r['magnitude']['dose_coordinate']
            rank = sum(x <= v for x in values) / len(values) if values else None
            r['magnitude']['relative_position'] = rank
            r['relative_level'] = ('diagnostic' if r['issues'] else 'narrow_singleton' if len(values) <= 1 else
                                   'low' if rank <= 1/3 else 'medium' if rank <= 2/3 else 'high')


def absolute_level(row):
    """Reporting bins are project settings, not household preference labels."""
    m = row['magnitude']
    if row['family'] in ('washer', 'dishwasher', 'dryer'):
        x = max(m.get('machine_shift_min', 0), m.get('manual_max_shift_min', 0))
        return 'small' if x <= 30 else 'medium' if x < 90 else 'large'
    if row['family'] == 'ev':
        return 'large' if m.get('service_slack_min', 1e9) < 30 or m.get('pause_min', 0) >= 180 else 'small' if m.get('pause_min', 0) <= 30 else 'medium'
    levels = [0.5, 1, 2] if row['family'] == 'ac' else [1, 3, 5]
    x = m['service_delta_C']
    return 'small' if x <= levels[0] else 'medium' if x <= levels[1] else 'large'


def event_status(known, unknown):
    if unknown:
        return 'unknown_with_known_reduction' if known > 1e-9 else 'unknown'
    return 'reduction' if known > 1e-9 else 'increase' if known < -1e-9 else 'zero'


def tags(row):
    f = row['features']
    out = {f'{k}={f[k]}' for k in ('device_count', 'intensity', 'admission', 'event', 'manual', 'thermal_direction', 'service_slack')}
    out.add('composition=' + f['composition'])
    out.update('mechanism=' + s for s in f['mechanisms'])
    for a, b in (('device_count', 'intensity'), ('device_count', 'admission'), ('event', 'manual')):
        out.add(a + '=' + f[a] + '|' + b + '=' + f[b])
    return sorted(out)


def semantic_signature(c, row):
    # Raw timestamps/IDs alone cannot create new household tradeoffs. Preserve
    # actual weekday, tariffs, manual availability, service bounds and uncertainty.
    context = {'weekday': __import__('datetime').date.fromisoformat(c['date']).weekday(),
        'tariff': c['tariff'], 'devices': [{k: d.get(k) for k in ('asset_id', 'types', 'parameters')} for d in c['devices']],
        'windows': {k: [[max(480,a), min(1920,z)] for a,z in v if z>480 and a<1920] for k,v in c['operator_windows'].items()},
        'needs': [{k:v for k,v in n.items() if k != 'need_id'} for n in c['needs']
                  if n['release_min'] < 1920 and n['deadline_min'] > 480],
        'authority': c['authority'], 'uncertainty': 'no_thermal_A_state',
        'electrical': c.get('electrical'),
        'A': {k:[{a:b for a,b in r.items() if a not in ('task_id','operation_id','_ab_control_id')}
                 for r in v] for k,v in c['A'].items()},
        'features': row['features'], 'reasons': row['issues'],
        'dose_bins': sorted((x['unit'], x['absolute_level'], x['mechanism'],
                            x['magnitude'].get('axis','none'),x['magnitude'].get('direction','none'),
                            x['magnitude'].get('duration_min',0)) for x in row['components'])}
    # Need IDs in lineage/source policy strings carry dates; remove date tokens
    # only from the near-duplicate key, never from exported plans or provenance.
    return digest(re.sub(r'\d{4}-\d{2}-\d{2}', '<date>', canonical(context)))


def report_counts(rows):
    return {k: dict(sorted(Counter(r['features'][k] for r in rows).items()))
            for k in ('device_count', 'intensity', 'admission', 'event', 'manual', 'composition')}
