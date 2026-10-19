"""Cumulative site-capacity screen with explicit known and conservative loads."""
import math
from .energy import task_power


def ev_profile(context, plan):
    devices = {d['asset_id']: d for d in context['devices']}
    groups = {}
    for step in context['reference'].get('ev_charging_steps', []):
        groups.setdefault(step['need_id'], []).append(step)
    profile = []
    for nid, steps in groups.items():
        original = [c for c in context['A']['controls'] if c['kind'] == 'ev_charge_window' and c['need_id'] == nid]
        controls = [c for c in plan['controls'] if c['kind'] == 'ev_charge_window' and c['need_id'] == nid]
        if not original:
            continue
        aid = original[0]['asset_id']; rating = devices[aid]['parameters']['charger_kw']
        remaining = sum(s['grid_kWh'] for s in steps if s['start_min'] >= context['decision_min'])
        release = max(context['decision_min'], min(s['start_min'] for s in steps))
        stop = max(c['end_min'] for c in original)
        for t in range(release, min(stop, context['horizon_min'][1]), 10):
            if remaining <= 1e-10:
                break
            if any(c['start_min'] <= t and t + 10 <= c['end_min'] for c in controls):
                energy = min(rating / 6, remaining); remaining -= energy
                profile.append({'asset_id': aid, 'start_min': t, 'end_min': t + 10, 'power_kw': energy * 6})
    return profile


def site_capacity(context, plan):
    contract = context.get('electrical')
    if contract is None:
        return {'status': 'not_declared_legacy', 'issues': [], 'scope': 'historical_context_has_no_site_capacity_certificate'}
    if (contract.get('schema') != 'eb.ab_site_capacity.v1' or any(type(contract[k]) not in (int, float)
            or not math.isfinite(contract[k]) or contract[k] < 0 for k in ('supply_W', 'background_upper_W')) or contract['supply_W'] <= 0):
        raise ValueError('INVALID_SITE_CAPACITY_CONTRACT')
    devices = {d['asset_id']: d for d in context['devices']}
    lo, hi = context['decision_min'], context['horizon_min'][1]
    known = {t: 0. for t in range(lo, hi, 10)}
    for task in plan['tasks']:
        watts = task_power(task, devices[task['asset_id']]['parameters']) * 1000
        for t in range(max(lo, task['start_min']), min(hi, task['end_min']), 10):
            known[t] += watts
    for step in ev_profile(context, plan):
        for t in range(step['start_min'], step['end_min'], 10):
            if t in known:
                known[t] += step['power_kw'] * 1000
    upper = dict(known)
    for t in upper:
        upper[t] += contract['background_upper_W']
    for d in devices.values():
        kind = d.get('kind', d['types'][0]); p = d['parameters']
        if kind not in ('ac', 'water_heater'):
            continue
        rating = p['nameplate_W'] if kind == 'ac' else p['heater_capacity_W'] / p['efficiency']
        enabled = set()
        for c in plan['controls']:
            if c['asset_id'] == d['asset_id']:
                enabled.update(range(max(lo, c['start_min']), min(hi, c['end_min']), 10))
        for t in enabled:
            upper[t] += rating
    supply = contract['supply_W']
    definite = [t for t in known if known[t] > supply + 1e-6]
    uncertain = [t for t in upper if upper[t] > supply + 1e-6]
    issues = ['SITE_KNOWN_PROFILE_EXCEEDS_SUPPLY'] if definite else ['SITE_CAPACITY_NOT_CERTIFIED'] if uncertain else []
    return {'status': 'known_profile_overload' if definite else 'conservative_bound_exceeded' if uncertain else 'certified_within_declared_envelope',
        'issues': issues, 'supply_W': supply, 'known_profile_peak_W': max(known.values(), default=0),
        'upper_envelope_peak_W': max(upper.values(), default=0), 'known_excess_minutes': definite,
        'uncertified_minutes': uncertain, 'interval_min': [lo, hi],
        'scope': '10min_batch_mean_and_given_EV_energy;all_thermal_nameplates_and_background_upper_reserved;conditional_on_model;not_breaker_trip_or_inrush',
        'B_native_measurement_used': False}
