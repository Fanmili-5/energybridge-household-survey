"""Per-target readback; never used to select or replace a proposal."""
from .common import digest

ENERGY_EPSILON_KWH = 1e-9
STATE_EPSILON = 1e-7


def targeted_response(pair, metas, traces, context, lo, hi):
    from .outcomes import channel
    from .sampling import normalized_commands
    plans = {s: normalized_commands(pair[s]) for s in ('A', 'B')}
    assets = sorted({r['asset_id'] for p in plans.values() for rows in p.values() for r in rows})
    changed = [a for a in assets if {k: [r for r in v if r['asset_id'] == a] for k, v in plans['A'].items()}
               != {k: [r for r in v if r['asset_id'] == a] for k, v in plans['B'].items()}]
    devices = {d['asset_id']: d for d in (context or {}).get('devices', [])}
    times = range(lo, hi, 10)
    rows = []
    for aid in changed:
        device = devices.get(aid, {})
        kind = device.get('kind')
        control_kinds = {r['kind'] for r in pair['A']['controls'] if r['asset_id'] == aid}
        names = [name for name, info in metas['A']['equipment_meter_mapping'].items() if info['asset_id'] == aid]
        if aid in metas['A']['HVAC_equipment_mapping']:
            variable, name = 'Zone Packaged Terminal Heat Pump Electricity Energy', metas['A']['HVAC_equipment_mapping'][aid]
            kind = 'ac'
        elif names:
            variable, name = 'Electric Equipment Electricity Energy', names[0]
            kind = metas['A']['equipment_meter_mapping'][name]['kind']
        elif 'ev_charge_window' in control_kinds:
            variable, name, kind = 'Exterior Equipment Electricity Energy', 'EXTERNAL_EV', 'ev'
        elif 'tank_setpoint' in control_kinds:
            variable, name, kind = 'Water Heater Electricity Energy', metas['A']['tank_name'], 'water_heater'
        else:
            raise ValueError('UNMAPPED_TARGET_RESPONSE:' + aid)
        series = {s: channel(traces[s], variable, name) for s in ('A', 'B')}
        differences = [series['B'][t] - series['A'][t] for t in times]
        energy_l1 = sum(abs(x) for x in differences) / 3600000
        peak_W = max(abs(x) for x in differences) / 600
        temperature_keys = []
        if kind == 'ac' and device.get('room_id'):
            temperature_keys = [('Zone Mean Air Temperature', device['room_id'])]
        elif kind == 'water_heater':
            temperature_keys = [('Water Heater Final Temperature Node ' + str(i), metas['A']['tank_name'])
                                for i in range(1, metas['A']['world_assembly']['tank_nodes'] + 1)]
            temperature_keys += [('Water Heater Use Side Outlet Temperature', metas['A']['tank_name'])]
        temp_delta = 0.0
        for variable, name in temperature_keys:
            a, b = (channel(traces[s], variable, name) for s in ('A', 'B'))
            temp_delta = max(temp_delta, max(abs(b[t] - a[t]) for t in times))
        ev_delta = 0.0
        if kind == 'ev':
            a, b = (dict(metas[s]['EV'].get('trace', [])) for s in ('A', 'B'))
            ev_delta = max([abs(a[t] - b[t]) for t in a.keys() & b.keys() if lo <= t < hi] + [0.0])
        executed_changes = []
        for collection, ident in [('tasks', 'task_id'), ('operations', 'operation_id')]:
            a = {r[ident]: r for r in metas['A']['execution'][collection] if r['asset_id'] == aid}
            b = {r[ident]: r for r in metas['B']['execution'][collection] if r['asset_id'] == aid}
            for key in a.keys() | b.keys():
                old, new = a.get(key), b.get(key)
                if old != new and any(r and r['start_min'] < hi and r['end_min'] > lo for r in (old, new)):
                    executed_changes.append({'collection': collection, 'id': key,
                                             'A_start_min': old['start_min'] if old else None,
                                             'B_start_min': new['start_min'] if new else None})
        response = energy_l1 > ENERGY_EPSILON_KWH or temp_delta > STATE_EPSILON or ev_delta > STATE_EPSILON or bool(executed_changes)
        rows.append({'asset_id': aid, 'kind': kind, 'energy_trace_L1_kWh': energy_l1,
                     'peak_absolute_power_change_W': peak_W, 'max_temperature_difference_C': temp_delta,
                     'max_EV_energy_difference_kWh': ev_delta, 'executed_timing_changes': sorted(executed_changes, key=lambda r: (r['collection'], r['id'])),
                     'observable_response': response})
    count = sum(r['observable_response'] for r in rows)
    pattern = ('identical_control' if not rows else 'all_targeted_assets_change' if count == len(rows)
               else 'mixed_target_response' if count else 'no_target_response')
    return {'interval_min': [lo, hi], 'records': rows, 'pattern': pattern,
            'requested_target_assets': len(rows), 'changed_target_assets': count,
            'B_native_trace_sha256': digest(traces['B']),
            'scope': 'modeled_observable_difference;not_human_salience_or_acceptance;L1_is_not_energy_saving',
            'numerical_guards': {'energy_kWh': ENERGY_EPSILON_KWH, 'temperature_C_or_battery_kWh': STATE_EPSILON},
            'used_for_reselection': False}
