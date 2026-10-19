"""Measured consequences, independent service requirements, and explicit units."""
from .model import chain_need_ids, overlap


def channel(trace, variable, key=''):
    found = [c for name, c in trace.items() if name.lower() == (variable + '|' + key).lower()]
    if len(found) != 1:
        raise ValueError('MISSING_PAIRED_CHANNEL:' + variable + '|' + key)
    expected = 'J' if variable.endswith(('Energy', 'Electricity')) or variable.startswith('Electricity:') else 'C'
    if found[0]['unit'] != expected:
        raise ValueError('PAIRED_CHANNEL_UNIT_MISMATCH:' + variable)
    return dict(found[0]['values'])


def controlled_energy(meta, trace):
    names = [('Zone Packaged Terminal Heat Pump Electricity Energy', n) for n in meta['HVAC_equipment_mapping'].values()]
    names += [('Electric Equipment Electricity Energy', n) for n in meta['equipment_meter_mapping']]
    if meta['tank_name']:
        names.append(('WaterSystems:Electricity', ''))
    if meta['EV']['installed']:
        names.append(('Exterior Equipment Electricity Energy', 'EXTERNAL_EV'))
    total = {t: 0.0 for t in channel(trace, 'Electricity:Facility')}
    for variable, name in names:
        for t, value in channel(trace, variable, name).items():
            total[t] = total.get(t, 0) + value / 3600000
    return total


def bill(values, tariff, lo, hi):
    if set(range(lo, hi, 10)) - values.keys():
        return None
    total = 0.0
    for t in range(lo, hi, 10):
        rates = [r['price_per_kWh'] for r in tariff if r['start_min'] <= t and t + 10 <= r['end_min']]
        if len(rates) != 1:
            return None
        total += values[t] * rates[0]
    return total


def interval_stats(values, lo, hi):
    samples = [values[t] for t in range(lo, hi, 10)]
    return {'minimum_C': min(samples), 'maximum_C': max(samples), 'mean_C': sum(samples) / len(samples)}


def service_changes(pair, metas):
    needs = {n['need_id']: n for n in metas['A'].get('service_needs', []) + pair['needs_A']}
    lo, hi = pair['decision_min'], metas['A']['run_interval_min'][1]
    ids = {b['need_id'] for side in metas.values() for b in side['execution']['batches'] if lo <= b['requested_program_end_min'] < hi}
    result = []
    for nid in sorted(ids):
        row = {'need_id': nid, 'deadline_min': needs.get(nid, {}).get('deadline_min')}
        for side in ('A', 'B'):
            b = next((b for b in metas[side]['execution']['batches'] if b['need_id'] == nid), None)
            row[side] = dict(b) if b else None
            if b:
                execution = metas[side]['execution']; chain = chain_need_ids(execution, nid)
                runs = [t for t in execution['tasks'] if t['need_id'] in chain]
                load = next((o for o in execution.get('operations', []) if o['need_id'] == nid and o['kind'] == 'load'), None)
                unload = next((o for o in execution.get('operations', []) if o['need_id'] == nid and o['kind'] == 'unload'), None)
                row[side]['realized_preload_wait_min'] = min(t['start_min'] for t in runs) - load['end_min'] if runs and load else None
                row[side]['realized_retrieval_wait_min'] = unload['start_min'] - max(t['end_min'] for t in runs) if runs and unload and b['collected'] else None
        row['retrieval_delay_min'] = (row['B']['requested_retrieval_end_min'] - row['A']['requested_retrieval_end_min']
                                      if row['A'] and row['B'] and row['A']['requested_retrieval_end_min'] is not None
                                      and row['B']['requested_retrieval_end_min'] is not None and row['A']['collected'] and row['B']['collected'] else None)
        result.append(row)
    old = {o['operation_id']: o for o in pair['A']['operations']}
    changed = [{'operation_id': o['operation_id'], 'operator_id': o['operator_id'],
                'shift_min': o['start_min'] - old[o['operation_id']]['start_min']}
               for o in pair['B']['operations'] if o['operation_id'] in old and o != old[o['operation_id']]]
    return {'services': result, 'manual_operation_changes': changed, 'interval_min': [lo, hi],
            'interpretation': 'modeled_service_and_handling;not_human_inconvenience_or_acceptance'}


def consequences(pair, metas, traces, audit, context=None):
    lo, primary = pair['decision_min'], (context or {}).get('horizon_min', [480, 1920])[1]
    end = metas['A']['run_interval_min'][1]
    intervals = {'primary_24h': (lo, primary), 'primary_and_followup': (lo, end)}
    facility = {s: {t: v / 3600000 for t, v in channel(traces[s], 'Electricity:Facility').items()} for s in ('A', 'B')}
    controlled = {s: controlled_energy(metas[s], traces[s]) for s in ('A', 'B')}
    events = []
    for e in pair['VPP_events']:
        a, z = e['start_min'], e['end_min']
        measures = {}
        for scope, series in (('whole_physical_dwelling', facility), ('modeled_controlled_equipment', controlled)):
            totals = {s: sum(series[s][t] for t in range(a, z, 10)) for s in ('A', 'B')}
            delta = (totals['B'] - totals['A']) * 60 / (z - a)
            measures[scope] = {'A_kWh': totals['A'], 'B_kWh': totals['B'], 'delta_kw': delta,
                               'aligned_response_kw': delta * (1 if e['direction'] == 'up' else -1)}
        scope = e.get('meter_scope', (context or {}).get('event_meter_scope', pair.get('AB_generation', {}).get('event_meter_scope', 'whole_physical_dwelling')))
        if scope not in measures:
            raise ValueError('UNKNOWN_EVENT_METER_SCOPE')
        chosen = measures[scope]
        events.append({'event_id': e['event_id'], 'interval_min': [a, z], 'requested_direction': e['direction'],
                       'meter_scope': scope, **chosen, 'target_kw': e['target_kw'],
                       'target_met': chosen['aligned_response_kw'] + 1e-8 >= e['target_kw'], 'measured_scopes': measures})
    costs = None
    if context is not None:
        provenance = context.get('tariff_provenance') or {}
        costs = {'currency': provenance.get('currency', 'declared_input_currency'), 'tariff_provenance': provenance or None,
                 'scope': 'whole_physical_dwelling_meter_including_shared_context;no_compensation_or_household_allocation', 'intervals': {}}
        for label, (a, z) in intervals.items():
            totals = {s: bill(facility[s], context['tariff'], a, z) for s in ('A', 'B')}
            costs['intervals'][label] = {'interval_min': [a, z], **totals,
                'B_minus_A': totals['B'] - totals['A'] if None not in totals.values() else None,
                'status': 'complete' if None not in totals.values() else 'explicit_tariff_or_meter_coverage_incomplete'}
    energy = {}
    for label, (a, z) in intervals.items():
        totals = {s: sum(facility[s][t] for t in range(a, z, 10)) for s in ('A', 'B')}
        energy[label] = {'interval_min': [a, z], **totals, 'B_minus_A': totals['B'] - totals['A'], 'unit': 'kWh'}
    temperatures = []
    for room in metas['A']['world_assembly']['room_ids']:
        values = {s: channel(traces[s], 'Zone Mean Air Temperature', room) for s in ('A', 'B')}
        temperatures.append({'room_id': room, 'interval_min': [lo, primary],
                             **{s: interval_stats(values[s], lo, primary) for s in ('A', 'B')},
                             'maximum_absolute_A_B_difference_C': max(abs(values['B'][t] - values['A'][t]) for t in range(lo, primary, 10))})
    comfort = []
    for need in pair['needs_A']:
        if need.get('kind') != 'comfort' or not overlap(lo, primary, need['release_min'], need['deadline_min']):
            continue
        band = need['temperature_band_C']; a, z = max(lo, need['release_min']), min(primary, need['deadline_min'])
        row = {'need_id': need['need_id'], 'room_id': need['room_id'], 'interval_min': [a, z],
               'declared_band_C': band, 'origin': need['origin'], 'unknown_preference_preserved': band is None}
        for side in ('A', 'B'):
            values = channel(traces[side], 'Zone Mean Air Temperature', need['room_id'])
            row[side] = {'outside_declared_band_min': None if band is None else sum(10 for t in range(a, z, 10) if not band[0] <= values[t] <= band[1]),
                         'outside_declared_band_degree_min': None if band is None else sum(max(0, band[0] - values[t], values[t] - band[1]) * 10 for t in range(a, z, 10))}
        comfort.append(row)
    return {'events': events, 'meter_scope': 'whole_physical_dwelling_including_shared_context;not_target_household_submeter',
            'metered_energy': energy, 'simulated_facility_cost': costs, 'service_changes': service_changes(pair, metas),
            'service_execution': {s: metas[s]['execution']['batches'] for s in ('A', 'B')},
            'temperature_outcomes': temperatures, 'independent_comfort': {'status': 'declared_requirements' if comfort else 'not_declared', 'records': comfort},
            'water_service': {s: audit['details'].get(s + '_water_services') for s in ('A', 'B')},
            'EV': {s: {k: v for k, v in metas[s]['EV'].items() if k != 'trace'} for s in ('A', 'B')},
            'recovery': {'observable_residuals': audit['details'].get('recovery_state_differences'),
                         'checks': {k: v for k, v in audit['checks'].items() if 'recovery' in k or 'terminal' in k}},
            'actual_results_used_for_reselection': False, 'human_acceptance': None}
