"""Command semantics and independent dose axes; never infer compressor/room state."""
from .model import apply, overlap


AC_CONTRACT = {
    'schema': 'eb.ac_control_semantics.v1',
    'cooling_off_fallback_C': 40.0,
    'encoding': 'cooling_threshold_fallback;not_native_availability_off',
    'basis': 'declared_project_life_A_encoding;original_EB_family_runner_fallback',
    'upstream_commit': '2b17ae63e613da776c93e900f5dace50d63a88a8',
    'native_availability_control_supported': False,
    'compressor_state_known': False,
}


def state(row, contract):
    if row is None:
        return {'mode': 'no_control_row', 'cooling_setpoint_C': None,
                'compressor_running': None}
    fallback = contract and row['cooling_setpoint_C'] == contract['cooling_off_fallback_C']
    return {'mode': 'cooling_stop_fallback' if fallback else 'thermostat_control',
            'cooling_setpoint_C': None if fallback else row['cooling_setpoint_C'],
            'heating_setpoint_C': row['heating_setpoint_C'],
            'encoded_cooling_threshold_C': row['cooling_setpoint_C'],
            'compressor_running': None}


def time_level(minutes, limits=(10,30)):
    """Absolute project bins, independent of how narrow a household's domain is."""
    return 'none' if minutes == 0 else 'small' if minutes <= limits[0] else 'medium' if minutes <= limits[1] else 'large'


def temperature_level(delta, levels):
    return 'not_applicable' if delta is None else 'none' if delta == 0 else 'small' if delta <= levels[0] else 'medium' if delta <= levels[1] else 'large'


def describe(c, aid, patches, axis, event, temperature_levels):
    """Compare literal full-phase commands; fallback transitions have no delta-T.

    A setpoint in a newly enabled interval is compared to a named occupied
    reference only, never to the fallback sentinel as a comfort temperature.
    """
    before = [r for r in c['A']['controls'] if r['asset_id'] == aid and r['kind'] == 'ac_setpoint']
    b = apply({'tasks': [], 'operations': [], 'controls': before}, patches)
    after = b['controls']
    lo = min(p['start_min'] for p in patches)
    hi = max(p['end_min'] for p in patches)
    points = sorted({lo, hi} | {max(lo, min(hi, r[k])) for r in before + after for k in ('start_min', 'end_min')})
    contract = c['reference'].get('ac_control_contract')
    key = axis + '_setpoint_C'
    reference = next(r[key] for r in before if r['start_min'] <= event['start_min'] < r['end_min'])
    phases = []; enabled = paused = pre = 0; comparable = []; requested = []
    for left, right in zip(points, points[1:]):
        a = next((r for r in before if r['start_min'] <= left < r['end_min']), None)
        z = next((r for r in after if r['start_min'] <= left < r['end_min']), None)
        if a == z or a is None or z is None:
            continue
        av, bv = state(a, contract), state(z, contract)
        # Interval boundaries alone are not a command change.
        if {k:v for k,v in a.items() if k not in ('start_min','end_min')} == {k:v for k,v in z.items() if k not in ('start_min','end_min')}:
            continue
        both = av['mode'] == bv['mode'] == 'thermostat_control'
        delta = z[key] - a[key] if both else None
        if delta is not None: comparable.append(abs(delta))
        if bv['mode'] == 'thermostat_control': requested.append(abs(z[key] - reference))
        if av['mode'] == 'cooling_stop_fallback' and bv['mode'] == 'thermostat_control': enabled += right-left
        if av['mode'] == 'thermostat_control' and bv['mode'] == 'cooling_stop_fallback': paused += right-left
        pre += overlap(left,right,lo,event['start_min'])
        phases.append({'start_min':left,'end_min':right,'A':av,'B':bv,
            'same_time_setpoint_delta_C':delta,
            'occupied_reference_setpoint_C':reference,
            'B_offset_from_occupied_reference_C':z[key]-reference if bv['mode']=='thermostat_control' else None})
    max_comparable = max(comparable, default=None)
    max_reference = max(requested, default=None)
    event_minutes=sum(overlap(p['start_min'],p['end_min'],event['start_min'],event['end_min']) for p in phases)
    return {'schema':'eb.ac_intervention.v1','axis':axis,'phases':phases,
        'state_change':'mixed' if enabled and paused else 'leave_cooling_stop_fallback' if enabled else 'request_cooling_stop_fallback' if paused else 'unchanged',
        'additional_thermostat_enabled_min':enabled,'cooling_stop_requested_min':paused,
        'preconditioning_min':pre,'event_changed_min':event_minutes,
        'max_comparable_setpoint_delta_C':max_comparable,
        'max_offset_from_occupied_reference_C':max_reference,
        'amplitude_axes':{'temperature_offset':temperature_level(max_reference,temperature_levels),
            'preconditioning':time_level(pre),'additional_enable':time_level(enabled),
            'cooling_pause':time_level(paused,(20,40)),
            'event_duration':time_level(event_minutes,(20,40))},
        'native_availability_off_claimed':False,'actual_compressor_runtime_min':None,
        'actual_room_temperature_C':None,'response_kWh':None,
        'legacy_encoding_retained':True,'whole_intervention_intensity':None}
