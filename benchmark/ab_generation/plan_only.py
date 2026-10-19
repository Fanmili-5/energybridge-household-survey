"""Permission-bounded thermal exploration when no A thermal state exists.

These are commanded-plan alternatives, never evidence of operating headroom or
actual response. Oracle-backed thermal generation remains unchanged.
"""
from .model import apply, control_issues


def thermal_plan_candidates(context, device, rules):
    from .generate import candidate
    aid = device['asset_id']
    family = 'ac' if 'ac' in device['types'] else 'water_heater'
    kind = 'ac_setpoint' if family == 'ac' else 'tank_setpoint'
    controls = [r for r in context['A']['controls'] if r['asset_id'] == aid and r['kind'] == kind]
    rows, unavailable = [], []
    for event in context['events']:
        permitted = []
        for t in range(max(context['decision_min'], event['start_min']), event['end_min'], rules['step_min']):
            if not any(r['start_min'] <= t and t + rules['step_min'] <= r['end_min'] for r in controls):
                continue
            if family == 'ac' and not any(a <= t and t + rules['step_min'] <= z
                    for a, z in context['occupancy'].get(device['room_id'], [])):
                continue
            permitted.append(t)
        if not permitted:
            unavailable.append({'asset_id': aid, 'event_id': event['event_id'], 'reason': 'NO_DECLARED_CONTROL_AND_ROOM_WINDOW'})
            continue
        allowed = set(permitted)
        for duration in rules['thermal_duration_min']:
            spans = []
            for lo in permitted:
                hi = lo
                while hi < min(lo + duration, event['end_min']) and hi in allowed:
                    hi += rules['step_min']
                spans.append((lo, hi))
            lo, hi = min(spans, key=lambda s: (-(s[1] - s[0]), s[0]))
            for axis in (('heating', 'cooling') if family == 'ac' else ('tank',)):
                for direction in rules['thermal_request_directions']:
                    wanted = event['direction'] if direction == 'aligned' else ('up' if event['direction'] == 'down' else 'down')
                    for delta in rules['thermal_delta_C']:
                        change = delta * (1 if (axis in ('heating', 'tank')) == (wanted == 'up') else -1)
                        patches = []
                        for r in controls:
                            begin, end = max(lo, r['start_min']), min(hi, r['end_min'])
                            if begin >= end:
                                continue
                            key = axis + '_setpoint_C' if family == 'ac' else 'value_C'
                            values = {key: r[key] + change}
                            if axis == 'cooling' and 'value_C' in r:
                                values['value_C'] = values[key]
                            patches.append({'type': 'control_interval', 'asset_id': aid, 'kind': kind,
                                            'start_min': begin, 'end_min': end, 'values': values})
                        factors = {'event_id': event['event_id'], 'direction': direction, 'thermal_axis': axis,
                            'setpoint_delta_C': delta, 'requested_duration_min': duration,
                            'available_duration_min': hi - lo, 'A_active_support_min': None,
                            'available_duration_scope': 'declared_control_and_room_window_only;physical_headroom_unknown',
                            'manual_change_min': 0, 'program_shift_min': 0, 'baseline_restored_after_min': hi,
                            'opportunity_evidence': 'declared_permission_only;A_physical_state_unavailable'}
                        opportunity = {'status': 'exploratory', 'basis': 'declared_A_control_and_room_windows',
                            'reason': 'A_PHYSICAL_STATE_UNAVAILABLE', 'actual_response_confirmed': False,
                            'scope': 'plan_alternative_only;no_operating_load_or_energy_response_claim'}
                        issues = control_issues(context, apply(context['A'], patches))
                        rows.append(candidate(context, family, aid, factors, patches, issues, opportunity=opportunity))
    return rows, unavailable
