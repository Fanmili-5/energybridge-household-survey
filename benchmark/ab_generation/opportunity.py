"""Ex-ante mechanism screens. No B simulation or household answer is read."""
from .model import overlap

EPSILON = 1e-9  # numerical comparison only, never a human indifference threshold


def profile_evidence(context, before, after):
    """Time-resolved L1; equal daily totals do not imply equal operation."""
    lo, hi = context['decision_min'], context['horizon_min'][1]
    assets = sorted({r['asset_id'] for r in before + after})
    changes = {}
    for aid in assets:
        values = []
        for t in range(lo, hi, 10):
            energies = [sum(r['power_kw'] * overlap(t, t + 10, r['start_min'], r['end_min']) / 60
                            for r in rows if r['asset_id'] == aid) for rows in (before, after)]
            values.append(abs(energies[1] - energies[0]))
        changes[aid] = sum(values)
    supported = bool(changes) and all(v > EPSILON for v in changes.values())
    return {'status': 'supported' if supported else 'exploratory',
            'basis': 'declared_time_resolved_program_or_EV_profile',
            'asset_L1_kWh': changes, 'actual_response_confirmed': False,
            'reason': 'all_target_profiles_change' if supported else 'target_profile_unchanged_in_horizon'}


def thermal_evidence(device, axis, wanted, baseline, state, lo, hi, change, active_min):
    """Conservative sampled-A thermostat witnesses, not a counterfactual solver.

    For stratified tanks use bounds over ALL nodes, never mean tank temperature
    as if it were the thermostat sensor. Missing nodes remain exploratory.
    """
    witnesses, reasons = [], set()
    for t in range(lo, hi, 10):
        r = state[t]
        c = next(c for c in baseline if c['start_min'] <= t < c['end_min'])
        active = r.get('axis_electric_kWh', {}).get(axis) if axis != 'tank' else r['electric_kWh']
        if wanted == 'down' and (active is None or active <= active_min):
            reasons.add('no_native_A_axis_load'); continue
        if wanted == 'up' and r['headroom_kWh'] <= active_min:
            reasons.add('no_nominal_headroom'); continue
        if axis == 'tank':
            nodes = r.get('node_temperatures_C')
            deadband = device['parameters'].get('deadband_C')
            if not nodes or deadband is None:
                reasons.add('tank_node_or_deadband_evidence_missing'); continue
            target = c['value_C'] + change
            crosses = (max(nodes) < target - deadband - EPSILON if wanted == 'up'
                       else min(nodes) >= target - EPSILON)
        else:
            target = c[axis + '_setpoint_C'] + change
            temperature = r['temperature_C']
            crosses = ((temperature > target + EPSILON if axis == 'cooling' else temperature < target - EPSILON)
                       if wanted == 'up' else
                       (temperature <= target + EPSILON if axis == 'cooling' else temperature >= target - EPSILON))
        if crosses:
            witnesses.append(t)
        else:
            reasons.add('shifted_threshold_not_crossed_at_A_samples')
    return {'status': 'supported' if witnesses else 'exploratory',
            'basis': 'sampled_A_state_and_shifted_thermostat_threshold',
            'witness_minutes': witnesses, 'reasons': sorted(reasons),
            'actual_response_confirmed': False,
            'scope': 'A_state_mechanism_screen;not_guaranteed_B_response_or_acceptable_comfort'}


def joint_evidence(children):
    entries = [{'candidate_id': c['id'], 'asset_id': c['asset_id'], **c['opportunity']} for c in children]
    supported = sum(c['status'] == 'supported' for c in entries)
    return {'status': 'supported' if supported == len(entries) else 'exploratory',
            'joint_support': 'all_supported' if supported == len(entries) else 'mixed' if supported else 'all_exploratory',
            'children': entries, 'actual_response_confirmed': False,
            'scope': 'each_child_screened_separately;thermal_and_shared_resource_coupling_requires_paired_run'}
